"""Widget 抽象基类。

设计要点:
 - update(metrics) 在数据到来时调用,返回 True 表示视觉立刻需要变化
 - tick(dt)        在每帧调用,返回 True 表示有动画进行中需要继续渲染
   widget 内部用 AnimatedValue 实现进度条平滑过渡;无动画时返回 False
 - render(canvas) 时 canvas 已被 compositor translate 到 widget 左上角,
   widget 的坐标系是 (0, 0) → (rect.w, rect.h),不需要知道全局坐标。
 - dirty 在 update / tick 任一返回 True 时由 compositor 置位;
   render 完后由 compositor 调用 clear_dirty。
 - dirty_subrect: 可选的本地子矩形(widget 局部坐标系),表示"实际视觉变化"
   只在子区域内。None = 整个 widget 都变。compositor 据此最小化 SPI 传输。
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Optional

import skia

from ..collect.state import Metrics
from ..render.theme import Theme
from ..util.rect import Rect


class Widget(ABC):
    # widget 是否要求脏区 RGB888 → RGB666 时开启抖动。
    # UI/文字 widget (纯色为主)保持 False,避免噪点;photo/image widget 置 True,
    # 缓解 ILI9488 只用高 6 位造成的色带/马赛克。
    wants_dither: bool = False

    def __init__(self, rect: Rect, theme: Theme):
        self.rect = rect
        self.theme = theme
        self._dirty = True   # 首次必绘
        self._dirty_subrect: Optional[Rect] = None  # None = 整 widget

    @property
    def dirty(self) -> bool:
        return self._dirty

    @property
    def dirty_global_rect(self) -> Rect:
        """返回需要 SPI 传输的屏幕全局矩形。
        widget 在 tick 中可设置 self._dirty_subrect 把传输面积压缩到子区。"""
        if self._dirty_subrect is None:
            return self.rect
        s = self._dirty_subrect
        return Rect(self.rect.x + s.x, self.rect.y + s.y, s.w, s.h)

    def clear_dirty(self) -> None:
        self._dirty = False
        self._dirty_subrect = None

    def mark_dirty(self, subrect: Optional[Rect] = None) -> None:
        """置脏。subrect=None 表示整 widget 脏。
        多次调用时,"整 widget"优先级高于"子区"。"""
        if subrect is None:
            self._dirty_subrect = None
        elif not self._dirty:
            self._dirty_subrect = subrect
        # 已经 dirty 时:若旧值是 None(整框)保持;若旧值是 subrect,沿用第一个(简化)
        self._dirty = True

    @abstractmethod
    def update(self, m: Metrics) -> bool:
        """吸收新数据;若 widget 视觉需要变化,置脏并返回 True。"""

    def tick(self, dt: float) -> bool:
        """推进动画。默认无动画,返回 False。
        有动画的 widget 重写此方法,在动画完成前每次都返回 True。"""
        return False

    @abstractmethod
    def render(self, canvas: skia.Canvas) -> None:
        """在 (0,0) → (rect.w, rect.h) 局部坐标系内绘制完整 widget。
        必须先填充 widget 背景(本框区域),因为脏区刷新会覆盖旧像素。"""
