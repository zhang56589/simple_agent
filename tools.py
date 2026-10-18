"""工具模块：web_search（带 UA 池 + 节流 + 缓存）、read_file。

Action 调用格式：Action:tool_name[param]
"""
from __future__ import annotations

import hashlib
import json
import random
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import requests
from bs4 import BeautifulSoup

from config import (
    CRAWL_CACHE_TTL,
    CRAWL_MAX_RESULTS,
    CRAWL_RETRY,
    CRAWL_THROTTLE_SEC,
    CRAWL_TIMEOUT,
    PROJECT_ROOT,
    READ_FILE_MAX_BYTES,
)
from logger import get_logger
from security import (
    get_tool_whitelist,
    register_tool_name,
    sanitize_action_name,
    sanitize_param,
    validate_read_file_path,
)

log = get_logger("tools")

# --------------------------------------------------------------------------- #
#  UA 池                                                                      #
# --------------------------------------------------------------------------- #
_UA_POOL: tuple[str, ...] = (
    # Chrome / Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    # Edge
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36 Edg/123.0.2420.65",
    # Firefox / Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    # Chrome / macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    # Safari / macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    # 手机
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36",
)


def _pick_ua() -> str:
    return random.choice(_UA_POOL)


# --------------------------------------------------------------------------- #
#  节流器（滑动最小间隔）                                                      #
# --------------------------------------------------------------------------- #
class _Throttler:
    def __init__(self, min_interval: float):
        self.min_interval = max(0.0, float(min_interval))
        self._last_ts: float = 0.0
        self._lock = threading.Lock()

    def wait(self) -> None:
        if self.min_interval <= 0:
            return
        with self._lock:
            now = time.monotonic()
            delta = now - self._last_ts
            if delta < self.min_interval:
                time.sleep(self.min_interval - delta)
            self._last_ts = time.monotonic()


_throttler = _Throttler(CRAWL_THROTTLE_SEC)


# --------------------------------------------------------------------------- #
#  带 TTL 的线程安全内存缓存                                                    #
# --------------------------------------------------------------------------- #
@dataclass
class _CacheEntry:
    value: str
    expire_at: float


class _TTLCache:
    def __init__(self, ttl_seconds: int):
        self.ttl = max(0, int(ttl_seconds))  # 0 = 永不过期
        self._store: dict[str, _CacheEntry] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> str | None:
        with self._lock:
            e = self._store.get(key)
            if e is None:
                return None
            if self.ttl and e.expire_at and time.monotonic() > e.expire_at:
                self._store.pop(key, None)
                return None
            return e.value

    def set(self, key: str, value: str) -> None:
        expire_at = (time.monotonic() + self.ttl) if self.ttl else 0.0
        with self._lock:
            self._store[key] = _CacheEntry(value=value, expire_at=expire_at)

    def size(self) -> int:
        with self._lock:
            return len(self._store)


_search_cache = _TTLCache(CRAWL_CACHE_TTL)


