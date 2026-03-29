---
name: hypothesis-generation
description: 使用 ChemDeep MCP 进行机理假设生成与评估。当用户要求生成研究假设、分析反应机理、提出新的科学假说或评估已有假设时触发。需要先有文献基础（通过 literature-survey 获得或用户提供）。
tools:
  - mcp__chemdeep__formalize_research_goal
  - mcp__chemdeep__generate_hypotheses
  - mcp__chemdeep__evaluate_hypotheses
  - mcp__chemdeep__extract_evidence
  - mcp__chemdeep__search_papers
  - mcp__chemdeep__score_papers
---

# 机理假设生成 (Hypothesis Generation)

基于文献证据生成可证伪的化学/材料科学机理假设，并用已有证据评估其合理性。

## 适用场景

- 用户有了文献调研结果，需要提出新的机理假设
- 用户想探讨某个化学反应/材料性能的潜在机理
- 需要系统性地从文献中归纳可能的解释
- 需要评估假设与已有证据的一致性

## ⚠️ Token 节约规则

1. **不要重复检索**：如果用户已经通过 literature-survey 获得了文献列表，直接使用，不要重新搜索
2. **先形式化再生成**：必须先有 ProblemSpec，再生成假设；不要跳过形式化步骤
3. **按需评估**：生成假设后先展示给用户，确认需要评估哪些假设后再调用评估工具
4. **限制假设数量**：一次生成不超过 5 个假设，避免过多低质量假设

## 前置条件

此 skill 通常依赖以下输入之一：
- 来自 `literature-survey` skill 的文献列表和摘要
- 用户直接提供的论文信息和研究背景
- 用户描述的研究问题

## 工作流

### 步骤 1：确认输入

检查是否已有以下材料：

| 所需材料 | 来源 | 是否必需 |
|---------|------|---------|
| 研究目标描述 | 用户直接给出 | ✅ 必需 |
| 相关文献摘要 | literature-survey 或用户提供 | ✅ 推荐 |
| 已有的 ProblemSpec | formalize_research_goal 输出 | 可选（没有则在步骤 2 生成） |

如果缺少文献基础，提示用户先使用 `literature-survey` skill，或者提供至少 3 篇相关论文的摘要。

### 步骤 2：形式化研究目标

如果还没有 ProblemSpec：

```
→ formalize_research_goal(goal=<用户的研究目标>)
```

输出 ProblemSpec 后向用户确认：
- 研究对象是否正确？
- 控制变量是否完整？
- 性能指标是否合理？

用户确认后再继续。

### 步骤 3：生成机理假设

```
→ generate_hypotheses(
    problem_spec=<ProblemSpec>,
    abstracts=<文献摘要列表>
  )
```

向用户展示生成的假设，每个假设包含：
- **假设 ID 和描述**：机理的核心主张
- **所需变量**：验证此假设需要测量的变量
- **可证伪条件**：在什么条件下此假设会被否定
- **预期趋势**：如果假设成立，应该观察到什么趋势

**到这一步先停下来，让用户选择感兴趣的假设。**

### 步骤 4：证据提取（按需）

如果用户想评估假设，且还没有结构化证据：

```
→ extract_evidence(
    problem_spec=<ProblemSpec>,
    papers=<论文列表>
  )
```

### 步骤 5：假设评估（按需）

用户选定要评估的假设后：

```
→ evaluate_hypotheses(
    hypotheses=<用户选定的假设>,
    evidence=<步骤4的证据>
  )
```

输出每个假设的评估结果：
- **状态**：ACTIVE（证据支持）/ REJECTED（证据反驳）/ FROZEN（证据不足）
- **支持证据**和**反驳证据**的具体来源
- **置信度评分**

### 步骤 6：汇总

整理输出：
1. 研究目标概述
2. 假设列表及评估状态
3. 最有前景的假设（ACTIVE 且置信度高的）
4. 需要进一步验证的方向
5. 建议用户使用 `verification-design` skill 设计验证方案

## 约束

- **不要**在没有文献基础的情况下凭空生成假设
- **不要**一次生成超过 5 个假设
- **不要**自动评估所有假设，让用户选择
- **不要**在用户没有确认 ProblemSpec 的情况下直接生成假设
- 假设必须是可证伪的（有明确的否定条件）
- 输出应区分事实（已有证据支持的）和推测（假设中的新主张）
