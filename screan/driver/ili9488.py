"""ILI9488 驱动 — lgpio + spidev + 24 MHz + RGB666 + update_region。

设计要点:
 - GPIO 用 lgpio(内核 6.x 上 RPi.GPIO 已弃用)
 - 背光用 lgpio.tx_pwm(GPIO18 = PWM0 硬件通道)
 - 像素格式 RGB666(ILI9488 4-line SPI 硬限制,RGB565 会全白)
 - update_region(x,y,w,h,buf) 是核心 API:set_window + RAMWR + writebytes2
 - 关键边界:Rect 必须 2 像素对齐(已由 util/rect.py 保证)
 - shutdown 目标 < 200ms:关背光 + DISPOFF + 释放资源,不做整屏填黑

与原 ili9488_display.py 的差异:
 - GPIO 栈从 RPi.GPIO 改为 lgpio
 - 砍掉 PIL 依赖(由上层 Skia 渲染并预转字节后传入)
 - 新增 update_region,clear 仍保留(用 solid_rgb666 + update_region 实现)
 - speed 从 4M 提到 24M(spike 验证通过)
"""
from __future__ import annotations
import time
from dataclasses import dataclass

import lgpio
import spidev

from .colorconv import solid_rgb666
from ..util.log import get_logger

log = get_logger(__name__)

# ILI9488 命令
_SWRESET, _SLPOUT = 0x01, 0x11
_DISPOFF, _DISPON = 0x28, 0x29
_CASET, _PASET, _RAMWR = 0x2A, 0x2B, 0x2C
_MADCTL, _COLMOD = 0x36, 0x3A

# MADCTL 旋转(已修复镜像后的值)
_MADCTL_ROT = {
    0: 0x48,  # 竖屏 0°    MX | BGR
    1: 0x28,  # 横屏 90°   MV | BGR
    2: 0x88,  # 竖屏 180°  MY | BGR
    3: 0xE8,  # 横屏 270°  MX | MY | MV | BGR
}


@dataclass(frozen=True, slots=True)
class DisplayConfig:
    rotation: int = 1            # 横屏 480×320
    spi_bus: int = 0
    spi_device: int = 1          # CS 在 CE1
    spi_speed_hz: int = 24_000_000
    dc_pin: int = 25
    rst_pin: int = 24
    bl_pin: int = 18
    gpiochip: int = 0            # Pi4 主 bank
    backlight: float = 80.0      # 0..100 启动亮度;>0=点亮,=0=熄灭(纯 GPIO,无 PWM 抖动)
    pwm_hz: int = 0              # 0=纯 GPIO HIGH/LOW(默认);>0=lgpio 软 PWM(有可感知抖动)


