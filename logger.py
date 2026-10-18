"""日志系统：Python logging + 文件轮转 + 控制台彩色输出。"""
from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler

from config import (
    LOG_DIR,
    LOG_FILE_BACKUP,
    LOG_FILE_MAX_BYTES,
    LOG_LEVEL,
)

# 只初始化一次
_INITIALIZED = False

# 统一日志格式
_FMT = "%(asctime)s [%(levelname)s] %(name)s | %(message)s"
_DATE_FMT = "%Y-%m-%d %H:%M:%S"

# 控制台简易彩色（Windows cmd 也能识别）
_COLOR_RESET = "\033[0m"
_COLOR_MAP = {
    "DEBUG": "\033[36m",      # cyan
    "INFO": "\033[32m",       # green
    "WARNING": "\033[33m",    # yellow
    "ERROR": "\033[31m",      # red
    "CRITICAL": "\033[1;31m", # bold red
}


class _ColorFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        color = _COLOR_MAP.get(record.levelname, "")
        msg = super().format(record)
        if color and sys.platform != "win32":
            return f"{color}{msg}{_COLOR_RESET}"
        return msg


def setup_logging() -> None:
    """配置根日志：控制台 + 轮转文件。"""
    global _INITIALIZED
    if _INITIALIZED:
        return

    LOG_DIR.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))
    # 避免重复 handler
    if root.handlers:
        _INITIALIZED = True
        return

    # 控制台
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(_ColorFormatter(_FMT, _DATE_FMT))
    root.addHandler(console)

    # 轮转文件
    file_handler = RotatingFileHandler(
        LOG_DIR / "agent.log",
        maxBytes=LOG_FILE_MAX_BYTES,
        backupCount=LOG_FILE_BACKUP,
        encoding="utf-8",
    )
    file_handler.setFormatter(logging.Formatter(_FMT, _DATE_FMT))
    root.addHandler(file_handler)

    # 降噪
    for noisy in ("urllib3", "httpcore", "httpx", "openai"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    _INITIALIZED = True


def get_logger(name: str) -> logging.Logger:
    """模块级快捷入口：返回命名 logger（自动确保日志系统已初始化）。"""
    if not _INITIALIZED:
        setup_logging()
    return logging.getLogger(name)
