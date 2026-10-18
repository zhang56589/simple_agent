"""上下文摘要压缩：当对话轮次过多时，用 LLM 把较早的历史压成一条摘要。"""
from __future__ import annotations

from typing import Any

from config import CONTEXT_COMPRESS_THRESHOLD, CONTEXT_KEEP_RECENT
from logger import get_logger

log = get_logger("summarizer")

# 摘要系统提示
_SUMMARY_SYSTEM = "你是一个对话历史压缩器。请保留任务关键信息、已完成步骤、重要事实、待解决问题，删除重复与废话，用简洁中文分点输出。"
_SUMMARY_PROMPT_TEMPLATE = (
    "以下是更早的对话历史，请把它压缩成一段摘要，保留任务关键信息、已完成步骤、重要事实、待解决问题。\n"
    "要求：不超过 400 字，分点或段落均可。\n\n"
    "----- 开始历史 -----\n"
    "{history_text}\n"
    "----- 结束历史 -----"
)


def _format_history(messages: list[dict[str, Any]]) -> str:
    """把 messages 拼成可读文本（跳过 system，因为 system 本身是规则）。"""
    lines: list[str] = []
    for m in messages:
        role = m.get("role", "?")
        content = (m.get("content") or "").strip()
        if role == "system":
            continue
        if not content:
            continue
        lines.append(f"[{role}]\n{content}")
    return "\n\n".join(lines)


def needs_compression(messages: list[dict[str, Any]]) -> bool:
    """是否需要触发压缩（只统计非 system 消息，按轮次粗估）。"""
    non_system = [m for m in messages if m.get("role") != "system"]
    return len(non_system) >= CONTEXT_COMPRESS_THRESHOLD


def compress_context(
    messages: list[dict[str, Any]],
    llm_call,  # 延迟绑定，避免循环依赖
) -> list[dict[str, Any]]:
    """把较早的历史压成一条 compressed_context，返回新的 messages 列表。

    - 保留 system（第 0 条）
    - 把倒数 CONTEXT_KEEP_RECENT*2 条非 system 消息保留
    - 把更早的消息压缩成 1 条 summary 消息（role=system 以便不影响对话流程）
    """
    if not needs_compression(messages):
        return messages

    system_msgs = [m for m in messages if m.get("role") == "system"]
    non_system = [m for m in messages if m.get("role") != "system"]

    # 最近 N 轮（每轮约 2 条 user+assistant，或 3 条含 observation），保守取 KEEP_RECENT*2
    keep_count = max(2, CONTEXT_KEEP_RECENT * 2)
    if len(non_system) <= keep_count:
        return messages

    old_msgs = non_system[:-keep_count]
    recent_msgs = non_system[-keep_count:]

    history_text = _format_history(old_msgs)
    summary_prompt = _SUMMARY_PROMPT_TEMPLATE.format(history_text=history_text)

    try:
        # 构造一次性请求：摘要专用 system + user
        summary_messages = [
            {"role": "system", "content": _SUMMARY_SYSTEM},
            {"role": "user", "content": summary_prompt},
        ]
        summary = (llm_call(summary_messages) or "").strip()
    except Exception as e:
        log.warning("摘要 LLM 调用失败，降级为简单截断: %s", e)
        # 降级：直接把旧历史拼起来当摘要
        summary = "【历史摘要(自动降级)】\n" + _format_history(old_msgs)[:600]

    if not summary:
        log.warning("摘要为空，跳过压缩")
        return messages

    log.info(
        "上下文压缩: %d 条旧消息 → 摘要 %d 字；保留最近 %d 条",
        len(old_msgs),
        len(summary),
        len(recent_msgs),
    )

    summary_block = (
        "\n\n"
        "==== 历史摘要（更早对话的压缩）====\n"
        f"{summary}\n"
        "==== 历史摘要结束 ===="
    )

    # 把摘要合并到第一条 system 消息，避免多条 system 某些 provider 不兼容
    if system_msgs:
        first_system = system_msgs[0]
        merged_system = {
            "role": "system",
            "content": (first_system.get("content", "") + summary_block).strip(),
        }
        rest_systems = system_msgs[1:]
    else:
        merged_system = {
            "role": "system",
            "content": ("你是一个智能Agent。" + summary_block).strip(),
        }
        rest_systems = []

    new_messages: list[dict[str, Any]] = [merged_system]
    new_messages.extend(rest_systems)
    new_messages.extend(recent_msgs)
    return new_messages
