"""安全校验模块：路径穿越防护、Action 字符串清洗、工具参数白名单。"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable

from config import PROJECT_ROOT, READ_FILE_ALLOW_DIRS
from logger import get_logger

log = get_logger("security")

# 合法工具名白名单（运行时由 tools.py 注册）
# 先留空，tools 模块在 import 时调用 register_tool_name()
_TOOL_WHITELIST: set[str] = set()

# Action 名正则：只允许字母/数字/下划线，2-32 字符
_TOOL_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{1,31}$")


def register_tool_name(name: str) -> None:
    """tools 模块注册工具名到白名单。"""
    if _TOOL_NAME_RE.match(name):
        _TOOL_WHITELIST.add(name)
    else:
        log.warning("跳过格式非法的工具名注册: %s", name)


def get_tool_whitelist() -> frozenset[str]:
    return frozenset(_TOOL_WHITELIST)


def sanitize_action_name(name: str) -> str | None:
    """清洗/校验工具名；非法返回 None。"""
    name = name.strip()
    if not _TOOL_NAME_RE.match(name):
        log.warning("非法工具名格式: %r", name)
        return None
    if _TOOL_WHITELIST and name not in _TOOL_WHITELIST:
        log.warning("工具名不在白名单: %r (允许=%s)", name, sorted(_TOOL_WHITELIST))
        return None
    return name


def sanitize_param(param: str, max_len: int = 2000) -> str:
    """清洗工具参数字符串：剥离控制字符、限制长度。"""
    if param is None:
        return ""
    # 去除 \x00-\x08 \x0b-\x1f \x7f 等控制字符（保留换行/制表便于文本）
    cleaned = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", param)
    cleaned = cleaned.strip()
    if len(cleaned) > max_len:
        log.warning("参数超长 (%d>%d)，已截断", len(cleaned), max_len)
        cleaned = cleaned[:max_len]
    return cleaned


def validate_read_file_path(raw_path: str) -> Path | None:
    """read_file 路径安全校验：
    - 禁止空路径 / 控制字符
    - 禁止 .. 穿越
    - 若配置了白名单目录，必须在其中
    返回解析后的绝对 Path；非法返回 None。
    """
    if not raw_path or not raw_path.strip():
        log.warning("路径为空")
        return None

    # 禁止控制字符
    if re.search(r"[\x00-\x1f\x7f]", raw_path):
        log.warning("路径含控制字符: %r", raw_path)
        return None

    # 解析真实路径
    candidate = Path(raw_path).expanduser()
    try:
        # 若文件已存在，用 realpath 解析符号链接；若不存在则先 resolve()
        if candidate.exists():
            real = candidate.resolve(strict=True)
        else:
            real = candidate.resolve(strict=False)
    except (OSError, RuntimeError) as e:
        log.warning("路径解析失败: %s (%s)", raw_path, e)
        return None

    real_str = str(real).replace("\\", "/")
    project_root_str = str(PROJECT_ROOT.resolve()).replace("\\", "/")

    # 1. 默认：必须在项目根目录内（防 .. 穿越）
    if not real_str.startswith(project_root_str + "/") and real_str != project_root_str:
        # 2. 若配置了 READ_FILE_ALLOW_DIRS，则优先按白名单判断
        if READ_FILE_ALLOW_DIRS:
            in_whitelist = False
            for allowed in READ_FILE_ALLOW_DIRS:
                ap = Path(allowed).expanduser().resolve()
                ap_str = str(ap).replace("\\", "/")
                if real_str.startswith(ap_str + "/") or real_str == ap_str:
                    in_whitelist = True
                    break
            if not in_whitelist:
                log.warning("路径不在白名单: %s", raw_path)
                return None
        else:
            log.warning("路径越界(不在项目根目录内): %s", raw_path)
            return None

    return real
