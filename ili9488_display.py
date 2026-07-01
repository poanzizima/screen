#!/usr/bin/env python3
"""
ILI9488 3.5寸 TFT显示屏驱动程序
接线配置:
- VCC: 3.3V
- GND: GND
- CLK: GPIO 11 (SCLK)
- MOSI: GPIO 10 (MOSI)
- CS: GPIO 7 (CE1)
- DC/RS: GPIO 25
- RESET: GPIO 24
- BLK: GPIO 18 (PWM调光)
"""

import spidev
import RPi.GPIO as GPIO
import time
import numpy as np
from PIL import Image, ImageDraw, ImageFont

# ILI9488 命令定义
ILI9488_SWRESET = 0x01
ILI9488_SLPOUT = 0x11
ILI9488_DISPOFF = 0x28
ILI9488_DISPON = 0x29
ILI9488_CASET = 0x2A
ILI9488_PASET = 0x2B
ILI9488_RAMWR = 0x2C
ILI9488_MADCTL = 0x36
ILI9488_PIXFMT = 0x3A
ILI9488_FRMCTR1 = 0xB1
ILI9488_DFUNCTR = 0xB6
ILI9488_PWCTR1 = 0xC0
ILI9488_PWCTR2 = 0xC1
ILI9488_VMCTR1 = 0xC5
ILI9488_GMCTRP1 = 0xE0
ILI9488_GMCTRN1 = 0xE1

# MADCTL 参数
MADCTL_MY = 0x80
MADCTL_MX = 0x40
MADCTL_MV = 0x20
MADCTL_ML = 0x10
MADCTL_RGB = 0x00
MADCTL_BGR = 0x08
MADCTL_MH = 0x04

