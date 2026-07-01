"""通用绘制工具:进度条 + 文字测量 + 数据格式化。

这些函数在多个 widget 间共享。集中放这里避免重复实现 + 风格不一致。
"""
from __future__ import annotations
import skia

from ..render.theme import Theme


def measure_text(text: str, font: skia.Font) -> tuple[float, float]:
    """返回 (width, ascent_to_descent_height)。"""
    w = font.measureText(text)
    m = font.getMetrics()
    h = -m.fAscent + m.fDescent
    return w, h


def draw_text(canvas: skia.Canvas, text: str, x: float, y_baseline: float,
              font: skia.Font, color: int) -> None:
    paint = skia.Paint(Color=color, AntiAlias=True)
    canvas.drawString(text, x, y_baseline, font, paint)


def draw_text_right(canvas: skia.Canvas, text: str, x_right: float,
                    y_baseline: float, font: skia.Font, color: int) -> None:
    w = font.measureText(text)
    draw_text(canvas, text, x_right - w, y_baseline, font, color)


def draw_bar(canvas: skia.Canvas, x: float, y: float, w: float, h: float,
             ratio: float, *, theme: Theme, color: int) -> None:
    """绘制圆角进度条。ratio 自动 clamp 到 [0,1]。"""
    ratio = max(0.0, min(1.0, ratio))
    radius = h / 2  # 完全圆角(胶囊形)
    # 轨道
    rect_t = skia.Rect.MakeXYWH(x, y, w, h)
    rrect_t = skia.RRect.MakeRectXY(rect_t, radius, radius)
    canvas.drawRRect(rrect_t, theme.paint(theme.track))
    # 填充(至少 h 像素宽,否则圆角看不到)
    fill_w = max(0.0, w * ratio)
    if fill_w >= h:
        rect_f = skia.Rect.MakeXYWH(x, y, fill_w, h)
        rrect_f = skia.RRect.MakeRectXY(rect_f, radius, radius)
        canvas.drawRRect(rrect_f, theme.paint(color))
    elif fill_w > 1.5:
        # 比 2×radius 还窄时,画椭圆,避免变成"细线"
        rect_f = skia.Rect.MakeXYWH(x, y, max(h, fill_w), h)
        rrect_f = skia.RRect.MakeRectXY(rect_f, radius, radius)
        # 用裁剪让它不超过 fill_w
        canvas.save()
        canvas.clipRect(skia.Rect.MakeXYWH(x, y, fill_w, h))
        canvas.drawRRect(rrect_f, theme.paint(color))
        canvas.restore()


def fmt_bytes(n: float) -> str:
    """1234567 → '1.2 MB',对齐紧凑。"""
    n = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            if unit == "B":
                return f"{int(n)} {unit}"
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


def fmt_bps(bps: float) -> str:
    """字节/秒 → 紧凑字符串,如 '1.2 MB/s'。
    带量化:< 1KB/s 时归零显示为 '0 B/s',避免浮点抖动每秒重绘。"""
    if bps < 1024:
        return "0 B/s"
    return fmt_bytes(bps) + "/s"


def fill_bg(canvas: skia.Canvas, w: float, h: float, color: int) -> None:
    """填充 widget 整个区域为背景色 — 脏区重绘必须先盖掉旧像素。"""
    canvas.drawRect(skia.Rect.MakeWH(w, h), skia.Paint(Color=color))