class ILI9488:
    """工业级 ILI9488 驱动。线程不安全 — 上层必须串行调用。"""

    def __init__(self, cfg: DisplayConfig | None = None):
        self.cfg = cfg or DisplayConfig()
        if self.cfg.rotation not in _MADCTL_ROT:
            raise ValueError(f"rotation must be 0..3, got {self.cfg.rotation}")
        # 横屏 480×320,竖屏 320×480
        self.width, self.height = (480, 320) if self.cfg.rotation in (1, 3) else (320, 480)
        self._open()
        self._reset()
        self._init_panel()
        self.set_backlight(self.cfg.backlight)
        log.info("ILI9488 ready: %dx%d @ %.0fMHz rot=%d",
                 self.width, self.height, self.cfg.spi_speed_hz / 1e6, self.cfg.rotation)

    # ---------- 底层 I/O ----------
    def _open(self) -> None:
        c = self.cfg
        self._chip = lgpio.gpiochip_open(c.gpiochip)
        # RST 启动时必须为高,否则芯片被一直按住复位
        lgpio.gpio_claim_output(self._chip, c.rst_pin, 1)
        lgpio.gpio_claim_output(self._chip, c.dc_pin, 0)
        lgpio.gpio_claim_output(self._chip, c.bl_pin, 0)

        self._spi = spidev.SpiDev()
        self._spi.open(c.spi_bus, c.spi_device)
        self._spi.max_speed_hz = c.spi_speed_hz
        self._spi.mode = 0
        self._spi.bits_per_word = 8

    def _reset(self) -> None:
        c = self.cfg
        lgpio.gpio_write(self._chip, c.rst_pin, 1); time.sleep(0.05)
        lgpio.gpio_write(self._chip, c.rst_pin, 0); time.sleep(0.12)
        lgpio.gpio_write(self._chip, c.rst_pin, 1); time.sleep(0.25)

    def _cmd(self, byte: int) -> None:
        lgpio.gpio_write(self._chip, self.cfg.dc_pin, 0)
        self._spi.writebytes([byte])

    def _data(self, data) -> None:
        lgpio.gpio_write(self._chip, self.cfg.dc_pin, 1)
        if isinstance(data, int):
            self._spi.writebytes([data])
        elif isinstance(data, (bytes, bytearray, memoryview)):
            self._spi.writebytes2(data)
        else:                                    # list
            self._spi.writebytes2(data)

    def _init_panel(self) -> None:
        """ILI9488 初始化序列。沿用经验证可工作的参数(原 driver 同序列)。"""
        self._cmd(_SWRESET); time.sleep(0.2)
        self._cmd(_SLPOUT); time.sleep(0.15)
        # 电源 / VCOM
        self._cmd(0xC0); self._data([0x17, 0x15])
        self._cmd(0xC1); self._data(0x41)
        self._cmd(0xC5); self._data([0x00, 0x12, 0x80])
        # 方向
        self._cmd(_MADCTL); self._data(_MADCTL_ROT[self.cfg.rotation])
        # 像素格式:RGB666 18bpp(4-line SPI 唯一支持)
        self._cmd(_COLMOD); self._data(0x66)
        # 帧率
        self._cmd(0xB1); self._data([0xA0, 0x11])
        # 显示功能
        self._cmd(0xB6); self._data([0x02, 0x02, 0x3B])
        # Gamma
        self._cmd(0xE0); self._data([0x00, 0x09, 0x0F, 0x0E, 0x08, 0x14, 0x0F, 0x0B,
                                     0x12, 0x09, 0x11, 0x06, 0x0C, 0x07, 0x00])
        self._cmd(0xE1); self._data([0x00, 0x09, 0x0F, 0x0E, 0x08, 0x03, 0x0E, 0x0B,
                                     0x12, 0x09, 0x11, 0x06, 0x04, 0x07, 0x00])
        self._cmd(_DISPON); time.sleep(0.1)

    # ---------- 公共 API ----------
    def set_backlight(self, percent: float) -> None:
        """背光控制。
        默认模式(pwm_hz=0):纯 GPIO HIGH/LOW,工业级稳定无抖动。
            ≥1% 视为全亮(GPIO HIGH),<1% 视为熄灭(GPIO LOW)。
        PWM 模式(pwm_hz>0):lgpio 软件 PWM 实际可调光,但 1 kHz 频率下肉眼可见
            约 ±5% 的亮度脉动(Linux 调度抖动所致)。要真正稳定的 PWM 调光,
            需要 dtoverlay=pwm 启用硬件 PWM(GPIO18 = PWM0)。
        """
        p = max(0.0, min(100.0, float(percent)))
        if self.cfg.pwm_hz <= 0:
            lgpio.gpio_write(self._chip, self.cfg.bl_pin, 1 if p >= 1.0 else 0)
            return
        if p <= 0.01:
            lgpio.tx_pwm(self._chip, self.cfg.bl_pin, self.cfg.pwm_hz, 0.0)
            lgpio.gpio_write(self._chip, self.cfg.bl_pin, 0)
        else:
            lgpio.tx_pwm(self._chip, self.cfg.bl_pin, self.cfg.pwm_hz, p)

    def update_region(self, x: int, y: int, w: int, h: int, buf: bytes) -> None:
        """局部刷新:把 RGB666 字节流写到屏上 (x,y,w,h) 矩形。
        buf 长度必须 = w*h*3,行优先 [R,G,B,...]。"""
        if w <= 0 or h <= 0:
            return
        if x < 0 or y < 0 or x + w > self.width or y + h > self.height:
            raise ValueError(f"region ({x},{y},{w},{h}) out of {self.width}x{self.height}")
        expected = w * h * 3
        if len(buf) != expected:
            raise ValueError(f"buf size {len(buf)} != expected {expected}")

        x1, y1 = x + w - 1, y + h - 1
        self._cmd(_CASET); self._data([x >> 8, x & 0xFF, x1 >> 8, x1 & 0xFF])
        self._cmd(_PASET); self._data([y >> 8, y & 0xFF, y1 >> 8, y1 & 0xFF])
        self._cmd(_RAMWR)
        lgpio.gpio_write(self._chip, self.cfg.dc_pin, 1)
        self._spi.writebytes2(buf)

    def clear(self, r: int = 0, g: int = 0, b: int = 0) -> None:
        """整屏纯色填充。主要用于启动/退出。"""
        self.update_region(0, 0, self.width, self.height,
                           solid_rgb666(self.width, self.height, r, g, b))

    def shutdown(self) -> None:
        """优雅退出:关背光 → DISPOFF → 释放 SPI/GPIO。目标 <200ms。
        不做整屏填黑(整屏 RGB666 写 ~175ms 已逼近预算)。"""
        try:
            self.set_backlight(0)
        except Exception as e:
            log.warning("backlight off failed: %s", e)
        try:
            self._cmd(_DISPOFF)
        except Exception as e:
            log.warning("DISPOFF failed: %s", e)
        try:
            self._spi.close()
        except Exception:
            pass
        try:
            lgpio.gpiochip_close(self._chip)
        except Exception:
            pass
        log.info("ILI9488 shutdown")
