"""RGBA8888 (numpy) → RGB666 字节流 (ILI9488 SPI 4-line 唯一支持的格式)。

ILI9488 在 4-line SPI 下硬件限制为 18bpp(每像素 3 字节 R,G,B,低 2 位忽略)。
Skia surface 给出 (H, W, 4) uint8 RGBA;我们丢掉 A,拿前 3 通道连续打包。

性能:对 480x320 整屏 ≈ 0.5ms;对 120x40 数字块 ≈ 0.02ms。瓶颈在 SPI 不在这里。
"""
from __future__ import annotations
import numpy as np


def rgba_to_rgb666(arr: np.ndarray) -> bytes:
    """arr: (H, W, 4) uint8 RGBA → bytes 长度 = H*W*3,布局行优先 [R,G,B,...]。

    实现:取前三个通道,连续切片 + ascontiguousarray 保证 tobytes() 顺序正确。
    比循环或 struct.pack 快 100×以上。
    """
    if arr.ndim != 3 or arr.shape[2] < 3 or arr.dtype != np.uint8:
        raise ValueError(f"expect (H,W,>=3) uint8, got shape={arr.shape} dtype={arr.dtype}")
    rgb = arr[..., :3]                       # (H, W, 3) 视图,零拷贝
    return np.ascontiguousarray(rgb).tobytes()


def solid_rgb666(w: int, h: int, r: int, g: int, b: int) -> bytes:
    """构造单色 RGB666 缓冲(用于清屏/纯色背景)。"""
    pix = np.array([r & 0xFF, g & 0xFF, b & 0xFF], dtype=np.uint8)
    return np.broadcast_to(pix, (h, w, 3)).tobytes()
