# Web Search / 文档检索升级说明

## 背景

`asen-cli` 之前只有 `web_fetch`，只能在已知 URL 的前提下抓网页内容。这对于 coding agent 来说还不够：真实开发里，经常先要“查最新文档”，再读取正文、提取重点、给结论附来源。于是这次升级补上了一个轻量但完整的 Web Search / 文档检索闭环。

## 设计目标

首版只覆盖最值得做、最容易演示的能力：

1. 新增 `web_search` 工具。
2. 支持获取搜索结果并抓取前几个结果页。
3. 使用正文提取把 HTML 噪音压掉。
4. 为 Agent 提供参考资料摘要。
5. 在最终回答和 `asen ask --json` 中附来源。

明确不做的内容包括：浏览器渲染、登录态网页、长期缓存、复杂排序学习、多搜索引擎编排、知识库索引、自动向量化和多模态检索。

## 配置模型

在现有配置体系中新增了 3 个字段：

```yaml
search_provider: duckduckgo
search_api_key: null
web_search_max_results: 5
```

字段说明：

- `search_provider`：当前支持 `duckduckgo`（默认）和 `tavily`
- `search_api_key`：当 `search_provider=tavily` 时使用
- `web_search_max_results`：默认抓取多少条搜索结果

也支持通过环境变量配置：

```bash
ASEN_SEARCH_PROVIDER=duckduckgo
# ASEN_SEARCH_PROVIDER=tavily
# ASEN_SEARCH_API_KEY=tvly-your-key
ASEN_WEB_SEARCH_MAX_RESULTS=5
```

## 工具设计

### `web_search`

输入参数：

```json
{
  "query": "latest typer docs",
  "max_results": 5
}
```

执行流程：

1. 调搜索入口（默认 `duckduckgo` HTML 搜索，或 Tavily API）。
2. 解析搜索结果标题、URL 和 snippet。
3. 抓取前几个结果页。
4. 对 HTML 用 `Trafilatura` 提取正文，必要时回退到 `BeautifulSoup`。
5. 输出参考摘要，并在 `meta.sources` 中附来源。

### 增强版 `web_fetch`

`web_fetch` 不再只回原始 HTML 文本，而是会优先抽取可读正文，同时返回：

- `title`
- `final_url`
- `content_type`
- `sources`

这样单 URL 抓取也能直接用于引用展示。

## 来源引用链路

为了尽量少改动 Agent 主流程，本次没有新增复杂 citation manager，而是复用了现有的 `ToolResult.meta`：

1. `web_search` / `web_fetch` 把来源写入 `ToolResult.meta["sources"]`
2. `ToolRegistry` 把 `meta` 保留到 `ToolExecutionLog`
3. `Agent` 在最终回答前扫描工具日志，聚合去重后自动追加 `## Sources`
4. `AsenJsonConsole` 也会把聚合后的 `sources` 暴露到 `asen ask --json`

这条链路简单、解释成本低，而且对求职项目足够有说服力。

## 抓取与正文提取

当前实现采用两层策略：

- 抓取：`httpx.AsyncClient`
- 正文提取：优先 `Trafilatura`，失败时回退 `BeautifulSoup`

`Trafilatura` 的作用是把导航栏、页脚、模板噪音尽量剥掉，保留更适合送给 LLM 的正文。对 HTML 比直接丢原始源码给模型更稳定，也更节省 token。

## Timeout / Retry

为了让工具在真实网络环境里更稳，这次也顺手补了最基本的可靠性边界：

- `connect=10s`
- `read=20s`
- 失败最多重试 3 次
- 对 `408/425/429/5xx` 和 transport error 做重试
- 非 retryable HTTP 错误直接返回失败

首版没有做指数级复杂退避、代理池、IP 轮换或 robots 审计，原因很简单：求职项目的目标是证明能力闭环，而不是做成一套大规模采集平台。

## 演示方式

最自然的演示方法是直接让 Agent 查最新文档：

```bash
asen ask "搜索 Typer 最新文档，告诉我怎么定义子命令，并附来源" --workspace examples/demo_project --no-stream
```

如果要看机器可读结果：

```bash
asen ask "搜索 LangChain agent tools 最新文档，并总结重点" --workspace examples/demo_project --json --no-stream
```

输出里除了 `final_text`、`tool_results`，现在还会有 `sources`。

## 面试讲法

可以这样讲：

> Coding agent 经常需要查最新文档。如果只有 `web_fetch`，模型必须先知道 URL 才能抓。于是我补了 `web_search`，让 Agent 能先搜索，再抓正文，再把来源拼到回答里。这样它解决问题时依赖的是最新文档，而不只是参数知识。

进一步展开时，还可以强调四个技术点：

- `search API / search endpoint`
- `web scraping`
- `main-content extraction`
- `source citation`

## 验证方式

```bash
cd asen-cli
pytest tests/test_tools_web.py tests/test_tool_registry.py tests/test_agent.py tests/test_config.py tests/test_config_commands.py -q
ruff check src/asen_cli tests/test_tools_web.py tests/test_tool_registry.py tests/test_agent.py tests/test_config.py tests/test_config_commands.py
```

当前这轮升级的专项结果：

- `36 passed`
- `ruff check` 通过
