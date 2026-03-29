# ChemDeep MCP Server 配置说明

## 问题排查

如果 Cherry Studio 提示"无效输入"，请确保：

1. **JSON 格式正确** - 没有多余的逗号、引号等
2. **路径使用双反斜杠** - Windows 路径需要 `\\`
3. **复制完整的 JSON 对象** - 包括外层的 `{}`

## Cherry Studio 配置

### 方法1：手动配置（推荐）

1. 打开 Cherry Studio
2. 进入 **设置** → **MCP 服务器**
3. 点击 **添加服务器**
4. 选择 **手动配置**（不要选"导入JSON"）
5. 填写以下信息：
   - **名称**: `chemdeep`
   - **命令**: `python`
   - **参数**: `G:\LLM\chemdeep\mcp_server\server.py`

### 方法2：导入 JSON

将以下内容**完整复制**后导入：

```json
{
  "mcpServers": {
    "chemdeep": {
      "command": "python",
      "args": ["G:\\LLM\\chemdeep\\mcp_server\\server.py"],
      "env": {
        "PYTHONPATH": "G:\\LLM\\chemdeep"
      }
    }
  }
}
```

## OpenClaw 配置

在 OpenClaw 的配置文件中添加：

```json
{
  "mcpServers": {
    "chemdeep": {
      "command": "python",
      "args": ["G:\\LLM\\chemdeep\\mcp_server\\server.py"],
      "env": {
        "PYTHONPATH": "G:\\LLM\\chemdeep"
      }
    }
  }
}
```

## 测试 MCP 服务器

在命令行中运行以下命令测试服务器是否正常：

```bash
cd G:\LLM\chemdeep
python mcp_server\server.py
```

如果看到 `🚀 ChemDeep MCP Server 启动中...` 说明服务器正常。

## Cherry Studio 验收要点

完成配置并启用 `chemdeep` 后，在 Cherry Studio 的 MCP 工具列表中应至少看到以下搜索工具：

- `search_papers`：通用多源学术搜索
- `search_lanfanshu`：烂番薯学术专用搜索

推荐做如下验收：

1. 在工具列表中确认 `search_lanfanshu` 已出现。
2. 发送明确指令，例如“请用烂番薯学术搜索 COF photocatalysis 相关论文”。
3. 确认模型调用的是 `search_lanfanshu`，且返回中的 `requested_tool` 为 `search_lanfanshu`。
4. 若查看 MCP 服务日志，应能看到类似“tool=search_lanfanshu”与“actual_sources=['lanfanshu']”的记录。

如果 Cherry Studio 仍然只显示旧工具定义，通常是工具缓存未刷新。请按以下顺序处理：

1. 在 Cherry Studio 中禁用后重新启用 `chemdeep` MCP 服务器。
2. 关闭并重新打开 Cherry Studio，强制刷新工具缓存。
3. 重启 `chemdeep` MCP 服务进程后再次检查工具列表。

## 常见问题

### 1. 找不到 python 命令

使用完整路径：

```json
{
  "mcpServers": {
    "chemdeep": {
      "command": "C:\\Python311\\python.exe",
      "args": ["G:\\LLM\\chemdeep\\mcp_server\\server.py"],
      "env": {
        "PYTHONPATH": "G:\\LLM\\chemdeep"
      }
    }
  }
}
```

### 2. 使用虚拟环境

如果使用 uv 或 venv 虚拟环境：

```json
{
  "mcpServers": {
    "chemdeep": {
      "command": "G:\\LLM\\chemdeep\\.venv\\Scripts\\python.exe",
      "args": ["G:\\LLM\\chemdeep\\mcp_server\\server.py"],
      "env": {
        "PYTHONPATH": "G:\\LLM\\chemdeep"
      }
    }
  }
}
```

### 3. 使用 uv 直接运行

```json
{
  "mcpServers": {
    "chemdeep": {
      "command": "uv",
      "args": ["run", "python", "G:\\LLM\\chemdeep\\mcp_server\\server.py"],
      "cwd": "G:\\LLM\\chemdeep",
      "env": {
        "PYTHONPATH": "G:\\LLM\\chemdeep"
      }
    }
  }
}
```

### 4. 环境变量配置

如果需要配置 API Key，在 env 中添加：

```json
{
  "mcpServers": {
    "chemdeep": {
      "command": "python",
      "args": ["G:\\LLM\\chemdeep\\mcp_server\\server.py"],
      "env": {
        "PYTHONPATH": "G:\\LLM\\chemdeep",
        "CHEMDEEP_OPENAI_API_KEY": "sk-your-api-key",
        "CHEMDEEP_OPENAI_API_BASE": "https://your-api-base/v1",
        "CHEMDEEP_OPENAI_MODEL": "gpt-4o"
      }
    }
  }
}
```
