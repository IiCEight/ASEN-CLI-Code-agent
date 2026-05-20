# asen cli v0.5 安全代码修改能力升级说明

本次升级的目标是把 `asen cli` 的代码修改方式从“直接覆盖文件”升级为“diff-first 安全修改流程”。真实 coding agent 修改代码时，不能只把文件整块覆盖掉，而应该先读取文件、生成可审计 diff、让用户确认，再落盘写入，并在写入前保存快照。

## 新增工具

### 1. `replace_in_file`

`replace_in_file` 用于精确字符串替换。它要求模型提供 `old_text` 和 `new_text`，默认 `expected_replacements=1`，也就是必须恰好匹配一次才会修改。这样可以避免模型误把多个相似片段一起替换掉。

示例：

```json
{
  "tool_calls": [
    {
      "name": "replace_in_file",
      "arguments": {
        "path": "hello.py",
        "old_text": "def greeting():\n    return \"hello\"\n",
        "new_text": "def greeting(name: str = \"world\"):\n    return f\"hello {name}\"\n"
      }
    }
  ]
}
```

### 2. `apply_patch`

`apply_patch` 用于应用单文件 unified diff。它适合更复杂的局部修改，工具会检查 patch context 是否能和当前文件内容对上，如果对不上会返回 `patch_conflict`，让模型重新读取文件后再生成 patch。

示例：

```json
{
  "tool_calls": [
    {
      "name": "apply_patch",
      "arguments": {
        "path": "hello.py",
        "patch": "--- a/hello.py\n+++ b/hello.py\n@@ -1,2 +1,2 @@\n-def greeting():\n-    return \"hello\"\n+def greeting(name: str = \"world\"):\n+    return f\"hello {name}\"\n"
      }
    }
  ]
}
```

## diff-first 流程

两个工具都遵循同一套流程：先读取原文件，生成修改后的内容，再用 `difflib.unified_diff` 生成 diff。如果是 `dry_run=true`，只返回 diff，不写文件。如果需要写文件，会先把 diff 展示给用户确认。用户确认后，工具会先保存快照，再把新内容写入目标文件。

## dry-run 模式

所有编辑工具都支持 `dry_run`：

```json
{"name": "replace_in_file", "arguments": {"path": "hello.py", "old_text": "old", "new_text": "new", "dry_run": true}}
```

这适合让 Agent 先展示计划修改，用户确认思路后再真正应用。

## 快照机制

实际写入前，工具会把原文件保存到：

```text
.asen/snapshots/<timestamp>/<relative-file-path>
```

`.asen/` 已加入 `.gitignore`，避免把本地快照提交到仓库。这个机制为后续实现 checkpoint/rollback 打基础。

## 安全边界

`replace_in_file` 和 `apply_patch` 都复用 workspace 路径限制，目标文件必须位于 workspace 内。它们只处理 UTF-8 文本文件，并通过审批回调复用原有的确认机制。用户拒绝时返回 `user_rejected`，patch 上下文不匹配时返回 `patch_conflict`。

## 面试讲法

可以这样介绍：早期版本只有 `write_file`，这对于修改已有代码风险比较高，因为整文件覆盖不容易审计，也不好回滚。我新增了 diff-first 编辑工具：`replace_in_file` 适合精确文本替换，`apply_patch` 适合复杂局部修改。两个工具都会在写入前生成 unified diff，用户确认后才落盘，并且写入前自动保存快照。这样 Agent 的代码修改流程变得可审计、可确认、可恢复，更接近真实 CLI coding agent。

这一步体现了几个工程点：`difflib` 生成 diff、unified diff patch 解析、workspace 安全边界、用户确认、dry-run、文件快照和可回滚设计。
