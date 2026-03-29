
# ChemDeep Skills — 安装与使用指南

## 多语言/多领域与接口层扩展说明

本skills体系以中/英双语、化学/材料领域为起点，所有Skill均支持language（zh/en）、field（chemistry/materials）参数，未来可扩展至更多语言与领域。

### 接口层设计

- 支持三类扩展：
  - **API**：RESTful接口，便于与外部系统/平台集成
  - **Plugin**：本地/远程插件机制，支持能力热插拔
  - **Hook**：事件/回调机制，便于流程自定义与二次开发
- Skill输入输出、元数据、注册方式与Claude/Cherry Studio/Openclaw等平台保持一致
- 预留接口层，便于未来集成新模型、领域、语言或外部知识库

#### Skill接口参数示例

```json
{
  "language": "zh", // zh 或 en
  "field": "chemistry", // chemistry 或 materials
  "query": "COF 光催化 CO2 还原",
  "mode": "api" // 可选: api/plugin/hook
}
```

#### 扩展点说明

- API: skills/chemdeep-skills/每个Skill均可通过RESTful API暴露，便于平台远程调用
- Plugin: 支持本地/远程插件注册，skills可按需加载/卸载
- Hook: 支持在Skill关键节点注册自定义hook，实现流程扩展

> 具体接口与扩展点实现请见skills/chemdeep-skills/各Skill目录下SKILL.md与代码实现

---

ChemDeep 提供 4 个覆盖完整科研工作流的 Skills，可在 Cherry Studio 或 OpenClaw 中使用，并可在用户合法授权的浏览器会话下进一步执行全文抓取与 PDF 下载。

其中：
- `literature-survey` 被定位为 **默认科研入口**，负责承接大多数“搜论文 / 找相关工作 / 做综述 / 看领域现状 / 汇总证据”的请求
- `deep-research` 被定位为 **重型科研入口**，负责承接“全面调研 / 深度调研 / 完整研究报告 / 多轮整合分析”这类高成本请求
- 其余 skills 更多作为在主入口之后被调用的专项能力

## Skills 概览

| Skill | 适用场景 | Token 消耗 |
|-------|---------|-----------|
| `literature-survey` | 文献搜索、调研、空白分析 | 🟢 低-中 |
| `hypothesis-generation` | 机理假设生成与评估 | 🟡 中 |
| `verification-design` | 实验/计算验证方案设计 | 🟡 中 |
| `deep-research` | 一键完整深度调研 | 🔴 高 |

## 工作流关系

```
┌──────────────────────┐
│  literature-survey   │ ← 日常文献搜索与调研
│  （文献调研）          │
└──────────┬───────────┘
           │ 文献 + ProblemSpec
           ▼
┌──────────────────────┐
│ hypothesis-generation│ ← 基于文献生成机理假设
│  （假设生成）          │
└──────────┬───────────┘
           │ 假设 + 评估结果
           ▼
┌──────────────────────┐
│ verification-design  │ ← 设计验证方案
│  （验证设计）          │
└──────────────────────┘

  ┌──────────────────────┐
  │   deep-research      │ ← 以上全部一键执行
  │  （一键深度调研）      │
  └──────────────────────┘
```

建议从上到下分步使用以节约 token；只在需要全面系统性调研时使用 `deep-research`。

## 默认入口策略

为了减少 Cherry Studio 直接绕过 skill 裸调 MCP 工具的概率，ChemDeep 的 skills 采用以下入口定位：

- 遇到大多数科研相关请求时，优先进入 `literature-survey`
- 遇到明确的高成本完整调研请求时，优先进入 `deep-research`
- 不建议把裸 MCP 工具当作默认第一入口；MCP 工具更适合作为 skill 内部的执行层
- 只有在用户明确指定某个单独工具动作时，才适合直接调用对应 MCP 工具

## 全文抓取 / PDF 下载能力说明

ChemDeep Skills 现在支持把出版社页面抓取与 PDF 下载纳入工作流，但必须满足以下前提：

- 仅复用用户当前浏览器中的**合法授权会话**
- **不会绕过付费墙**，也不会伪造权限
- 若遇到验证码、Cloudflare、站点跳转确认，需由用户手动完成
- 更适合作为 `literature-survey` 或 `deep-research` 中的按需步骤，而不是默认动作

推荐流程：

1. 先执行 `prepare_live_browser_session`
2. 让用户在 Edge 中完成登录、验证码处理、必要时点击一次 `View PDF`
3. 再执行 `get_paper_details(fetch_full_text=true)` 或 `download_paper_pdf`

适用场景：
- 在调研中需要查看正文段落、方法细节、结果表述
- 需要把可访问论文 PDF 下载到本地以便后续整理
- 希望在 Deep Research 运行前先准备好受限站点会话

## 安装方式

### 方式 1：手动复制 Skill 文件（推荐）

1. 找到你的 Cherry Studio Agent 工作目录（通常在 Agent 设置中可查看路径）
2. 在 Agent 目录下创建 `skills/` 子目录（如已存在则跳过）
3. 将 `skills/chemdeep-skills/` 下的 4 个 skill 文件夹复制到 Agent 的 `skills/` 目录：

