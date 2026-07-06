"""Widget 名称 → 类 映射。

config.toml 里写 type = "cpu",经此映射查到具体类。
新增 widget 时只需在这里登记。
"""
import inspect
from typing import Type

from .base import Widget
from .clock import ClockWidget
from .cpu import CpuWidget
from .disk import DiskWidget
from .host import HostWidget
from .image import ImageWidget
from .memory import MemoryWidget
from .network import NetworkWidget
from .temperature import TemperatureWidget
from .weather import WeatherWidget


WIDGET_TYPES: dict[str, Type[Widget]] = {
    "clock": ClockWidget,
    "cpu": CpuWidget,
    "disk": DiskWidget,
    "host": HostWidget,
    "image": ImageWidget,
    "memory": MemoryWidget,
    "network": NetworkWidget,
    "temperature": TemperatureWidget,
    "weather": WeatherWidget,
}


def build(type_name: str, *args, **kw) -> Widget:
    if type_name not in WIDGET_TYPES:
        raise KeyError(f"unknown widget type: {type_name!r}. "
                       f"available: {list(WIDGET_TYPES)}")
    cls = WIDGET_TYPES[type_name]
    # 只保留该 widget 构造器实际接受的 kwargs,避免旧 widget 收到多余 path=... 报错
    sig = inspect.signature(cls.__init__)
    params = sig.parameters
    accepts_kwargs = any(
        p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values()
    )
    if not accepts_kwargs:
        kw = {k: v for k, v in kw.items() if k in params}
    return cls(*args, **kw)
