"""主题:颜色/字体/间距/苹果克制风的视觉常量。

集中在这里方便日后从 config.toml 装载,目前先硬编码默认值。
所有颜色都用 skia.Color(r,g,b),Paint 对象按需创建(轻量,不缓存也行)。
"""
from __future__ import annotations
from dataclasses import dataclass, field
import skia


def rgb(r: int, g: int, b: int, a: int = 255) -> int:
    return skia.Color(r, g, b, a)


@dataclass(slots=True)
class Theme:
    # ---- 颜色 ----
    bg: int = rgb(0xF5, 0xF5, 0xF7)         # 浅灰背景(苹果系)
    surface: int = rgb(0xFF, 0xFF, 0xFF)    # 卡片白
    fg: int = rgb(0x1D, 0x1D, 0x1F)         # 主深字
    fg_secondary: int = rgb(0x6E, 0x6E, 0x73)
    muted: int = rgb(0x86, 0x86, 0x8B)      # 辅助灰
    track: int = rgb(0xE5, 0xE5, 0xEA)      # 进度条轨道
    accent: int = rgb(0x0A, 0x84, 0xFF)     # 蓝
    warn: int = rgb(0xFF, 0x9F, 0x0A)       # 橙
    danger: int = rgb(0xFF, 0x45, 0x3A)     # 红
    success: int = rgb(0x32, 0xD7, 0x4D)    # 绿

    # ---- 字体 ----
    font_regular: str = "DejaVu Sans"
    font_mono: str = "DejaVu Sans Mono"

    # ---- 尺寸 ----
    title_size: float = 22.0
    label_size: float = 14.0
    label_size_lg: float = 20.0      # 进度条 widget 的标签字号(显眼)
    value_size: float = 30.0
    value_size_md: float = 20.0      # 进度条 widget 的数值字号
    bar_radius: float = 8.0
    bar_height: int = 10
    padding: int = 16
    row_gap: int = 12

    # ---- 字体对象缓存 ----
    _fonts: dict = field(default_factory=dict, repr=False)

    def font(self, key: str = "regular", size: float | None = None,
             bold: bool = False) -> skia.Font:
        """惰性创建并缓存 Font 对象。Font 在 skia-python 里相对昂贵,缓存值得。"""
        family = self.font_mono if key == "mono" else self.font_regular
        size = size if size is not None else self.label_size
        cache_key = (family, size, bold)
        if cache_key not in self._fonts:
            style = skia.FontStyle.Bold() if bold else skia.FontStyle.Normal()
            tf = skia.Typeface(family, style)
            f = skia.Font(tf, size)
            f.setSubpixel(True)
            f.setEdging(skia.Font.Edging.kAntiAlias)
            self._fonts[cache_key] = f
        return self._fonts[cache_key]

    def paint(self, color: int, *, stroke: float = 0.0) -> skia.Paint:
        """便利构造:抗锯齿是默认开的。"""
        p = skia.Paint(Color=color, AntiAlias=True)
        if stroke > 0:
            p.setStyle(skia.Paint.kStroke_Style)
            p.setStrokeWidth(stroke)
        return p
