# Session Persistence 升级说明

## 背景

Agent 的很多任务并不是一次完成的：你可能先读代码、跑一次工具、改一部分文件，过几个小时再回来继续。如果每次退出都丢上下文，CLI Agent 的工作流就会被打断。因此，这次升级给 `asen-cli` 增加了轻量版会话持久化，让交互式会话可以保存、列出和恢复。

## 本次升级内容

### 1. 自动保存到 `.asen/sessions/`

每次启动 `asen chat` 或 `asen shell`，都会在当前 workspace 下创建一个新的会话目录：

```text
.asen/sessions/<session_id>/
```

目录里包含三类文件：

- `events.jsonl`：按时间顺序记录会话事件
- `meta.json`：保存 session id、模式、模型、更新时间、turn/tool 计数、摘要预览等元数据
- `summary.md`：保存最终修改摘要或最近一次回答摘要

### 2. 新增 `asen session list`

现在可以用：

```bash
asen session list --workspace examples/demo_project
```

列出当前工作区下的历史会话。列表会显示：

- `session_id`
- `session_mode`（`chat` / `shell`）
- 最近更新时间
- 对话轮次
- 工具调用次数
- 摘要预览

默认按最近更新时间倒序排序，这样最新的会话会排在最前面。

### 3. 新增 `asen session resume <id>`

现在可以用：

```bash
asen session resume 2026-05-19-demo --workspace examples/demo_project
```

恢复指定会话。恢复时会读取 `events.jsonl` 里最新的 `context_snapshot`，把历史 `messages`、`summary`、`facts` 和 `plan_steps` 重新注入 `agent.context`，然后继续进入交互会话。

如果传入的是唯一前缀，也能匹配成功；如果命中了多个 session，则会直接报歧义错误，避免恢复错会话。

### 4. 保存工具调用记录

这次升级没有一开始就引入数据库，而是沿用了现有 `ToolRegistry.logs()` 的结构，把工具调用记录写进 `events.jsonl`。记录内容包括：

- 工具名
- 参数
- 是否成功
- 错误类型 / 错误信息
- 是否可重试
- 耗时毫秒数

这样第一版就能保留足够的调试与追溯信息，同时保持实现足够轻量。

### 5. 保存最终修改摘要

会话层会在每轮交互后生成摘要，并写入 `summary.md` 与 `meta.json`：

- 如果上下文里有文件修改事实，会优先整理成“Recent file edits”
- 如果有执行中的 plan，会附带 plan 状态
- 如果有最近失败的工具调用，也会写入摘要
- 否则退化为最近一次 assistant 回答摘要

这让 `session list` 能显示简短摘要，也让恢复或回顾会话时更容易快速建立上下文。

## 关键实现点

### `core/session_store.py`

新增 `SessionStore`，负责：

- 创建会话目录与 session id
- 追加 JSONL 事件
- 维护 `meta.json`
- 写入 `summary.md`
- 读取最近一次上下文快照
- 支持按完整 id 或唯一前缀打开会话

### `core/context_manager.py`

新增：

- `snapshot()`：导出当前消息、summary、facts、plan steps
- `load_snapshot()`：把导出的快照重新恢复到 context
- `latest_assistant_message()`：帮助生成最终摘要

这让 resume 不必重放整个事件流，也不需要数据库就能恢复到最近状态。

### `core/session.py`

`ChatSession` 现在会：

- 启动时创建或恢复 `SessionStore`
- 记录 `user_message` / `assistant_message`
- 记录 `shell_command`
- 记录新增的工具日志
- 在每轮结束后写入 `context_snapshot`
- 在退出时写入 `session_closed`

因此，session 持久化主要发生在交互层，而不是侵入 Agent 主循环太深。

### `app.py`

CLI 层新增：

- `asen session list`
- `asen session resume <id>`

同时 `chat` / `shell` 启动路径也接上了自动创建 `SessionStore` 的逻辑。

## 为什么先用 JSONL，不急着上 SQLite

第一版选择 JSONL，主要因为：

- 结构简单，可直接打开查看和调试
- 追加写入天然适合 event log
- 不需要额外 schema migration
- 更适合教学和面试演示，容易说明“会话就是事件流”

它的缺点也很明确：

- 大会话读取会变慢
- 查询能力弱，不适合复杂过滤
- 并发写入能力一般

但对于当前 `asen-cli` 的单用户、本地工作区、交互式使用场景，这个取舍是合理的。等后面真的出现大量 session 检索、跨项目聚合、复杂统计需求，再升级到 SQLite 会更顺。

## 使用建议

推荐工作流：

1. `asen chat` 或 `asen shell`
2. 让 Agent 分析、执行工具、修改文件
3. 输入 `/exit` 退出
4. 之后用 `asen session list` 找回会话
5. 用 `asen session resume <id>` 继续工作

这个流程最适合跨时段开发、任务被打断、或者需要回顾改动路径的场景。

## 面试讲法

可以这样概括：

> Agent 的任务往往不是一次完成的，所以我给 CLI 设计了会话持久化。第一版我没有急着上数据库，而是用 JSONL 记录事件流，再用 `meta.json` 和 `summary.md` 做索引和摘要。这样用户可以通过 `asen session list` 找到历史会话，再用 `asen session resume <id>` 恢复上下文继续执行，同时也能保留工具调用记录和最终修改摘要。

## 验证

本次升级新增或更新了以下测试：

- `test_session_store.py`：快照恢复、列表与前缀查找、摘要生成
- `test_session.py`：交互会话内的事件持久化与 summary 写盘
- `test_streaming_cli.py`：`session resume` 参数透传和 `session list` 空状态
- `test_context_manager.py`：上下文快照导出与恢复

相关回归测试与 `ruff check` 也已通过。
