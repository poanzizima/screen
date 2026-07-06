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
    # 频率:psutil.cpu_freq() 在少数系统上返回 None,兜住
    freq_mhz = 0.0
    try:
        f = psutil.cpu_freq()
        if f is not None and f.current:
            freq_mhz = float(f.current)
    except (OSError, AttributeError):
        pass
    return {
        "cpu_percent": overall,
        "cpu_per_core": per_core,
        "cpu_freq_mhz": freq_mhz,
    }


def read_load() -> dict:
    """1/5/15 分钟平均负载。os.getloadavg() 直接读 /proc/loadavg,零成本。"""
    try:
        l1, l5, l15 = os.getloadavg()
        return {"load_1": l1, "load_5": l5, "load_15": l15}
    except OSError:
        return {"load_1": 0.0, "load_5": 0.0, "load_15": 0.0}


def read_procs() -> dict:
    """当前进程数。快速数 /proc 下的数字目录,比 psutil.pids() 快。"""
    try:
        n = sum(1 for name in os.listdir("/proc") if name.isdigit())
        return {"proc_count": n}
    except OSError:
        return {"proc_count": 0}


def read_memory() -> dict:
    m = psutil.virtual_memory()
    s = psutil.swap_memory()
    return {
        "mem_percent": m.percent,
        "mem_used": int(m.used),
        "mem_total": int(m.total),
        "swap_percent": s.percent,
        "swap_used": int(s.used),
        "swap_total": int(s.total),
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


# ---- 天气 (wttr.in) --------------------------------------------------------
# wttr.in 是免费、无需 API key 的天气服务(Igor Chubin,GitHub 20k+ star)。
# 用 ?format=j1 拿 JSON。30 分钟刷一次即可,别打爆人家。
# 网络失败/超时全部静默为 weather_ok=False,不影响其他 widget。
#
# 定位策略:
#   1. config 里手填 weather_city → 直接用
#   2. 否则:先 ip-api.com 拿经纬度(比 wttr.in 内部 GeoIP 库准),缓存 24h
#   3. 拿到经纬度后传给 wttr.in 精确查询
#   4. 全部失败时 fallback 到 wttr.in 默认(按 IP 猜,可能不准)

_WTTR_URL = "https://wttr.in/{q}?format=j1"
_WTTR_TIMEOUT = 6.0
_GEO_URL = "http://ip-api.com/json/?fields=status,city,regionName,lat,lon"
_GEO_TIMEOUT = 4.0
_GEO_CACHE_TTL = 86400.0   # 24h,IP 不太可能天天变

# 模块级缓存,进程生命期内共享
_geo_cache: dict | None = None
_geo_cache_ts: float = 0.0


def _fetch_geo() -> dict | None:
    """从 ip-api.com 拿地理位置。返回 {'lat':..., 'lon':..., 'city':...} 或 None。
    结果缓存 24 小时,避免每次天气刷新都查一遍。"""
    global _geo_cache, _geo_cache_ts
    now = time.monotonic()
    if _geo_cache is not None and (now - _geo_cache_ts) < _GEO_CACHE_TTL:
        return _geo_cache

    import json
    import urllib.request
    try:
        req = urllib.request.Request(_GEO_URL, headers={"User-Agent": "curl/8.0"})
        with urllib.request.urlopen(req, timeout=_GEO_TIMEOUT) as resp:
            data = json.load(resp)
        if data.get("status") != "success":
            return None
        result = {
            "lat": float(data["lat"]),
            "lon": float(data["lon"]),
            "city": data.get("city", ""),
            "region": data.get("regionName", ""),
        }
        _geo_cache = result
        _geo_cache_ts = now
        return result
    except Exception:
        return None


def read_weather(city: str = "") -> dict:
    """取当前天气。city 非空 → 直接用作 wttr.in 查询;否则自动 ip-api 定位。
    慢 IO,必须走 executor。"""
    import json
    import urllib.request
    import urllib.parse

    # 决定查询串
    if city:
        query = urllib.parse.quote(city)
    else:
        geo = _fetch_geo()
        if geo is not None:
            # 用经纬度最精确
            query = f"{geo['lat']:.4f},{geo['lon']:.4f}"
        else:
            query = ""   # fallback: wttr.in 按自己的 IP 库猜

    url = _WTTR_URL.format(q=query)
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "curl/8.0"},   # wttr.in 认 curl UA
        )
        with urllib.request.urlopen(req, timeout=_WTTR_TIMEOUT) as resp:
            data = json.load(resp)
    except Exception:
        return {"weather_ok": False}

    try:
        cur = data["current_condition"][0]
        # location 反显:优先 ip-api 返回的 city(更准),再 fallback wttr.in
        loc = ""
        if not city:
            geo = _geo_cache
            if geo and geo.get("city"):
                loc = geo["city"]
        if not loc:
            area = data.get("nearest_area", [{}])[0]
            for key in ("areaName", "region", "country"):
                arr = area.get(key)
                if arr and arr[0].get("value"):
                    loc = arr[0]["value"]
                    break
        desc = ""
        wd = cur.get("weatherDesc") or []
        if wd:
            desc = wd[0].get("value", "").strip()
        return {
            "weather_ok": True,
            "weather_temp_c": float(cur.get("temp_C", 0)),
            "weather_feels_c": float(cur.get("FeelsLikeC", 0)),
            "weather_desc": desc,
            "weather_code": int(cur.get("weatherCode", 0)),
            "weather_humidity": int(cur.get("humidity", 0)),
            "weather_wind_kmh": int(cur.get("windspeedKmph", 0)),
            "weather_location": loc,
        }
    except (KeyError, IndexError, TypeError, ValueError):
        return {"weather_ok": False}


