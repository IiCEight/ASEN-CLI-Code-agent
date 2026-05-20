# asen cli v0.3 工具调用协议升级说明

本次升级把 `asen cli` 的工具层从简单 JSON 字典调用，升级为更规范的 Tool Calling 层。核心变化是：每个工具用 Pydantic 定义 Args 模型，`BaseTool` 自动导出 JSON Schema 并统一校验参数，`ToolRegistry` 统一负责工具分发和执行日志，`Agent` 根据工具失败类型给模型反馈，允许模型修正参数后重试。

## 升级内容

### 1. Pydantic Args 模型

每个工具都拥有独立的输入参数模型。例如 `read_file`：

```python
class ReadFileArgs(BaseModel):
    path: str = Field(..., description="Relative or absolute path inside the workspace.")
```

这样参数类型、必填字段、默认值和字段描述都集中在一个地方，工具内部不再散落大量 `arguments.get(...)`。

### 2. 标准 JSON Schema 导出

`BaseTool.schema()` 会自动把 Args 模型转换成 JSON Schema。工具 schema 现在类似：

```json
{
  "name": "read_file",
  "description": "Read a UTF-8 text file inside the workspace.",
  "parameters": {
    "type": "object",
    "properties": {
      "path": {
        "type": "string",
        "description": "Relative or absolute path inside the workspace."
      }
    },
    "required": ["path"]
  }
}
```

这比原来的 `arguments: {"path": "..."}` 更接近真实 LLM Tool Calling / Function Calling 的设计。

### 3. 统一参数校验

所有工具都通过 `BaseTool.execute()` 统一校验参数。如果模型漏传字段、字段类型错误或 URL 格式不合法，会返回：

```text
ERROR[validation_error] retryable=true: Invalid arguments for read_file: ...
```

这类错误被标记为 `retryable=true`，Agent 会把失败原因反馈给模型，提示它修正参数后重试。

### 4. 结构化 ToolResult

`ToolResult` 现在包含：

```text
ok
content
error
error_type
retryable
```

常见错误类型包括：`validation_error`、`unknown_tool`、`safety_error`、`user_rejected`、`file_not_found`、`network_error`、`timeout`。其中 validation、unknown、网络和部分 IO 错误通常可重试，安全拦截和用户拒绝不可重试。

### 5. ToolRegistry 执行日志

`ToolRegistry` 会记录每次工具调用：工具名、参数、是否成功、错误类型、是否可重试和耗时。后续可以基于这个日志继续做 `/logs`、调试面板、执行轨迹导出等能力。

### 6. Agent 失败重试反馈

当工具调用失败时，Agent 会把失败原因写回上下文：

```text
The previous tool call `read_file` failed with validation_error: ... Please correct the tool name or arguments and retry if needed.
```

如果是 `safety_error` 或 `user_rejected`，Agent 会提示模型不要重复执行同样的危险或被拒绝操作。

## 面试讲法

可以这样介绍：第一版工具调用只是让模型返回简单 JSON，工具自己从 dict 里取参数。第二版我把工具调用升级成标准化 Tool Calling 层：每个工具用 Pydantic 定义输入模型，自动导出 JSON Schema，`ToolRegistry` 统一做参数校验、工具分发和执行日志，`Agent` 只负责根据模型输出调度工具。新增工具时只需要新增一个 Tool 类和 Args 模型，不需要修改 Agent 主循环，符合开放封闭原则。

失败处理也做了区分：`validation_error` 会反馈给模型让它修正参数并重试，`safety_error` 和 `user_rejected` 不会盲目重试，避免危险操作循环执行。
