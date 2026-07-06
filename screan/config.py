"""配置加载 + 校验。

使用 Python 3.11+ 标准库 tomllib(无外部依赖)。
所有 dataclass 都是不可变的,启动后不允许动态改;改了请重启 systemd 服务。
"""
from __future__ import annotations
import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

from .driver.ili9488 import DisplayConfig
from .collect.sampler import SamplerConfig, DEFAULT_PERIODS
from .util.rect import Rect


# ---------------- dataclass ----------------

@dataclass(frozen=True, slots=True)
class WidgetConfig:
    type: str
    rect: Rect
    # image widget 之类需要额外参数(如 path)。dict 不可 hash,故不参与 eq/hash
    options: dict = field(default_factory=dict, compare=False, hash=False)


@dataclass(frozen=True, slots=True)
class RenderConfig:
    max_rects: int = 4
    max_fps: int = 60


@dataclass(frozen=True, slots=True)
class AppConfig:
    display: DisplayConfig
    render: RenderConfig
    sampling: SamplerConfig
    widgets: tuple[WidgetConfig, ...]


# ---------------- 解析 ----------------

def _coerce_display(d: dict) -> DisplayConfig:
    """把 TOML 字典塞到 DisplayConfig,只取存在字段,忽略未知键。"""
    allowed = {f.name for f in fields(DisplayConfig)}
    kw = {k: v for k, v in d.items() if k in allowed}
    return DisplayConfig(**kw)


def _coerce_render(d: dict) -> RenderConfig:
    allowed = {f.name for f in fields(RenderConfig)}
    return RenderConfig(**{k: v for k, v in d.items() if k in allowed})


def _coerce_sampling(d: dict) -> SamplerConfig:
    periods = dict(DEFAULT_PERIODS)
    city = ""
    for k, v in d.items():
        if k in DEFAULT_PERIODS:
            periods[k] = float(v)
        elif k == "weather_city":
            city = str(v).strip()
    return SamplerConfig(periods=periods, weather_city=city)


def _coerce_widgets(items: list[dict], screen_w: int, screen_h: int
                    ) -> tuple[WidgetConfig, ...]:
    from .widgets.registry import WIDGET_TYPES
    out: list[WidgetConfig] = []
    for i, w in enumerate(items):
        type_name = w.get("type")
        if not type_name:
            raise ValueError(f"widget #{i}: missing 'type'")
        if type_name not in WIDGET_TYPES:
            raise ValueError(f"widget #{i}: unknown type {type_name!r}, "
                             f"available: {list(WIDGET_TYPES)}")
        rect = w.get("rect")
        if not (isinstance(rect, list) and len(rect) == 4):
            raise ValueError(f"widget #{i}: rect must be [x,y,w,h]")
        x, y, ww, hh = (int(v) for v in rect)
        if ww <= 0 or hh <= 0:
            raise ValueError(f"widget #{i}: rect w/h must be > 0")
        if x < 0 or y < 0 or x + ww > screen_w or y + hh > screen_h:
            raise ValueError(
                f"widget #{i}: rect {rect} out of screen {screen_w}x{screen_h}"
            )
        # 收集 type/rect 之外的所有字段作为 options(image 用 path 等)
        options = {k: v for k, v in w.items() if k not in ("type", "rect")}
        out.append(WidgetConfig(type=type_name, rect=Rect(x, y, ww, hh),
                                options=options))
    if not out:
        raise ValueError("widgets list is empty")
    return tuple(out)


# ---------------- 入口 ----------------

def load(path: str | Path) -> AppConfig:
    """从 TOML 文件加载配置。文件不存在或字段缺失会抛清晰的异常。"""
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"config file not found: {path}")
    with open(path, "rb") as f:
        data = tomllib.load(f)

    display = _coerce_display(data.get("display", {}))
    # 推断屏幕尺寸用于校验 widget 位置
    if display.rotation in (1, 3):
        screen_w, screen_h = 480, 320
    else:
        screen_w, screen_h = 320, 480

    render = _coerce_render(data.get("render", {}))
    sampling = _coerce_sampling(data.get("sampling", {}))
    widgets = _coerce_widgets(data.get("widgets", []), screen_w, screen_h)
    return AppConfig(display=display, render=render, sampling=sampling, widgets=widgets)


def default_config_path() -> Path:
    """按惯例查找配置:工作目录优先,然后 /opt/screan,然后包内默认。"""
    for p in (Path.cwd() / "config.toml",
              Path("/opt/screan/config.toml"),
              Path(__file__).parent.parent / "config.toml"):
        if p.is_file():
            return p
    raise FileNotFoundError("no config.toml found in CWD, /opt/screan, or package dir")
