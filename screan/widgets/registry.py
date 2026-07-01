"""Widget 名称 → 类 映射。

config.toml 里写 type = "cpu",经此映射查到具体类。
新增 widget 时只需在这里登记。
"""
from __future__ import annotations
from typing import Type

from .base import Widget
from .clock import ClockWidget
from .cpu import CpuWidget
from .disk import DiskWidget
from .host import HostWidget
from .memory import MemoryWidget
from .network import NetworkWidget
from .temperature import TemperatureWidget


WIDGET_TYPES: dict[str, Type[Widget]] = {
    "clock": ClockWidget,
    "cpu": CpuWidget,
    "disk": DiskWidget,
    "host": HostWidget,
    "memory": MemoryWidget,
    "network": NetworkWidget,
    "temperature": TemperatureWidget,
}


def build(type_name: str, *args, **kw) -> Widget:
    if type_name not in WIDGET_TYPES:
        raise KeyError(f"unknown widget type: {type_name!r}. "
                       f"available: {list(WIDGET_TYPES)}")
    return WIDGET_TYPES[type_name](*args, **kw)
