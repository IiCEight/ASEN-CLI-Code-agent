# Editor Integration / VS Code Extension 升级说明

## 背景

终端 AI 编程助手一旦开始接入编辑器，就不能只靠“给人看”的 Rich 输出。编辑器需要稳定的机器可读协议，知道一次运行的最终文本、执行事件、哪些文件被改了、diff 在哪、checkpoint 又在哪。

因此这次升级把目标拆成两层：

1. 在 `asen-cli` 里提供稳定的 `--json` 输出模式。
2. 在编辑器侧做一个轻量 VS Code Extension，直接调用本地 `asen`。

## 设计原则

### 1. CLI 是能力中心，编辑器是消费层

`asen-cli` 继续负责：

- Agent 循环
- 工具调用
- 文件修改
- checkpoint / diff 生成
- 安全边界

VS Code Extension 只负责：

- 读取当前工作区 / 当前文件
- 收集用户输入
- 调用本地 `asen` 命令
- 解析 JSON 结果
- 打开 diff / 展示输出 / 触发 restore

### 2. 首版不做 ACP / LSP，先做命令协议

首版没有直接上 ACP、MCP transport 或 LSP，而是先把边界稳定在命令协议：

```bash
asen ask "..." --json --no-stream --workspace <workspace>
asen checkpoint list --json --workspace <workspace>
asen checkpoint diff <id> --json --workspace <workspace>
asen checkpoint restore <id> --json --force --workspace <workspace>
```

优点是：

- 改动小，能快速演示
- 其他编辑器也能复用
- 后续升级到更重协议时，不会推翻现有 JSON 结构

## CLI 侧改动

### `asen ask --json`

输出单个 JSON 对象，包含：

- `ok`
- `command`
- `task`
- `workspace`
- `final_text`
- `events`
- `tool_results`
- `tool_failures`
- `checkpoints`
- `changed_files`

### `asen checkpoint * --json`

- `asen checkpoint list --json`：返回 checkpoint 摘要列表
- `asen checkpoint diff <id> --json`：返回 checkpoint 元数据、变更文件和 unified diff
- `asen checkpoint restore <id> --json --force`：返回 restore 动作结果

### 结构化工具结果

`ToolResult` 新增 `meta` 字段。对会修改文件的工具，`meta` 会携带：

- `changed_files`
- `checkpoints`
- `diff`
- `before_snapshot_path`
- `after_snapshot_path`
- `diff_file_path`

这样 JSON 输出层不需要再去解析人类可读字符串。

## VS Code Extension 侧改动

扩展目录：`../asen-vscode-extension`

### 当前命令

- `ASEN: Modify Current File`
- `ASEN: Show Last Diff`
- `ASEN: Restore Checkpoint`

### 工作流

1. 用户在 VS Code 里打开一个文件。
2. 扩展提示输入修改意图。
3. 扩展拼装任务文本，并执行 `asen ask --json --no-stream`。
4. CLI 返回 `final_text`、`changed_files`、`checkpoints`。
5. 扩展把 `final_text` 写到 `OutputChannel`，再根据 `before_snapshot_path` 打开 `vscode.diff`。
6. 如果用户需要回滚，扩展调用 `asen checkpoint list --json` 和 `asen checkpoint restore --json --force`。

## 面试讲法

可以这样讲：

> 终端 AI 助手和编辑器集成时，最重要的是把“人类可读输出”和“机器可读协议”分开。我在 CLI 里增加了 `--json` 输出模式，把 `final_text`、工具调用事件、diff、checkpoint 和快照路径结构化返回；然后做了一个轻量 VS Code Extension，只负责收集当前文件上下文、调用本地 `asen` 命令，并用这些 JSON 字段打开 diff 和触发回滚。这样边界很清晰：CLI 管能力，编辑器管 UI。

## 验证方式

```bash
cd asen-cli
pytest tests/test_streaming_cli.py tests/test_tools_file.py tests/test_tools_edit.py tests/test_checkpoint_store.py -q
ruff check src/asen_cli tests/test_streaming_cli.py tests/test_tools_file.py tests/test_tools_edit.py tests/test_checkpoint_store.py

cd ../asen-vscode-extension
npm install
npm run compile
```
