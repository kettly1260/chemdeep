"""
机理假设生成器 (Hypothesis Layer)
用于在检索前生成基于机理的竞争性假设
"""
import logging
import json
import re
from typing import List, Optional
from core.ai import simple_chat
from .core_types import IterativeResearchState, Hypothesis, HypothesisSet
from .prompts import HYPOTHESIS_GENERATION_PROMPT

logger = logging.getLogger('deep_research')

from typing import Callable

def generate_hypotheses(state: IterativeResearchState, abstracts: List[str] = None, 
                       interaction_callback: Callable[[str, List[str]], str] = None) -> IterativeResearchState:
    """
    基于 ProblemSpec 生成机理假设
    
    Args:
        state: 当前研究状态
        abstracts: 可选的初始摘要列表（用于启发）
        interaction_callback: 交互回调 (prompt, options) -> selection
    """
    logger.info("\n🧠 阶段 1.5: 机理假设生成 (Hypothesis Layer)")
    
    spec = state.problem_spec
    if not spec:
        logger.warning("ProblemSpec 为空，跳过假设生成")
        return state

    abstracts_section = ""
    if abstracts:
        abstracts_section = "\n参考摘要:\n" + "\n".join([f"- {a[:200]}..." for a in abstracts[:3]])

    prompt = HYPOTHESIS_GENERATION_PROMPT.format(
        goal=spec.goal,
        research_object=spec.research_object,
        control_variables=", ".join(spec.control_variables),
        abstracts_section=abstracts_section
    )
    
    while True:
        try:
            # [P80] Enable json_mode for auto-repair
            resp = simple_chat(prompt, json_mode=True)
            
            # simple_chat with json_mode=True might return dict-as-string or just string
            # _parse_json should handle both if resp is stringified dict
            # If simple_chat returns dict (via P67 logic), current _parse_json expects string.
            # Let's ensure compatibility.
            if isinstance(resp, dict):
                 data = resp
            else:
                 data = _parse_json(resp)
            
            hypotheses = []
            for item in data:
                h = Hypothesis(
                    hypothesis_id=item.get("hypothesis_id", f"H{len(hypotheses)+1}"),
                    mechanism_description=item.get("mechanism_description", "未描述"),
                    required_variables=item.get("required_variables", []),
                    irrelevant_variables=item.get("irrelevant_variables", []),
                    falsifiable_conditions=item.get("falsifiable_conditions", []),
                    expected_performance_trend=item.get("expected_performance_trend", "")
                )
                hypotheses.append(h)
                
            state.hypothesis_set = HypothesisSet(hypotheses=hypotheses)
            state.hypothesis_set.selected_hypothesis_ids = [h.hypothesis_id for h in hypotheses]
            
            logger.info(f"✅ 已生成 {len(hypotheses)} 个机理假设")
            break # Success
            
        except Exception as e:
            logger.error(f"机理假设生成失败: {e}")
            
            action = "Skip" # Default
            if interaction_callback:
                # [P68] Add Switch Model option
                action = interaction_callback(f"⚠️ 机理假设生成失败: {e}\n\n建议操作:", ["重试", "切换模型", "跳过", "终止"])
            
            if action == "重试":
                logger.info("用户选择重试...")
                continue
                
            elif action == "切换模型":
                from core.ai import MODEL_STATE
                # Provide common models
                candidates = ["gpt-4o", "gpt-4-turbo", "gpt-3.5-turbo", "gemini-1.5-pro"]
                
                sel_model = interaction_callback(
                    f"当前 OpenAI 模型: {MODEL_STATE.openai_model}\n请选择新模型:", 
                    candidates
                )
                
                if sel_model:
                     # Update logic
                     if "gemini" in sel_model:
                         # Switching provider requires more deep change in simple_chat usually
                         # For now, just warn if not supported, or try to set if dual stack
                         logger.warning("切换到 Gemini 可能需要底层 Provider 支持")
                         MODEL_STATE.gemini_model = sel_model
                     else:
                         MODEL_STATE.openai_model = sel_model
                         logger.info(f"🔄 模型已切换为: {sel_model}")
                continue

            elif action == "终止":
                raise e
            else:
                # Skip / Fallback
                logger.warning("使用默认假设继续")
                # Create default assumption
                default_h = Hypothesis(
                    hypothesis_id="H0",
                    mechanism_description="基于通用理化性质的探索 (Fallback)",
                    required_variables=spec.control_variables,
                    irrelevant_variables=[],
                    falsifiable_conditions=[],
                    expected_performance_trend="未知"
                )
                state.hypothesis_set = HypothesisSet(hypotheses=[default_h], selected_hypothesis_ids=["H0"])
                break
        
    return state


def _parse_json(text: str) -> List[dict]:
    """解析 LLM 返回的 JSON"""
    try:
        # 去除非 JSON 字符
        if "```" in text:
            pattern = r"```(?:json)?\s*(.*?)```"
            match = re.search(pattern, text, re.DOTALL)
            if match:
                text = match.group(1)
        
        # 尝试查找列表
        start = text.find('[')
        end = text.rfind(']')
        if start != -1 and end != -1:
            text = text[start:end+1]
            return json.loads(text)
            
        return json.loads(text)
    except Exception as e:
        raise ValueError(f"Cannot parse JSON: {e}")
