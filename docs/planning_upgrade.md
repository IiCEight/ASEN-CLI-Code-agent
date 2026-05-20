# asen cli v0.6 任务计划能力升级说明

本次升级把 `asen cli` 从“模型直接调用工具”的执行方式，升级为更接近真实 coding agent 的“计划-执行-反馈”循环。对于多步骤、项目级或会修改 workspace 的任务，模型可以先返回计划，CLI 展示计划后再继续逐步执行。

## 新增协议

### Plan JSON

模型现在可以返回计划：

```json
{
  "plan": [
    {"id": "1", "content": "Inspect project structure"},
    {"id": "2", "content": "Read relevant files"},
    {"id": "3", "content": "Apply safe edit"},
    {"id": "4", "content": "Run verification"},
    {"id": "5", "content": "Summarize result"}
  ]
}
```

`Agent` 接收到计划后会把每一步转成 `PlanStep`，初始状态是 `pending`。随后它会向模型反馈 `Plan accepted`，让模型开始逐步执行。

### PlanStep 状态

每个计划步骤有四种状态：

```text
pending
in_progress
completed
failed
```

当模型开始执行工具调用时，Agent 会把第一个 pending 步骤标记为 `in_progress`。工具调用成功后标记为 `completed`；如果工具失败，则标记为 `failed`，并把失败原因反馈给模型。

## UI 展示

`asen chat` 会用 Rich Table 展示 Execution Plan，并在执行过程中输出步骤状态变化：

```text
Execution Plan
1 pending     Inspect project structure
2 pending     Read relevant files
3 pending     Apply safe edit

├─ plan 1. Inspect project structure [running]
├─ tool show_tree
├─ plan 1. Inspect project structure [done]
```

## 失败后重新规划

如果工具调用失败，Agent 会根据 `ToolResult.retryable` 给模型不同反馈：

如果错误可重试，例如 `validation_error`、`file_not_found`、`patch_conflict`，Agent 会提示模型修正参数或在必要时返回新计划。

如果错误不可重试，例如 `safety_error`、`user_rejected`，Agent 会提示模型不要重复危险或被拒绝的动作，而是解释失败或选择更安全的替代方案。

## 设计取舍

当前版本没有实现复杂的多 Agent 调度，也没有把计划持久化到数据库。它选择了一个教学友好的轻量实现：计划在单次 Agent 运行中保存在内存里，状态通过 `AgentEvents` 发给 UI 展示。这样代码复杂度可控，但已经能讲清楚真实 coding agent 中“计划层”和“执行层”解耦的核心思想。

## 面试讲法

可以这样介绍：早期版本的 Agent 拿到任务后可能直接调用工具，这对复杂任务不够稳定。我引入了 `PlanStep` 状态模型和计划协议，让模型先把任务拆成 3-7 个步骤，Agent 展示计划后再逐步执行。每次工具调用会驱动计划状态从 `pending` 到 `in_progress`，再到 `completed` 或 `failed`。失败时 Agent 会把错误类型反馈给模型，支持修正参数、重试或重新规划。

这一步体现了几个工程点：Agent state machine、plan/execution separation、task status model、失败反馈、retry strategy，以及通过事件回调让核心 Agent 与 Rich UI 解耦。
