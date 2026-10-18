"""Action 正则解析测试：tools.parse_action。"""
from __future__ import annotations

import pytest

from tools import parse_action


# --------------------------------------------------------------------------- #
#  正常解析                                                                     #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "text, expected_name, expected_param",
    [
        # 典型格式
        ("Action:web_search[2026国内AI Agent现状]", "web_search", "2026国内AI Agent现状"),
        ("Action:read_file[agent.py]", "read_file", "agent.py"),
        # 参数带空格
        ("Action:web_search[hello world]", "web_search", "hello world"),
        # 前后空白（Action 与 tool 名之间允许；param 经 sanitize_param 会 strip）
        ("  Action:  web_search  [  query  ]  ", "web_search", "query"),
        # 空参数
        ("Action:web_search[]", "web_search", ""),
        ("Action:read_file", "read_file", ""),
        # 带数字后缀的已注册工具名 → 不在白名单，挪到下方白名单拒绝测试
    ],
)
def test_parse_action_ok(text: str, expected_name: str, expected_param: str) -> None:
    result = parse_action(text)
    assert result is not None, f"解析失败: {text!r}"
    name, param = result
    assert name == expected_name
    assert param == expected_param


def test_parse_action_nested_brackets_in_param() -> None:
    """参数里自带 [] 的情况。正则 (.*) 是贪婪匹配，吃到最后一个 ] 为止。"""
    result = parse_action("Action:read_file[file[name].md]")
    assert result is not None
    name, param = result
    assert name == "read_file"
    # 贪婪匹配，(.*) 吃到最后一个 ] 前 → file[name].md
    assert param == "file[name].md"


# --------------------------------------------------------------------------- #
#  非法输入 → 返回 None                                                          #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("text", [
    "",
    None,              # type: ignore[list-item]
    "   ",
    "FinalAnswer:2+3=5",
    "Thought:我先想想",
    "Action:",         # 工具名缺失
    "Action: ",        # 空白工具名
    "Action:1tool[x]", # 数字开头
    "Action:tool-name[x]",  # 含连字符
    "Action:tool name[x]",  # 工具名含空格
    "Action:A" * 40 + "[x]",  # 工具名超长（>32）
    "action:web_search[x]",   # 小写 action
    "ACTION:web_search[x]",   # 大写 ACTION
    "Action:tool[x]extra",    # 括号后还有字符
])
def test_parse_action_invalid(text: str) -> None:
    assert parse_action(text) is None


# --------------------------------------------------------------------------- #
#  白名单行为：格式合法但工具未注册 → 返回 None                                      #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("text", [
    "Action:my_tool[x]",           # 格式 OK 但未注册
    "Action:calculator[1+2]",      # 未注册
    "Action:crawl_web[http://x]",  # 未注册
])
def test_parse_action_tool_not_in_whitelist_rejected(text: str) -> None:
    """格式合法但工具名未在 security 白名单注册 → parse_action 返回 None。"""
    assert parse_action(text) is None


# --------------------------------------------------------------------------- #
#  参数清洗（超过最大长度会被截断）                                                #
# --------------------------------------------------------------------------- #
def test_parse_action_param_stripped() -> None:
    """parse_action 内部调用 sanitize_param，会 strip + 去控制字符。"""
    text = "Action:web_search[\x00query\x1f]"
    result = parse_action(text)
    assert result is not None
    name, param = result
    assert name == "web_search"
    assert "\x00" not in param
    assert "\x1f" not in param
    assert "query" in param


def test_parse_action_long_param_truncated() -> None:
    """超过 2000 字符的参数会被截断（sanitize_param max_len=2000）。"""
    long_param = "A" * 5000
    text = f"Action:web_search[{long_param}]"
    result = parse_action(text)
    assert result is not None
    _, param = result
    assert len(param) <= 2000
