# asen cli v0.2 交互体验升级说明

本次升级的目标是把 `asen chat` 从简单的 `while True + input` 循环升级为一个更像真实 CLI coding agent 的交互式 Agent Shell。它不改变核心 Agent 推理逻辑，而是在外层补齐 slash commands、历史输入、多行输入、状态提示和 verbose 调试能力。

## 升级内容

### 1. Slash commands

交互模式现在支持本地控制命令：

| 命令 | 作用 |
|---|---|
| `/help` | 查看可用命令 |
| `/tools` | 查看当前 Agent 可调用的工具 |
| `/config` | 查看当前运行配置，API Key 会被隐藏 |
| `/clear` | 清空终端屏幕 |
| `/paste` | 进入多行输入模式，单独输入 `EOF` 结束 |
| `/exit`、`/quit` | 退出会话 |

设计上，slash commands 不交给大模型处理，而是在 CLI 本地执行。这样可以保证 `/exit`、`/clear`、`/config` 这类控制命令稳定、快速、可预测。

### 3. prompt-toolkit 输入层

新增 `src/asen_cli/ui/input.py`，使用 `prompt-toolkit` 替换简单的 Rich Prompt。现在交互模式支持历史记录和命令补全，历史文件默认保存到 `~/.asen/history.txt`，不会污染当前项目目录。

### 3. 多行输入

通过 `/paste` 支持多行内容输入，适合粘贴错误日志、代码片段、需求描述。示例：

```text
asen> /paste
Paste multiline input. Finish with a single EOF line.
... 下面是报错日志：
... Traceback ...
... EOF
```

### 4. 状态提示和 verbose 模式

`Agent` 新增 `AgentEvents` 事件回调，不直接依赖 Rich 或终端 UI。`AsenConsole` 订阅这些事件后，可以展示：模型正在思考、正在调用哪个工具、工具结果、原始模型响应等。

普通模式会展示简洁状态：

```text
thinking... step 1
calling tool read_file
```

verbose 模式会展示更完整的调试信息：

```bash
asen chat --workspace examples/demo_project --verbose
asen ask "读取 hello.py 并解释" --workspace examples/demo_project --verbose
```

### 6. 模块拆分

本次新增或调整的核心模块：

```text
src/asen_cli/ui/input.py      # prompt-toolkit 输入、历史记录、补全、多行输入
src/asen_cli/ui/slash.py      # slash command 解析和帮助文案
src/asen_cli/core/session.py  # ChatSession 主循环
src/asen_cli/core/agent.py    # AgentEvents 事件回调
src/asen_cli/ui/console.py    # Rich 状态展示和 verbose 输出
```

`app.py` 现在只负责 Typer 命令入口和对象装配，不再承载复杂交互循环。

## 使用方式

安装依赖后启动交互模式：

```bash
asen chat --workspace examples/demo_project
```

查看命令：

```text
asen> /help
```

查看工具：

```text
asen> /tools
```

查看配置：

```text
asen> /config
```

粘贴多行内容：

```text
asen> /paste
... 请解释下面的代码：
... print("hello")
... EOF
```

开启详细执行日志：

```bash
asen chat --workspace examples/demo_project --verbose
```

## 面试讲法

可以这样介绍这次升级：第一版实现了 coding agent 的最小闭环，第二版重点优化 CLI 交互层。我引入 `prompt-toolkit` 支持历史输入和命令补全，用 slash command 区分本地控制命令和自然语言任务，用 `ChatSession` 把交互循环从 Typer 命令入口中拆出来，并通过 `AgentEvents` 事件回调把 Agent 执行过程可视化，同时保持核心 Agent 与终端 UI 解耦。

这个设计体现了几个工程点：CLI 交互体验、职责分离、事件回调、可测试性、调试可观测性，以及对真实 coding agent 产品体验的理解。
