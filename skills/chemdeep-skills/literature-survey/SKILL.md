---
name: literature-survey
description: ChemDeep 的默认科研入口。凡是用户要求搜索论文、寻找相关工作、做文献综述、调研某个研究方向、分析领域现状、比较技术路线、总结研究空白或为后续机理分析收集证据时，优先触发本 skill，而不是直接调用裸 MCP 检索工具。本 skill 负责统一编排检索、筛选、证据提取、全文获取与调研汇总流程。
tools:
  - mcp__chemdeep__search_papers
  - mcp__chemdeep__search_lanfanshu
  - mcp__chemdeep__get_paper_details
  - mcp__chemdeep__prepare_live_browser_session
  - mcp__chemdeep__download_paper_pdf
  - mcp__chemdeep__score_papers
  - mcp__chemdeep__formalize_research_goal
  - mcp__chemdeep__extract_evidence
  - mcp__chemdeep__cluster_methods
  - mcp__chemdeep__analyze_research_gaps
---

# 文献调研 (Literature Survey)

ChemDeep 在 Cherry Studio / OpenClaw 中的**默认科研入口 skill**。当任务仍处于“先找文献、先看相关工作、先判断现状与证据强弱”的阶段时，应优先进入本 skill，再由本 skill 决定调用哪些 ChemDeep MCP 工具，而不是直接裸调单个 MCP 工具。

本 skill 面向系统性的化学/材料科学文献调研工作流，通过 ChemDeep MCP Server 的工具链完成从检索、筛选、证据提取到全文获取与调研汇总的完整流程。

## 默认入口定位

- 当用户说“帮我搜论文”“找相关工作”“做个综述”“看看这个方向现在做到哪里了”“帮我整理证据”时，**优先触发本 skill**
- 当用户尚未明确需要哪一个具体 MCP 工具时，**优先触发本 skill**
- 不要因为看到了 `search_papers`、`score_papers`、`get_paper_details` 等工具名就绕过本 skill
- 只有在用户明确要求某一个单独工具步骤，或上层系统明确要求直调某工具时，才跳过本 skill
- 如果后续需要重型完整调研，再从本 skill 过渡到 `deep-research`

## 适用场景

- 用户给出研究方向或关键词，需要了解领域现状
- 需要找到某个课题的高质量文献
- 需要分析研究空白和技术路径
- 需要对文献做系统性归纳和证据提取

## 路由原则

1. **先走入口，再选工具**：先进入本 skill，再由本 skill 判断是否调用 `search_papers`、`search_lanfanshu`、`score_papers`、`extract_evidence` 等工具
2. **默认不要裸调 MCP**：除非用户明确要求单一步骤，否则不要绕过本 skill 直接调用 ChemDeep MCP 工具
3. **从轻到重**：优先做检索与筛选，只有在用户确认时才进入证据提取、全文抓取或更重的研究流程
4. **必要时再升级**：当用户明确要求“完整调研”“深度调研”“生成完整研究报告”时，再切换到 `deep-research`

## ⚠️ Token 节约规则

1. **检索阶段**：单次检索不超过 20 篇，优先使用 `search_lanfanshu`（中文文献多）或 `search_papers`（英文文献多）
2. **评分筛选**：先用 `score_papers` 过滤掉低分论文（≥5分），再做后续分析，避免对低质量论文浪费 AI 调用
3. **按需深入**：只在用户确认需要时才进入证据提取、全文抓取或 PDF 下载步骤
4. **避免重复**：同一查询不要重复搜索；如果结果不够，调整关键词而不是重跑
5. **全文/PDF 下载需显式授权**：只有在用户明确要求抓取全文或下载 PDF 时，才调用 `get_paper_details(fetch_full_text=true)`、`prepare_live_browser_session` 或 `download_paper_pdf`

## 工作流

### 步骤 1：明确调研目标

向用户确认：
- 研究方向/关键词是什么？
- 需要中文文献还是英文文献？（决定用 `search_lanfanshu` 还是 `search_papers`）
- 时间范围偏好？（默认近 5 年）
- 需要多少篇？（默认 10-20 篇）

