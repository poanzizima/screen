"""sd_notify:无依赖实现 systemd Type=notify 协议。

通过 $NOTIFY_SOCKET 环境变量找 unix socket,发送 KEY=VALUE 行。
当 systemd 没拉起服务(开发态)时 socket 不存在,所有操作变 no-op。
"""
from __future__ import annotations
import os
import socket


_sock: socket.socket | None = None
_addr: str | None = None


def _ensure_socket() -> socket.socket | None:
    global _sock, _addr
    if _sock is not None:
        return _sock
    addr = os.environ.get("NOTIFY_SOCKET")
    if not addr:
        return None
    # @-前缀表示 abstract namespace
    if addr.startswith("@"):
        addr = "\0" + addr[1:]
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM | socket.SOCK_CLOEXEC)
        _sock = s
        _addr = addr
        return s
    except OSError:
        return None


def notify(message: str) -> None:
    s = _ensure_socket()
    if s is None or _addr is None:
        return
    try:
        s.sendto(message.encode("utf-8"), _addr)
    except OSError:
        pass


def ready() -> None:
    """通知 systemd 服务已就绪(Type=notify 必须)。"""
    notify("READY=1")


def watchdog() -> None:
    """喂狗。需要 unit 配置 WatchdogSec=N。"""
    notify("WATCHDOG=1")


def stopping() -> None:
    notify("STOPPING=1")
