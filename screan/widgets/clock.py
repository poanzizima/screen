"""时钟 widget:大号 HH:MM:SS + 日期。"""
from __future__ import annotations
import time
import skia

from ..collect.state import Metrics
from .base import Widget
from ._draw import draw_text, draw_text_right, fill_bg


class ClockWidget(Widget):
    """显示当前本地时间。1Hz 自更新(不依赖 metrics)。"""

    def __init__(self, rect, theme):
        super().__init__(rect, theme)
        self._last_sec: int = -1
        self._time_str: str = ""
        self._date_str: str = ""

    def update(self, m: Metrics) -> bool:
        # 不依赖 metrics,自己每秒检查
        return self._refresh()

    def tick(self, dt: float) -> bool:
        # 每帧检查秒是否变化(metrics 推送频率可能不到 1Hz)
        return self._refresh()

    def _refresh(self) -> bool:
        now = time.localtime()
        sec_of_day = now.tm_hour * 3600 + now.tm_min * 60 + now.tm_sec
        if sec_of_day == self._last_sec:
            return False
        self._last_sec = sec_of_day
        self._time_str = time.strftime("%H:%M:%S", now)
        self._date_str = time.strftime("%Y-%m-%d %a", now)
        self._dirty = True
        return True

    def render(self, canvas: skia.Canvas) -> None:
        t = self.theme
        w, h = self.rect.w, self.rect.h
        fill_bg(canvas, w, h, t.bg)

        # 大号时间字号:尽量占满高度但留 8px 给日期
        time_size = max(20.0, min(h - 22, w / 4.2))
        time_font = t.font("mono", time_size, bold=True)
        date_font = t.font("regular", t.label_size, bold=False)

        # 时间在上方居中
        tw = time_font.measureText(self._time_str)
        # 简单基线:顶部 padding + 字号
        canvas.drawString(self._time_str, (w - tw) / 2, time_size,
                          time_font, t.paint(t.fg))

        # 日期在底部居中
        dw = date_font.measureText(self._date_str)
        canvas.drawString(self._date_str, (w - dw) / 2, h - 4,
                          date_font, t.paint(t.muted))