class ILI9488:
    def __init__(self, width=320, height=480, spi_bus=0, spi_device=1,
                 dc_pin=25, rst_pin=24, bl_pin=18, rotation=0,
                 col_offset=0, row_offset=0, spi_speed_hz=4000000):
        self.width = width
        self.height = height
        self.dc_pin = dc_pin
        self.rst_pin = rst_pin
        self.bl_pin = bl_pin
        self.rotation = rotation
        self.col_offset = col_offset
        self.row_offset = row_offset
        
        # 初始化SPI。灰屏时优先使用较低速率排除线长/杜邦线信号完整性问题。
        self.spi = spidev.SpiDev()
        self.spi.open(spi_bus, spi_device)
        self.spi.max_speed_hz = spi_speed_hz
        self.spi.mode = 0
        self.spi.bits_per_word = 8
        self.spi.lsbfirst = False
        self.spi.no_cs = False
        
        # 初始化GPIO
        GPIO.setmode(GPIO.BCM)
        GPIO.setwarnings(False)
        GPIO.setup(self.dc_pin, GPIO.OUT)
        GPIO.setup(self.rst_pin, GPIO.OUT)
        GPIO.setup(self.bl_pin, GPIO.OUT)
        
        # 初始化PWM背光
        self.bl_pwm = GPIO.PWM(self.bl_pin, 1000)  # 1kHz
        self.bl_pwm.start(0)
        
        # 初始化显示
        self.reset()
        self.init_display()
        self.set_rotation(rotation)
        
    def reset(self):
        """复位显示屏。拉高后等待足够时间，避免复位刚释放就发送初始化命令。"""
        GPIO.output(self.rst_pin, GPIO.HIGH)
        time.sleep(0.05)
        GPIO.output(self.rst_pin, GPIO.LOW)
        time.sleep(0.12)
        GPIO.output(self.rst_pin, GPIO.HIGH)
        time.sleep(0.25)
        
    def send_command(self, cmd):
        """发送命令"""
        GPIO.output(self.dc_pin, GPIO.LOW)
        self.spi.xfer2([cmd])
        
    def send_data(self, data):
        """发送数据"""
        GPIO.output(self.dc_pin, GPIO.HIGH)
        if isinstance(data, list):
            self.spi.xfer2(data)
        else:
            self.spi.xfer2([data])
            
    def init_display(self):
        """初始化显示屏 - 使用标准ILI9488初始化序列"""
        # 软件复位
        self.send_command(ILI9488_SWRESET)
        time.sleep(0.2)
        
        # 退出睡眠模式
        self.send_command(ILI9488_SLPOUT)
        time.sleep(0.15)
        
        # 电源控制 1
        self.send_command(ILI9488_PWCTR1)
        self.send_data([0x17, 0x15])  # VRH1=4.60V, VRH2=4.40V
        
        # 电源控制 2
        self.send_command(ILI9488_PWCTR2)
        self.send_data(0x41)
        
        # VCOM 控制
        self.send_command(ILI9488_VMCTR1)
        self.send_data([0x00, 0x12, 0x80])
        
        # 内存访问控制
        self.send_command(ILI9488_MADCTL)
        self.send_data(0xE8)  # 尝试不同的方向设置
        
        # 像素格式 - 使用18位 RGB666
        self.send_command(ILI9488_PIXFMT)
        self.send_data(0x66)  # 18-bit RGB666
        
        # 帧率控制 - 正常模式
        self.send_command(ILI9488_FRMCTR1)
        self.send_data([0xA0, 0x11])
        
        # 显示功能控制
        self.send_command(ILI9488_DFUNCTR)
        self.send_data([0x02, 0x02, 0x3B])
        
        # 接口控制
        self.send_command(0xF6)
        self.send_data([0x01, 0x00, 0x00])
        
        # Gamma 校正
        self.send_command(ILI9488_GMCTRP1)
        self.send_data([0x00, 0x09, 0x0F, 0x0E, 0x08, 0x14, 0x0F, 0x0B,
                        0x12, 0x09, 0x11, 0x06, 0x0C, 0x07, 0x00])
        
        self.send_command(ILI9488_GMCTRN1)
        self.send_data([0x00, 0x09, 0x0F, 0x0E, 0x08, 0x03, 0x0E, 0x0B,
                        0x12, 0x09, 0x11, 0x06, 0x04, 0x07, 0x00])
        
        # 开启显示
        self.send_command(ILI9488_DISPON)
        time.sleep(0.1)
        
    def set_window(self, x0, y0, x1, y1):
        """设置显示窗口 - 应用偏移量"""
        # 应用列偏移
        x0 += self.col_offset
        x1 += self.col_offset
        # 应用行偏移
        y0 += self.row_offset
        y1 += self.row_offset
        
        self.send_command(ILI9488_CASET)
        self.send_data([x0 >> 8, x0 & 0xFF, x1 >> 8, x1 & 0xFF])
        
        self.send_command(ILI9488_PASET)
        self.send_data([y0 >> 8, y0 & 0xFF, y1 >> 8, y1 & 0xFF])
        
        self.send_command(ILI9488_RAMWR)
        
    def set_rotation(self, rotation):
        """设置屏幕旋转角度"""
        self.rotation = rotation % 4
        self.send_command(ILI9488_MADCTL)
        
        # MADCTL: 翻转 MX 位以修正左右镜像;BGR 顺序保持不变
        if self.rotation == 0:
            self.send_data(0x48)  # MX | BGR  竖屏 0°
            self.width, self.height = 320, 480
        elif self.rotation == 1:
            self.send_data(0x28)  # MV | BGR  横屏 90°
            self.width, self.height = 480, 320
        elif self.rotation == 2:
            self.send_data(0x88)  # MY | BGR  竖屏 180°
            self.width, self.height = 320, 480
        elif self.rotation == 3:
            self.send_data(0xE8)  # MX|MY|MV | BGR  横屏 270°
            self.width, self.height = 480, 320
            
    def clear(self, color=0x000000):
        """清屏 - 使用RGB666 18位，分批传输"""
        self.set_window(0, 0, self.width - 1, self.height - 1)
        r = (color >> 16) & 0xFF
        g = (color >> 8) & 0xFF
        b = color & 0xFF
        
        GPIO.output(self.dc_pin, GPIO.HIGH)
        # RGB666 格式: 每像素3字节
        chunk = [r, g, b] * 1365  # 1365像素 = 4095字节
        total_pixels = self.width * self.height
        remaining = total_pixels
        
        while remaining > 0:
            send_size = min(remaining, 1365)
            if send_size < 1365:
                chunk = [r, g, b] * send_size
            self.spi.xfer2(chunk)
            remaining -= send_size
        
    def display_image(self, image):
        """显示PIL图像 - 使用RGB666 18位"""
        if image.mode != 'RGB':
            image = image.convert('RGB')
        
        if image.size != (self.width, self.height):
            image = image.resize((self.width, self.height), Image.LANCZOS)
            
        self.set_window(0, 0, self.width - 1, self.height - 1)
        
        pixel_data = list(image.getdata())
        data = []
        for pixel in pixel_data:
            r, g, b = pixel
            # RGB666 直接使用像素值
            data.extend([r, g, b])
            
        GPIO.output(self.dc_pin, GPIO.HIGH)
        # 分批发送避免内存问题
        chunk_size = 4095  # 1365 * 3
        for i in range(0, len(data), chunk_size):
            self.spi.xfer2(data[i:i+chunk_size])
        
    def set_backlight(self, brightness):
        """设置背光亮度 (0-100)"""
        brightness = max(0, min(100, brightness))
        self.bl_pwm.ChangeDutyCycle(brightness)
        
    def cleanup(self):
        """清理资源"""
        self.clear()
        self.set_backlight(0)
        self.spi.close()
        self.bl_pwm.stop()
        GPIO.cleanup()


