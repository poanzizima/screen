"""天气图标(Skia 自绘几何图形)。

不用 Emoji / 字体图标 —— 树莓派默认字体覆盖不全,渲不出。
所有图标都是矢量原子:圆(太阳/月)、云(3 圆合并 + 圆角矩形底)、
雨滴(斜线)、雪花(星形)、闪电(折线)、雾(3 条横线)。

统一入口 `draw_weather_icon(canvas, code, cx, cy, size, theme)`,size
指图标外接方框的边长(px);cx/cy 为图标中心。
"""
from __future__ import annotations
import math
import skia

from ..render.theme import Theme


# WWO code → 图标 kind。kind 决定绘制函数。
_KIND = {
    113: "sun",
    116: "partly", 119: "cloud", 122: "cloud",
    143: "fog",  248: "fog",   260: "fog",
    149: "fog",   # Smoke haze (wttr.in 扩展码,当雾处理)
    # 雨系列
    176: "rain_light", 263: "rain_light", 266: "rain",
    281: "rain", 284: "rain", 293: "rain_light", 296: "rain",
    299: "rain", 302: "rain", 305: "rain_heavy", 308: "rain_heavy",
    311: "rain", 314: "rain_heavy", 353: "rain_light", 356: "rain",
    359: "rain_heavy",
    # 雪 / 雨夹雪
    179: "sleet", 182: "sleet", 185: "rain_light",
    317: "sleet", 320: "sleet", 362: "sleet", 365: "sleet",
    323: "snow_light", 326: "snow", 329: "snow", 332: "snow",
    335: "snow_heavy", 338: "snow_heavy", 227: "snow",
    230: "snow_heavy", 368: "snow", 371: "snow_heavy",
    350: "sleet", 374: "sleet", 377: "sleet",
    # 雷暴
    200: "thunder", 386: "thunder", 389: "thunder",
    392: "thunder", 395: "thunder",
}


def _paint(color: int, *, stroke: float = 0, fill: bool = False) -> skia.Paint:
    p = skia.Paint(Color=color, AntiAlias=True)
    if fill and stroke == 0:
        p.setStyle(skia.Paint.kFill_Style)
    else:
        p.setStyle(skia.Paint.kStroke_Style)
        p.setStrokeWidth(stroke)
        p.setStrokeCap(skia.Paint.kRound_Cap)
        p.setStrokeJoin(skia.Paint.kRound_Join)
    return p


def _draw_sun(canvas: skia.Canvas, cx: float, cy: float, size: float,
              color: int) -> None:
    """居中的太阳:圆盘 + 8 道光芒。"""
    r_core = size * 0.22
    r_inner = size * 0.32
    r_outer = size * 0.46
    canvas.drawCircle(cx, cy, r_core, _paint(color, fill=True))
    ray_paint = _paint(color, stroke=max(1.5, size * 0.05))
    for i in range(8):
        ang = i * math.pi / 4
        x1 = cx + math.cos(ang) * r_inner
        y1 = cy + math.sin(ang) * r_inner
        x2 = cx + math.cos(ang) * r_outer
        y2 = cy + math.sin(ang) * r_outer
        canvas.drawLine(x1, y1, x2, y2, ray_paint)


def _draw_cloud(canvas: skia.Canvas, cx: float, cy: float, size: float,
                color: int, *, fill: bool = True) -> None:
    """云:3 个不同半径的圆 + 底部圆角矩形合并。"""
    # 基础几何:云横跨 ~size 宽,高 ~size*0.55
    w = size * 0.85
    h = size * 0.55
    left = cx - w / 2
    top = cy - h / 2
    # 三个圆(左小、中大、右中)
    r1 = h * 0.42
    r2 = h * 0.52
    r3 = h * 0.42
    y_c = cy + h * 0.05
    p = _paint(color, fill=True) if fill else _paint(color, stroke=max(1.5, size * 0.05))
    # 用 Path 合并,不留缝
    path = skia.Path()
    path.addCircle(left + r1 * 1.1, y_c - h * 0.05, r1)
    path.addCircle(cx - w * 0.05, y_c - h * 0.18, r2)
    path.addCircle(left + w - r3 * 1.1, y_c - h * 0.02, r3)
    # 底部矩形
    rect = skia.Rect.MakeLTRB(left + r1 * 0.4, y_c - h * 0.05,
                               left + w - r3 * 0.4, y_c + h * 0.35)
    path.addRect(rect)
    canvas.drawPath(path, p)


def _draw_partly(canvas: skia.Canvas, cx: float, cy: float, size: float,
                 sun_color: int, cloud_color: int) -> None:
    """晴间多云:太阳(右上)+ 云(左下,遮挡太阳一部分)。"""
    # 太阳偏右上、缩小
    _draw_sun(canvas, cx + size * 0.18, cy - size * 0.16, size * 0.65,
              sun_color)
    # 云偏左下、盖住太阳一部分
    _draw_cloud(canvas, cx - size * 0.05, cy + size * 0.12, size * 0.85,
                cloud_color)


