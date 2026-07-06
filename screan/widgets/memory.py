"""内存 widget:标签 + 进度条(平滑动画) + 'used / total' 紧凑数字。
Swap 使用时在右侧追加 "+swap XM" 提示(树莓派健康状态 swap 应接近 0)。"""
from __future__ import annotations
import skia

from ..collect.state import Metrics
from ..util.anim import AnimatedValue
from ..util.rect import Rect
from .base import Widget
from ._draw import draw_bar, draw_text, fill_bg, fmt_bytes, measure_text


class MemoryWidget(Widget):
    def __init__(self, rect, theme):
        super().__init__(rect, theme)
        self._txt: str = ""
        self._swap_txt: str = ""
        self._anim = AnimatedValue(0.0, speed=10.0)
        self._last_bar_px: int = -1

    def update(self, m: Metrics) -> bool:
        new_txt = f"{fmt_bytes(m.mem_used)} / {fmt_bytes(m.mem_total)}"
        # swap 用量 < 16 MB 视作噪音,不显示
        if m.swap_used < 16 * 1024 * 1024:
            new_swap = ""
        else:
            new_swap = f"+swap {fmt_bytes(m.swap_used)}"
        text_changed = new_txt != self._txt or new_swap != self._swap_txt
        self._txt = new_txt
        self._swap_txt = new_swap
        self._anim.set_target(m.mem_percent)
        if text_changed:
            self._dirty = True
            return True
        return False

    def tick(self, dt: float) -> bool:
        if not self._anim.tick(dt):
            return False
        bar_px = int(self.rect.w * max(0.0, self._anim.current) / 100.0)
        if bar_px != self._last_bar_px:
            t = self.theme
            bar_local = Rect(0, self.rect.h - t.bar_height, self.rect.w, t.bar_height)
            self.mark_dirty(bar_local)
            return True
        return False

    def render(self, canvas: skia.Canvas) -> None:
        t = self.theme
        w, h = self.rect.w, self.rect.h
        fill_bg(canvas, w, h, t.bg)

        label_font = t.font("regular", t.label_size, bold=True)
        value_font = t.font("mono", t.label_size, bold=True)
        small_font = t.font("mono", t.label_size - 2, bold=False)

        baseline = t.label_size + 2
        draw_text(canvas, "MEM", 0, baseline, label_font, t.fg_secondary)

        # 右侧:先量 used/total 宽度,再在其左边加 swap 提示(如有)
        val_w, _ = measure_text(self._txt, value_font)
        draw_text(canvas, self._txt, w - val_w, baseline, value_font, t.fg)
        if self._swap_txt:
            sw_w, _ = measure_text(self._swap_txt, small_font)
            draw_text(canvas, self._swap_txt, w - val_w - sw_w - 8,
                      baseline, small_font, t.warn)

        ratio = self._anim.current / 100.0
        if ratio < 0.6:
            color = t.success
        elif ratio < 0.85:
            color = t.accent
        else:
            color = t.warn

        bar_y = h - t.bar_height
        draw_bar(canvas, 0, bar_y, w, t.bar_height, ratio, theme=t, color=color)
        self._last_bar_px = int(w * max(0.0, ratio))