# ---- 网络链路 (低频,5s 一次) --------------------------------------------
# 目标:一次调用返回默认路由接口的 (iface, is_wifi, ssid, signal_dbm,
# link_mbps, link_up)。全部零依赖读 /proc & /sys;SSID 走 iwgetid subprocess
# (安装 wireless-tools;若不存在则留空,不报错)。

_IWGETID_PATHS = ("/usr/sbin/iwgetid", "/sbin/iwgetid", "/usr/bin/iwgetid")


def _default_iface() -> str:
    """从 /proc/net/route 找默认路由(Destination=0)的接口。
    格式:Iface Destination Gateway Flags RefCnt Use Metric Mask ...
    """
    try:
        with open("/proc/net/route") as f:
            next(f)  # header
            best_metric = None
            best_iface = ""
            for line in f:
                parts = line.split()
                if len(parts) < 8:
                    continue
                if parts[1] != "00000000":  # 只看默认路由
                    continue
                try:
                    metric = int(parts[6])
                except ValueError:
                    continue
                if best_metric is None or metric < best_metric:
                    best_metric = metric
                    best_iface = parts[0]
            return best_iface
    except OSError:
        return ""


def _is_wifi(iface: str) -> bool:
    return bool(iface) and os.path.isdir(f"/sys/class/net/{iface}/wireless")


def _read_operstate(iface: str) -> str:
    try:
        with open(f"/sys/class/net/{iface}/operstate") as f:
            return f.read().strip()
    except OSError:
        return ""


def _read_link_mbps(iface: str) -> int:
    """有线接口协商速率。未 up 时读会返回 EINVAL,忽略。"""
    try:
        with open(f"/sys/class/net/{iface}/speed") as f:
            v = int(f.read().strip())
        return v if v > 0 else 0
    except (OSError, ValueError):
        return 0


def _read_wifi_signal(iface: str) -> int:
    """/proc/net/wireless 第 4 列是 link quality,第 5 列是 signal level(dBm)。
    典型行:  wlan0: 0000   70.  -40.  -256        0      0      0     42        0
    """
    try:
        with open("/proc/net/wireless") as f:
            for line in f:
                line = line.strip()
                if not line.startswith(iface + ":"):
                    continue
                # 去掉 iface: 前缀,split
                rest = line.split(":", 1)[1].split()
                if len(rest) < 3:
                    return 0
                # 第 3 个字段是 signal level (dBm);可能带 "." 后缀
                sig = rest[2].rstrip(".")
                return int(float(sig))
    except (OSError, ValueError, IndexError):
        pass
    return 0


def _read_ssid(iface: str) -> str:
    """iwgetid -r <iface> 输出 SSID。未装 wireless-tools 时静默返回 ""。"""
    for path in _IWGETID_PATHS:
        if not os.path.exists(path):
            continue
        try:
            import subprocess
            out = subprocess.run(
                [path, "-r", iface],
                capture_output=True, text=True, timeout=1.0,
            )
            return out.stdout.strip()
        except Exception:
            return ""
    return ""


def read_netinfo() -> dict:
    """默认路由接口的链路信息。5s 采一次足够。"""
    iface = _default_iface()
    if not iface:
        return {
            "net_iface": "", "net_is_wifi": False, "net_ssid": "",
            "net_signal_dbm": 0, "net_link_mbps": 0, "net_link_up": False,
        }
    up = _read_operstate(iface) == "up"
    wifi = _is_wifi(iface)
    if wifi:
        return {
            "net_iface": iface,
            "net_is_wifi": True,
            "net_ssid": _read_ssid(iface) if up else "",
            "net_signal_dbm": _read_wifi_signal(iface) if up else 0,
            "net_link_mbps": 0,
            "net_link_up": up,
        }
    return {
        "net_iface": iface,
        "net_is_wifi": False,
        "net_ssid": "",
        "net_signal_dbm": 0,
        "net_link_mbps": _read_link_mbps(iface) if up else 0,
        "net_link_up": up,
    }