def demo():
    """演示程序 - 尝试不同的偏移量"""
    print("初始化 ILI9488 显示屏...")
    # 尝试使用列偏移（某些3.5寸屏需要）
    display = ILI9488(col_offset=0, row_offset=0)
    
    try:
        # 打开背光
        display.set_backlight(80)
        print("背光已开启 (80%)")
        
        # 清屏为蓝色
        print("清屏为蓝色...")
        display.clear(0x0000FF)
        time.sleep(1)
        
        # 清屏为绿色
        print("清屏为绿色...")
        display.clear(0x00FF00)
        time.sleep(1)
        
        # 清屏为红色
        print("清屏为红色...")
        display.clear(0xFF0000)
        time.sleep(1)
        
        # 创建测试图像
        print("创建测试图像...")
        img = Image.new('RGB', (320, 480), color='black')
        draw = ImageDraw.Draw(img)
        
        # 绘制彩色条纹
        colors = [0xFF0000, 0xFF7F00, 0xFFFF00, 0x00FF00, 0x0000FF, 0x4B0082, 0x9400D3]
        bar_height = 480 // len(colors)
        for i, color in enumerate(colors):
            r = (color >> 16) & 0xFF
            g = (color >> 8) & 0xFF
            b = color & 0xFF
            draw.rectangle([0, i * bar_height, 320, (i + 1) * bar_height], 
                          fill=(r, g, b))
        
        # 绘制文字
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 24)
        except:
            font = ImageFont.load_default()
        
        draw.text((10, 10), "ILI9488 TFT Display", fill=(255, 255, 255), font=font)
        draw.text((10, 50), "320x480 3.5 inch", fill=(255, 255, 255), font=font)
        draw.text((10, 90), "Raspberry Pi 4B", fill=(255, 255, 255), font=font)
        draw.text((10, 130), "SPI Interface", fill=(255, 255, 255), font=font)
        
        # 绘制一些图形
        draw.rectangle([50, 200, 150, 300], outline=(255, 255, 255), width=3)
        draw.ellipse([170, 200, 270, 300], outline=(255, 255, 0), width=3)
        draw.line([50, 350, 270, 350], fill=(0, 255, 255), width=5)
        
        display.display_image(img)
        print("测试图像显示完成")
        
        # 测试背光调节
        print("测试背光调节...")
        for brightness in [100, 75, 50, 25, 50, 75, 100]:
            display.set_backlight(brightness)
            time.sleep(0.5)
            
        print("演示完成! 按 Ctrl+C 退出")
        while True:
            time.sleep(1)
            
    except KeyboardInterrupt:
        print("\n退出中...")
    finally:
        display.cleanup()
        print("已清理资源")


if __name__ == "__main__":
    demo()