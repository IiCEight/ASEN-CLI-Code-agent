# asen cli v0.4 代码搜索能力升级说明

本次升级的目标是让 `asen cli` 不再只能读取单个文件，而是具备项目级上下文发现能力。真实 coding agent 在修改代码前通常会先查看目录结构、查找文件、搜索关键字，再批量读取相关文件。本次新增的搜索工具正是为了补齐这个能力。

## 新增工具

### 1. `find_files`

按文件名或相对路径 glob 查找文件，适合快速定位入口、测试文件、配置文件。

示例工具调用：

```json
{"tool_calls": [{"name": "find_files", "arguments": {"pattern": "*.py"}}]}
```

### 2. `search_text`

在项目文件中搜索普通文本，适合查找函数名、类名、配置项、错误文案。它使用 literal substring 搜索，不把查询当正则处理。

```json
{"tool_calls": [{"name": "search_text", "arguments": {"query": "ToolRegistry", "file_pattern": "*.py"}}]}
```

### 3. `grep_context`

按正则搜索并返回上下文行，适合分析调用点、日志关键字、相邻代码逻辑。

```json
{"tool_calls": [{"name": "grep_context", "arguments": {"pattern": "class\\s+Agent", "file_pattern": "*.py", "context_lines": 2}}]}
```

### 4. `show_tree`

展示压缩后的目录树，适合让 Agent 快速了解项目结构。

```json
{"tool_calls": [{"name": "show_tree", "arguments": {"max_depth": 3}}]}
```

### 5. `read_many_files`

批量读取多个 UTF-8 文本文件，适合在搜索定位后一次性加载相关上下文。

```json
{"tool_calls": [{"name": "read_many_files", "arguments": {"paths": ["src/asen_cli/app.py", "src/asen_cli/core/agent.py"]}}]}
```

## 安全与边界

所有搜索工具都复用 workspace 路径限制，用户传入的路径必须在 workspace 内。搜索过程默认跳过 `.git`、`__pycache__`、`.venv`、`node_modules`、`dist`、`build` 等常见噪音目录，并对输出进行截断，避免一次搜索把上下文撑爆。

`search_text` 和 `grep_context` 只读取 UTF-8 文本文件，遇到二进制或无法解码的文件会跳过。`read_many_files` 会检查文件大小，超过配置的 `max_file_bytes` 会返回结构化错误而不是强行读取。

## 面试讲法

可以这样介绍：早期版本的 Agent 只能通过 `read_file` 单点读取文件，这对真实项目不够。Coding agent 需要先做项目级检索，定位相关文件，再读取和修改。因此我新增了 `find_files`、`search_text`、`grep_context`、`show_tree` 和 `read_many_files` 五个工具，让 Agent 具备从“项目结构理解”到“相关上下文收集”的完整链路。

这一步体现了几个工程点：`pathlib` 路径处理、`fnmatch` glob 匹配、`re` 正则检索、workspace 安全边界、输出截断和工具 schema 可扩展性。新增工具只需要实现独立 Tool 类和 Args 模型，再注册到 `ToolRegistry`，不需要修改 Agent 主循环，符合开放封闭原则。
