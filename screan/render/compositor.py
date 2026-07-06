"""Compositor:协调 Surface + Widgets + Display。
核心职责:
 1) on_metrics(m): 数据来时,遍历所有 widget 调 update(m),记录哪些变脏
 2) tick(dt):      每帧调用,推进 widget 内部动画(进度条平滑过渡等)
 3) render_frame(): 对每个脏 widget,clip + translate 到局部坐标系后渲染
 4) flush_dirty():  把脏区合并 → 取 Surface 子区 → RGB888→666 → SPI update_region
 5) 异常隔离:单 widget render 抛异常不影响其他

帧节流:由外层 app.py 控制,这里只暴露 render_frame() / tick() 同步 API。
"""
from __future__ import annotations
import time
from typing import Iterable

import skia

from ..collect.state import Metrics
from ..driver.colorconv import rgba_to_rgb666
from ..driver.ili9488 import ILI9488
from ..render.surface import Surface
from ..render.theme import Theme
from ..util.log import get_logger
from ..util.rect import Rect, coalesce
from ..widgets.base import Widget

log = get_logger(__name__)


def _intersects(a: Rect, b: Rect) -> bool:
    """两个矩形是否有交集(用于判断脏区是否落在 photo widget 上)。"""
    return (a.x < b.x + b.w and b.x < a.x + a.w
            and a.y < b.y + b.h and b.y < a.y + a.h)


class Compositor:
    def __init__(
        self,
        display: ILI9488,
        surface: Surface,
        theme: Theme,
        widgets: list[Widget],
        *,
        max_rects: int = 4,
    ):
        self.display = display
        self.surface = surface
        self.theme = theme
        self.widgets = widgets
        self.max_rects = max_rects
        self._bounds = Rect(0, 0, surface.width, surface.height)
        self._first_frame_done = False

    # ------ 数据进 ------
    def on_metrics(self, m: Metrics) -> bool:
        """返回是否有任何 widget 变脏。"""
        any_dirty = False
        for w in self.widgets:
            try:
                if w.update(m):
                    any_dirty = True
            except Exception:
                log.exception("widget %s update raised", type(w).__name__)
        return any_dirty

    # ------ 每帧动画 ------
    def tick(self, dt: float) -> bool:
        """推进所有 widget 的内部动画。返回是否仍有动画在进行。"""
        any_animating = False
        for w in self.widgets:
            try:
                if w.tick(dt):
                    any_animating = True
            except Exception:
                log.exception("widget %s tick raised", type(w).__name__)
        return any_animating

    # ------ 帧渲染 ------
    def render_frame(self) -> int:
        """渲染所有脏 widget,推送到屏。返回本帧推送的字节数(0 = 无脏区)。
        首帧强制全屏(让背景填上)。"""
        if not self._first_frame_done:
            return self._render_full_frame()

        dirty_widgets = [w for w in self.widgets if w.dirty]
        if not dirty_widgets:
            return 0

        # 在 Skia surface 上局部重绘每个脏 widget(canvas.save/clip/translate)
        canvas = self.surface.canvas
        dirty_rects: list[Rect] = []
        for w in dirty_widgets:
            try:
                # 收集需要 SPI 传输的全局矩形(可能是 widget 子区)
                dirty_rects.append(w.dirty_global_rect)
                canvas.save()
                canvas.clipRect(skia.Rect.MakeXYWH(w.rect.x, w.rect.y, w.rect.w, w.rect.h))
                canvas.translate(w.rect.x, w.rect.y)
                w.render(canvas)
            except Exception:
                log.exception("widget %s render raised", type(w).__name__)
            finally:
                canvas.restore()
                w.clear_dirty()
        self.surface.flush()

        # 合并脏区,逐区推 SPI
        merged = coalesce(dirty_rects, bounds=self._bounds,
                          max_rects=self.max_rects, align=2, gap=16)

        # 收集需要抖动的 widget 全局 rect,判断脏区是否落在其上
        photo_rects = [w.rect for w in self.widgets if w.wants_dither]

        total_bytes = 0
        for r in merged:
            sub = self.surface.snapshot_rect(r)
            dither = any(_intersects(r, p) for p in photo_rects)
            buf = rgba_to_rgb666(sub, dither=dither)
            self.display.update_region(r.x, r.y, r.w, r.h, buf)
            total_bytes += len(buf)
        return total_bytes

    def _render_full_frame(self) -> int:
        """首帧:整屏背景 + 所有 widget,一次 SPI 推送。"""
        canvas = self.surface.canvas
        canvas.clear(self.theme.bg)
        for w in self.widgets:
            try:
                canvas.save()
                canvas.clipRect(skia.Rect.MakeXYWH(w.rect.x, w.rect.y, w.rect.w, w.rect.h))
                canvas.translate(w.rect.x, w.rect.y)
                w.render(canvas)
            except Exception:
                log.exception("widget %s render raised", type(w).__name__)
            finally:
                canvas.restore()
                w.clear_dirty()
        self.surface.flush()

        arr = self.surface.snapshot_array()
        # 首帧:若布局中有任何 photo widget,整屏开抖动(1ms 代价换正常肤色)
        any_photo = any(w.wants_dither for w in self.widgets)
        buf = rgba_to_rgb666(arr, dither=any_photo)
        self.display.update_region(0, 0, self.surface.width, self.surface.height, buf)
        self._first_frame_done = True
        return len(buf)
