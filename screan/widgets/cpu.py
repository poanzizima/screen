"""CPU widget:标签 + 横向进度条(平滑动画) + 右对齐百分比。

动画策略:进度条填充用 AnimatedValue 平滑;但只在"填充像素宽度"实际变化时
才置脏,避免亚像素级抖动导致每帧重画(屏闪源)。
"""
from __future__ import annotations
import skia

from ..collect.state import Metrics
from ..util.anim import AnimatedValue
from ..util.rect import Rect
from .base import Widget
from ._draw import draw_bar, draw_text, draw_text_right, fill_bg


class CpuWidget(Widget):
    def __init__(self, rect, theme):
        super().__init__(rect, theme)
        self._displayed_int: int = -1
        self._anim = AnimatedValue(0.0, speed=10.0)
        self._last_bar_px: int = -1   # 上次绘制时进度条填充的像素宽度

    def update(self, m: Metrics) -> bool:
        v = int(round(m.cpu_percent))
        text_changed = v != self._displayed_int
        self._displayed_int = v
        self._anim.set_target(float(v))
        if text_changed:
            self._dirty = True
            return True
        return False

    def tick(self, dt: float) -> bool:
        if not self._anim.tick(dt):
            return False
        # 量化:动画值映射到当前 widget 进度条的整像素宽度
        bar_px = int(self.rect.w * max(0.0, self._anim.current) / 100.0)
        if bar_px != self._last_bar_px:
            # 只标进度条那一窄条为脏,避免每帧重传整个 widget(屏闪根因)
            t = self.theme
            bar_local = Rect(0, self.rect.h - t.bar_height, self.rect.w, t.bar_height)
            self.mark_dirty(bar_local)
            return True
        return False

    def render(self, canvas: skia.Canvas) -> None:
        t = self.theme
        w, h = self.rect.w, self.rect.h
        fill_bg(canvas, w, h, t.bg)

        v_text = max(0, self._displayed_int)
        v_anim = self._anim.current

        label_font = t.font("regular", t.label_size_lg, bold=True)
        value_font = t.font("mono", t.value_size_md, bold=True)

        # 文字顶端基线对齐:标签和数值都画在 label_size_lg 高度上
        baseline = t.label_size_lg + 2
        draw_text(canvas, "CPU", 0, baseline, label_font, t.fg_secondary)
        draw_text_right(canvas, f"{v_text}%", w, baseline, value_font, t.fg)

        if v_anim < 50:
            color = t.success
        elif v_anim < 75:
            color = t.accent
        elif v_anim < 90:
            color = t.warn
        else:
            color = t.danger

        bar_y = h - t.bar_height
        draw_bar(canvas, 0, bar_y, w, t.bar_height, v_anim / 100.0,
                 theme=t, color=color)
        self._last_bar_px = int(w * max(0.0, v_anim) / 100.0)
