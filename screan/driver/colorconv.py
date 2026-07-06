"""RGBA8888 (numpy) → RGB666 字节流 (ILI9488 SPI 4-line 唯一支持的格式)。

ILI9488 在 4-line SPI 下硬件限制为 18bpp(每像素 3 字节 R,G,B,低 2 位忽略)。
Skia surface 给出 (H, W, 4) uint8 RGBA;我们丢掉 A,拿前 3 通道连续打包。

关键细节:因为 ILI9488 只用每字节高 6 位,直接截断低 2 位会导致照片的
细腻过渡(尤其人脸、天空)出现马赛克色块。用 Bayer 4×4 有序抖动 (dithering)
把量化误差扩散,视觉上恢复渐变。抖动开销 ~1ms/整屏,是值得的。

抖动开关:solid_rgb666/UI widget 场景不需要抖动(纯色区域反而会因噪点变糙);
只有真实照片(image widget)才需要。rgba_to_rgb666(..., dither=True) 打开。

性能:对 480x320 整屏 ≈ 0.5ms (直通);≈ 1.5ms (抖动)。瓶颈仍在 SPI。
"""
from __future__ import annotations
import numpy as np


# Bayer 4×4 阈值矩阵(0..15) → 抖动偏移。
# 数学:丢弃低 2 位 = 量化步长 4。抖动幅度必须 = ±step/2 = ±2,否则:
#   过大(如 ±16) → 每个像素随机跳几个色级,视觉上是小黑点/彩噪
#   过小(<1)     → 抖动没有跨越量化边界,等于没抖
# 用浮点 (bayer + 0.5) / 16 - 0.5 得到 16 个均匀分布的偏移(-0.469..+0.469),
# 再乘量化步长 4 → -1.875..+1.875,round 后是 -2/-1/0/+1/+2 五种,分布均匀。
_BAYER4_RAW = np.array([
    [ 0,  8,  2, 10],
    [12,  4, 14,  6],
    [ 3, 11,  1,  9],
    [15,  7, 13,  5],
], dtype=np.float32)
_BAYER4_OFFSET = np.round(
    ((_BAYER4_RAW + 0.5) / 16.0 - 0.5) * 4.0
).astype(np.int16)     # -2..+2,16 个位置均匀分布


def rgba_to_rgb666(arr: np.ndarray, *, dither: bool = False) -> bytes:
    """arr: (H, W, 4) uint8 RGBA → bytes 长度 = H*W*3,布局行优先 [R,G,B,...]。

    dither=True 时用 Bayer 4×4 有序抖动补偿 ILI9488 只用高 6 位的信息损失,
    适合照片。dither=False (默认)适合 UI/纯色/文字,不会引入噪点。
    """
    if arr.ndim != 3 or arr.shape[2] < 3 or arr.dtype != np.uint8:
        raise ValueError(f"expect (H,W,>=3) uint8, got shape={arr.shape} dtype={arr.dtype}")
    rgb = arr[..., :3]                       # (H, W, 3) 视图,零拷贝

    if not dither:
        return np.ascontiguousarray(rgb).tobytes()

    # Bayer 抖动:把 4×4 阈值 tile 到整个图,加到 int16 上,clip 回 uint8
    h, w, _ = rgb.shape
    # tile 到 (h, w),再扩到 3 通道
    tiled = np.tile(_BAYER4_OFFSET, ((h + 3) // 4, (w + 3) // 4))[:h, :w]
    offset = tiled[:, :, None]               # (h, w, 1) 广播到 3 通道
    dithered = np.clip(rgb.astype(np.int16) + offset, 0, 255).astype(np.uint8)
    return np.ascontiguousarray(dithered).tobytes()


def solid_rgb666(w: int, h: int, r: int, g: int, b: int) -> bytes:
    """构造单色 RGB666 缓冲(用于清屏/纯色背景)。"""
    pix = np.array([r & 0xFF, g & 0xFF, b & 0xFF], dtype=np.uint8)
    return np.broadcast_to(pix, (h, w, 3)).tobytes()
