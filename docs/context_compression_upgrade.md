# asen cli v0.7 上下文压缩升级说明

本次升级的目标是解决长对话和大工具结果带来的上下文膨胀问题。早期版本只用简单消息数量窗口来裁剪历史，容易把任务目标、计划状态、已修改文件、工具失败原因等关键信息一起丢掉。v0.7 引入轻量 `ContextManager`，用 token 预算、摘要、关键事实、计划保留和工具结果压缩来构建发送给模型的上下文。

## 设计参考

这版设计参考了两个开源 coding agent 的常见思路：Aider 的 token budget / repo map 思路强调“只把重要上下文放进预算”，OpenHands 的 context condenser 思路强调“压缩早期历史，保留最近交互”。`asen cli` 没有直接上向量库、embedding 或 LLM 自动摘要，而是先实现可解释、可测试、适合求职项目的轻量版本。

## 新增模块

```text
src/asen_cli/core/token_budget.py       # 轻量 token 估算与输入预算
src/asen_cli/core/context_manager.py    # 上下文构建、摘要、facts、计划和工具结果压缩
```

`Agent` 现在不再直接使用简单 `ConversationContext`，而是使用 `ContextManager` 构造每次 LLM 请求的消息。

## TokenBudget

`TokenBudget` 使用字符数近似估算 token：

```text
tokens ~= len(text) // 4
```

默认配置：

```text
max_context_tokens = 16000
reserve_output_tokens = 2000
```

也可以通过环境变量调整：

```bash
ASEN_MAX_CONTEXT_TOKENS=16000
ASEN_RESERVE_OUTPUT_TOKENS=2000
```

## ContextManager 组合策略

每次调用模型前，`ContextManager` 会组合：

```text
system prompt
+ Conversation summary
+ Key facts
+ Current plan
+ recent messages
```

其中 system prompt、关键事实和当前计划优先保留。旧消息超过窗口后会被合并进规则摘要，最近消息仍保持原样。

## 工具结果压缩

工具结果过大时，`ContextManager` 不会把完整内容塞给模型，而是生成规则压缩版本：

```text
[compressed tool result]
tool=read_file
original_chars=30000
kept_head_chars=1600
kept_tail_chars=1200

--- head ---
...
--- omitted N chars ---
--- tail ---
...
```

这样可以保留文件头尾、命令输出首尾、搜索结果摘要，同时避免上下文爆炸。

## 关键事实保留

`ContextManager` 会自动保留一些关键事实，例如：用户原始目标、当前计划、文件编辑结果、工具失败结果。后续模型即使旧消息被摘要，也能看到任务目标和重要状态。

## read_file_chunk

本次新增工具 `read_file_chunk`，用于按行读取文件片段：

```json
{"tool_calls": [{"name": "read_file_chunk", "arguments": {"path": "src/app.py", "start_line": 100, "max_lines": 80}}]}
```

这比一次性读取大文件更适合定位函数、错误行和局部上下文。

## 面试讲法

可以这样介绍：LLM 应用的核心问题之一是上下文管理。早期版本只做了简单滑动窗口，历史长了会直接丢消息。v0.7 我引入 `ContextManager`，把上下文拆成 system、summary、facts、plan 和 recent messages。每次请求前根据 token budget 构造输入，对旧消息做规则摘要，对大工具结果做压缩，并自动保留用户目标、当前计划、文件编辑和测试结果等关键事实。这样既控制 token 成本，又不会丢掉任务状态。

这一步体现了 token 预算、message trimming、context compression、tool result summarization 和状态保留设计。后续可以把规则摘要升级成 LLM summarizer，或者接入 tiktoken 做更精确的 token 估算。
