"""采集源:每个函数读一类指标,返回 dict 字段(后续由 sampler 合并到 Metrics)。

设计原则:
 - 短小,单一职责
 - 用 psutil 的非阻塞 API(cpu_percent(interval=None) 等)
 - 温度直接读 /sys 比 psutil.sensors_temperatures 快几十倍
 - 网络/磁盘速率需要"上一次值",由 sampler 持有
"""
from __future__ import annotations
import os
import socket
import time
from typing import Optional

import psutil


# 第一次调 cpu_percent 会返回 0,所以 sampler 启动前 warm-up
psutil.cpu_percent(interval=None)
psutil.cpu_percent(interval=None, percpu=True)


def read_cpu() -> dict:
    overall = psutil.cpu_percent(interval=None)
    per_core = tuple(psutil.cpu_percent(interval=None, percpu=True))
    return {"cpu_percent": overall, "cpu_per_core": per_core}


def read_memory() -> dict:
    m = psutil.virtual_memory()
    return {
        "mem_percent": m.percent,
        "mem_used": int(m.used),
        "mem_total": int(m.total),
    }


_THERMAL = "/sys/class/thermal/thermal_zone0/temp"


def read_temp() -> dict:
    try:
        with open(_THERMAL) as f:
            raw = f.read().strip()
        return {"temp_c": int(raw) / 1000.0}
    except (OSError, ValueError):
        return {"temp_c": 0.0}


_THROTTLED_PATHS = [
    "/usr/bin/vcgencmd",
    "/opt/vc/bin/vcgencmd",
]


def read_throttled() -> dict:
    """读 vcgencmd get_throttled。位掩码:
        0x1   = under-voltage now
        0x2   = freq capped now
        0x4   = throttled now
        0x10000 = under-voltage occurred
        0x20000 = freq capped occurred
        0x40000 = throttled occurred
    工业级副屏可视化时:当前位>0 高亮告警。
    """
    for path in _THROTTLED_PATHS:
        if not os.path.exists(path):
            continue
        try:
            import subprocess
            out = subprocess.run(
                [path, "get_throttled"], capture_output=True, text=True, timeout=1.0
            )
            # 输出: throttled=0x0
            val = out.stdout.strip().split("=", 1)[-1]
            return {"throttled": int(val, 16)}
        except Exception:
            return {"throttled": 0}
    return {"throttled": 0}


def read_net(prev: dict | None) -> tuple[dict, dict]:
    """返回 (metrics_fields, new_prev)。
    prev: {'ts': float, 'rx': int, 'tx': int}。
    """
    now = time.monotonic()
    io = psutil.net_io_counters()
    rx, tx = int(io.bytes_recv), int(io.bytes_sent)
    if prev is None:
        return {"net_rx_bps": 0.0, "net_tx_bps": 0.0}, {"ts": now, "rx": rx, "tx": tx}
    dt = max(1e-6, now - prev["ts"])
    rx_bps = max(0.0, (rx - prev["rx"]) / dt)
    tx_bps = max(0.0, (tx - prev["tx"]) / dt)
    return ({"net_rx_bps": rx_bps, "net_tx_bps": tx_bps},
            {"ts": now, "rx": rx, "tx": tx})


def read_disk(path: str = "/") -> dict:
    u = psutil.disk_usage(path)
    return {
        "disk_percent": u.percent,
        "disk_used": int(u.used),
        "disk_total": int(u.total),
    }


def read_hostname() -> dict:
    return {"hostname": socket.gethostname()}
