"""温度 widget:大数字 + 单位 + 颜色随阈值变化。"""
from __future__ import annotations
import skia

from ..collect.state import Metrics
from .base import Widget
from ._draw import draw_text, draw_text_right, fill_bg


class TemperatureWidget(Widget):
    def __init__(self, rect, theme):
        super().__init__(rect, theme)
        self._displayed: float = -1.0    # 上次显示的温度(0.1°C 精度)

    def update(self, m: Metrics) -> bool:
        v = round(m.temp_c, 1)
        if v != self._displayed:
            self._displayed = v
            self._dirty = True
            return True
        return False

    def render(self, canvas: skia.Canvas) -> None:
        t = self.theme
        w, h = self.rect.w, self.rect.h
        fill_bg(canvas, w, h, t.bg)

        label_font = t.font("regular", t.label_size, bold=False)
        big_font = t.font("mono", t.value_size, bold=True)
        unit_font = t.font("regular", t.label_size, bold=False)

        v = max(0.0, self._displayed)
        if v < 60:
            color = t.fg
        elif v < 75:
            color = t.warn
        else:
            color = t.danger

        draw_text(canvas, "TEMP", 0, t.label_size, label_font, t.muted)

        big_str = f"{v:.1f}"
        big_w = big_font.measureText(big_str)
        unit_str = " °C"
        # 把"数字 + 单位"整体右对齐
        unit_w = unit_font.measureText(unit_str)
        x_right = w
        # 单位画在底部基线上
        baseline = h - 4
        draw_text(canvas, unit_str, x_right - unit_w, baseline, unit_font, t.muted)
        draw_text(canvas, big_str, x_right - unit_w - big_w, baseline, big_font, color)
