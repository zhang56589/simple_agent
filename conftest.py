"""pytest 全局配置：把项目根目录插入 sys.path，保证 `import tools` 等能工作。"""
from __future__ import annotations

import sys
from pathlib import Path

# 项目根 = conftest.py 所在目录
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
