# ChemDeep MCP Server

为 Cherry Studio 和 OpenClaw 提供学术文献搜索、评分、文献调研、机理假设生成、证据验证设计以及基于合法浏览器会话的全文抓取 / PDF 下载能力。

## 功能概览

### 🔍 文献检索层

| 工具 | 说明 |
|------|------|
| `search_papers` | 通用多源学术搜索（可组合 OpenAlex、CrossRef、烂番薯学术等来源） |
| `search_lanfanshu` | 烂番薯学术专用搜索，显式固定使用 `lanfanshu` 来源 |
| `score_papers` | 论文评分（期刊、机构、关键词等维度） |
| `get_paper_details` | 获取论文详情；可在显式传入 `fetch_full_text=true` 时尝试抓取正文/全文 |
| `prepare_live_browser_session` | 检测或启动带 CDP 的 Edge 会话，为受限站点全文抓取做准备 |
| `download_paper_pdf` | 通过当前浏览器合法授权会话按 DOI 下载 PDF |
| `filter_by_year` | 按年份筛选论文 |
| `generate_search_strategy` | 生成搜索策略 |

### 🧠 分析与推理层

| 工具 | 说明 |
|------|------|
| `infer_research_needs` | 通过文献分析推断研究需求 |
| `analyze_research_gaps` | 分析研究空白和机会 |
| `formalize_research_goal` | 将自然语言研究目标形式化为结构化 ProblemSpec |
| `extract_evidence` | 从论文池中提取结构化证据 |
| `cluster_methods` | 对提取的证据按技术路径进行聚类分析 |

### 💡 假设与验证层

| 工具 | 说明 |
|------|------|
| `generate_hypotheses` | 基于 ProblemSpec 和文献摘要生成可证伪的机理假设 |
| `evaluate_hypotheses` | 用证据评估假设状态（支持/反驳/搁置） |
| `design_verification_plan` | 为假设设计实验与计算验证方案 |

### 🚀 完整流程

| 工具 | 说明 |
|------|------|
| `run_deep_research` | 一键执行完整的迭代式深度调研流程 |

## 全文抓取与授权边界

ChemDeep 的全文抓取与 PDF 下载能力遵循以下原则：

- **不绕过付费墙**：不会生成、伪造或扩大用户权限
- **只复用合法授权会话**：仅使用用户当前浏览器中已经具备的登录态、机构订阅态或访问权限
- **人工验证优先**：遇到验证码、Cloudflare、出版社跳转确认等页面时，需要用户手动完成
- **适合 Skills 显式编排**：建议先准备浏览器会话，再执行全文抓取或 PDF 下载

典型顺序：

```
prepare_live_browser_session
        ↓
用户在 Edge 中完成登录 / 验证 / 打开文章页
        ↓
download_paper_pdf
或
get_paper_details(fetch_full_text=true)
```

## 典型工作流

ChemDeep 的 skills 可以按照以下工作流协同使用：

```
                    ┌─────────────────────┐
                    │  search_papers /    │
                    │  search_lanfanshu   │
                    └─────────┬───────────┘
                              │ 文献列表
                    ┌─────────▼───────────┐
                    │  score_papers       │
                    │  filter_by_year     │
                    └─────────┬───────────┘
                              │ 高质量论文池
         ┌────────────────────┼────────────────────┐
         │                    │                    │
┌────────▼────────┐ ┌────────▼────────┐ ┌────────▼────────┐
│ formalize_      │ │ extract_        │ │ analyze_        │
│ research_goal   │ │ evidence        │ │ research_gaps   │
└────────┬────────┘ └────────┬────────┘ └────────┬────────┘
         │ ProblemSpec       │ Evidence[]         │ 研究空白
         │                    │                    │
┌────────▼────────┐          │                    │
│ generate_       │◄─────────┘                    │
│ hypotheses      │ 摘要 + ProblemSpec             │
└────────┬────────┘                               │
         │ Hypothesis[]                           │
┌────────▼────────┐                               │
│ evaluate_       │◄──────────────────────────────┘
│ hypotheses      │ 证据 + 假设交叉评估
└────────┬────────┘
         │ 评估结果
         ├──────────────────┐
┌────────▼────────┐ ┌──────▼──────────┐
│ cluster_methods │ │ design_         │
│                 │ │ verification_   │
│                 │ │ plan            │
└─────────────────┘ └─────────────────┘
  技术路径聚类          验证方案设计
```

