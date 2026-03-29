"""
Problem Formalizer Module
Implements Instruction 2: 需求可操作化 (LLM核心能力)
"""
import logging
from core.ai import AIClient
from .core_types import ProblemSpec, IterativeResearchState

logger = logging.getLogger('deep_research')

FORMALIZE_PROMPT = '''You are a scientific methodology expert. Please formalize the user's research goal into a retrievable variable space.

IMPORTANT: Regardless of the language of the user's input, you MUST respond with rigorous academic English terminology.

用户目标 (User Goal): {goal}

{refinement_section}

Please return in the following JSON format (no markdown code blocks):
{{
  "research_object": "Precise research object in English",
  "domain": "Research domain in English",
  "control_variables": [
    "Variable 1",
    "Variable 2"
  ],
  "performance_metrics": [
    "Metric 1",
    "Metric 2"
  ],
  "constraints": [
    "Realistic constraints"
  ]
}}

Requirements:
1. All terms MUST be in rigorous academic English
2. Variables must be specific concepts searchable in literature databases
3. Performance metrics must be quantifiable or comparable
4. Constraints should reflect practical research limitations'''


def formalize_problem(goal: str, refinement_context: str = "") -> ProblemSpec:
    """
    将用户一句话目标形式化为 ProblemSpec
    """
    logger.info("📋 正在形式化科研问题...")
    
    refinement_section = ""
    if refinement_context:
        logger.info("   ⚠️ 包含上一轮研究的上下文信息")
        refinement_section = f"PREVIOUS RESEARCH CONTEXT (For refinement/deepening):\n{refinement_context}\n\nINSTRUCTION: Refine the variable space based on the previous findings above."
    
    from core.ai import get_ai_client
    ai = get_ai_client()
    result = ai.call(FORMALIZE_PROMPT.format(goal=goal, refinement_section=refinement_section), json_mode=True)
    
    if result.success and isinstance(result.data, dict):
        spec = ProblemSpec(
            goal=goal,
            research_object=result.data.get("research_object", goal),
            control_variables=result.data.get("control_variables", []),
            performance_metrics=result.data.get("performance_metrics", []),
            constraints=result.data.get("constraints", []),
            domain=result.data.get("domain"),
            refinement_context=refinement_context
        )

        logger.info(f"✅ 问题形式化完成")
        logger.info(f"   研究对象: {spec.research_object}")
        logger.info(f"   可调控变量: {spec.control_variables}")
        logger.info(f"   性能指标: {spec.performance_metrics}")
        return spec
    else:
        logger.warning("⚠️ 问题形式化失败，使用默认变量")
        # 提供默认的变量和指标，以便证据提取能正常工作
        return ProblemSpec(
            goal=goal, 
            research_object=goal,
            control_variables=["结构设计", "取代基", "合成方法"],
            performance_metrics=["荧光性能", "光学特性", "检测灵敏度"],
            constraints=["合成可行性"]
        )


def formalize(state: IterativeResearchState) -> IterativeResearchState:
    """
    State-based interface for problem formalization
    输入: state (with goal in problem_spec or to be created)
    输出: state.problem_spec updated
    """
    if state.problem_spec is None:
        raise ValueError("state.problem_spec must be initialized with goal")
    
    goal = state.problem_spec.goal
    context = getattr(state.problem_spec, 'refinement_context', "") # Safe getattr
    
    state.problem_spec = formalize_problem(goal, refinement_context=context)
    return state
