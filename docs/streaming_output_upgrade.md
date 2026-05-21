# asen cli v1.0 流式输出升级说明

本次升级把 `asen cli` 从“等模型完整返回再显示”，升级为“能流就流、该停就停”的 CLI Agent 交互方式。目标不是单纯把 token 打出来，而是让流式体验与当前 JSON 协议、工具调用循环、Rich UI 兼容。

## 调研结论

主流 CLI Agent 和 coding assistant 普遍会默认启用 streaming，再提供一个关闭开关。底层通常依赖：

- OpenAI-compatible SSE streaming
- `httpx.AsyncClient.stream(...)`
- async iterator 增量消费
- Rich / TUI live rendering

但 `asen cli` 有一个额外约束：当前模型不是直接输出自然语言，而是输出严格的 JSON 协议：`final`、`plan`、`tool_calls`。这意味着不能把原始 token 无脑打印到终端，否则用户会看到半截 JSON、转义字符和工具参数。

因此本次实现采用了一个更贴近真实工程的方案：**Provider 负责流式拿 token，Agent 负责累积完整响应并做增量 JSON 预览提取，Console 只渲染已经确认属于最终回答正文的部分。**

参考资料：

- [httpx async streaming docs](https://www.python-httpx.org/async/)
- [OpenAI streaming docs](https://platform.openai.com/docs/api-reference/streaming)
- [Ollama API docs](https://docs.ollama.com/api)
- [Claude Code streaming output](https://code.claude.com/docs/zh-CN/agent-sdk/streaming-output)
- [Aider docs](https://aider.chat/docs/)

## 设计目标

这一步主要解决五个问题：

1. CLI 默认支持 LLM streaming
2. 终端里最终回答支持 Rich Live 边生成边刷新
3. 遇到 `tool_calls` 时不把半截 JSON 暴露给用户
4. `asen ask` 和 `asen chat` 都支持 `--no-stream`
5. 保持现有 plan/tool calling 架构不被破坏

## 关键实现

### 1. Agent 增加流式主循环

`Agent` 新增 `stream` 开关。CLI 层默认传入 `True`，但类本身默认值保持关闭，这样不会破坏已有直接实例化测试。

在每轮 LLM 调用时：

- `stream=False`：继续走原来的 `complete()`
- `stream=True`：走 `stream_complete()`，一边累积 `raw_response`，一边尝试提取 `final/final_text` 的增量文本

这样可以同时满足两件事：

- 最终仍然拿到完整 JSON 字符串用于协议解析
- 用户侧可以提前看到最终回答正文，而不是看到原始 JSON

### 2. 增量 JSON 预览提取

新增 `_extract_partial_final_text()` 和 `_decode_partial_json_string()`。

职责是：

- 从当前已累积的流式文本里识别是否已经进入 `{"final":"...` 或 `{"final_text":"...`
- 正确处理 `\n`、`\uXXXX` 等 JSON escape
- 只返回当前可安全展示的正文前缀
- 对 `tool_calls` / `plan` / 普通脏输出返回 `None`

这让流式输出和现有协议兼容，而无需把协议整体推翻成 event-based schema。

### 3. Rich Live 渲染

`AsenConsole` 新增了流式渲染状态：

- `_stream_live`
- `_stream_buffer`
- `_last_streamed_message`

工作方式：

- 收到 `on_stream_delta` 时，创建或更新 `Live(Panel(Markdown(...)))`
- 收到 `on_stream_end` 时停止 live，并保留最后一帧
- 后续 `assistant()` 如果发现已经完整流式渲染过同一条消息，就不再重复打印

这保证了用户看到的是单份最终结果，而不是“先流一遍、再面板重复打一遍”。

### 4. 工具调用前停止流

本项目的协议里，工具调用不是自然语言和 tool call 混流，而是由模型返回 `{"tool_calls": [...]}`。

因此这里的“工具调用前停止流”实现为：

- 只有识别到 `final/final_text` 时才开启用户可见流式渲染
- 如果这一轮是 `tool_calls` 或 `plan`，不会向用户流出 JSON
- 在每次流式响应完成后触发 `stream_end()`，再继续走 `parse_agent_response()` 和工具执行

这比“先把 JSON 刷到屏幕上再收回”更符合真实 CLI 体验。

### 5. `--stream/--no-stream`

`app.py` 中 `asen chat` 和 `asen ask` 都新增：

```bash
--stream / --no-stream
```

默认值为 `--stream`。如果需要稳定截图、录屏回放，或者想保留旧行为，可以直接加 `--no-stream`。

## 受影响文件

```text
src/asen_cli/core/agent.py
src/asen_cli/ui/console.py
src/asen_cli/app.py
src/asen_cli/llm/openai_client.py
src/asen_cli/llm/ollama_client.py
tests/test_agent.py
tests/test_llm_providers.py
tests/test_streaming_cli.py
```

其中：

- `agent.py`：流式主循环、增量 final 提取、流式事件
- `console.py`：Rich Live 渲染与最终回答去重
- `app.py`：CLI 开关与参数透传
- `openai_client.py` / `ollama_client.py`：流式接口复用注入的 `AsyncClient`
- 测试：覆盖 provider streaming、Agent streaming、CLI 参数透传

## 使用方式

默认流式：

```bash
asen chat --workspace examples/demo_project
```

一次性任务也支持流式：

```bash
asen ask "解释 hello.py" --workspace examples/demo_project
```

关闭流式：

```bash
asen ask "解释 hello.py" --workspace examples/demo_project --no-stream
```

查看内部细节：

```bash
asen chat --workspace examples/demo_project --verbose
```

## 验证

本次升级新增并通过了以下验证：

- `Agent` 流式最终回答事件测试
- partial JSON final 提取测试
- OpenAI-compatible streaming 测试
- Ollama streaming 测试
- `--stream/--no-stream` CLI 透传测试

执行结果：

```bash
.venv/bin/python -m pytest tests/test_agent.py tests/test_llm_providers.py tests/test_streaming_cli.py -q
.venv/bin/python -m ruff check src/asen_cli/core/agent.py src/asen_cli/ui/console.py src/asen_cli/app.py src/asen_cli/llm/openai_client.py src/asen_cli/llm/ollama_client.py tests/test_agent.py tests/test_llm_providers.py tests/test_streaming_cli.py
```

## 面试讲法

可以这样讲：我给 CLI Agent 增加了流式输出，不只是把 HTTP streaming 打通，而是结合现有 JSON 工具协议做了“增量 final 提取”。底层用 `httpx.AsyncClient.stream` 和 async iterator 从 OpenAI-compatible SSE、Ollama JSON lines 里持续读取数据；中间层由 Agent 保持完整响应缓冲，同时增量识别 `final/final_text` 字段；终端层用 Rich Live 渲染最终答案，并在工具调用阶段自动停流。这能体现我对异步编程、流式协议解析、终端渲染和工程兼容性的理解。
