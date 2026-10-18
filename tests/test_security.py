"""security.validate_read_file_path 路径安全校验测试。"""
from __future__ import annotations

from pathlib import Path

import pytest

from config import PROJECT_ROOT
from security import validate_read_file_path


# --------------------------------------------------------------------------- #
#  合法路径 → 返回 Path 对象                                                     #
# --------------------------------------------------------------------------- #
class TestValidPath:
    def test_relative_root_file(self) -> None:
        """项目根下直接存在的文件"""
        # conftest.py 在项目根目录下一定存在
        result = validate_read_file_path("conftest.py")
        assert result is not None
        assert result.is_absolute()
        assert result.name == "conftest.py"

    def test_relative_subdir_file(self) -> None:
        """prompts/system_prompt.txt 一定存在"""
        result = validate_read_file_path("prompts/system_prompt.txt")
        assert result is not None
        assert result.name == "system_prompt.txt"

    def test_absolute_path_inside_project(self) -> None:
        """绝对路径但仍在项目根内"""
        abs_path = str(PROJECT_ROOT / "agent.py")
        result = validate_read_file_path(abs_path)
        assert result is not None
        assert result.name == "agent.py"

    def test_path_with_trailing_slash_variant(self) -> None:
        """带 ./ 前缀"""
        result = validate_read_file_path("./conftest.py")
        assert result is not None
        assert result.name == "conftest.py"


# --------------------------------------------------------------------------- #
#  非法路径 → 返回 None                                                          #
# --------------------------------------------------------------------------- #
class TestInvalidPath:
    @pytest.mark.parametrize("raw", [None, "", "   "])
    def test_empty_or_blank(self, raw: str | None) -> None:
        assert validate_read_file_path(raw) is None

    def test_dotdot_traversal(self) -> None:
        """.. 直接穿越"""
        assert validate_read_file_path("..") is None
        assert validate_read_file_path("../outside.txt") is None

    def test_embedded_dotdot_escape(self) -> None:
        """嵌入的 .. 最终解析会逃逸"""
        # prompts/../.. → 逃逸
        result = validate_read_file_path("prompts/../..")
        assert result is None

    def test_absolute_path_outside_project(self) -> None:
        """Windows 典型外部绝对路径"""
        assert validate_read_file_path("C:/Windows/system32/config/sam") is None
        assert validate_read_file_path("D:/secret/data.txt") is None

    def test_control_char_in_path(self) -> None:
        """路径包含 \x00 / \x1f 等控制字符"""
        assert validate_read_file_path("conftest.py\x00") is None
        assert validate_read_file_path("subdir\x0b/file.txt") is None
        assert validate_read_file_path("path\x7fname.txt") is None

    def test_null_byte_in_middle(self) -> None:
        """中途嵌入 null 字节"""
        assert validate_read_file_path("conftest\x00.py") is None


# --------------------------------------------------------------------------- #
#  边界：不存在但在项目根内的路径                                                #
# --------------------------------------------------------------------------- #
class TestNonExistentPath:
    def test_nonexistent_inside_project_still_passes_security(self) -> None:
        """路径解析仍在项目根内，但文件不存在。security 只检查安全，不检查存在性。"""
        result = validate_read_file_path("prompts/definitely_not_exists_xyz.txt")
        assert result is not None  # security 层面放行
        assert isinstance(result, Path)
