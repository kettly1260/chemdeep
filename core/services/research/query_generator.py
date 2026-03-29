"""
Search Query Generator Module
Implements Instruction 4: 从 ProblemSpec 生成初始检索空间
Implements Instruction 12: 不足时扩展检索空间
[P29] Adaptive "Zoom-In" Iteration
"""

import logging
from typing import List
from core.ai import get_ai_client  # [P30] Use singleton
from .core_types import (
    ProblemSpec,
    SearchQuery,
    SearchQuerySet,
    IterativeResearchState,
    EvaluationResult,
    HypothesisSet,
)

logger = logging.getLogger("deep_research")

# [P29] Adaptive Iteration Focus Keywords
ITERATION_FOCUS = {
    1: {
        "name": "Landscape",
        "focus": "broad overview, synthesis methods, general properties, applications",
        "keywords_hint": "synthesis, properties, applications, structure, characterization",
    },
    2: {
        "name": "Mechanism",
        "focus": "deep mechanistic understanding, photophysics, binding",
        "keywords_hint": "PET mechanism, ICT, orbital energy, binding constant, selectivity, HOMO LUMO, quantum yield",
    },
    3: {
        "name": "Critique",
        "focus": "critical assessment, failure modes, limitations",
        "keywords_hint": "interference, stability, quenching, solubility, photobleaching, limitations, drawbacks",
    },
}


def get_iteration_focus(iteration: int) -> dict:
    """[P29] Get focus keywords for current iteration."""
    return ITERATION_FOCUS.get(iteration, ITERATION_FOCUS[1])


QUERY_GENERATION_PROMPT = """你是科研文献检索专家。根据形式化的研究问题和【机理假设】，生成检索查询集以验证或证伪这些假设。

研究问题:
- 研究对象: {research_object}
- 可调控变量: {variables}
- 性能指标: {metrics}
- 约束条件: {constraints}

已生成的机理假设 (Hypothesis Layer):
{hypotheses_info}

[P29] 当前迭代焦点: {iteration_focus}
[P61] 已知 FACTS (避免重复检索):
{learnings}

请优先生成与上述焦点相关的查询。建议结合 FACTS 进行更深层的探索。

请生成检索查询（按 "变量 × 性能" 或 "机理验证" 组合），返回JSON数组:
[
  {{
    "keywords": "英文检索关键词 (学术术语)",
    "source": "openalex",  # 或 "crossref" 或 "lanfanshu" (烂番薯学术，国内友好)
    "variable_focus": "该查询针对哪个变量/假设",
    "metric_focus": "该查询针对哪个性能指标",
    "priority": 1,
    "bucket": "Broad"  # 或 "Specific" (见下文)
  }},
  ...
]

要求:
1. 优先使用 openalex, crossref 和 lanfanshu (烂番薯学术，国内可访问)
2. 检索词必须针对【机理假设中必需的变量】，忽略【无关变量】
3. 增加验证机理本身的查询 (如: "mechanism X" AND "object")
4. [P63] 标注 bucket: "Broad" (宽泛调研) 或 "Specific" (特定机理/数据)
5. 返回 6-10 个查询"""

EXPANSION_PROMPT = """已有检索未能充分覆盖研究问题，请生成扩展查询。

研究问题:
- 研究对象: {research_object}
- 可调控变量: {variables}
- 性能指标: {metrics}

[P29] 当前迭代焦点: {iteration_focus}
迭代 {iteration}: {iteration_name} - {focus_description}

已执行的查询关键词 (Query History):
{executed_keywords}

已知 FACTS (Learnings):
{learnings}

缺失的覆盖:
- 未覆盖变量: {missing_variables}
- 未覆盖指标: {missing_metrics}
- 扩展建议: {suggestions}

请生成 3-5 个新的检索查询，优先关注当前迭代焦点，且不要与 Query History 重复：
[
  {{
    "keywords": "新的英文检索关键词",
    "source": "openalex",
    "variable_focus": "变量",
    "metric_focus": "指标",
    "priority": 2,
    "bucket": "Specific"
  }}
]"""


