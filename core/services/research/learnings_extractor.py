"""
Learnings Extractor Module
Extracts incremental knowledge (learnings) from research evidence.
"""
import logging
import json
from .core_types import IterativeResearchState
# [P85] Removed unused import: LEARNINGS_EXTRACTION_PROMPT

logger = logging.getLogger('deep_research')

def extract_learnings(state: IterativeResearchState) -> IterativeResearchState:
    """
    从本轮证据中提取新的知识点 (Learnings)
    """
    if not state.evidence_set:
        return state
        
    logger.info("🧠 正在提取增量知识点 (Learnings)...")
    
    from core.ai import get_ai_client
    ai = get_ai_client()
    
    # 1. 准备上下文
    # 仅使用本轮新增的证据或 Top 证据，避免 Context 过长
    # 这里简单取最近 10 条证据作为输入
    recent_evidence = state.evidence_set[-10:] 
    # [P87] Fix: Evidence object uses 'implementation' not 'content'
    evidence_text = "\n".join([f"- {e.implementation} (Source: {e.source_url})" for e in recent_evidence])
    
    existing_learnings_text = "\n".join([f"- {l}" for l in state.learnings])
    
    prompt = f"""
    基于以下最新获取的科研证据，提取关键的事实性知识点 (Learnings)。
    
    【已有知识库】 (请勿重复):
    {existing_learnings_text if existing_learnings_text else "无"}
    
    【最新证据】:
    {evidence_text}
    
    【任务目标】:
    {state.problem_spec.goal if state.problem_spec else ""}
    
    【提取要求】:
    1. 提取 3-5 个关键事实。
    2. 必须是明确的化学/材料事实（如合成条件、性能数据、机理结论）。
    3. 使用简体中文。
    4. 简练明确，单句不超过 50 字。
    5. 不要提取与【已有知识库】重复的内容。
    6. 返回 JSON 格式: {{"learnings": ["知识点1", "知识点2"]}}
    """
    
    # 2. 调用 LLM
    result = ai.call(prompt, json_mode=True)
    
    if result.success:
        try:
            new_learnings = result.data.get("learnings", [])
            # 简单去重
            for l in new_learnings:
                if l not in state.learnings:
                    state.learnings.append(l)
                    logger.info(f"   + 新增知识: {l}")
        except Exception as e:
            logger.error(f"提取 Learnings 解析失败: {e}")
    else:
        logger.warning(f"提取 Learnings 失败: {result.error}")
        
    return state
