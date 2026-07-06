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
    cpu_freq_mhz: float = 0.0     # 当前 CPU 频率 (MHz)。0 表未知
    load_1: float = 0.0           # 1 分钟平均负载
    load_5: float = 0.0
    load_15: float = 0.0
    # 内存
    mem_percent: float = 0.0
    mem_used: int = 0            # bytes
    mem_total: int = 0
    swap_percent: float = 0.0     # swap 使用率
    swap_used: int = 0
    swap_total: int = 0
    # 进程
    proc_count: int = 0
    # 温度
    temp_c: float = 0.0
    throttled: int = 0           # vcgencmd get_throttled 原始位掩码(0 表健康)
    # 网络
    net_rx_bps: float = 0.0
    net_tx_bps: float = 0.0
    # 网络链路(低频采样,5s 一次)
    net_iface: str = ""          # 默认路由接口名,如 wlan0 / eth0;无网时 ""
    net_is_wifi: bool = False    # True → 显示 SSID + signal; False → 显示 speed
    net_ssid: str = ""           # 无线 SSID(未连接为 "")
    net_signal_dbm: int = 0      # 无线 RSSI dBm;0 表未知
    net_link_mbps: int = 0       # 有线协商速率;0 表未知
    net_link_up: bool = False    # operstate == "up"
    # 磁盘
    disk_percent: float = 0.0
    disk_used: int = 0
    disk_total: int = 0
    # 主机
    hostname: str = ""
    # 天气 (wttr.in 30 分钟刷新一次)
    weather_ok: bool = False       # False → 未取到 / 网络失败
    weather_temp_c: float = 0.0    # 当前气温
    weather_feels_c: float = 0.0   # 体感
    weather_desc: str = ""         # "Sunny" / "Partly cloudy" ...
    weather_code: int = 0          # WWO 天气码 → icon 映射
    weather_humidity: int = 0      # %
    weather_wind_kmh: int = 0
    weather_location: str = ""     # 城市名(反显)

    def update(self, **kw) -> "Metrics":
        return replace(self, **kw)