def generate_initial_queries(
    spec: ProblemSpec, hypothesis_set: HypothesisSet = None, learnings: List[str] = None
) -> SearchQuerySet:
    """
    从 ProblemSpec 和 HypothesisSet 生成初始检索空间
    """
    logger.info("🔍 正在生成检索查询空间 (基于机理假设)...")

    query_set = SearchQuerySet()

    hypotheses_info = "无额外假设"
    if hypothesis_set and hypothesis_set.hypotheses:
        hypotheses_info = ""
        for h in hypothesis_set.hypotheses:
            hypotheses_info += f"- [{h.hypothesis_id}] {h.mechanism_description}\n"
            hypotheses_info += f"  必需变量: {', '.join(h.required_variables)}\n"
            hypotheses_info += f"  无关变量: {', '.join(h.irrelevant_variables)}\n"

    # [P29] Initial iteration is always 1 (Landscape)
    focus = get_iteration_focus(1)

    # [P61] Format learnings
    learnings_text = "无"
    if learnings:
        learnings_text = "\n".join([f"- {l}" for l in learnings])

    ai = get_ai_client()  # [P30] Use singleton
    prompt = QUERY_GENERATION_PROMPT.format(
        research_object=spec.research_object,
        variables=", ".join(spec.control_variables),
        metrics=", ".join(spec.performance_metrics),
        constraints=", ".join(spec.constraints),
        hypotheses_info=hypotheses_info,
        iteration_focus=focus["keywords_hint"],
        learnings=learnings_text,  # [P61]
    )

    result = ai.call(prompt, json_mode=True)

    if result.success and isinstance(result.data, list):
        for item in result.data:
            query = SearchQuery(
                keywords=item.get("keywords", ""),
                source=item.get("source", "openalex"),
                variable_focus=item.get("variable_focus"),
                metric_focus=item.get("metric_focus"),
                priority=item.get("priority", 1),
            )
            if query.keywords:
                query_set.add_query(query)
        logger.info(f"✅ 生成 {len(query_set.queries)} 个检索查询")
    else:
        # Fallback: 基于变量和指标构造基础查询
        logger.warning("⚠️ LLM查询生成失败，使用回退策略")
        base_keywords = spec.research_object
        for var in spec.control_variables[:2]:
            query_set.add_query(
                SearchQuery(
                    keywords=f"{base_keywords} {var}",
                    source="openalex",
                    variable_focus=var,
                )
            )
        for metric in spec.performance_metrics[:2]:
            query_set.add_query(
                SearchQuery(
                    keywords=f"{base_keywords} {metric}",
                    source="crossref",
                    metric_focus=metric,
                )
            )

    return query_set


def expand_queries(
    spec: ProblemSpec,
    query_set: SearchQuerySet,
    evaluation: EvaluationResult,
    iteration: int = 1,  # [P29] Current iteration
    learnings: List[str] = None,  # [P61]
    query_history: List[str] = None,  # [P61]
) -> SearchQuerySet:
    """
    指令 12: 不足时扩展检索空间
    [P29] Uses adaptive iteration focus
    """
    # [P29] Get iteration focus
    focus = get_iteration_focus(iteration)
    logger.info(f"🔄 正在扩展检索查询空间... [P29] 迭代 {iteration}: {focus['name']}")

    # [P61] Prepare context
    learnings_text = "无"
    if learnings:
        learnings_text = "\n".join([f"- {l}" for l in learnings])

    history_text = "无"
    if query_history:
        # Limit history somewhat to avoid huge prompt, but need to check dupes
        history_text = "\n".join(query_history[-30:])

    ai = get_ai_client()  # [P30] Use singleton
    prompt = EXPANSION_PROMPT.format(
        research_object=spec.research_object,
        variables=", ".join(spec.control_variables),
        metrics=", ".join(spec.performance_metrics),
        iteration_focus=focus["keywords_hint"],
        iteration=iteration,
        iteration_name=focus["name"],
        focus_description=focus["focus"],
        executed_keywords=history_text,  # [P61] Use query_history
        learnings=learnings_text,  # [P61] Inject learnings
        missing_variables=", ".join(evaluation.missing_variables),
        missing_metrics=", ".join(evaluation.missing_metrics),
        suggestions=", ".join(evaluation.suggested_expansions),
    )

    result = ai.call(prompt, json_mode=True)

    new_count = 0
    if result.success and isinstance(result.data, list):
        for item in result.data:
            query = SearchQuery(
                keywords=item.get("keywords", ""),
                source=item.get("source", "openalex"),
                variable_focus=item.get("variable_focus"),
                metric_focus=item.get("metric_focus"),
                priority=item.get("priority", 2),
            )
            # [P63] Parse bucket
            bucket = item.get("bucket", "Specific")

            if query.keywords and query_set.add_query(query):
                new_count += 1

    query_set.iteration += 1
    logger.info(f"✅ 扩展了 {new_count} 个新查询 (迭代 {query_set.iteration})")

    return query_set


