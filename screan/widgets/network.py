"""网络 widget:自适应 WiFi / 有线 / DOWN。

布局(左上 156×80,与 CLOCK 并排):
    ┌─────────────────┐
    │ NET      ▂▄▆▇   │  第 1 行:label + 信号柱(WiFi 时)
    │ WiFi-5566       │  第 2 行:SSID / iface+speed / OFFLINE
    │ ↓ 1.2 MB/s      │  第 3 行:下载
    │ ↑ 320 KB/s      │  第 4 行:上传
    └─────────────────┘

- WiFi:信号柱在右上,SSID 单独一行(可放长名字)。
- 有线:第 2 行 "eth0  1Gbps"。
- 无网/DOWN:第 2 行 "OFFLINE"(红)。
"""
from __future__ import annotations
import skia

from ..collect.state import Metrics
from .base import Widget
from ._draw import draw_text, draw_text_right, fill_bg, fmt_bps, measure_text


def _signal_bars(dbm: int) -> int:
    if dbm == 0:
        return 0
    if dbm > -55: return 4
    if dbm > -65: return 3
    if dbm > -75: return 2
    if dbm > -85: return 1
    return 0


def _fmt_link_speed(mbps: int) -> str:
    if mbps <= 0:
        return ""
    if mbps >= 1000:
        g = mbps / 1000
        return f"{g:.0f}Gbps" if g == int(g) else f"{g:.1f}Gbps"
    return f"{mbps}Mbps"


class NetworkWidget(Widget):
    def __init__(self, rect, theme):
        super().__init__(rect, theme)
        self._rx_txt: str = ""
        self._tx_txt: str = ""
        self._iface: str = ""
        self._is_wifi: bool = False
        self._ssid: str = ""
        self._dbm: int = 0
        self._link_mbps: int = 0
        self._up: bool = False

    def update(self, m: Metrics) -> bool:
        changed = False

        rx = fmt_bps(m.net_rx_bps)
        tx = fmt_bps(m.net_tx_bps)
        if rx != self._rx_txt or tx != self._tx_txt:
            self._rx_txt, self._tx_txt = rx, tx
            changed = True

        if (m.net_iface != self._iface
                or m.net_is_wifi != self._is_wifi
                or m.net_ssid != self._ssid
                or m.net_signal_dbm != self._dbm
                or m.net_link_mbps != self._link_mbps
                or m.net_link_up != self._up):
            self._iface = m.net_iface
            self._is_wifi = m.net_is_wifi
            self._ssid = m.net_ssid
            self._dbm = m.net_signal_dbm
            self._link_mbps = m.net_link_mbps
            self._up = m.net_link_up
            changed = True

        if changed:
            self._dirty = True
        return changed

    def _draw_signal_bars(self, canvas: skia.Canvas, x_right: float,
                          y_center: float, bars_lit: int) -> float:
        t = self.theme
        bar_w = 3
        gap = 2
        heights = (4, 7, 10, 13)
        max_h = heights[-1]
        total_w = 4 * bar_w + 3 * gap
        x0 = x_right - total_w
        y_bottom = y_center + max_h / 2
        if bars_lit >= 3:
            lit_color = t.success
        elif bars_lit == 2:
            lit_color = t.warn
        else:
            lit_color = t.danger
        for i, h in enumerate(heights):
            lit = i < bars_lit
            color = lit_color if lit else t.track
            rect = skia.Rect.MakeXYWH(x0 + i * (bar_w + gap),
                                      y_bottom - h, bar_w, h)
            canvas.drawRect(rect, t.paint(color))
        return x0

    def render(self, canvas: skia.Canvas) -> None:
        t = self.theme
        w, h = self.rect.w, self.rect.h
        fill_bg(canvas, w, h, t.bg)

        label_font = t.font("regular", t.label_size, bold=True)
        text_font = t.font("regular", t.label_size + 1, bold=True)
        value_font = t.font("mono", t.label_size, bold=True)

        # 4 行等分,基线间距 ~18px
        y1 = t.label_size + 2                # ≈ 16, "NET" 行
        y2 = y1 + 20                          # ≈ 36, SSID/状态
        y3 = y2 + 18                          # ≈ 54, 下载
        y4 = y3 + 18                          # ≈ 72, 上传

        # ---- 第 1 行:NET 标签 + WiFi 信号柱 ----
        draw_text(canvas, "NET", 0, y1, label_font, t.fg_secondary)
        if self._up and self._iface and self._is_wifi:
            bars = _signal_bars(self._dbm)
            self._draw_signal_bars(canvas, w, y1 - 5, bars)

        # ---- 第 2 行:SSID / iface+speed / OFFLINE ----
        if not self._up or not self._iface:
            draw_text(canvas, "OFFLINE", 0, y2, text_font, t.danger)
        elif self._is_wifi:
            ssid = self._ssid or "(no SSID)"
            # 剪到 widget 宽度内,避免超长 SSID 溢出
            canvas.save()
            canvas.clipRect(skia.Rect.MakeXYWH(0, y2 - t.label_size - 2,
                                                w, t.label_size + 6))
            draw_text(canvas, ssid, 0, y2, text_font, t.fg)
            canvas.restore()
        else:
            iface = self._iface
            speed = _fmt_link_speed(self._link_mbps)
            draw_text(canvas, iface, 0, y2, text_font, t.fg)
            if speed:
                draw_text_right(canvas, speed, w, y2, value_font, t.success)

        # ---- 第 3 / 4 行:↓ rx / ↑ tx ----
        draw_text(canvas, "↓", 0, y3, label_font, t.success)
        draw_text_right(canvas, self._rx_txt, w, y3, value_font, t.fg)
        draw_text(canvas, "↑", 0, y4, label_font, t.accent)
        draw_text_right(canvas, self._tx_txt, w, y4, value_font, t.fg)
