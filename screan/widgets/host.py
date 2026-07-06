"""主机信息 widget:hostname、IP、运行时长、负载。

工业副屏右上/中区常驻信息,变化极少 → 几乎零 SPI 字节。
"""
from __future__ import annotations
import socket
import time
import skia

from ..collect.state import Metrics
from .base import Widget
from ._draw import draw_text, draw_text_right, fill_bg


def _detect_ip() -> str:
    """无视 DNS,用一个 UDP socket 探测出口接口的 IP。"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.1)
        # 不真的发包,connect UDP 只设置路由
        s.connect(("8.8.8.8", 53))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return "—"


class HostWidget(Widget):
    """显示 hostname、IP 地址、uptime、load average。"""

    def __init__(self, rect, theme):
        super().__init__(rect, theme)
        self._hostname: str = ""
        self._ip: str = ""
        self._uptime_str: str = ""
        self._load_str: str = ""
        self._ip_ts: float = 0.0
        self._boot_ts: float | None = self._read_boot_ts()

    @staticmethod
    def _read_boot_ts() -> float | None:
        try:
            with open("/proc/uptime") as f:
                up = float(f.read().split()[0])
            return time.time() - up
        except OSError:
            return None

    @staticmethod
    def _fmt_uptime(seconds: float) -> str:
        s = int(seconds)
        d, s = divmod(s, 86400)
        h, s = divmod(s, 3600)
        m, _ = divmod(s, 60)
        if d > 0:
            return f"{d}d {h}h"
        if h > 0:
            return f"{h}h {m}m"
        return f"{m}m"

    @staticmethod
    def _fmt_load(l1: float, l5: float, l15: float) -> str:
        return f"{l1:.2f} {l5:.2f} {l15:.2f}"

    def update(self, m: Metrics) -> bool:
        changed = False
        if m.hostname and m.hostname != self._hostname:
            self._hostname = m.hostname
            changed = True
        # IP 每 60 秒重测一次(网络可能切换)
        now = time.monotonic()
        if now - self._ip_ts > 60.0:
            new_ip = _detect_ip()
            if new_ip != self._ip:
                self._ip = new_ip
                changed = True
            self._ip_ts = now
        # uptime 每分钟变一次的粒度
        if self._boot_ts is not None:
            new_up = self._fmt_uptime(time.time() - self._boot_ts)
            if new_up != self._uptime_str:
                self._uptime_str = new_up
                changed = True
        # loadavg
        new_load = self._fmt_load(m.load_1, m.load_5, m.load_15)
        if new_load != self._load_str:
            self._load_str = new_load
            changed = True
        if changed:
            self._dirty = True
        return changed

    def tick(self, dt: float) -> bool:
        # uptime 也通过 tick 每秒检查一次(metrics 推送可能更慢)
        if self._boot_ts is None:
            return False
        new_up = self._fmt_uptime(time.time() - self._boot_ts)
        if new_up != self._uptime_str:
            self._uptime_str = new_up
            self._dirty = True
            return True
        return False

    def render(self, canvas: skia.Canvas) -> None:
        t = self.theme
        w, h = self.rect.w, self.rect.h
        fill_bg(canvas, w, h, t.bg)

        title_font = t.font("regular", t.label_size, bold=True)
        label_font = t.font("regular", t.label_size - 2, bold=False)
        value_font = t.font("mono", t.label_size - 2, bold=False)

        # 4 行紧凑排:hostname(粗) / IP / UP / LOAD
        # 行高 14px:14 * 4 + 4 padding = 60px 内塞进 62 px
        y1 = t.label_size                    # ≈ 14
        y2 = y1 + 14                          # ≈ 28
        y3 = y2 + 14                          # ≈ 42
        y4 = y3 + 14                          # ≈ 56

        # 第 1 行:hostname(粗体主色)
        canvas.drawString(self._hostname or "—", 0, y1,
                          title_font, t.paint(t.fg))

        # 第 2 行:IP
        canvas.drawString("IP", 0, y2, label_font, t.paint(t.muted))
        draw_text_right(canvas, self._ip or "—", w, y2, value_font, t.fg)

        # 第 3 行:UP
        canvas.drawString("UP", 0, y3, label_font, t.paint(t.muted))
        draw_text_right(canvas, self._uptime_str or "—", w, y3,
                        value_font, t.fg)

        # 第 4 行:LOAD 1/5/15。> cpu_count 视为过载 → 主色标红
        # 简单起见,>2 就着色警示(树莓派 4B 有 4 核,>4 才是真过载,>2 已经忙)
        canvas.drawString("LD", 0, y4, label_font, t.paint(t.muted))
        # 用 load_str 里第一个数值判断色阶
        try:
            l1 = float(self._load_str.split()[0]) if self._load_str else 0.0
        except (ValueError, IndexError):
            l1 = 0.0
        if l1 >= 4.0:
            load_color = t.danger
        elif l1 >= 2.0:
            load_color = t.warn
        else:
            load_color = t.fg
        draw_text_right(canvas, self._load_str or "—", w, y4,
                        value_font, load_color)

