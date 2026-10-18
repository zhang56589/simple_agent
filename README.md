# simple_agent — 纯 Python ReAct 单 Agent

一个**不依赖 LangChain / LangGraph** 的轻量级 ReAct Agent 框架，基于原生 Python + OpenAI 兼容 API。

## 目录结构

```
simple_agent/
├── agent.py          # ReAct 主循环（入口）
├── llm.py            # 大模型封装（超时/重试）
├── tools.py          # 工具注册 + 调度：web_search, read_file
├── config.py         # 集中配置（.env + 默认值）
├── logger.py         # 日志系统（console + 轮转文件）
├── security.py       # 安全校验（路径穿越/工具名白名单/参数清洗）
├── summarizer.py     # 上下文摘要压缩
├── state.py          # 状态持久化（JSON，支持断点续跑）
├── prompts/
│   └── system_prompt.txt   # 系统提示词模板（可外部编辑）
├── tests/
│   ├── __init__.py
│   ├── test_action_parser.py   # Action 正则解析单测
│   └── test_security.py        # 路径安全校验单测
├── conftest.py       # pytest 配置（sys.path 修复）
├── requirements.txt
├── .env              # LLM_API_KEY / LLM_BASE_URL / LLM_MODEL
└── logs/agent.log    # 运行日志（自动生成）
```

## 快速开始

```bash
# 1. 创建虚拟环境并安装依赖
python -m venv .venv
.venv\Scripts\activate           # Windows PowerShell
# source .venv/bin/activate      # macOS/Linux
pip install -r requirements.txt

# 2. 在 .env 中填好 LLM 凭证（已给示例）

# 3. 运行
python agent.py "2026 国内 AI Agent 行业现状"
# 或 CLI 形式
python agent.py --question "计算 (123+456)*2" --max-round 5
```

## Action 调用格式

Agent 与工具之间通过**单行文本协议**通信，保持 ReAct 风格：

| 类型 | 格式 | 示例 |
|------|------|------|
| 调用工具 | `Action:tool_name[param]` | `Action:web_search[2026国内AI Agent现状]` |
| 返回答案 | `FinalAnswer:xxx` | `FinalAnswer:2+3=5` |

解析使用预编译正则：`^Action\s*:\s*([A-Za-z_][A-Za-z0-9_]{1,31})\s*(?:\[(.*)\])?$`，支持空参数、参数内换行、方括号嵌套。

## 可用工具

| 工具 | 参数 | 说明 |
|------|------|------|
| `web_search` | `query` | Bing（cn.bing.com）搜索，返回最多 3 条标题/摘要/链接 |
| `read_file` | `path` | 读取本地文本文件（仅限允许目录内，最大 200KB） |

### 新增自定义工具

在 `tools.py` 中：

```python
def my_tool(param: str) -> str:
    """工具实现，参数已经过 sanitize_param 清洗。"""
    return f"处理结果：{param}"

_register("my_tool", my_tool)  # 自动进入 security 白名单
```

同时更新 `TOOL_DESCRIPTIONS` 让 Agent 知道新工具的存在。

## 新增能力说明

### 1. 日志系统 (`logger.py`)
- Python `logging` 标准库，自动配置根日志
- 控制台彩色输出 + 轮转文件（`logs/agent.log`，默认 2MB × 3 份）
- 降噪 urllib3 / httpx / openai 等依赖

### 2. 爬虫 UA 池 + 节流 + 缓存 (`tools.py`)
- 8 个真实浏览器 User-Agent 随机轮换
- `_Throttler` 保证两次搜索之间最小间隔（默认 1.2s）
- `_TTLCache` 带 TTL 线程安全内存缓存（默认 3600s）
- 检测 captcha / 中文验证页 → 自动换 UA 重试

