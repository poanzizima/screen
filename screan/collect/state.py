"""Metrics:不可变的系统指标快照。

每次采集后构造一个新实例,推给渲染层。frozen + slots 确保:
 - 不可篡改(并发安全)
 - 内存紧凑
 - widget 比较脏判断时,语义清晰(看字段是否变化)
"""
from __future__ import annotations
from dataclasses import dataclass, field, replace
from typing import Tuple


@dataclass(frozen=True, slots=True)
class Metrics:
    ts: float = 0.0
    # CPU
    cpu_percent: float = 0.0
    cpu_per_core: Tuple[float, ...] = ()
    # 内存
    mem_percent: float = 0.0
    mem_used: int = 0            # bytes
    mem_total: int = 0
    # 温度
    temp_c: float = 0.0
    throttled: int = 0           # vcgencmd get_throttled 原始位掩码(0 表健康)
    # 网络
    net_rx_bps: float = 0.0
    net_tx_bps: float = 0.0
    # 磁盘
    disk_percent: float = 0.0
    disk_used: int = 0
    disk_total: int = 0
    # 主机
    hostname: str = ""

    def update(self, **kw) -> "Metrics":
        return replace(self, **kw)
