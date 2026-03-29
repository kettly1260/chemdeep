"""
Goal Decomposer Module
Breaks down user's research goal into actionable components
"""
import logging
from core.ai import AIClient
from .types import ResearchState
from .prompts import GOAL_DECOMPOSITION_PROMPT

logger = logging.getLogger('deep_research')


def decompose(state: ResearchState) -> ResearchState:
    """
    [New] 需求可操作化
    输入: state.question
    输出: state.intermediate_results["decomposition"]
    """
    logger.info("📋 正在拆解研究目标...")
    
    question = state.question.question
    
    from core.ai import get_ai_client
    ai = get_ai_client()
    prompt = GOAL_DECOMPOSITION_PROMPT.format(question=question)
    
    result = ai.call(prompt, json_mode=True)
    
    if result.success and isinstance(result.data, dict):
        decomposition = {
            "research_object": result.data.get("research_object", question),
            "control_variables": result.data.get("control_variables", []),
            "performance_metrics": result.data.get("performance_metrics", []),
            "constraints": result.data.get("constraints", []),
            "initial_search_keywords": result.data.get("search_keywords", [])
        }
        state.intermediate_results["decomposition"] = decomposition
        logger.info(f"✅ 目标拆解完成: {decomposition['research_object']}")
        logger.info(f"   可调控变量: {decomposition['control_variables']}")
        logger.info(f"   性能指标: {decomposition['performance_metrics']}")
    else:
        # Fallback
        state.intermediate_results["decomposition"] = {
            "research_object": question,
            "control_variables": [],
            "performance_metrics": [],
            "constraints": [],
            "initial_search_keywords": [question]
        }
        logger.warning("⚠️ 目标拆解失败，使用原始问题")
    
    return state