### 3. 上下文摘要压缩 (`summarizer.py`)
- 触发条件：非 system 消息数 ≥ `CONTEXT_COMPRESS_THRESHOLD`（默认 10）
- 策略：把较早历史交给 LLM 压缩成一条 `system` 摘要消息，保留最近 `CONTEXT_KEEP_RECENT`（默认 4）轮完整上下文
- 降级方案：摘要 LLM 调用失败时，自动退化为简单截断
- 每轮迭代后自动检查

### 4. 状态持久化 (`state.py`)
- 每轮迭代后把 `messages / round / user_query` 原子写入 `agent_state.json`
- 下一次运行同一 query 时自动续跑（`--no-resume` 可关闭）
- 任务正常完成时自动清理状态文件
- 原子写入：先写 `.tmp` 再 `replace()`，避免中断导致文件损坏

### 5. 安全校验 (`security.py`)
- **工具名**：正则白名单 + `register_tool_name` 动态注册
- **参数**：剥离 `\x00-\x1f \x7f` 控制字符 + 长度截断（默认 2000）
- **文件路径**：`realpath` 解析后检查是否在项目根 / `READ_FILE_ALLOW_DIRS` 白名单内，禁止 `..` 穿越、符号链接逃逸、绝对路径越界

### 6. read_file 工具 (`tools.py`)
- 路径穿越防护见上
- 支持 UTF-8 / GBK 自动探测
- 文件大小上限保护（默认 200KB）
- 统一错误返回格式，Agent 可据此调整策略

## 配置项

全部通过 `.env` 环境变量覆盖，`config.py` 内置合理默认值：

| 变量 | 默认 | 说明 |
|------|------|------|
| `LLM_BASE_URL` | `https://ark.cn-beijing.volces.com/api/v1` | OpenAI 兼容接口 |
| `LLM_API_KEY` | — | 必填 |
| `LLM_MODEL` | `doubao-seed-2-1-pro-260915` | 模型名 |
| `LLM_TEMPERATURE` | `0.1` | 采样温度 |
| `LLM_TIMEOUT` | `30` | 单请求超时秒 |
| `AGENT_MAX_ROUND` | `8` | Agent 默认最大迭代轮次 |
| `CONTEXT_COMPRESS_THRESHOLD` | `10` | 压缩触发阈值（消息条数） |
| `CONTEXT_KEEP_RECENT` | `4` | 压缩后保留最近几轮 |
| `CRAWL_TIMEOUT` | `10` | 爬虫超时秒 |
| `CRAWL_RETRY` | `2` | 爬虫重试次数 |
| `CRAWL_THROTTLE_SEC` | `1.2` | 两次搜索最小间隔 |
| `CRAWL_CACHE_TTL` | `3600` | 搜索缓存 TTL（0=永不过期） |
| `CRAWL_MAX_RESULTS` | `3` | 每次搜索返回条数 |
| `READ_FILE_ALLOW_DIRS` | 空 | 允许读取的白名单目录（`;` 分隔），空=项目根内 |
| `READ_FILE_MAX_BYTES` | `200000` | 单文件最大读取字节 |
| `STATE_FILE` | `agent_state.json` | 状态文件路径 |
| `LOG_DIR` | `logs` | 日志目录 |
| `LOG_LEVEL` | `INFO` | 日志级别 |

## CLI 参数

```
python agent.py [query] [options]

位置参数:
  query                  用户问题

选项:
  -q, --question         用户问题（与位置参数二选一）
  -r, --max-round        最大迭代轮次（默认 8）
  --no-resume            禁用断点续跑
  --no-save              禁用自动持久化
  --clear-state          运行前先清理状态文件
```

## 架构图

