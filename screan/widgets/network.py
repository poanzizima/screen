"""网络 widget:↓ rx, ↑ tx 双行速率。"""
from __future__ import annotations
import skia

from ..collect.state import Metrics
from .base import Widget
from ._draw import draw_text, draw_text_right, fill_bg, fmt_bps


class NetworkWidget(Widget):
    def __init__(self, rect, theme):
        super().__init__(rect, theme)
        self._rx_txt: str = ""
        self._tx_txt: str = ""

    def update(self, m: Metrics) -> bool:
        rx = fmt_bps(m.net_rx_bps)
        tx = fmt_bps(m.net_tx_bps)
        if rx != self._rx_txt or tx != self._tx_txt:
            self._rx_txt, self._tx_txt = rx, tx
            self._dirty = True
            return True
        return False

    def render(self, canvas: skia.Canvas) -> None:
        t = self.theme
        w, h = self.rect.w, self.rect.h
        fill_bg(canvas, w, h, t.bg)

        label_font = t.font("regular", t.label_size, bold=False)
        value_font = t.font("mono", t.label_size, bold=True)

        draw_text(canvas, "NET", 0, t.label_size, label_font, t.muted)

        # 两行紧凑显示
        line_h = t.label_size + 4
        y1 = t.label_size                           # 第一行基线(下载)
        y2 = h - 2                                  # 第二行基线(上传)
        draw_text(canvas, "↓", w / 2 - 8, y1, label_font, t.success)
        draw_text_right(canvas, self._rx_txt, w, y1, value_font, t.fg)
        draw_text(canvas, "↑", w / 2 - 8, y2, label_font, t.accent)
        draw_text_right(canvas, self._tx_txt, w, y2, value_font, t.fg)
