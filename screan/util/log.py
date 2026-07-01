"""logging 配置:输出走 stdout/stderr,systemd 自动收到 journald。

journald 协议:首字符 `<N>` 是 syslog 优先级。我们把 Python level 映射过去,
journalctl 就能按 priority 过滤 / 着色。
"""
import logging
import sys


_PRIO = {
    logging.CRITICAL: 2,
    logging.ERROR: 3,
    logging.WARNING: 4,
    logging.INFO: 6,
    logging.DEBUG: 7,
}


class JournalFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        msg = super().format(record)
        return f"<{_PRIO.get(record.levelno, 6)}>{msg}"


def setup(level: str = "INFO", journal: bool = True) -> None:
    """journal=True 时输出带 syslog 优先级前缀(systemd 会解析掉);
    False 时纯文本,便于交互调试。"""
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    for h in list(root.handlers):
        root.removeHandler(h)
    h = logging.StreamHandler(sys.stderr)
    fmt = "%(asctime)s %(levelname)s %(name)s: %(message)s"
    h.setFormatter(JournalFormatter(fmt) if journal else logging.Formatter(fmt))
    root.addHandler(h)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
