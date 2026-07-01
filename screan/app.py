"""主应用:asyncio 事件循环 + 信号处理 + systemd 集成。

生命周期:
  load config
  → init display / surface / widgets / compositor
  → render first frame                 (← 首帧后才发 READY=1)
  → start sampler task & render task & watchdog task
  → wait for SIGTERM/SIGINT
  → cancel tasks + display.shutdown()  (目标 <200ms)
"""
from __future__ import annotations
import asyncio
import os
import signal
import sys
import time

import skia

from .collect.sampler import Sampler
from .collect.state import Metrics
from .config import AppConfig
from .driver.ili9488 import ILI9488
from .render.compositor import Compositor
from .render.surface import Surface
from .render.theme import Theme
from .util import sdnotify
from .util.log import get_logger
from .widgets.registry import build as build_widget

log = get_logger(__name__)


class Screan:
    def __init__(self, cfg: AppConfig):
        self.cfg = cfg
        self.theme = Theme()
        self.display = ILI9488(cfg.display)
        # 屏幕尺寸由 display 决定(横/竖)
        self.surface = Surface(self.display.width, self.display.height)
        self.widgets = [
            build_widget(w.type, w.rect, self.theme) for w in cfg.widgets
        ]
        self.compositor = Compositor(
            self.display, self.surface, self.theme, self.widgets,
            max_rects=cfg.render.max_rects,
        )
        self._stop = asyncio.Event()
        self._dirty = asyncio.Event()      # 数据来了置位,渲染循环消费

    # ----- 信号 -----
    def _install_signal_handlers(self) -> None:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                loop.add_signal_handler(sig, self._on_stop)
            except NotImplementedError:
                # Windows 等不支持的平台,这里直接跳过
                pass

    def _on_stop(self) -> None:
        log.info("stop signal received")
        self._stop.set()

    # ----- 回调:采集 -----
    def _on_metrics(self, m: Metrics) -> None:
        if self.compositor.on_metrics(m):
            self._dirty.set()

    # ----- 渲染循环 -----
    async def _render_loop(self) -> None:
        max_fps = max(1, self.cfg.render.max_fps)
        anim_period = 1.0 / 30.0    # 动画时固定 30 FPS,够丝滑且省 CPU/SPI
        min_period = 1.0 / max_fps  # 帧率上限保护
        last_render = time.monotonic()
        animating = False
        while not self._stop.is_set():
            # 等待 dirty 或动画 tick
            if animating:
                # 动画进行中:固定周期推进
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=anim_period)
                    break
                except asyncio.TimeoutError:
                    pass
            else:
                # 完全静止:等 dirty 事件或 1 秒超时(让时钟有机会刷新)
                try:
                    await asyncio.wait_for(self._dirty.wait(), timeout=1.0)
                except asyncio.TimeoutError:
                    pass
                self._dirty.clear()

            now = time.monotonic()
            dt = now - last_render
            # 推进 widget 动画
            animating = self.compositor.tick(dt)

            if animating or any(w.dirty for w in self.widgets):
                # 帧率上限保护
                wait = min_period - dt
                if wait > 0:
                    try:
                        await asyncio.wait_for(self._stop.wait(), timeout=wait)
                        break
                    except asyncio.TimeoutError:
                        pass
                t0 = time.perf_counter()
                n = self.compositor.render_frame()
                last_render = time.monotonic()
                if n > 0:
                    dt_ms = (time.perf_counter() - t0) * 1000
                    log.debug("frame: %.1f ms, %d bytes", dt_ms, n)
            else:
                last_render = now

    # ----- 喂狗 -----
    async def _watchdog_loop(self) -> None:
        usec = os.environ.get("WATCHDOG_USEC")
        if not usec:
            return  # 未启用,无操作
        try:
            interval = int(usec) / 2 / 1e6
        except ValueError:
            return
        interval = max(0.5, interval)
        while not self._stop.is_set():
            sdnotify.watchdog()
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=interval)
            except asyncio.TimeoutError:
                pass

    # ----- 主入口 -----
    async def run(self) -> int:
        self._install_signal_handlers()
        t0 = time.perf_counter()

        # 首帧:走 compositor 的 full-frame 路径
        first_bytes = self.compositor.render_frame()
        log.info("first frame: %.0f ms, %d bytes",
                 (time.perf_counter() - t0) * 1000, first_bytes)

        sdnotify.ready()

        sampler = Sampler(self._on_metrics, self.cfg.sampling)
        sampler_task = asyncio.create_task(sampler.run(), name="sampler")
        render_task = asyncio.create_task(self._render_loop(), name="render")
        wd_task = asyncio.create_task(self._watchdog_loop(), name="watchdog")

        try:
            await self._stop.wait()
        finally:
            log.info("shutting down…")
            sdnotify.stopping()
            sampler.stop()
            for t in (sampler_task, render_task, wd_task):
                t.cancel()
            # 静默吞 CancelledError
            for t in (sampler_task, render_task, wd_task):
                try:
                    await t
                except (asyncio.CancelledError, Exception):
                    pass
            t_shutdown = time.perf_counter()
            self.display.shutdown()
            log.info("display shutdown: %.0f ms",
                     (time.perf_counter() - t_shutdown) * 1000)
        return 0
