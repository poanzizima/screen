"""异步分频采样器。

设计:单 asyncio 循环 + 每个源独立的 next_due,避免起 N 个 Task。
阻塞 IO(disk/throttled subprocess)走 run_in_executor,不挡循环。
每次有新数据 → 调用 on_update(metrics)。
"""
from __future__ import annotations
import asyncio
import time
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Optional

from . import sources
from .state import Metrics
from ..util.log import get_logger

log = get_logger(__name__)


@dataclass(slots=True)
class _Schedule:
    name: str
    period: float
    next_due: float = 0.0


# 默认采样周期(秒)。可在 SamplerConfig 覆盖。
DEFAULT_PERIODS = {
    "cpu":       0.5,    # 0.5s,够流畅又不抢 CPU
    "load":      2.0,    # loadavg 变化慢,2s 够
    "procs":     3.0,    # /proc 扫描,低频
    "memory":    1.0,
    "temp":      1.0,
    "throttled": 5.0,    # subprocess,贵,低频
    "net":       1.0,
    "netinfo":   5.0,    # SSID/信号/链路速率:iwgetid subprocess,低频
    "disk":      5.0,
    "hostname":  60.0,
    "weather":   1800.0,   # 30 分钟一次,wttr.in 免费服务别打爆
}


@dataclass(slots=True)
class SamplerConfig:
    periods: dict = field(default_factory=lambda: dict(DEFAULT_PERIODS))
    weather_city: str = ""     # "" → 让 wttr.in 按 IP 猜(可能不准);填 "Shanghai" 之类明确定位


class Sampler:
    """on_update 是同步回调,接收 Metrics 不可变快照。
    若需要 async,在回调里 schedule task 即可,避免在采样循环里等渲染。"""

    def __init__(
        self,
        on_update: Callable[[Metrics], None],
        cfg: SamplerConfig | None = None,
    ):
        self.on_update = on_update
        self.cfg = cfg or SamplerConfig()
        self._metrics = Metrics()
        self._net_prev: dict | None = None
        self._stop = asyncio.Event()
        self._schedules = [
            _Schedule(name=k, period=v) for k, v in self.cfg.periods.items()
        ]

    def stop(self) -> None:
        self._stop.set()

    async def run(self) -> None:
        loop = asyncio.get_running_loop()
        # 首轮强制全部采集(立刻给渲染层一个完整快照)
        for s in self._schedules:
            s.next_due = 0.0

        # CPU 预热(psutil 第一次返回 0)
        sources.read_cpu()

        while not self._stop.is_set():
            now = time.monotonic()
            updates: dict = {}

            for s in self._schedules:
                if now < s.next_due:
                    continue
                try:
                    if s.name == "cpu":
                        updates.update(sources.read_cpu())
                    elif s.name == "load":
                        updates.update(sources.read_load())
                    elif s.name == "procs":
                        updates.update(sources.read_procs())
                    elif s.name == "memory":
                        updates.update(sources.read_memory())
                    elif s.name == "temp":
                        updates.update(sources.read_temp())
                    elif s.name == "throttled":
                        val = await loop.run_in_executor(None, sources.read_throttled)
                        updates.update(val)
                    elif s.name == "net":
                        fields, self._net_prev = sources.read_net(self._net_prev)
                        updates.update(fields)
                    elif s.name == "netinfo":
                        val = await loop.run_in_executor(None, sources.read_netinfo)
                        updates.update(val)
                    elif s.name == "disk":
                        val = await loop.run_in_executor(None, sources.read_disk)
                        updates.update(val)
                    elif s.name == "hostname":
                        updates.update(sources.read_hostname())
                    elif s.name == "weather":
                        city = self.cfg.weather_city
                        val = await loop.run_in_executor(
                            None, sources.read_weather, city
                        )
                        updates.update(val)
                except Exception as e:
                    log.warning("source %s failed: %s", s.name, e)
                s.next_due = now + s.period

            if updates:
                self._metrics = self._metrics.update(ts=time.time(), **updates)
                try:
                    self.on_update(self._metrics)
                except Exception:
                    log.exception("on_update callback raised")

            # 下一次最早唤醒
            wakeup = min(s.next_due for s in self._schedules) - time.monotonic()
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=max(0.0, wakeup))
            except asyncio.TimeoutError:
                pass

    @property
    def snapshot(self) -> Metrics:
        return self._metrics
