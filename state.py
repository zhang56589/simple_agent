"""Agent 状态持久化：把 messages / round / user_query 存为 JSON，支持断点续跑。"""
from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config import STATE_FILE
from logger import get_logger

log = get_logger("state")


class AgentState:
    """轻量状态对象：messages + round + meta。"""

    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []
        self.round: int = 0
        self.user_query: str = ""
        self.updated_at: str = ""
        self._lock = threading.Lock()

    # ---------- 序列化 ----------
    def to_dict(self) -> dict[str, Any]:
        return {
            "messages": self.messages,
            "round": self.round,
            "user_query": self.user_query,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AgentState":
        s = cls()
        s.messages = list(data.get("messages", []))
        s.round = int(data.get("round", 0))
        s.user_query = str(data.get("user_query", ""))
        s.updated_at = str(data.get("updated_at", ""))
        return s

    # ---------- 文件 IO ----------
    def save(self, path: Path | str | None = None) -> None:
        target = Path(path) if path else STATE_FILE
        target.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            self.updated_at = datetime.now(timezone.utc).isoformat()
            try:
                tmp = target.with_suffix(target.suffix + ".tmp")
                tmp.write_text(
                    json.dumps(self.to_dict(), ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                tmp.replace(target)  # 原子替换
                log.debug("状态已保存: %s (round=%d)", target, self.round)
            except OSError as e:
                log.error("状态保存失败 %s: %s", target, e)

    @classmethod
    def load(cls, path: Path | str | None = None) -> "AgentState | None":
        target = Path(path) if path else STATE_FILE
        if not target.exists():
            return None
        try:
            raw = target.read_text(encoding="utf-8")
            data = json.loads(raw)
            log.info("已加载状态: %s (round=%d)", target, data.get("round", 0))
            return cls.from_dict(data)
        except (OSError, json.JSONDecodeError) as e:
            log.error("状态加载失败 %s: %s", target, e)
            return None

    @classmethod
    def exists(cls, path: Path | str | None = None) -> bool:
        target = Path(path) if path else STATE_FILE
        return target.exists()

    @classmethod
    def clear(cls, path: Path | str | None = None) -> None:
        target = Path(path) if path else STATE_FILE
        try:
            if target.exists():
                target.unlink()
                log.info("已清理状态文件: %s", target)
        except OSError as e:
            log.warning("状态清理失败 %s: %s", target, e)
