"""CLI 入口:python -m screan [--config PATH]
默认查找配置位置:CWD/config.toml → /opt/screan/config.toml → 包内默认。
"""
from __future__ import annotations
import argparse
import asyncio
import os
import sys

from . import __version__
from .app import Screan
from .config import default_config_path, load
from .util.log import get_logger, setup as log_setup


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="screan",
        description="Industrial monitor for ILI9488 sub-display",
    )
    parser.add_argument("-c", "--config", help="path to config.toml")
    parser.add_argument("--log-level", default="INFO",
                        choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    parser.add_argument("--no-journal", action="store_true",
                        help="不带 journald 优先级前缀(开发用)")
    parser.add_argument("--version", action="version", version=f"screan {__version__}")
    args = parser.parse_args(argv)

    # systemd 会设置 JOURNAL_STREAM,以此自动切换日志格式
    journal = (not args.no_journal) and (os.environ.get("JOURNAL_STREAM") is not None)
    log_setup(level=args.log_level, journal=journal)
    log = get_logger("screan")

    try:
        cfg_path = args.config or default_config_path()
        log.info("using config: %s", cfg_path)
        cfg = load(cfg_path)
    except Exception as e:
        log.error("config load failed: %s", e)
        return 2

    app = Screan(cfg)
    try:
        return asyncio.run(app.run())
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