def generate_abstract_pivot_queries(
    spec: ProblemSpec, executed_keywords: List[str] = None
) -> List[SearchQuery]:
    """
    [P87] Abstract Pivot Logic
    使用 LLM 生成 Class-Level 和 Method-Level 查询
    当 total_evidence == 0 时触发
    """
    logger.info("🔀 [P87] 触发抽象化查询转向: 零证据场景，生成方法论查询...")

    from core.ai import simple_chat
    from .prompts import ABSTRACT_PIVOT_PROMPT
    import json

    research_object = spec.research_object or spec.goal
    goal = spec.goal
    metrics = (
        ", ".join(spec.performance_metrics)
        if spec.performance_metrics
        else "general properties"
    )
    executed = ", ".join(executed_keywords[:10]) if executed_keywords else "none"

    prompt = ABSTRACT_PIVOT_PROMPT.format(
        research_object=research_object,
        goal=goal,
        metrics=metrics,
        executed_keywords=executed,
    )

    queries = []

    try:
        response = simple_chat(prompt, json_mode=True)

        if isinstance(response, list):
            query_data = response
        elif isinstance(response, str):
            query_data = json.loads(response)
        else:
            raise ValueError("Invalid response format")

        for item in query_data:
            keywords = item.get("keywords", "")
            source = item.get("source", "openalex")
            q_type = item.get("type", "method_level")

            if keywords:
                queries.append(
                    SearchQuery(
                        keywords=keywords,
                        source=source,
                        bucket="Methodological" if "method" in q_type else "Broad",
                        priority=2,
                    )
                )

        logger.info(f"✅ [P87] LLM 生成了 {len(queries)} 个抽象化查询")

    except Exception as e:
        logger.warning(f"[P87] LLM 生成抽象化查询失败: {e}，使用回退逻辑")

        # 回退: 硬编码基础查询
        base_obj = spec.research_object or "target compound"

        for metric in spec.performance_metrics[:2]:
            queries.append(
                SearchQuery(
                    keywords=f"measurement of {metric} methodology",
                    source="crossref",
                    metric_focus=metric,
                    bucket="Methodological",
                )
            )

        queries.append(
            SearchQuery(
                keywords=f"{base_obj} review", source="openalex", bucket="Broad"
            )
        )

        queries.append(
            SearchQuery(
                keywords=f"{base_obj} characterization protocols",
                source="scholar",
                bucket="Methodological",
            )
        )

    return queries


# State-based interfaces
def init_search_space(state: IterativeResearchState) -> IterativeResearchState:
    """从 ProblemSpec 和 HypothesisSet 初始化检索空间"""
    if state.problem_spec is None:
        raise ValueError("problem_spec must be set first")

    # 传入 hypothesis_set (如果存在)
    state.query_set = generate_initial_queries(
        state.problem_spec,
        state.hypothesis_set,
        learnings=state.learnings,  # [P61]
    )
    return state


def expand_search_space(state: IterativeResearchState) -> IterativeResearchState:
    """扩展检索空间"""
    if state.evaluation is None:
        raise ValueError("evaluation must be done first")

    # [P87] Check for Zero Evidence Pivot
    if state.evaluation.total_evidence == 0 and state.iteration > 0:
        pivot_queries = generate_abstract_pivot_queries(state.problem_spec)
        for q in pivot_queries:
            state.query_set.add_query(q)
        logger.info(
            f"🔀 Added {len(pivot_queries)} pivot queries due to zero evidence."
        )
    else:
        state.query_set = expand_queries(
            state.problem_spec,
            state.query_set,
            state.evaluation,
            iteration=state.iteration + 1,  # Pass next iter
            learnings=state.learnings,  # [P61]
            query_history=state.query_history,  # [P61]
        )

    state.iteration += 1
    return state
