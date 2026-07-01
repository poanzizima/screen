"""动画值:把"目标值"平滑过渡到"当前值",用于进度条等视觉过渡。

实现:指数平滑 (exponential smoothing)。每个 tick 把差值缩小固定比例,
渐进逼近目标,前期快、后期慢,符合 CSS ease-out 的视觉感受。

speed=8 时,99% 收敛大约 0.58s。
"""
from __future__ import annotations
import math


class AnimatedValue:
    __slots__ = ("current", "target", "speed", "epsilon")

    def __init__(self, initial: float = 0.0, speed: float = 8.0,
                 epsilon: float = 0.002):
        self.current = float(initial)
        self.target = float(initial)
        self.speed = speed
        self.epsilon = epsilon

    def set_target(self, value: float) -> None:
        self.target = float(value)

    def snap(self, value: float) -> None:
        """跳到目标值(不动画)。用于首次设置或重置。"""
        self.current = self.target = float(value)

    @property
    def animating(self) -> bool:
        return abs(self.target - self.current) > self.epsilon

    def tick(self, dt: float) -> bool:
        """推进动画。返回 True 表示仍在动画中(渲染层应保持帧循环)。"""
        diff = self.target - self.current
        if abs(diff) < self.epsilon:
            if self.current != self.target:
                self.current = self.target
                return True   # 最后一帧吸附到目标
            return False
        alpha = 1.0 - math.exp(-self.speed * max(0.0, dt))
        self.current += diff * alpha
        return True
