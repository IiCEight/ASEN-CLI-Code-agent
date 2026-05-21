# asen cli v0.9 多模型 Provider 升级说明

本次升级把 `asen cli` 的 LLM 调用从单一 `OpenAICompatibleClient`，升级为可扩展的 Provider 架构。目标是让 Agent 不依赖具体模型供应商，后续接入新模型时只需要新增适配器和工厂映射。

## 调研参考

Aider、OpenHands、Continue 这类 CLI / Agent 工具通常不会把 Agent 主循环绑定到某一个模型 SDK，而是通过统一 LLM 接口隔离供应商差异。OpenHands 依赖 LiteLLM 做统一 provider 层；Aider 支持多种模型配置和 OpenAI-compatible endpoint；Ollama 提供 OpenAI compatibility，也提供本地原生 API。`asen cli` 作为教学项目，没有引入 LiteLLM 这类重依赖，而是自己实现轻量 Provider 工厂和两个代表性适配器。

参考资料：

- [OpenHands LLM docs](https://docs.openhands.org.cn/sdk/arch/llm)
- [Ollama OpenAI compatibility](https://docs.ollama.com/api/openai-compatibility)
- [Aider Repository / model docs](https://aider.chat/docs/)

## 新增结构

```text
src/asen_cli/llm/
├── __init__.py
├── base.py          # LlmClient 协议、工具提示渲染
├── factory.py       # provider -> client 工厂
├── openai_client.py # OpenAI-compatible adapter
└── ollama_client.py # Ollama native /api/chat adapter
```

`Agent` 只依赖 `complete(messages, tools)` 这个接口，不关心底层是 OpenAI、DeepSeek、Kimi、通义、智谱还是 Ollama。

## 支持的 Provider

当前支持：

```text
openai
openai-compatible
deepseek
kimi
tongyi
zhipu
ollama
```

其中 `openai`、`openai-compatible`、`deepseek`、`kimi`、`tongyi`、`zhipu` 都走 OpenAI-compatible Chat Completions 协议，只是默认 `base_url` 不同。`ollama` 使用本地原生 `/api/chat` 协议，不需要 API Key。

## 配置方式

OpenAI：

```bash
asen config set provider openai
asen config set api_key sk-your-api-key
asen config set base_url https://api.openai.com/v1
asen config set model gpt-4o-mini
```

DeepSeek：

```bash
asen config set provider deepseek
asen config set api_key sk-your-api-key
asen config set model deepseek-chat
```

Kimi：

```bash
asen config set provider kimi
asen config set api_key sk-your-api-key
asen config set model moonshot-v1-8k
```

Ollama 本地模型：

```bash
ollama serve
ollama pull llama3.1
asen config set provider ollama
asen config set base_url http://localhost:11434
asen config set model llama3.1
```

## Provider 工厂

`create_llm_client(config)` 会根据 `config.provider` 返回具体适配器：

```python
if provider == "ollama":
    return OllamaClient(config)
return OpenAICompatibleClient(config)
```

如果用户设置了自定义 `base_url`，会优先使用用户配置；否则使用 provider 默认地址。

## Streaming 扩展点

`LlmClient` 接口包含 `stream_complete()`。当前 Agent 主循环仍然使用 `complete()`，但 Provider 已经预留了 streaming 能力：OpenAI-compatible 解析 SSE `data:` 行，Ollama 解析逐行 JSON。后续可以把 `AgentEvents` 和 `AsenConsole` 接到 streaming 输出，实现真正的边生成边打印。

## 面试讲法

可以这样介绍：早期版本把 Agent 直接绑定到 OpenAI-compatible HTTP Client，后续要接 Ollama 或其它模型时会污染 Agent 主循环。我引入了 Provider 抽象和工厂模式，Agent 只依赖统一的 `LlmClient` 接口。OpenAI、DeepSeek、Kimi、通义、智谱复用 OpenAI-compatible adapter；Ollama 使用独立 adapter 适配本地 `/api/chat` 协议。这样新增模型供应商只需要增加一个 client 和 factory 映射，符合依赖倒置和适配器模式。