```mermaid
graph TD
    U[用户 CLI / query] --> A[agent.py 主循环]
    A -->|每轮| L[llm.py 调用]
    L --> O[OpenAI 兼容 API]
    O -->|Action:xxx[param]| T[tools.py 调度]
    O -->|FinalAnswer:| R[返回答案]

    subgraph 工具层
        T --> WS[web_search<br/>UA池+节流+缓存]
        T --> RF[read_file<br/>路径安全校验]
    end

    subgraph 支撑层
        A -.读取.-> P[prompts/<br/>system_prompt.txt]
        A -.压缩.-> SZ[summarizer.py]
        A -.持久化.-> ST[state.py<br/>agent_state.json]
        T -.安全.-> SE[security.py]
        T -.日志.-> L2[logger.py]
        A -.配置.-> C[config.py / .env]
    end

    WS -->|Observation| A
    RF -->|Observation| A
```

## 测试

使用 **pytest**，无需真实 LLM / 网络调用即可运行：

```bash
pip install -r requirements.txt   # pytest 已包含
python -m pytest tests/ -v        # 运行全部用例
python -m pytest tests/test_action_parser.py -v
python -m pytest tests/test_security.py -v
```

当前测试覆盖：

| 文件 | 覆盖范围 | 用例数 |
|------|----------|--------|
| `test_action_parser.py` | Action 正则解析：正常 / 空参 / 无参 / 空白 / FinalAnswer / 非法格式 / 超长 / 控制字符 / 白名单拒绝 / 嵌套方括号 | 28 |
| `test_security.py` | 路径安全：合法相对路径 / 绝对路径在根内 / `..` 穿越 / 嵌入 `..` / 绝对越界 / 空值 / 控制字符 / 不存在但在根内 | 11 |

```
============================= 39 passed in 0.31s ==============================
```

## 运行示例

### 场景 1：直接回答（无需工具）

```bash
python agent.py "计算 2+3*4 等于多少？只需要答案" --max-round 3 --no-resume
```

```
2026-10-18 12:44:56 [INFO] tools | 工具已注册: web_search
2026-10-18 12:44:56 [INFO] tools | 工具已注册: read_file
2026-10-18 12:44:56 [INFO] agent | ===== 第 1/3 轮思考 =====
2026-10-18 12:44:59 [INFO] agent | 模型输出: FinalAnswer: 14
2026-10-18 12:44:59 [INFO] agent | ✅ 任务完成，返回答案

✅ Agent 最终结果： 14
```

### 场景 2：读取本地文件

```bash
python agent.py "先读取 agent.py，再告诉我它用什么格式调用工具" --max-round 5
```

模型第 1 轮输出 `Action:read_file[agent.py]` → 执行后得到全文 → 第 2 轮输出 `FinalAnswer:...`。

### 场景 3：网络搜索（可能需要多轮）

```bash
python agent.py "搜索 2026 国内 AI Agent 行业现状，总结" --max-round 8
```

### 断点续跑

如果 Agent 在第 N 轮中断（网络波动等），下次用**相同 query** 再次运行会自动从第 N+1 轮继续：

```bash
python agent.py "搜索..." --no-save     # 强制不续跑
```

## 设计理念

1. **零重型依赖**：除 `openai`、`requests`、`beautifulsoup4`、`python-dotenv` 外无其他依赖
2. **单向数据流**：`agent.py → llm.py / tools.py / summarizer.py → security.py / config.py / logger.py`，`state.py` 独立
3. **可插拔工具**：注册式架构，新工具只需实现 `(str) -> str` 并调用 `_register`
4. **安全默认**：路径越界、控制字符、白名单工具名全部硬拦截
5. **可观测**：全链路 logging，关键节点都有 INFO 级别打点

## 项目亮点
1. 原生手写ReAct循环，无LangChain等重型框架，底层可控，适合安全审计
2. 独立安全模块，针对Agent文件访问做路径穿越防护
3. 工程化能力：断点续跑、原子写入、轮转日志、上下文摘要压缩、爬虫节流缓存
4. 外部化Prompt模板，提示词与业务代码解耦
5. 单元测试覆盖核心协议解析与安全校验，支持自动化回归


## License

MIT
