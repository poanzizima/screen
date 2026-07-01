"""配置文件加载 / 校验单元测试。"""
import tempfile
from pathlib import Path

import pytest

from screan.config import load


VALID_TOML = """
[display]
rotation = 1
spi_speed_hz = 24000000

[render]
max_rects = 4
max_fps = 60

[sampling]
cpu = 0.5

[[widgets]]
type = "cpu"
rect = [16, 16, 448, 70]

[[widgets]]
type = "memory"
rect = [16, 102, 448, 70]
"""


def _write(content: str) -> str:
    f = tempfile.NamedTemporaryFile("w", delete=False, suffix=".toml")
    f.write(content); f.close()
    return f.name


def test_load_valid():
    p = _write(VALID_TOML)
    cfg = load(p)
    assert cfg.display.rotation == 1
    assert cfg.display.spi_speed_hz == 24_000_000
    assert cfg.render.max_rects == 4
    assert cfg.sampling.periods["cpu"] == 0.5
    assert len(cfg.widgets) == 2
    assert cfg.widgets[0].type == "cpu"
    assert cfg.widgets[0].rect.w == 448


def test_widget_out_of_screen():
    """480x320 横屏下放一个超出边界的 widget"""
    bad = VALID_TOML.replace("rect = [16, 102, 448, 70]",
                              "rect = [16, 102, 600, 70]")
    p = _write(bad)
    with pytest.raises(ValueError, match="out of screen"):
        load(p)


def test_unknown_widget_type():
    bad = VALID_TOML.replace('type = "cpu"', 'type = "nonexistent"')
    p = _write(bad)
    with pytest.raises(ValueError, match="unknown type"):
        load(p)


def test_empty_widgets():
    minimal = """
[display]
rotation = 1
"""
    p = _write(minimal)
    with pytest.raises(ValueError, match="widgets list is empty"):
        load(p)


def test_missing_file():
    with pytest.raises(FileNotFoundError):
        load("/tmp/definitely_not_a_real_config_file_xyz.toml")


def test_portrait_screen_dimensions():
    """rotation=0 → 320x480,widget 校验应按竖屏判断"""
    portrait = VALID_TOML.replace("rotation = 1", "rotation = 0")
    portrait = portrait.replace("rect = [16, 16, 448, 70]",
                                  "rect = [16, 16, 300, 70]")
    portrait = portrait.replace("rect = [16, 102, 448, 70]",
                                  "rect = [16, 102, 300, 70]")
    p = _write(portrait)
    cfg = load(p)
    assert cfg.display.rotation == 0
    assert cfg.widgets[0].rect.w == 300
