"""Skia Surface 管理:持有常驻 RGBA8888 surface,提供"取一个矩形子区"的接口。

为什么不直接 surface.toarray() 整屏?
 - 整屏 480×320×4 = 614400 B numpy 拷贝,~2ms;
 - 切片再 ascontiguousarray 又一次拷贝;
 - 实际只发脏区,所以**先 toarray 整屏 → 再切脏区切片**是最简单且足够快的。
   480×320 抗锯齿绘制 + toarray + 转 666 + SPI 一次性 ≈ 175ms,瓶颈在 SPI。

如果未来要追求极致,可以用 surface.peekPixels() 拿到 zero-copy 视图,
但 skia-python 144 的 peekPixels 返回 Pixmap,再 .toarray() 还是要拷贝。先不优化。
"""
from __future__ import annotations
import numpy as np
import skia

from ..util.rect import Rect


class Surface:
    def __init__(self, width: int, height: int):
        self.width = width
        self.height = height
        self._surface = skia.Surface(width, height)
        self._canvas = self._surface.getCanvas()

    @property
    def canvas(self) -> skia.Canvas:
        return self._canvas

    def flush(self) -> None:
        self._surface.flushAndSubmit()

    def snapshot_array(self) -> np.ndarray:
        """整屏 RGBA8888 numpy 数组,shape=(H,W,4)。"""
        return self._surface.toarray(colorType=skia.kRGBA_8888_ColorType)

    def snapshot_rect(self, r: Rect) -> np.ndarray:
        """返回 (h, w, 4) uint8 子区(行连续,可直接 tobytes)。"""
        arr = self.snapshot_array()
        sub = arr[r.y:r.y + r.h, r.x:r.x + r.w]
        return np.ascontiguousarray(sub)
