"""
Research prompts
"""

PLAN_GENERATION_PROMPT = '''你是一个专业的化学/材料科学研究助手。用户提出了研究问题，请生成详细的搜索策略。

用户问题: {question}

请分析问题并生成 JSON 格式的研究计划（仅返回 JSON）：
{{
  "objectives": [
    "研究目标1: 具体描述",
    "研究目标2: 具体描述"
  ],
  "criteria": {{
    "must_haves": {{
      "material_type": "材料类型 (如: MOF, Anode, etc.)",
      "performance_metrics": "性能指标 (如: Capacity, Efficiency, etc.)",
      "experiment_type": "实验/计算类型"
    }},
    "bonus": [
      "是否有系统对照",
      "是否讨论结构–性能关系"
    ]
  }},
  "search_queries": [
    {{"keywords": "英文关键词组合1", "source": "openalex"}},
    {{"keywords": "英文关键词组合2", "source": "crossref"}},
    {{"keywords": "TS=(term1 AND term2 AND term3)", "source": "wos"}}
  ],
  "analysis_focus": "synthesis|performance|mechanism|characterization|general",
  "key_aspects": [
    "需要关注的方面1",
    "需要关注的方面2"
  ]
}}

注意:
1. 必须明确提取材料类型、性能指标和实验类型
2. 搜索关键词应该是英文，使用学术术语
3. CrossRef 和 Scholar 使用简单英文关键词
4. WoS 使用布尔检索式 (TS=, AND, OR)
5. analysis_focus 根据问题类型选择合适的分析重点'''


PAPER_SCREENING_PROMPT = '''你是一个严格的学术审稿人。请根据以下标准评估这批论文是否值得深入阅读。

用户研究问题: {question}

待评估论文列表:
{papers_text}

【评分标准 (0-12分)】
1. 相关性 (0-4): 是否直接处理了用户关心的问题？
2. 方法学价值 (0-3): 是否提供了具体的实验/计算/合成细节？
3. 结果可信度 (0-3): 是否有定量数据支持？
4. 创新性 (0-2): 是否提出了新见解或新材料？

【筛选配置】
- 【必须满足】
    - 材料类型：符合问题要求
    - 性能指标：有具体数据
    - 实验或计算类型：符合预期
- 【加分项】
    - 是否有系统对照
    - 是否讨论结构–性能关系

对每篇文献，请按以下JSON格式返回评分数组 (根据论文的[index]标识):

[
  {{
    "index": 1,
    "total_score": 0,
    "scores": {{
      "relevance": 0,
      "methodology": 0,
      "credibility": 0,
      "novelty": 0
    }},
    "reason": "一句话理由",
    "label": "Must Read"
  }},
  ...
]

label 规则: >=9: Must Read, 6-8: Optional, <=5: Ignore'''


DYNAMIC_ANALYSIS_PROMPT = '''基于用户的研究问题，从这篇论文中提取关键信息。

研究问题: {question}

需要关注的方面:
{key_aspects}

论文内容:
{content}

请提取以下维度的详细信息，并以 JSON 格式返回:

1. 研究目的: 这篇论文想解决什么问题？
2. 材料/体系: 具体涉及哪些材料或化学体系？
3. 关键实验/合成方法: 核心的制备或测试方法是什么？
4. 核心结果 (表格化): 提取关键性能数据（如产率、效率、稳定性等），以 Markdown 表格形式表示字符串。
5. 作者结论: 作者得出的主要结论。
6. 明显不足/未讨论点: 论文的局限性或未涉及的方面。

请返回 JSON:
{{
  "relevant": true/false,
  "analysis": {{
    "research_purpose": "...",
    "material_system": "...",
    "key_methods": "...",
    "core_results_table": "| Parameter | Value | Note |\n|---|---|---|\n| ... | ... | ... |",
    "author_conclusion": "...",
    "limitations": "..."
  }},
  "relevance_note": "..."
}}'''


REPORT_GENERATION_PROMPT = '''你是化学/材料领域的资深研究专家。基于提供的多篇文献分析结果，进行深度的对比与推理。

用户问题: {question}

研究目标:
{objectives}

文献分析集合:
{analyses}

请撰写一份深度综述报告 (Markdown)，重点进行"判断"而非简单的"总结"。
报告结构如下:

# 深度研究报告: {short_title}

## 1. 核心结论 (Executive Summary)
简要回答用户问题。

## 2. 共识 (Consensus)
- 哪些结论在多篇文献中是一致的？
- 哪些因素被反复证明是关键的？

## 3. 分歧 (Divergence)
- 这里的重点是推理：为什么文献结论不同？
- 例如：A 认为 XXX 有效，B 未观察到，差异可能来自 XXX (如实验条件、体系差异等)。
- 尝试解释表面上的冲突。

## 4. 明显空白 (Gaps)
- 尚无文献系统比较 XXX
- 哪些关键变量被经常忽视？
- “作者没意识到的共性”是什么？

## 5. 详细数据对比
(基于文献中的核心结果，总结为对比表格或关键数据综述)

## 6. 参考文献
列出主要参考的 DOI。

---
*报告由 Deep Research 智能生成*
'''