def _cache_key(text: str) -> str:
    return hashlib.md5(text.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------- #
#  工具函数：web_search                                                         #
# --------------------------------------------------------------------------- #
def web_search(query: str) -> str:
    """Bing 网页搜索。返回最多 CRAWL_MAX_RESULTS 条标题/摘要/链接。"""
    query = (query or "").strip()
    if not query:
        return "搜索失败：query 为空"

    cache_key = _cache_key("bing:" + query)
    cached = _search_cache.get(cache_key)
    if cached is not None:
        log.info("搜索缓存命中: %s", query[:40])
        return cached

    # 节流
    _throttler.wait()

    headers = {
        "User-Agent": _pick_ua(),
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Referer": "https://www.bing.com/",
    }
    url = f"https://cn.bing.com/search?q={requests.utils.quote(query)}"

    last_err: str = ""
    for attempt in range(1, CRAWL_RETRY + 1):
        try:
            resp = requests.get(url, headers=headers, timeout=CRAWL_TIMEOUT)
            resp.encoding = resp.apparent_encoding or "utf-8"
            text = resp.text or ""

            if resp.status_code != 200 or "captcha" in text.lower() or "验证" in text[:500]:
                last_err = f"被拦截(status={resp.status_code})"
                log.warning("Bing 拦截，重试 %d/%d", attempt, CRAWL_RETRY)
                # 换 UA 再试
                headers["User-Agent"] = _pick_ua()
                time.sleep(1.5 + attempt * 0.5)
                continue

            soup = BeautifulSoup(text, "html.parser")
            items = soup.select(".b_algo")
            parts: list[str] = []
            for item in items[:CRAWL_MAX_RESULTS]:
                title_tag = item.select_one("h2 a")
                if not title_tag:
                    continue
                title = title_tag.get_text(strip=True)
                link = title_tag.get("href", "")
                abstract_tag = item.select_one(".b_caption p")
                abstract = abstract_tag.get_text(strip=True) if abstract_tag else "无摘要"
                parts.append(f"【标题】{title}\n【摘要】{abstract}\n【链接】{link}\n---")

            result = "\n".join(parts) if parts else "搜索未获取到有效结果"
            _search_cache.set(cache_key, result)
            log.info("搜索完成: query=%s results=%d", query[:40], len(parts))
            return result

        except requests.RequestException as e:
            last_err = f"{type(e).__name__}: {e}"
            log.warning("搜索异常，重试 %d/%d: %s", attempt, CRAWL_RETRY, e)
            time.sleep(2 + attempt)

    return f"搜索失败：多次重试后仍无法获取数据（最后错误：{last_err}）"


# --------------------------------------------------------------------------- #
#  工具函数：read_file                                                         #
# --------------------------------------------------------------------------- #
def read_file(raw_path: str) -> str:
    """读取项目根目录下的文本文件，返回内容。"""
    raw_path = (raw_path or "").strip()
    if not raw_path:
        return "读取失败：路径为空"

    # 安全校验
    resolved = validate_read_file_path(raw_path)
    if resolved is None:
        return f"读取失败：路径非法或越界（raw={raw_path!r}）"

    if not resolved.exists():
        return f"读取失败：文件不存在 {resolved}"
    if not resolved.is_file():
        return f"读取失败：不是普通文件 {resolved}"

    try:
        size = resolved.stat().st_size
        if size > READ_FILE_MAX_BYTES:
            return (
                f"读取失败：文件过大({size}字节 > 允许{READ_FILE_MAX_BYTES})，"
                f"请分段读取或让我用 search 查找相关片段"
            )
        # 尝试 UTF-8，失败回退 GBK（中文 Windows）
        try:
            text = resolved.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            text = resolved.read_text(encoding="gbk", errors="replace")
        log.info("读取文件: %s (%d bytes)", resolved, size)
        return text
    except OSError as e:
        log.warning("读取文件失败 %s: %s", resolved, e)
        return f"读取失败：{type(e).__name__}: {e}"


# --------------------------------------------------------------------------- #
#  注册表 + 调度                                                               #
# --------------------------------------------------------------------------- #
_TOOL_REGISTRY: dict[str, Callable[[str], str]] = {}


def _register(name: str, fn: Callable[[str], str]) -> None:
    _TOOL_REGISTRY[name] = fn
    register_tool_name(name)
    log.info("工具已注册: %s", name)


_register("web_search", web_search)
_register("read_file", read_file)

# 工具描述（直接给 Agent 的 system prompt）
TOOL_DESCRIPTIONS = """可用工具：
- web_search[query]  : 调用 Bing 搜索，返回前几条结果的标题/摘要/链接。参数为搜索关键词。
- read_file[path]     : 读取本地文本文件，返回全文。参数为相对或绝对路径（仅限允许目录内）。

Action 格式：Action:工具名[参数]
示例：
  Action:web_search[2026国内AI Agent行业现状]
  Action:read_file[docs/report.md]
"""

# 预编译 Action 解析正则：Action:name[param]   或   Action:name (无参)
_ACTION_RE = re.compile(r"^\s*Action\s*:\s*([A-Za-z_][A-Za-z0-9_]{1,31})\s*(?:\[(.*)\])?\s*$", re.DOTALL)


def parse_action(text: str) -> tuple[str, str] | None:
    """解析模型输出，返回 (tool_name, param)；不是合法 Action 返回 None。"""
    if not text:
        return None
    text = text.strip()
    m = _ACTION_RE.match(text)
    if not m:
        return None
    name, param = m.group(1), m.group(2) or ""
    # 安全清洗
    clean_name = sanitize_action_name(name)
    if clean_name is None:
        log.warning("非法工具名: %s", name)
        return None
    clean_param = sanitize_param(param)
    return clean_name, clean_param


def execute_action(action_text: str) -> str:
    """高层入口：解析 + 校验 + 执行。返回工具输出或错误信息。"""
    parsed = parse_action(action_text)
    if parsed is None:
        whitelist = ", ".join(sorted(get_tool_whitelist())) or "(未注册)"
        return (
            f"执行失败：无法解析 Action 文本。"
            f"合法格式为 Action:tool_name[param]，可用工具=[{whitelist}]"
        )
    name, param = parsed
    fn = _TOOL_REGISTRY.get(name)
    if fn is None:
        return f"执行失败：工具 {name} 未注册"
    log.info("执行工具: %s(param_len=%d)", name, len(param))
    try:
        return fn(param)
    except Exception as e:  # pragma: no cover - 兜底
        log.exception("工具 %s 抛异常", name)
        return f"执行失败：{type(e).__name__}: {e}"


# 保留旧别名，兼容已有引用
execute_tool = execute_action
