# Shell Mode 升级说明

## 背景

真实 CLI Agent 往往不只会“对话”，还会把自然语言工作流和传统 shell 操作揉在一起。对 `asen-cli` 来说，加入轻量版 Shell 模式的目标不是做一个完整终端替代品，而是让用户在同一个会话里既能 `!pytest`、`!git status`，也能立刻追问 Agent “刚才为什么失败” 或 “下一步该怎么修”。

## 本次升级内容

### 1. 新增 `asen shell`

现在可以通过：

```bash
asen shell --workspace examples/demo_project
```

进入一个 shell-heavy 的交互会话。它本质上仍然保留 Agent 对话能力，但启动标题、提示文案和使用习惯都会更偏向命令行工作流。

### 2. `asen chat` / `asen shell` 都支持 `!command`

例如：

```text
! ls
! pytest -q
! git status
```

会话层会先拦截 `!` 前缀，然后交给交互式 Shell runner 执行，而不是让模型决定是否调用 `shell` tool。

### 3. 安全分级

手动 Shell 模式采用了三档策略：

- `safe`：直接执行，例如 `ls`、`pwd`、`git status`、`pytest`
- `confirm`：高风险命令先确认，例如 `git push`、`git reset`、依赖安装、输出重定向、`docker` / `kubectl` / `ssh` 等
- `blocked`：明显危险命令直接拒绝，例如 `sudo`、`rm -rf /`、`mkfs`、`dd of=/dev/...`、`shutdown`、fork bomb

这样做的原因是：手动输入的命令本来就带有更强的用户意图，因此没必要像模型 tool call 一样默认每条都确认；但涉及文件破坏、远程环境或不可逆副作用时，仍然需要 guard。

### 4. 输出捕获与截断

命令执行仍复用已有 `ShellCommandTool` 的 subprocess 实现：

- `asyncio.create_subprocess_shell`
- workspace 作为 `cwd`
- stdout / stderr 捕获
- timeout 保护
- 输出按 `max_tool_output_chars` 截断

终端侧使用新的 `shell_command` / `shell_result` 渲染：先显示命令，再用 Rich Panel 展示结果。

### 5. 结果进入 Agent 上下文

这是这次升级的关键点。`!command` 执行完成后，结果会被写成一条 `tool` 消息：

```text
command=pytest -q
exit_code=1
...
```

然后进入 `agent.context`。因此下一轮自然语言提问时，模型可以直接利用刚才的命令结果继续推理，而不是要求用户重复粘贴。

## 关键实现点

### `core/shell_mode.py`

新增 `InteractiveShellRunner`，负责：

- 校验空命令
- 使用 `assess_command_safety()` 做风险分级
- 在 `require_approval=True` 时对高风险命令发起确认
- 最终复用 `ShellCommandTool(require_approval=False)` 进行实际执行

### `core/session.py`

`ChatSession.run()` 增加 `!command` 分支：

1. 读取输入
2. 如果以 `!` 开头，走 `_run_shell_command()`
3. 否则继续 slash command 或普通 Agent 输入逻辑

`_run_shell_command()` 会负责显示输出，并把结果写入 `agent.context`。

### `utils/safety.py`

新增 `CommandSafetyCheck` 和 `assess_command_safety()`，把“阻断”和“确认”从原来单一的危险命令判断拆成两层，既保住安全边界，也让手动 shell 更顺手。

### `ui/console.py`

终端 UI 新增：

- shell 会话标题
- `!command` 提示
- shell 命令执行行
- shell 结果面板

## 使用建议

### 日常工作流

推荐这样用：

1. `asen shell`
2. `!pytest -q`
3. `!git status`
4. 直接输入“根据失败结果帮我修一下”

这样可以把“执行命令”和“解释结果”合在一个闭环里。

### 什么时候用 `asen shell`

- 你要频繁跑命令，再让 Agent 解读结果
- 你想把 shell 输出自动带进上下文
- 你希望会话提示更偏向命令行工作流

### 什么时候继续用 `asen chat`

- 任务主要是自然语言驱动，偶尔才需要 `!command`
- 你更看重纯 Agent 风格的交互

## 面试讲法

可以这样概括：

> 我把自然语言 Agent 和传统 shell 操作结合到一个会话里。用户既可以直接 `!pytest`、`!git status`，也可以马上让 Agent 基于这些结果继续分析。实现上我用 subprocess 做命令执行、timeout 和输出捕获，用命令 guard 做风险分级，并把 shell 结果回填到 Agent 上下文，形成一个更贴近真实 CLI Agent 的工作流。

## 验证

本次升级补充了以下测试：

- `test_shell_mode.py`：风险分级、确认、阻断与 no-approval 行为
- `test_session.py`：`!command` 分发与上下文注入
- `test_streaming_cli.py`：`asen shell` 命令与流式参数透传
- `test_safety.py`：命令风险分级判断

相关回归测试也已通过。