# --- Iterative Workflow Prompts ---

GOAL_DECOMPOSITION_PROMPT = '''将用户的科研目标拆解为可操作的研究要素。

用户目标: {goal}

请分析并提取（返回 JSON）:
{{
  "research_object": "精确的研究对象 (如: 锂金属负极 SEI 膜)",
  "control_variables": [
    "可调控变量1 (如: 电解液添加剂 FEC)",
    "可调控变量2 (如: 施加压力)"
  ],
  "performance_metrics": [
    "关键性能指标1 (如: 库伦效率 CE)",
    "关键性能指标2 (如: 循环寿命)"
  ],
  "constraints": [
    "现实约束条件 (如: 室温下, 无稀有金属)"
  ],
  "initial_search_queries": [
    {{"keywords": "核心变量 AND 研究对象", "source": "openalex"}},
    {{"keywords": "变量2 AND 性能指标", "source": "crossref"}}
  ]
}}'''

EVIDENCE_EXTRACTION_PROMPT = '''从文献中提取具体的实验证据。

研究对象: {research_object}
关注变量: {variables}

文献内容:
{content}

请提取以下关键信息（JSON）:
{{
  "relevant": true,
  "evidence": {{
    "implementation": "具体的实现手段/技术路线",
    "key_variables": "文中实际调节的关键变量及其范围",
    "performance_results": "获得的核心性能数据（定量）",
    "limitations": "局限条件或负面结果",
    "method_category": "该方法属于哪类技术路线？(简短标签)"
  }}
}}'''


METHOD_SYNTHESIS_PROMPT = '''基于提取的证据，构建实现路径决策表 (Research Path Decision Table)。

研究问题: {goal}

提取的证据集合:
{evidence_list}

请分析并返回如下严谨的 JSON 结构 (不要 markdown 代码块，仅返回 JSON):

{{
  "research_question": "{goal}",
  "path_summary": {{
    "total_paths": 0,
    "mechanism_categories": ["机制A", "机制B"]
  }},
  "decision_table": [
    {{
      "path_id": "P1",
      "mechanism_type": "物理/化学本质机制 (ICT/AIE/FRET等)",
      "core_idea": "一句话核心思路",
      "typical_structure_features": ["结构特征1", "结构特征2"],
      "target_application": ["应用场景1"],
      "key_performance_metrics": ["关键指标1"],
      "literature_support": {{
        "paper_count": 0,
        "representative_examples": ["Paper 1", "Paper 2"]
      }},
      "advantages": ["优势1", "优势2"],
      "limitations": ["局限1", "局限2"],
      "synthetic_feasibility": {{
        "difficulty_level": "low / medium / high",
        "key_risk_steps": ["风险步骤1"]
      }},
      "novelty_space": {{
        "is_saturated": true/false,
        "possible_innovation_angles": ["创新点1"]
      }},
      "overall_score": 0  // 0-10 分
    }}
  ],
  "overall_recommendation": {{
    "recommended_path_ids": ["P1"],
    "reason": "推荐理由",
    "risk_warning": "风险提示"
  }}
}}

注意：
1. **mechanism_type**: 必须写物理/化学本质，不能只写"改结构"。
2. **synthetic_feasibility**: 必须站在合成化学家视角评估难度。
3. **novelty_space**: 评估是否还有发文空间。
'''

SUFFICIENCY_CHECK_PROMPT = '''判断当前的研究结果是否足以覆盖用户目标。

用户目标: {goal}
已识别的方法路线: {method_categories}
包含的文献数量: {paper_count}

请判断:
1. 方法是否足够覆盖？(多样性是否足够)
2. 证据链是否完整？(是否有关键数据缺失)

返回 JSON:
{{
  "sufficient": true/false,
  "reason": "判断理由",
  "missing_aspects": ["缺失方面1", "缺失方面2"],
  "suggested_queries": [
    // 如果不足，提供 2-3 个新的扩展搜索词
    {{"keywords": "新方向查询", "source": "scholar"}}
  ]
}}'''


