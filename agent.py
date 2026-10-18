"""ReAct 单 Agent 主循环。

核心流程：
    system + user_query
    for i in range(max_round):
        resp = llm(messages)
        if FinalAnswer: return
        if Action: tool -> observation -> 追加 messages
        else: 格式错误提示
        每轮后：上下文压缩检查 + 状态持久化

Action 格式：Action:tool_name[param]
"""
from __future__ import annotations

import argparse
import sys
from typing import Any

from config import DEFAULT_MAX_ROUND, PROJECT_ROOT
from logger import get_logger, setup_logging
from llm import llm_call
from state import AgentState
from summarizer import compress_context, needs_compression
from tools import TOOL_DESCRIPTIONS, execute_action

log = get_logger("agent")

_FINAL_ANSWER_PREFIX = "FinalAnswer:"

# 模板文件路径（外部化）
_SYSTEM_PROMPT_FILE = PROJECT_ROOT / "prompts" / "system_prompt.txt"

# fallback：模板文件缺失时的硬编码兜底（内容与 prompts/system_prompt.txt 保持一致）
_FALLBACK_SYSTEM_PROMPT_TEMPLATE = """你是一个智能Agent，使用 ReAct 模式完成任务。

{tool_descriptions}

规则：
1. 每一轮只能输出一行：要么 Action:tool_name[param]，要么 FinalAnswer:xxx
2. 工具名只能从可用工具中挑选，参数写在方括号 [] 内
3. 仔细观察工具返回结果，结合历史信息继续思考
4. 最多迭代 {max_round} 轮，不要无限循环；当你认为答案已足够时立刻输出 FinalAnswer:
5. 不要暴露你的思考过程（不要输出 Thought: 等），直接按规则输出
"""

# 模块级缓存：避免重复读磁盘
_PROMPT_TEMPLATE_CACHE: str | None = None


def _load_system_prompt_template() -> str:
    """从 prompts/system_prompt.txt 加载系统提示词模板，首次加载后缓存。"""
    global _PROMPT_TEMPLATE_CACHE
    if _PROMPT_TEMPLATE_CACHE is not None:
        return _PROMPT_TEMPLATE_CACHE
    try:
        _PROMPT_TEMPLATE_CACHE = _SYSTEM_PROMPT_FILE.read_text(encoding="utf-8")
        log.info("系统提示词模板已加载: %s", _SYSTEM_PROMPT_FILE)
    except OSError as e:
        log.warning("提示词模板读取失败(%s)，使用内置兜底模板: %s", _SYSTEM_PROMPT_FILE, e)
        _PROMPT_TEMPLATE_CACHE = _FALLBACK_SYSTEM_PROMPT_TEMPLATE
    return _PROMPT_TEMPLATE_CACHE


def _build_system_prompt(max_round: int) -> str:
    return _load_system_prompt_template().format(
        tool_descriptions=TOOL_DESCRIPTIONS,
        max_round=max_round,
    )


def run_agent(
    user_query: str,
    max_round: int = DEFAULT_MAX_ROUND,
    *,
    resume: bool = True,
    auto_save: bool = True,
) -> str:
    """运行 Agent 主循环，返回 FinalAnswer 字符串。"""
    setup_logging()

    # 断点续跑
    state: AgentState | None = None
    if resume and AgentState.exists():
        state = AgentState.load()

    if state and state.messages and state.user_query == user_query:
        messages = state.messages
        start_round = state.round
        log.info("续跑：从第 %d 轮继续", start_round + 1)
    else:
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": _build_system_prompt(max_round)},
            {"role": "user", "content": user_query},
        ]
        start_round = 0
        state = AgentState()
        state.user_query = user_query
        state.messages = messages

    for i in range(start_round, max_round):
        log.info("===== 第 %d/%d 轮思考 =====", i + 1, max_round)

        # 上下文压缩检查
        if needs_compression(messages):
            try:
                messages = compress_context(messages, llm_call)
                state.messages = messages
                log.info("已执行上下文压缩")
            except Exception as e:
                log.warning("上下文压缩失败，跳过: %s", e)

        # 调用 LLM
        try:
            resp = llm_call(messages)
        except Exception as e:
            log.error("LLM 调用失败，终止: %s", e)
            return f"LLM 调用失败：{e}"

        log.info("模型输出: %s", resp[:200])

        # ---- FinalAnswer ----
        if resp.startswith(_FINAL_ANSWER_PREFIX):
            answer = resp.removeprefix(_FINAL_ANSWER_PREFIX).strip()
            if not answer:
                messages.append({
                    "role": "user",
                    "content": "FinalAnswer 不能为空，请重新给出最终答案。",
                })
                continue
            log.info("✅ 任务完成，返回答案")
            if auto_save:
                AgentState.clear()
            return answer

        # ---- Action ----
        if resp.startswith("Action:"):
            obs = execute_action(resp)
            log.info("工具返回 (%d 字)", len(obs))
            messages.append({"role": "assistant", "content": resp})
            messages.append({"role": "user", "content": f"Observation:{obs}"})
        else:
            # 格式错误
            log.warning("模型输出格式错误: %s", resp[:120])
            messages.append({
                "role": "user",
                "content": (
                    "输出格式错误！请严格且只能输出以下两种格式之一：\n"
                    "  1) Action:tool_name[param]\n"
                    "  2) FinalAnswer:你的最终答案\n"
                    f"你刚才输出的是：{resp[:200]}"
                ),
            })

        # 更新状态 + 持久化
        state.round = i + 1
        state.messages = messages
        if auto_save:
            state.save()

    log.warning("达到最大轮次 %d，任务终止", max_round)
    return "达到最大迭代轮次，任务终止"


# --------------------------------------------------------------------------- #
#  CLI                                                                        #
# --------------------------------------------------------------------------- #
def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="ReAct 单 Agent")
    p.add_argument("query", nargs="?", help="用户问题")
    p.add_argument("-q", "--question", dest="question", help="用户问题（与位置参数二选一）")
    p.add_argument("-r", "--max-round", type=int, default=DEFAULT_MAX_ROUND, help="最大迭代轮次")
    p.add_argument("--no-resume", action="store_true", help="禁用断点续跑，强制新会话")
    p.add_argument("--no-save", action="store_true", help="禁用自动持久化")
    p.add_argument("--clear-state", action="store_true", help="运行前先清理状态文件")
    return p.parse_args()


def main(argv: list[str] | None = None) -> int:
    args = _parse_args()
    query = args.query or args.question
    if not query:
        print("请提供问题，例如：python agent.py '2026国内AI Agent现状'", file=sys.stderr)
        return 2

    setup_logging()
    log.info("项目根目录: %s", PROJECT_ROOT)

    if args.clear_state:
        AgentState.clear()

    result = run_agent(
        query,
        max_round=args.max_round,
        resume=not args.no_resume,
        auto_save=not args.no_save,
    )
    print("\n✅ Agent 最终结果：", result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