或者直接使用 `run_deep_research` 一键完成上述全部步骤。

如果希望在深度调研中尽量抓取出版社正文，可先执行 `prepare_live_browser_session`，确保浏览器中已有合法授权会话。

## 安装

### 使用 uv（推荐）

```bash
cd G:\LLM\chemdeep\mcp_server
uv sync
```

### 使用 pip

```bash
cd G:\LLM\chemdeep
pip install -e .
pip install mcp
```

## 配置到 Cherry Studio

1. 打开 Cherry Studio
2. 进入 **设置** → **MCP 服务器**
3. 添加新的 MCP 服务器：

```json
{
  "name": "chemdeep",
  "command": "python",
  "args": ["G:\\LLM\\chemdeep\\mcp_server\\server.py"],
  "env": {
    "PYTHONPATH": "G:\\LLM\\chemdeep",
    "CHEMDEEP_AI_PROVIDER": "openai",
    "CHEMDEEP_OPENAI_MODEL": "gpt-4o-mini",
    "CHEMDEEP_OPENAI_API_BASE": "https://api.openai.com/v1",
    "CHEMDEEP_OPENAI_API_KEY": "<your-api-key>",
    "CHEMDEEP_GEMINI_MODEL": "gemini-2.0-flash",
    "CHEMDEEP_GEMINI_API_KEY": "<your-gemini-api-key>"
  }
}
```

或者使用 uv：

```json
{
  "name": "chemdeep",
  "command": "uv",
  "args": ["run", "--directory", "G:\\LLM\\chemdeep\\mcp_server", "python", "server.py"],
  "env": {
    "PYTHONPATH": "G:\\LLM\\chemdeep",
    "CHEMDEEP_AI_PROVIDER": "openai",
    "CHEMDEEP_OPENAI_MODEL": "gpt-4o-mini",
    "CHEMDEEP_OPENAI_API_BASE": "https://api.openai.com/v1",
    "CHEMDEEP_OPENAI_API_KEY": "<your-api-key>",
    "CHEMDEEP_GEMINI_MODEL": "gemini-2.0-flash",
    "CHEMDEEP_GEMINI_API_KEY": "<your-gemini-api-key>"
  }
}
```

4. 保存并启用该服务器

## 配置到 OpenClaw

1. 打开 OpenClaw
2. 进入 **设置** → **工具/插件**
3. 添加 MCP 工具：

```json
{
  "mcpServers": {
    "chemdeep": {
      "command": "python",
      "args": ["G:\\LLM\\chemdeep\\mcp_server\\server.py"],
      "env": {
        "PYTHONPATH": "G:\\LLM\\chemdeep",
        "CHEMDEEP_AI_PROVIDER": "openai",
        "CHEMDEEP_OPENAI_MODEL": "gpt-4o-mini",
        "CHEMDEEP_OPENAI_API_BASE": "https://api.openai.com/v1",
        "CHEMDEEP_OPENAI_API_KEY": "<your-api-key>",
        "CHEMDEEP_GEMINI_MODEL": "gemini-2.0-flash",
        "CHEMDEEP_GEMINI_API_KEY": "<your-gemini-api-key>"
      }
    }
  }
}
```

## Cherry Studio 中哪些内容能显示出来

按当前 Cherry Studio 常见 MCP 展示方式，可见入口主要有两类：

1. **MCP 服务器配置 / 服务器选项**
   - 来自服务器配置 JSON 里的 `command`、`args`、`env`
   - 其中 `env` 最适合暴露全局默认配置，通常会在 Cherry Studio 的 MCP 服务器配置面板里直接可见、可编辑