如果用户已经给出足够信息，直接进入步骤 2，不要反复追问。

### 步骤 2：文献检索

根据用户需求调用搜索工具：

**英文/多源检索：**
```
→ search_papers(query, sources=["openalex","crossref"], max_results=15, min_year=2020)
```

**中文/烂番薯学术检索：**
```
→ search_lanfanshu(query, max_results=15, min_year=2020, fetch_abstracts=true)
```

**注意**：一次检索通常就够了。只有在结果明显不足（<5篇）时，才用不同关键词补充检索。

### 步骤 3：质量筛选

```
→ score_papers(papers=<步骤2的结果>, topic=<研究方向>)
```

向用户报告：
- 总共检索到 N 篇，评分 ≥5 的有 M 篇
- 列出 Top 论文的标题、年份、评分和摘要要点
- 询问是否需要深入分析

**到这一步先停下来，等用户确认是否继续。**

### 步骤 4：全文抓取 / PDF 下载（可选）

仅当用户明确要求“看全文”“抓正文”“下载 PDF”时才进入本步骤。

**4A. 优先尝试正文抓取：**

```
→ get_paper_details(doi=<目标 DOI>, title=<论文标题>, fetch_full_text=true)
```

适用场景：
- 先快速查看正文预览、方法段、结论段
- 不一定需要完整 PDF 文件，只需要支撑调研摘要与证据提取

**4B. 受限站点会话准备：**

如果目标站点需要机构授权、登录态、验证码或 Cloudflare 校验：

```
→ prepare_live_browser_session(purpose="publisher full-text fetch / PDF download")
```

然后明确提示用户：
- 在 Edge 中完成合法登录
- 手动通过验证码/Cloudflare
- 必要时先打开目标文章页，并点击一次 `View PDF` / `Download PDF`

**4C. 显式下载 PDF：**

```
→ download_paper_pdf(doi=<目标 DOI>, title=<论文标题>)
```

**必须遵守的边界：**
- 不宣称可绕过付费墙
- 只复用用户当前浏览器中已合法获得的访问权限
- 若站点仍拒绝访问，应如实说明失败原因并回退到摘要/元数据分析

### 步骤 5：研究目标形式化（可选）

如果用户需要进一步分析，先形式化研究目标：

```
→ formalize_research_goal(goal=<用户的研究方向描述>)
```

输出 ProblemSpec（目标、变量、指标、约束），供后续步骤使用。

### 步骤 6：证据提取（可选）

对筛选后的高分论文提取结构化证据：

```
→ extract_evidence(problem_spec=<步骤4的ProblemSpec>, papers=<高分论文列表>)
```

输出每篇论文的：实施方案、关键变量、性能结果、局限性。

### 步骤 7：方法聚类（可选）

对提取的证据按技术路径分类：

```
→ cluster_methods(evidence=<步骤5的证据列表>)
```

输出技术路径分类：每类方法的优势、局限、创新角度。

### 步骤 8：研究空白分析（可选）

```
→ analyze_research_gaps(topic=<研究方向>, papers=<高分论文列表>)
```

输出当前研究的空白和未来方向建议。

### 步骤 9：汇总报告

将上述结果整理成结构化的调研报告，包含：
1. 调研概述（目标、检索策略、文献数量）
2. 高质量文献列表（标题、来源、年份、核心发现）
3. 全文/正文获取情况（如果执行了步骤 4）
4. 技术路径分析（如果执行了步骤 7）
5. 研究空白与机会（如果执行了步骤 8）
6. 建议的后续研究方向

## 约束

- **不要**在用户没有要求时自动执行步骤 4-8，这些步骤消耗大量 token 或需要外部站点会话
- **不要**对同一查询重复搜索
- **不要**在检索结果很少（<3篇）时强行做证据提取，应先提示用户调整关键词
- **不要**跳过评分筛选直接做深入分析
- **不要**声称可绕过出版社权限控制；全文抓取与 PDF 下载仅限用户合法授权会话
- 输出应简洁、结构化，突出关键发现而非堆砌内容
