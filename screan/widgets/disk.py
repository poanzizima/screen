"""磁盘 widget:进度条 + used / total。复用 memory 风格。"""
from __future__ import annotations
import skia

from ..collect.state import Metrics
from ..util.anim import AnimatedValue
from ..util.rect import Rect
from .base import Widget
from ._draw import draw_bar, draw_text, draw_text_right, fill_bg, fmt_bytes


class DiskWidget(Widget):
    def __init__(self, rect, theme):
        super().__init__(rect, theme)
        self._txt: str = ""
        self._anim = AnimatedValue(0.0, speed=6.0)
        self._last_bar_px: int = -1

    def update(self, m: Metrics) -> bool:
        new_txt = f"{fmt_bytes(m.disk_used)} / {fmt_bytes(m.disk_total)}"
        text_changed = new_txt != self._txt
        self._txt = new_txt
        self._anim.set_target(m.disk_percent)
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

        draw_text(canvas, "DISK", 0, t.label_size, label_font, t.fg_secondary)
        draw_text_right(canvas, self._txt, w, t.label_size, value_font, t.fg)

        ratio = self._anim.current / 100.0
        if ratio < 0.7:
            color = t.success
        elif ratio < 0.9:
            color = t.warn
        else:
            color = t.danger

        bar_y = h - t.bar_height
        draw_bar(canvas, 0, bar_y, w, t.bar_height, ratio, theme=t, color=color)
        self._last_bar_px = int(w * max(0.0, ratio))