2. **工具调用参数 UI**
   - 来自 MCP `list_tools` 返回的工具 `description`
   - 以及每个工具的 `inputSchema`、字段名、字段描述、`enum`、`format`、默认值等
   - Cherry Studio 通常能展示顶层参数；对嵌套对象（例如 `llm_config`）的可视化编辑支持可能因版本而异

### 配置优先级

1. 工具调用时传入的顶层 `provider/model/base_url/api_key`
2. 工具调用时传入的 `llm_config`
3. Cherry Studio MCP 服务器配置中的 `env`
4. 服务端 `.env` / 既有全局配置

## 使用示例

### 搜索文献（通用多源）

```
请帮我搜索关于 "carbon borane fluorescent probe Fe3+" 的近5年高分论文
```

AI 会调用 `search_papers` 工具：
```json
{
  "query": "carbon borane fluorescent probe Fe3+",
  "sources": ["lanfanshu", "openalex", "crossref"],
  "max_results": 20,
  "min_year": 2020
}
```

### 准备实时浏览器会话

当你希望让 Skills 抓取受限出版商页面或下载 PDF 时，可先调用：

```json
{
  "purpose": "ScienceDirect PDF download",
  "launch_if_needed": true
}
```

该工具会：
- 检测当前是否已有可连接的 Edge/CDP 会话
- 必要时尝试启动专用 Edge 会话
- 返回手动登录、验证码处理、点击 `View PDF` 的操作提示

### 下载论文 PDF

```json
{
  "doi": "10.1016/j.jhazmat.2024.134567",
  "title": "A hypothetical example paper"
}
```

### 形式化研究目标

```
请把"开发一种基于COF的光催化CO2还原体系"这个研究目标形式化
```

AI 会调用 `formalize_research_goal`：
```json
{
  "goal": "开发一种基于COF的光催化CO2还原体系，在可见光下实现高选择性CO2转化为CO",
  "previous_context": ""
}
```

返回结构化的 ProblemSpec，包含研究对象、控制变量、性能指标、约束条件等。

### 生成机理假设

```
基于以下形式化目标和文献摘要，生成可证伪的机理假设
```

AI 会调用 `generate_hypotheses`：
```json
{
  "problem_spec": {
    "goal": "...",
    "research_object": "COF光催化体系",
    "control_variables": ["连接体结构", "金属掺杂"],
    "performance_metrics": ["CO选择性", "量子效率"],
    "constraints": ["可见光激发"],
    "domain": "光催化"
  },
  "abstracts": ["论文摘要1...", "论文摘要2..."]
}
```

### 提取结构化证据

```
从这些论文中提取关于光催化效率的实验证据
```

AI 会调用 `extract_evidence`：
```json
{
  "problem_spec": { "goal": "..." },
  "papers": [
    {
      "title": "Paper A",
      "abstract": "...",
      "doi": "10.xxxx/yyyy"
    }
  ]
}
```

### 评估假设

```
用提取的证据评估这些假设的合理性
```

AI 会调用 `evaluate_hypotheses`：
```json
{
  "problem_spec": { "goal": "..." },
  "hypotheses": [
    {
      "hypothesis_id": "H1",
      "mechanism_description": "COF层间电荷传输促进CO2活化",
      "required_variables": ["层间距", "电子态密度"],
      "falsifiable_conditions": ["若层间距>5nm则效率下降"],
      "expected_performance_trend": "层间距越小效率越高"
    }
  ],
  "evidence": [
    {
      "source_doi": "10.xxxx/yyyy",
      "implementation": "...",
      "key_variables": {},
      "performance_results": {}
    }
  ]
}
```

### 设计验证方案

```
为假设"COF层间电荷传输促进CO2活化"设计实验验证方案
```

