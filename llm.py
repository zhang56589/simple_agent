"""LLM 封装：OpenAI 兼容 ChatCompletion，带超时/重试/日志。"""
from __future__ import annotations

import time
from typing import Any

from openai import OpenAI

from config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL, LLM_TEMPERATURE, LLM_TIMEOUT
from logger import get_logger

log = get_logger("llm")

# ---- 延迟初始化 client（避免 import 时就因缺 key 崩） ----
_client: OpenAI | None = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(
            api_key=LLM_API_KEY or "EMPTY",
            base_url=LLM_BASE_URL,
            timeout=LLM_TIMEOUT,
        )
    return _client


def llm_call(
    messages: list[dict[str, Any]],
    *,
    max_retries: int = 2,
    temperature: float | None = None,
) -> str:
    """调用大模型，返回文本内容；失败时重试 max_retries 次。"""
    if not messages:
        raise ValueError("messages 不能为空")

    temp = temperature if temperature is not None else LLM_TEMPERATURE
    last_err: Exception | None = None

    for attempt in range(1, max_retries + 1):
        try:
            log.debug("LLM 请求: model=%s, 消息数=%d, attempt=%d", LLM_MODEL, len(messages), attempt)
            client = _get_client()
            resp = client.chat.completions.create(
                model=LLM_MODEL,
                messages=messages,  # type: ignore[arg-type]
                temperature=temp,
            )
            content = (resp.choices[0].message.content or "").strip()
            log.debug("LLM 返回: %d 字", len(content))
            return content
        except Exception as e:  # openai 包异常层次较散，兜底捕获
            last_err = e
            log.warning("LLM 调用失败 (attempt %d/%d): %s", attempt, max_retries, e)
            time.sleep(1 + attempt)

    # 所有重试耗尽
    raise RuntimeError(f"LLM 调用失败：{last_err}") from last_err