def _draw_drops(canvas: skia.Canvas, cx: float, cy: float, size: float,
                color: int, n: int) -> None:
    """云下方 n 条斜线代表雨滴。y 从 cy+size*0.15 开始。"""
    stroke = max(1.5, size * 0.045)
    p = _paint(color, stroke=stroke)
    y0 = cy + size * 0.20
    y1 = cy + size * 0.42
    span = size * 0.55
    x_start = cx - span / 2
    gap = span / max(1, n - 1) if n > 1 else 0
    for i in range(n):
        x = x_start + i * gap
        canvas.drawLine(x, y0, x - size * 0.05, y1, p)


def _draw_flakes(canvas: skia.Canvas, cx: float, cy: float, size: float,
                 color: int, n: int) -> None:
    """云下方 n 个雪花(6 芒星)。"""
    stroke = max(1.2, size * 0.035)
    p = _paint(color, stroke=stroke)
    y = cy + size * 0.30
    r = size * 0.06
    span = size * 0.55
    x_start = cx - span / 2
    gap = span / max(1, n - 1) if n > 1 else 0
    for i in range(n):
        x0 = x_start + i * gap
        for k in range(3):
            ang = k * math.pi / 3
            dx = math.cos(ang) * r
            dy = math.sin(ang) * r
            canvas.drawLine(x0 - dx, y - dy, x0 + dx, y + dy, p)


def _draw_bolt(canvas: skia.Canvas, cx: float, cy: float, size: float,
               color: int) -> None:
    """闪电:折线 Z 型。"""
    p = _paint(color, fill=True)
    path = skia.Path()
    s = size
    # 起点在 cx, cy - s*0.05
    path.moveTo(cx + s * 0.05, cy + s * 0.10)
    path.lineTo(cx - s * 0.10, cy + s * 0.10)
    path.lineTo(cx + s * 0.02, cy + s * 0.28)
    path.lineTo(cx - s * 0.08, cy + s * 0.28)
    path.lineTo(cx + s * 0.10, cy + s * 0.50)
    path.lineTo(cx + s * 0.00, cy + s * 0.32)
    path.lineTo(cx + s * 0.12, cy + s * 0.32)
    path.lineTo(cx - s * 0.05, cy + s * 0.10)
    path.close()
    canvas.drawPath(path, p)


def _draw_fog(canvas: skia.Canvas, cx: float, cy: float, size: float,
              color: int) -> None:
    """雾:3 条水平线,交错端点。"""
    stroke = max(2.0, size * 0.07)
    p = _paint(color, stroke=stroke)
    w = size * 0.7
    for i, y_off in enumerate((-0.15, 0.00, 0.15)):
        y = cy + size * y_off
        # 交错缩短
        shrink = 0.15 * (i % 2)
        canvas.drawLine(cx - w / 2 + w * shrink, y,
                        cx + w / 2 - w * (0.1 if i == 1 else 0), y, p)


# --- 主入口 -----------------------------------------------------------------

def draw_weather_icon(canvas: skia.Canvas, code: int, cx: float, cy: float,
                      size: float, theme: Theme) -> None:
    """按天气码在 (cx, cy) 中心画 size×size 的图标。"""
    kind = _KIND.get(code, "sun")
    sun = theme.warn        # 阳光橙黄
    cloud = theme.fg_secondary
    rain = theme.accent
    snow = theme.fg_secondary
    bolt = theme.warn

    if kind == "sun":
        _draw_sun(canvas, cx, cy, size, sun)
    elif kind == "partly":
        _draw_partly(canvas, cx, cy, size, sun, cloud)
    elif kind == "cloud":
        _draw_cloud(canvas, cx, cy, size, cloud)
    elif kind == "fog":
        _draw_fog(canvas, cx, cy, size, cloud)
    elif kind == "rain_light":
        _draw_cloud(canvas, cx, cy - size * 0.12, size * 0.85, cloud)
        _draw_drops(canvas, cx, cy, size, rain, 2)
    elif kind == "rain":
        _draw_cloud(canvas, cx, cy - size * 0.12, size * 0.85, cloud)
        _draw_drops(canvas, cx, cy, size, rain, 3)
    elif kind == "rain_heavy":
        _draw_cloud(canvas, cx, cy - size * 0.12, size * 0.85, cloud)
        _draw_drops(canvas, cx, cy, size, rain, 4)
    elif kind == "snow_light":
        _draw_cloud(canvas, cx, cy - size * 0.12, size * 0.85, cloud)
        _draw_flakes(canvas, cx, cy, size, snow, 2)
    elif kind == "snow":
        _draw_cloud(canvas, cx, cy - size * 0.12, size * 0.85, cloud)
        _draw_flakes(canvas, cx, cy, size, snow, 3)
    elif kind == "snow_heavy":
        _draw_cloud(canvas, cx, cy - size * 0.12, size * 0.85, cloud)
        _draw_flakes(canvas, cx, cy, size, snow, 4)
    elif kind == "sleet":
        _draw_cloud(canvas, cx, cy - size * 0.12, size * 0.85, cloud)
        _draw_drops(canvas, cx - size * 0.12, cy, size, rain, 1)
        _draw_flakes(canvas, cx + size * 0.15, cy, size, snow, 1)
    elif kind == "thunder":
        _draw_cloud(canvas, cx, cy - size * 0.12, size * 0.85, cloud)
        _draw_bolt(canvas, cx, cy, size, bolt)
    else:
        # 兜底:单个圆点 + label 由 widget 显示描述
        canvas.drawCircle(cx, cy, size * 0.1, _paint(cloud, fill=True))