AI 会调用 `design_verification_plan`：
```json
{
  "hypotheses": [
    {
      "hypothesis_id": "H1",
      "mechanism_description": "COF层间电荷传输促进CO2活化",
      "status": "ACTIVE"
    }
  ],
  "evidence_summary": "已有文献显示...",
  "available_resources": "拥有XRD、BET、光化学反应器、DFT计算集群"
}
```

### 技术路径聚类

```
对提取的证据按技术方法聚类，分析各路径优劣
```

AI 会调用 `cluster_methods`：
```json
{
  "evidence": [
    {
      "implementation": "溶剂热合成COF...",
      "method_category": "溶剂热法",
      "key_variables": {"温度": "120°C"},
      "performance_results": {"CO选择性": "85%"}
    }
  ]
}
```

### 一键深度调研

```
请帮我对"基于MOF的电催化氮气还原"进行完整的文献调研和假设生成
```

AI 会调用 `run_deep_research`：
```json
{
  "goal": "基于MOF的电催化氮气还原机理研究",
  "max_iterations": 3,
  "min_year": 2020,
  "min_score": 5.0
}
```

该工具会自动执行：形式化目标 → 检索文献 → 提取证据 → 生成假设 → 评估假设 → 聚类分析 → 生成报告。

### LLM 配置透传

所有涉及 AI 调用的工具都支持请求级 LLM 配置覆盖：

```json
{
  "goal": "...",
  "provider": "openai",
  "model": "gpt-4o",
  "base_url": "https://api.openai.com/v1",
  "api_key": "sk-xxx"
}
```

也可以使用嵌套的 `llm_config` 对象：

```json
{
  "goal": "...",
  "llm_config": {
    "provider": "openai",
    "model": "gpt-4o",
    "base_url": "https://api.openai.com/v1",
    "api_key": "sk-xxx"
  }
}
```

## 环境变量

在 `.env` 文件或环境变量中配置：

```env
# Provider 选择
CHEMDEEP_AI_PROVIDER=openai

# OpenAI 兼容 API
CHEMDEEP_OPENAI_API_KEY=sk-xxx
CHEMDEEP_OPENAI_API_BASE=https://api.openai.com/v1
CHEMDEEP_OPENAI_MODEL=gpt-4o-mini

# Gemini
CHEMDEEP_GEMINI_API_KEY=<your-gemini-api-key>
CHEMDEEP_GEMINI_MODEL=gemini-2.0-flash

# 代理设置（可选）
CHEMDEEP_OPENAI_PROXY=socks5://127.0.0.1:7890
```

## Cherry Studio 侧的已知限制

1. Cherry Studio 是否为**嵌套对象 schema** 生成完整 UI，可能取决于其版本与当前实现；因此不能保证 `llm_config.*` 一定会在工具面板中单独展开成完整表单。
2. Cherry Studio 通常更稳定地展示 **顶层工具参数**，所以本项目已额外把 `provider`、`model`、`base_url`、`api_key` 直接暴露在工具顶层。
3. Cherry Studio 的"服务器选项"层通常基于 MCP 配置 JSON 的 `env`，而不是服务端动态返回的工具参数；因此若要让配置在"服务器选项"里可见，最可靠方式仍然是填写 `env` 模板。

## 故障排除

### 1. 找不到模块

确保在 `G:\LLM\chemdeep` 目录下运行，或设置 PYTHONPATH：

```bash
set PYTHONPATH=G:\LLM\chemdeep;%PYTHONPATH%
```

### 2. AI 调用失败

检查环境变量是否正确配置，特别是 API Key、Provider、Model 和 API Base。

### 3. 搜索无结果

- 检查网络连接
- 如果使用代理，确保代理配置正确
- `search_papers` 为通用多源搜索，可通过 `sources` 控制来源
- `search_lanfanshu` 会显式走烂番薯学术

### 4. 假设生成/证据提取返回空

- 确保传入的 `problem_spec` 包含必需字段（至少 `goal`）
- 确保 `papers` 列表非空且包含 `abstract` 字段
- 检查 LLM 配置是否正确（这些工具都需要 AI 调用）