```
你的Agent工作目录/
└── skills/
    ├── literature-survey/
    │   └── SKILL.md
    ├── hypothesis-generation/
    │   └── SKILL.md
    ├── verification-design/
    │   └── SKILL.md
    └── deep-research/
        └── SKILL.md
```

4. 确保 ChemDeep MCP Server 已在 Cherry Studio 中配置（参见下方 MCP 配置）

### 方式 2：目录安装

1. 打开 Cherry Studio → **设置** → **Agent 设置** → **插件管理**
2. 点击 **从目录安装**
3. 选择 `G:\LLM\chemdeep\skills\chemdeep-skills` 目录
4. 配置 MCP Server 的环境变量

> **注意**：ZIP 上传安装可能因安全策略限制而失败。如遇安装错误，请使用方式 1 手动复制。

## MCP Server 配置

无论使用哪种安装方式，都需要确保 ChemDeep MCP Server 可用。

### Cherry Studio 配置

在 **设置** → **MCP 服务器** 中添加：

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
    "CHEMDEEP_OPENAI_API_KEY": "<your-api-key>"
  }
}
```

### OpenClaw 配置

在 **设置** → **工具/插件** 中添加：

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
        "CHEMDEEP_OPENAI_API_KEY": "<your-api-key>"
      }
    }
  }
}
```

## 使用示例

### 示例 1：快速文献搜索

> 用户：帮我搜索关于 "COF photocatalysis CO2 reduction" 的近5年论文

→ 触发 `literature-survey` skill
→ 调用 `search_papers` → `score_papers`
→ 返回高质量论文列表

### 示例 2：生成研究假设

> 用户：基于这些文献，分析 COF 光催化 CO2 还原的可能机理，生成假设

→ 触发 `hypothesis-generation` skill
→ 调用 `formalize_research_goal` → `generate_hypotheses`
→ 返回可证伪的机理假设列表

### 示例 3：设计验证方案

> 用户：为假设 "COF 层间电荷传输促进 CO2 活化" 设计验证实验

→ 触发 `verification-design` skill
→ 调用 `design_verification_plan`
→ 返回实验和计算验证方案

### 示例 4：准备出版社实时会话并下载 PDF

> 用户：帮我把这篇 ScienceDirect 论文的 PDF 下载下来，如果需要我可以先登录学校订阅

→ 触发 `literature-survey` 或相关调研 skill 的全文分支
→ 先调用 `prepare_live_browser_session`
→ 提示用户在 Edge 中完成登录 / 验证 / 点击 `View PDF`
→ 再调用 `download_paper_pdf`
→ 返回下载结果与本地路径

### 示例 5：一键深度调研

> 用户：请对"基于 MOF 的电催化氮气还原"进行全面深度调研

→ 触发 `deep-research` skill
→ 确认后调用 `run_deep_research`
→ 返回完整调研报告

## Token 使用建议

| 操作 | 预估 Token | 建议 |
|------|-----------|------|
| 单次文献搜索 | ~500 | 随时使用 |
| 评分筛选 | ~1,000 | 搜索后必做 |
| 目标形式化 | ~2,000 | 深入分析前做 |
| 假设生成 | ~3,000 | 有文献基础后做 |
| 证据提取 | ~5,000 | 按需做 |
| 假设评估 | ~3,000 | 选择性评估 |
| 验证方案设计 | ~4,000 | 按需做 |
| 全文抓取 / PDF 下载 | 取决于站点与会话 | 仅在用户明确需要时使用 |
| 一键深度调研 | ~30,000-80,000 | 慎用，需确认 |

**省 token 的关键原则**：
1. 从轻量级 skill 开始，按需深入
2. 每步都确认后再继续
3. 只对高分论文做深入分析
4. 避免重复检索同一查询
5. 全文抓取与 PDF 下载只在用户明确要求且已具备合法会话时执行

## 故障排除

### Skill 未被触发

- 确认 skill 文件已正确安装
- 确认 MCP Server 已启动且可用
- 尝试在提示中明确提到 skill 关键词（如"文献调研"、"生成假设"）

### MCP 工具调用失败

- 检查 MCP Server 是否正常运行
- 检查 PYTHONPATH 是否正确设置
- 检查 API Key 是否有效
- 查看 Cherry Studio 的 MCP 日志
- 若全文抓取失败，先检查是否已在浏览器中完成登录、验证码或 Cloudflare 验证

### 深度调研超时

- `run_deep_research` 可能需要 5-15 分钟
- 如果超时，改用分步 skill 逐步执行
- 降低 `max_iterations`（如从 3 降到 2）

### 全文/PDF 下载失败

- 先调用 `prepare_live_browser_session`，确认 Edge/CDP 会话可用
- 在浏览器中手动打开目标文章页
- 如站点要求，先点击一次 `View PDF` 或 `Download PDF`
- 若仍失败，回退到摘要/元数据分析，并明确说明权限或站点限制

### 全文/PDF 下载失败

- 先调用 `prepare_live_browser_session`，确认 Edge/CDP 会话可用
- 在浏览器中手动打开目标文章页
- 如站点要求，先点击一次 `View PDF` 或 `Download PDF`
- 若仍失败，回退到摘要/元数据分析，并明确说明权限或站点限制
