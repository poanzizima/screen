"""天气 widget:大图标 + 气温 + 描述 + 城市。

数据来源:wttr.in(免费,无需 API key),30 分钟刷新一次。
图标用 Skia 自绘几何图形(见 _weather_icons.py),不依赖 Emoji 字体
—— 树莓派默认字体覆盖不全,渲不出 emoji。

未取到数据(冷启动/网络断)时显示 "…" 占位,不报错。

布局(144×128 右下角):
    ┌──────────────┐
    │ WEATHER      │
    │              │
    │      ☀       │  大图标(自绘)
    │    23 °C     │  当前气温
    │  Sunny       │  描述
    │  Shanghai    │  城市
    └──────────────┘
"""
from __future__ import annotations
import skia

from ..collect.state import Metrics
from .base import Widget
from ._draw import draw_text, fill_bg, measure_text
from ._weather_icons import draw_weather_icon


class WeatherWidget(Widget):
    def __init__(self, rect, theme):
        super().__init__(rect, theme)
        self._ok: bool = False
        self._temp_c: float = 0.0
        self._feels_c: float = 0.0
        self._desc: str = ""
        self._code: int = 0
        self._loc: str = ""
        # 首次数据到达前显示占位
        self._first_data: bool = False

    def update(self, m: Metrics) -> bool:
        if not m.weather_ok:
            if self._first_data and self._ok:
                self._ok = False
                self._dirty = True
                return True
            return False

        changed = (
            not self._ok
            or round(m.weather_temp_c, 0) != round(self._temp_c, 0)
            or round(m.weather_feels_c, 0) != round(self._feels_c, 0)
            or m.weather_desc != self._desc
            or m.weather_code != self._code
            or m.weather_location != self._loc
        )
        if changed:
            self._ok = True
            self._first_data = True
            self._temp_c = m.weather_temp_c
            self._feels_c = m.weather_feels_c
            self._desc = m.weather_desc
            self._code = m.weather_code
            self._loc = m.weather_location
            self._dirty = True
            return True
        return False

    def render(self, canvas: skia.Canvas) -> None:
        t = self.theme
        w, h = self.rect.w, self.rect.h
        fill_bg(canvas, w, h, t.bg)

        label_font = t.font("regular", t.label_size, bold=False)
        temp_font = t.font("mono", t.label_size_lg, bold=True)
        desc_font = t.font("regular", t.label_size - 2, bold=False)
        loc_font = t.font("regular", t.label_size - 2, bold=False)

        # 标签
        draw_text(canvas, "WEATHER", 0, t.label_size, label_font, t.muted)

        if not self._first_data:
            hint = "…"
            hw, _ = measure_text(hint, temp_font)
            draw_text(canvas, hint, (w - hw) / 2, h / 2 + 8, temp_font, t.muted)
            return

        # 图标:居中偏上,占约 48px 见方
        icon_size = 48
        icon_cx = w / 2
        icon_cy = t.label_size + 6 + icon_size / 2
        draw_weather_icon(canvas, self._code, icon_cx, icon_cy, icon_size, t)

        # 气温:图标下方,大字
        temp_str = f"{round(self._temp_c)}°C"
        tw, _ = measure_text(temp_str, temp_font)
        temp_baseline = icon_cy + icon_size / 2 + t.label_size_lg
        color = t.fg
        if self._temp_c >= 32:
            color = t.danger
        elif self._temp_c >= 28:
            color = t.warn
        elif self._temp_c <= 0:
            color = t.accent
        draw_text(canvas, temp_str, (w - tw) / 2, temp_baseline, temp_font, color)

        # 描述
        if self._desc:
            desc_baseline = temp_baseline + 14
            canvas.save()
            canvas.clipRect(skia.Rect.MakeXYWH(0, desc_baseline - t.label_size,
                                                w, t.label_size + 4))
            dw, _ = measure_text(self._desc, desc_font)
            draw_text(canvas, self._desc, max(0, (w - dw) / 2),
                      desc_baseline, desc_font, t.fg_secondary)
            canvas.restore()

        # 城市:底部
        if self._loc:
            canvas.save()
            canvas.clipRect(skia.Rect.MakeXYWH(0, h - t.label_size,
                                                w, t.label_size + 4))
            lw, _ = measure_text(self._loc, loc_font)
            draw_text(canvas, self._loc, max(0, (w - lw) / 2),
                      h - 4, loc_font, t.muted)
            canvas.restore()
