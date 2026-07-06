"""图片 widget:显示磁盘上的一张图,自动缩放到 widget 尺寸(保持比例居中)。

设计:
- 每 2 秒检查文件 mtime,变化时重解码(热更换图片)。
- 首次或 rect 尺寸变化 → 重解码。
- 用 PIL 解码保证 RGBA 通道顺序正确(Skia 的 MakeFromEncoded 对 JPEG 有时会
  弄反 R/B 通道,导致画面偏蓝/红),然后手动构造 skia.Image。
- 路径不存在或解码失败:显示占位文字,不崩溃。
- 缩放策略:contain(保持长宽比,居中,四周填 bg)。

配置格式(config.toml):
    [[widgets]]
    type = "image"
    rect = [x, y, w, h]
    path = "/opt/screan/media/xxx.jpg"
"""
from __future__ import annotations
import os
from pathlib import Path
from typing import Optional
import numpy as np
import skia
from PIL import Image as PILImage

from ..collect.state import Metrics
from .base import Widget
from ._draw import draw_text, fill_bg, measure_text


class ImageWidget(Widget):
    # 照片区需要抖动,否则 ILI9488 的 6bit/通道会让皮肤/天空等平滑过渡变成色带
    wants_dither = True

    def __init__(self, rect, theme, *, path: str = ""):
        super().__init__(rect, theme)
        self._path: str = path
        self._image: Optional[skia.Image] = None
        # 保 numpy 数组的引用,确保 skia.Image 生命周期内底层内存不被 GC
        self._pixels: Optional[np.ndarray] = None
        self._mtime: float = 0.0
        self._check_ts: float = 0.0
        self._error: str = ""
        self._decoded_size: tuple[int, int] = (0, 0)
        # 初次立即加载
        self._reload()

    def _reload(self) -> None:
        """从磁盘用 PIL 解码为 RGBA,再包装成 skia.Image。"""
        self._error = ""
        self._image = None
        self._pixels = None
        if not self._path:
            self._error = "no path"
            return
        p = Path(self._path)
        if not p.is_file():
            self._error = f"not found: {p.name}"
            return
        try:
            with PILImage.open(str(p)) as pil:
                # 强制 RGBA:JPEG/BMP 是 RGB,PNG 可能是 P/L/LA,统一转
                # PIL 保证通道顺序 = (R, G, B, A),不会跟平台端序玩花样
                pil = pil.convert("RGBA")
                arr = np.array(pil, dtype=np.uint8)   # (H, W, 4)
            # 用 numpy 数组构造 skia.Image。
            # 必须显式声明 colorType=kRGBA_8888,否则 skia-python 默认走
            # kN32_ColorType (在 ARM/x86 上通常 = BGRA),会把 R/B 通道弄反,
            # 表现为图片偏红或偏蓝。
            img = skia.Image.fromarray(
                arr,
                colorType=skia.ColorType.kRGBA_8888_ColorType,
                alphaType=skia.AlphaType.kUnpremul_AlphaType,
            )
            if img is None:
                self._error = "fromarray fail"
                return
            self._image = img
            self._pixels = arr
            self._decoded_size = (arr.shape[1], arr.shape[0])
            try:
                self._mtime = p.stat().st_mtime
            except OSError:
                self._mtime = 0.0
        except Exception as e:
            self._error = f"err: {type(e).__name__}: {e}"

    def update(self, m: Metrics) -> bool:
        # Metrics 不含图片信息,靠 tick 定时检查 mtime
        return False

    def tick(self, dt: float) -> bool:
        # 每 2 秒检查一次文件是否被替换
        self._check_ts += dt
        if self._check_ts < 2.0:
            return False
        self._check_ts = 0.0
        if not self._path:
            return False
        try:
            new_mtime = os.stat(self._path).st_mtime
        except OSError:
            new_mtime = 0.0
            if self._image is not None or not self._error:
                # 从有到无:重载
                self._reload()
                self._dirty = True
                return True
            return False
        if new_mtime != self._mtime:
            self._reload()
            self._dirty = True
            return True
        return False

    def render(self, canvas: skia.Canvas) -> None:
        t = self.theme
        w, h = self.rect.w, self.rect.h
        fill_bg(canvas, w, h, t.bg)

        if self._image is None:
            # 占位
            label_font = t.font("regular", t.label_size, bold=True)
            small_font = t.font("regular", t.label_size - 2, bold=False)
            draw_text(canvas, "IMG", 0, t.label_size, label_font, t.muted)
            msg = self._error or "loading…"
            mw, _ = measure_text(msg, small_font)
            draw_text(canvas, msg, max(0, (w - mw) / 2), h / 2 + 6,
                      small_font, t.fg_secondary)
            return

        # contain 缩放:保持长宽比,居中
        iw, ih = self._decoded_size
        if iw <= 0 or ih <= 0:
            return
        scale = min(w / iw, h / ih)
        draw_w = iw * scale
        draw_h = ih * scale
        dx = (w - draw_w) / 2
        dy = (h - draw_h) / 2

        src = skia.Rect.MakeXYWH(0, 0, iw, ih)
        dst = skia.Rect.MakeXYWH(dx, dy, draw_w, draw_h)
        # 高质量采样(SPI 传输的是 RGB666,反正带宽是瓶颈)
        paint = skia.Paint(AntiAlias=True)
        canvas.drawImageRect(
            self._image, src, dst,
            skia.SamplingOptions(skia.CubicResampler.Mitchell()),
            paint, skia.Canvas.kStrict_SrcRectConstraint,
        )
