"""集中配置模块：从环境变量 + 默认值读取全项目可配置项。"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# 加载 .env
load_dotenv()

# ---- 项目根目录 ----
PROJECT_ROOT: Path = Path(__file__).resolve().parent

# ---- LLM ----
LLM_BASE_URL: str = os.getenv("LLM_BASE_URL", "https://ark.cn-beijing.volces.com/api/v1")
LLM_API_KEY: str = os.getenv("LLM_API_KEY", "")
LLM_MODEL: str = os.getenv("LLM_MODEL", "doubao-seed-2-1-pro-260915")
LLM_TEMPERATURE: float = float(os.getenv("LLM_TEMPERATURE", "0.1"))
LLM_TIMEOUT: int = int(os.getenv("LLM_TIMEOUT", "30"))

# ---- Agent ----
DEFAULT_MAX_ROUND: int = int(os.getenv("AGENT_MAX_ROUND", "8"))
# 当历史消息条数超过该阈值时触发上下文压缩
CONTEXT_COMPRESS_THRESHOLD: int = int(os.getenv("CONTEXT_COMPRESS_THRESHOLD", "10"))
# 压缩后保留最近 N 轮不压缩 (system 不计)
CONTEXT_KEEP_RECENT: int = int(os.getenv("CONTEXT_KEEP_RECENT", "4"))

# ---- 爬虫 ----
CRAWL_TIMEOUT: int = int(os.getenv("CRAWL_TIMEOUT", "10"))
CRAWL_RETRY: int = int(os.getenv("CRAWL_RETRY", "2"))
# 两次搜索之间的最小间隔秒数
CRAWL_THROTTLE_SEC: float = float(os.getenv("CRAWL_THROTTLE_SEC", "1.2"))
# 搜索结果缓存 TTL (秒)，0 表示永不过期
CRAWL_CACHE_TTL: int = int(os.getenv("CRAWL_CACHE_TTL", "3600"))
# 每个 query 返回的最大结果条数
CRAWL_MAX_RESULTS: int = int(os.getenv("CRAWL_MAX_RESULTS", "3"))

# ---- read_file ----
# 允许读取的根目录（白名单目录），多个用 ; 分隔；为空则允许任意路径
READ_FILE_ALLOW_DIRS: list[str] = [
    d for d in os.getenv("READ_FILE_ALLOW_DIRS", "").split(";") if d
]
READ_FILE_MAX_BYTES: int = int(os.getenv("READ_FILE_MAX_BYTES", "200000"))

# ---- 状态持久化 ----
STATE_FILE: Path = PROJECT_ROOT / os.getenv("STATE_FILE", "agent_state.json")

# ---- 日志 ----
LOG_DIR: Path = PROJECT_ROOT / os.getenv("LOG_DIR", "logs")
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO").upper()
LOG_FILE_MAX_BYTES: int = int(os.getenv("LOG_FILE_MAX_BYTES", "2_000_000"))
LOG_FILE_BACKUP: int = int(os.getenv("LOG_FILE_BACKUP", "3"))
