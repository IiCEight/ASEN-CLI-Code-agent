# asen cli v0.8 配置系统升级说明

本次升级把 `asen cli` 的配置系统从单一 `.env` / 手动 YAML，升级为多层配置加载与 CLI 管理命令。目标是同时支持个人全局默认配置、项目级覆盖配置和临时 CLI 参数覆盖。

## 配置文件位置

`asen cli` 现在支持两类固定配置文件：

```text
~/.asen/config.yaml      # 全局配置，适合个人常用模型和 base_url
.asen/config.yaml        # 项目配置，适合当前项目覆盖 workspace、模型或安全选项
```

`.asen/` 已加入 `.gitignore`，默认不会提交本地项目配置和快照。

## 配置优先级

加载顺序从低到高是：

```text
.env / 环境变量
< ~/.asen/config.yaml
< .asen/config.yaml
< --config 指定的 YAML
< CLI 显式参数，如 --workspace、--no-approval
```

也就是说，项目配置会覆盖全局配置，CLI 参数具有最高优先级。

## 新增命令

### 查看最终生效配置

```bash
asen config
asen config get
asen config get model
```

输出会自动隐藏 `api_key`。

### 初始化配置

默认初始化项目配置：

```bash
asen config init
```

初始化全局配置：

```bash
asen config init --global
```

覆盖已有配置：

```bash
asen config init --force
```

### 写入配置

默认写入项目配置 `.asen/config.yaml`：

```bash
asen config set model gpt-4o-mini
asen config set base_url https://api.openai.com/v1
asen config set require_approval false
```

写入全局配置：

```bash
asen config set model gpt-4o-mini --global
```

## 面试讲法

可以这样介绍：我设计了多层配置加载机制，既支持用户级全局配置，也支持项目级配置覆盖，同时保留环境变量和显式 CLI 参数。配置优先级清晰：环境变量作为基础，`~/.asen/config.yaml` 提供个人默认值，`.asen/config.yaml` 提供项目覆盖，`--config` 和 `--workspace` 这类 CLI 参数优先级最高。为了提升可用性，我还实现了 `asen config init/get/set`，用户不需要手动编辑 YAML 也能管理配置。

这一步体现了配置优先级、YAML 读写、用户目录、项目目录、敏感字段脱敏和 CLI 子命令设计。