HYPOTHESIS_GENERATION_PROMPT = '''基于用户的研究目标，生成相互区分、互斥或竞争的机理假设。
不要进行文献检索，而是基于你的专业知识进行逻辑推演。

用户研究目标: {goal}
研究对象: {research_object}
控制变量: {control_variables}
{abstracts_section}

请生成 3-5 个【相互区分】的机理假设。每个假设必须是“可被证伪”的，且明确指出在该机理下哪些变量是真正相关的，哪些是无关的。

严格遵循以下 JSON 格式 (纯 JSON，不要包含注释，不要使用 Markdown 代码块):
[
  {{
    "hypothesis_id": "H1",
    "mechanism_description": "详细描述该假设的机理解释",
    "required_variables": ["该机理下必需的变量"],
    "irrelevant_variables": ["在该机理下可忽略的变量"],
    "falsifiable_conditions": ["如果观察到什么现象，则该假设被否定"],
    "expected_performance_trend": "定性的性能预期"
  }},
  ...
]

要求:
1. 假设之间应有明显的区分度（不同的物理/化学过程）。
2. 不要生成“万能型”描述，要有特异性。
3. "irrelevant_variables" 用于后续裁剪搜索空间，必须填写。
'''



HYPOTHESIS_FALSIFICATION_PROMPT = '''基于提取的证据，判断该机理假设是否已被证伪。

机理假设: {mechanism_description}
预期性能趋势: {expected_performance_trend}
证伪条件: 
{falsifiable_conditions}

提取的证据集合:
{evidence_list}

请分析证据是否触发了上述证伪条件。
返回 JSON:
{{
  "is_falsified": true/false,
  "rejection_reason": "如果被证伪，详细说明理由",
  "refuting_evidence_indices": [1, 3], // 强烈反驳该假设的证据编号 (1-based)
  "supporting_evidence_count": 0,
  "conflicting_evidence_count": 0
}}
'''


DATA_NORMALIZATION_PROMPT = '''将提取的实验数据归一化为标准数值。

待处理数据:
{data_json}

请将其转换为数值格式 (float)。
标准单位参考:
- 浓度: M (mol/L) 或 mg/mL
- 产率/效率: % (0-100)
- 温度: C
- 时间: h

规则:
1. "500 ug/mL" -> value: 0.5, unit: "mg/mL"
2. "80-90%" -> value: 85.0, unit: "%", range: [80, 90]
3. "High yield" -> value: null, tag: "qualitative_high" (禁止瞎编数值)
4. "room temp" -> value: 25.0, unit: "C"
5. 对于无法确定的，value: null
6. 禁止将定性描述 (high, low, good) 映射为具体阈值

返回 JSON 字典 (key 对应原数据 key):
{{
  "key_name": {{
    "value": float or null,
    "unit": "string",
    "range": [min, max],
    "tag": "string"
  }}
}}
'''


# ============================================================
# [P87] 通用语义相关性 Prompt
# ============================================================
SEMANTIC_RELEVANCE_PROMPT = '''You are a semantic relevance classifier for academic research.

**User's Research Target**: {research_object}
**User's Research Goal**: {goal}

For each paper below, classify its relevance to the research target:
- **Direct**: The paper directly studies the target object.
- **Analogous**: The paper studies a closely related class/analogue (e.g., same family of compounds).
- **Methodological**: The paper provides methods/protocols applicable to studying the target.
- **Irrelevant**: The paper shares keywords but studies an unrelated entity (NOISE).

Papers to classify:
{papers_batch}

Return JSON array (one per paper, maintain order):
[
  {{"index": 0, "category": "Direct|Analogous|Methodological|Irrelevant", "reason": "brief reason"}},
  ...
]

CRITICAL:
- Be STRICT about "Irrelevant" - remove noise aggressively.
- If a paper studies a completely different class (e.g., biological rhodopsin when target is carborane), mark as Irrelevant.
- Analogous is for same family (e.g., other boron clusters when target is carborane).
- Methodological is for papers describing how to measure/test the properties of interest.
'''


# ============================================================
# [P87] 抽象化查询转向 Prompt
# ============================================================
ABSTRACT_PIVOT_PROMPT = '''You are a research query strategist. The user has found ZERO direct evidence for their research target.
Generate abstract pivot queries to find methodological and analogous evidence.

**Research Object**: {research_object}
**Research Goal**: {goal}
**Properties of Interest**: {metrics}
**Already Searched Keywords**: {executed_keywords}

Generate queries in two categories:

1. **Class-Level Queries** (2-3 queries):
   - Search for the parent class/family of the target
   - Search for reviews/overviews of the broader category
   - Example: If target is "B(9,12)-(芘-5-噻吩-2)2-邻-碳硼烷", search for "carborane" or "boron cluster" reviews

2. **Method-Level Queries** (2-3 queries):
   - Search for how to measure/test the properties of interest
   - Search for experimental/computational protocols
   - Example: If measuring "nonlinear optical properties", search for "NLO measurement method" or "hyperpolarizability calculation"

Return JSON:
[
  {{"keywords": "English search keywords", "source": "openalex", "type": "class_level"}},
  {{"keywords": "English search keywords", "source": "openalex", "type": "method_level"}},
  ...
]
'''

