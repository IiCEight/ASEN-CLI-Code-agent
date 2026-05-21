# Checkpoint / 回滚能力升级说明

## 背景

AI 修改代码的效率很高，但风险也很直接：一旦写错文件、替换错内容、或者批量改动后才发现方向不对，用户需要一种比手动撤销更稳定的恢复方式。为了解决这个问题，这次升级给 `asen-cli` 增加了轻量版 checkpoint 机制，让核心写文件工具在真正写盘前自动创建快照，并支持列表、diff 和回滚。

## 本次升级内容

### 1. 写文件前自动创建 checkpoint

现在 `write_file`、`replace_in_file`、`apply_patch` 在真正落盘前，都会自动在当前 workspace 下创建一个 checkpoint：

```text
.asen/checkpoints/<checkpoint_id>/
```

这意味着只要 Agent 触发了实际文件修改，就会留下一个可检索、可查看、可恢复的回滚点。

### 2. Checkpoint 的目录结构

每个 checkpoint 目录里包含：

```text
.asen/checkpoints/<checkpoint_id>/
├── meta.json
├── manifest.json
├── diff.patch
├── before/
└── after/
```

这些文件分别承担不同职责：

- `meta.json`：保存 `checkpoint_id`、工具名、工作区、创建时间、更新时间、文件数、摘要预览
- `manifest.json`：保存本次 checkpoint 涉及的文件条目，例如文件路径、修改类型、快照路径、字节数
- `diff.patch`：保存本次修改对应的 unified diff，供 `asen checkpoint diff <id>` 直接展示
- `before/`：保存修改前文件内容
- `after/`：保存修改后文件内容

第一版保持一个 checkpoint 对应一次核心文件写入，这样实现简单、语义直观，也更容易演示和调试。

### 3. 新增 `asen checkpoint list`

现在可以用：

```bash
asen checkpoint list --workspace examples/demo_project
```

列出当前工作区下的历史 checkpoint。列表会显示：

- `checkpoint_id`
- `tool_name`
- 最近更新时间
- 文件数
- 摘要预览

默认按最近更新时间倒序排序，最新的 checkpoint 会排在最前面。

### 4. 新增 `asen checkpoint diff <id>`

现在可以用：

```bash
asen checkpoint diff 2026-05-21-170512-write-file --workspace examples/demo_project
```

直接查看该 checkpoint 当时捕获到的 unified diff。第一版采用“写入时静态保存 diff”的方式，而不是运行时动态比对当前文件状态。这样做有两个好处：

第一，diff 展示稳定，不会因为用户之后又改过文件而变化。第二，实现简单，不需要在查看 diff 时再做一轮复杂状态推导。

### 5. 新增 `asen checkpoint restore <id>`

现在可以用：

```bash
asen checkpoint restore 2026-05-21-170512-write-file --workspace examples/demo_project
```

恢复指定 checkpoint。默认会要求确认，也支持：

```bash
asen checkpoint restore 2026-05-21-170512-write-file --workspace examples/demo_project --force
```

恢复逻辑遵循 manifest：

- 如果该文件在 checkpoint 前就存在，则回写 `before/` 中保存的旧内容
- 如果该文件是在 checkpoint 中新建的，则 restore 时删除该文件

这使得第一版无需引入数据库、无需依赖 Git，也能完成稳定的文件级回滚。

## 关键实现点

### `core/checkpoint_store.py`

新增 `CheckpointStore`，负责：

- 生成 checkpoint id
- 创建 `.asen/checkpoints/<checkpoint_id>/`
- 保存 `meta.json`、`manifest.json`、`diff.patch`
- 保存 `before/` 和 `after/` 快照
- 提供 `list()`、`open()`、`render_diff()`、`restore()` 等能力
- 支持按完整 id 或唯一前缀打开 checkpoint

### `tools/file.py`

`WriteFileTool` 现在会：

- 先读取旧内容（如果文件已存在）
- 生成 diff 预览
- 在用户确认后、真正写盘前创建 checkpoint
- 在工具结果中返回 checkpoint id

这补齐了原先 `write_file` 没有写前快照的问题。

### `tools/edit.py`

`ReplaceInFileTool` 和 `ApplyPatchTool` 现在会同时保留两层安全网：

- 旧的 `.asen/snapshots/` 低层文件快照
- 新的 `.asen/checkpoints/` 高层 checkpoint

这样既不破坏已有 snapshot 行为，又把 checkpoint list / diff / restore 所需的数据模型补齐了。

### `app.py`

CLI 层新增一个新的 `checkpoint` 子应用，包含：

- `asen checkpoint list`
- `asen checkpoint diff <id>`
- `asen checkpoint restore <id>`

命令风格和 `session` 子应用保持一致，也支持唯一前缀匹配。

### `ui/console.py`

为 checkpoint 功能新增了：

- checkpoint 列表表格渲染
- checkpoint diff 面板渲染

这样终端输出风格能和 `session list`、工具结果展示保持统一。

## 为什么第一版不用 Git 或数据库

这一步刻意没有把 checkpoint 做成完整版本控制系统，也没有引入 SQLite。原因很简单：目标是先解决“AI 改错文件后能稳定回滚”这个核心问题，而不是在第一版就做复杂历史管理。

相比 Git 或数据库，这套方案的优点是：

- 目录结构透明，直接打开就能看
- 写前快照和 diff 的实现成本低
- 不依赖用户仓库一定已经初始化 Git
- 非常适合教学、演示和面试讲述

它的边界也很明确：

- 当前以单次核心写工具为粒度，不是多文件事务 checkpoint
- 没做冲突合并策略，只做确定性回写
- 没做大规模历史检索和复杂过滤

但对当前 `asen-cli` 的阶段来说，这个取舍是合理的。

## 使用建议

推荐工作流：

1. 正常使用 `asen chat` / `asen shell` 让 Agent 修改文件
2. 如果怀疑某次修改不对，先执行 `asen checkpoint list`
3. 用 `asen checkpoint diff <id>` 确认这个 checkpoint 改了什么
4. 再执行 `asen checkpoint restore <id>` 回滚

这比手动找文件、复制旧内容、逐个撤销更稳，也更适合 AI 编码场景。

## 面试讲法

可以这样概括：

> AI 修改代码有风险，所以我给 CLI Agent 设计了 checkpoint 机制。第一版我没有直接上数据库或完整版本控制，而是让核心写文件工具在真正写盘前自动保存文件快照、diff 和元数据。这样用户可以通过 `asen checkpoint list` 找到历史修改点，再用 `asen checkpoint diff` 看具体改动，最后用 `asen checkpoint restore` 快速回滚，保证每次 AI 写代码都可追溯、可恢复。

## 验证

本次升级新增或更新了以下测试：

- `test_checkpoint_store.py`：覆盖 list、diff、restore existing-file、restore created-file
- `test_tools_file.py`：覆盖 `write_file` 的 checkpoint 创建
- `test_tools_edit.py`：覆盖 `replace_in_file` / `apply_patch` 的 checkpoint 创建
- `test_streaming_cli.py`：覆盖 `checkpoint list` 空状态、`checkpoint diff` 输出、`checkpoint restore --force`

相关回归测试共 45 项通过，`ruff check` 也已通过。
