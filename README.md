# ChemDeep - AI 驱动的化学深度研究助手

ChemDeep 是一个基于 AI Agent 的深度研究系统，专为化学领域的文献调研、机理假设生成和证据验证设计。它集成了 Telegram 机器人接口、浏览器自动化 (Playwright/Edge) 和多源搜索 (MCP) 能力。

## 🚀 快速开始 (Quick Start)

### 1. 准备环境
- **操作系统**: Windows (推荐)
- **Python**: 3.10+ (如果你没有安装 uv，bootstrap 会自动尝试安装)
- **Edge 浏览器**: 必需 (用于获取付费文献)
- **Node.js**: 可选 (用于构建 WoS/SciHub 搜索插件)

### 2. 一键部署
在项目根目录下打开 PowerShell，运行以下命令即可完成所有环境准备（Python 依赖、虚拟环境、浏览器组件、配置文件初始化）：

```powershell
.\bootstrap.ps1
```

> **注意**: 首次运行会自动生成 `requirements.lock.txt`，请将此文件提交到仓库以确保团队环境一致性。

### 3. 配置 API Key
运行 bootstrap 后，`config` 目录下会自动生成 `config/.env` 文件。请使用文本编辑器打开并填入必要的 Key：

- `CHEMDEEP_TELEGRAM_TOKEN`: 你的 Telegram Bot Token ([BotFather](https://t.me/BotFather))
- `CHEMDEEP_TELEGRAM_CHAT_ID`: 你的 Chat ID (Bot 会只响应此 ID)
- `CHEMDEEP_OPENAI_API_KEY`: OpenAI 或兼容 API 的 Key
- `CHEMDEEP_OPENAI_API_BASE`: (可选) API Base URL (默认 `https://api.openai.com/v1`)

### 4. 启动机器人
环境就绪后，使用以下命令启动 Bot：

```powershell
.\.venv\Scripts\python.exe main.py bot
```

此时，向 Bot 发送任何化学问题（如 "研究...的机理"），它将自动开始深度研究流程。

---

## � 终端运行模式 (Terminal Mode)

ChemDeep 不仅支持 Telegram Bot，还提供完整的命令行接口，适合开发调试、批量处理和自动化脚本。

### 基本用法

```bash
# 激活虚拟环境
.\.venv\Scripts\Activate.ps1

# 查看所有可用命令
python main.py --help
```

### 核心命令

#### 🔍 文献搜索
```bash
# 搜索文献（默认使用 OpenAlex + Crossref）
python main.py search "有机合成新方法" --max-results 20

# 指定数据源
python main.py search "药物设计" --sources "openalex,pubmed,semantic_scholar"
```

#### 🤖 AI 模型管理
```bash
# 列出可用模型
python main.py models

# 测试 AI 连接
python main.py test-ai --prompt "请解释什么是自由基反应"

# 切换模型
python main.py setmodel "gpt-4-turbo"

# 查看当前模型配置
python main.py currentmodel
```

#### ⚙️ 系统管理
```bash
# 查看最近任务状态
python main.py status --limit 10

# 显示当前配置
python main.py config

# 初始化配置文件
python main.py init
```

#### 🌐 浏览器操作
```bash
# 交互式登录 Web of Science
python main.py login --url "https://www.webofscience.com"
```

### 高级用法示例

#### 批量文献调研
```powershell
# 激活环境
.\.venv\Scripts\Activate.ps1

# 1. 搜索相关文献
python main.py search "光催化有机合成" --max-results 50

# 2. 测试 AI 理解能力
python main.py test-ai --prompt "分析光催化在有机合成中的应用前景"

# 3. 检查系统状态
python main.py status
```

#### 开发调试模式
```powershell
# 快速测试搜索功能
python main.py search "酶催化不对称合成" --sources "pubmed"

# 验证 AI 配置
python main.py test-ai --model "gpt-3.5-turbo"
```

---

## �🛠️ 常用维护操作

### 更新依赖
如果你修改了 `requirements.txt` 或拉取了新代码：
再次运行 `.\bootstrap.ps1` 即可。它会自动同步 `requirements.lock.txt`。

### 浏览器问题 (Profile Locked)
Bot 默认使用独立的 `profiles/isolated_edge_bot` 目录以避免与你的主浏览器冲突。
如果遇到 "Edge 启动超时" 或 "Profile Locked" 错误：
1. Bot 会自动推送交互按钮，点击 **"🔪 杀掉进程并重试"** 即可。
2. 或在 PowerShell 运行: `taskkill /F /IM msedge.exe` (注意这会关闭所有 Edge 窗口)。

### 目录结构说明
- `config/`: 配置文件
- `core/`: 核心逻辑 (搜索、AI、浏览器)
- `data/library/`: 下载的文献库 (PDF/MD)
- `data/reports/`: 生成的研究报告
- `profiles/`: Bot 专用的浏览器配置目录
- `logs/`: 运行日志

## 🤖 主要指令 (/help)
- `/status`: 查看当前任务状态和交互选项
- `/stop`: 停止当前任务
- `/report`: 生成最近任务的报告
- `/run_load <id>`: 加载历史任务并继续

