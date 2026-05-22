# 轻量 MCP 支持升级说明

## 背景

MCP（Model Context Protocol）已经成为 Agent 工具生态里越来越重要的标准协议，但对求职项目来说，首版没必要一上来就做 resources、prompts、sampling、SSE/HTTP transport 和复杂连接池。更合适的方式是先把最小闭环做出来：能读配置、能启动本地 server、能发现 tools、能调用一个 tool。

## 设计目标

这次升级只覆盖最小可演示能力：

1. 读取 `mcp_servers` 配置。
2. 启动本地 stdio MCP server。
3. 执行 `initialize` 与 `notifications/initialized` 握手。
4. 支持 `tools/list` 与 `tools/call`。
5. 提供一个零外部依赖的 filesystem demo server。

明确不做的内容包括：resources、prompts、sampling、Streamable HTTP/SSE transport、多 server 长连接池和自动 tool 注入 Agent。

## 配置模型

`asen-cli` 在现有配置体系中新增了 `mcp_servers`：

```yaml
mcp_servers:
  filesystem-demo:
    command: python
    args:
      - -m
      - asen_cli.mcp.demo_server
    cwd: /absolute/path/to/workspace
    timeout_seconds: 20
    enabled: true
    description: Local filesystem demo
```

字段说明：

- `command`：启动 server 的可执行文件
- `args`：传给 server 的命令参数
- `env`：可选环境变量
- `cwd`：server 启动目录；filesystem demo 会把这里当成允许访问的根目录
- `timeout_seconds`：单次 MCP 请求超时
- `enabled`：是否启用
- `description`：可选说明文本

## CLI 命令

### `asen mcp list`

查看当前解析后的 MCP server 配置。

### `asen mcp add`

保存或更新一个 MCP server 配置：

```bash
asen mcp add filesystem-demo python --arg -m --arg asen_cli.mcp.demo_server --cwd examples/demo_project --description "Local filesystem demo"
```

这里使用 repeatable `--arg`，而不是可变位置参数。原因是 Typer/Click 对“位置参数 + 后续选项”的解析非常容易歧义，首版为了稳定性选择了更明确的命令形式。

### `asen mcp tools <server>`

启动本地 stdio server，执行：

1. `initialize`
2. `notifications/initialized`
3. `tools/list`

然后把返回的 tools 列出来。

### `asen mcp call <server> <tool> '{...}'`

启动本地 stdio server，执行一次 `tools/call`，并把结果按文本模式或 `--json` 输出。

## 协议实现

当前实现位于 `src/asen_cli/mcp/`：

- `client.py`：轻量 stdio MCP client
- `protocol.py`：最小协议模型
- `demo_server.py`：filesystem demo server

stdio transport 按 MCP 规范走 **UTF-8 + newline-delimited JSON-RPC**：

- 客户端把 server 作为子进程启动
- 通过 `stdin` 写入单行 JSON-RPC 请求
- 通过 `stdout` 读取单行 JSON-RPC 响应
- `stderr` 只用于日志，不参与协议消息

## Demo Server

内置 demo server 为 `asen_cli.mcp.demo_server`，同时通过 `pyproject.toml` 暴露脚本入口：

```bash
asen-mcp-filesystem-demo
```

它提供三个只读工具：

- `list_directory`
- `read_file`
- `stat_path`

并通过安全路径检查保证访问范围不会逃出 `cwd` 根目录。

## 面试讲法

可以这样讲：

> MCP 是 Agent 工具生态里的标准协议。我没有在求职项目里直接复刻商业级完整能力，而是实现了最小 MCP 调用闭环：支持读取 server 配置、启动本地 stdio server、做 initialize 握手、发现 tools、调用一个 tool，并且做了 filesystem demo。这样既证明了项目具备 extensibility，又把实现复杂度控制在可解释、可演示的范围内。

## 验证方式

```bash
cd asen-cli
pytest tests/test_mcp_client.py tests/test_mcp_commands.py tests/test_config_commands.py -q
ruff check src/asen_cli tests/test_mcp_client.py tests/test_mcp_commands.py
```
