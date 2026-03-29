"""
Evidence Extractor
"""
import logging
from typing import Callable
from core.ai import AIClient
from .prompts import EVIDENCE_EXTRACTION_PROMPT

logger = logging.getLogger('deep_research')

class EvidenceExtractor:
    def __init__(self, notify: Callable[[str], None]):
        self.notify = notify

    def extract_evidence(self, papers: list[dict], research_object: str, variables: list[str]) -> list[dict]:
        """从论文中提取结构化证据"""
        evidence_list = []
        
        if not papers:
            return []

        self.notify(f"🔍 正在从 {len(papers)} 篇文献中提取证据...")
        
        # Batch processing or One-by-One? 
        # Extraction is heavy, one-by-one is safer for context context limits if full text.
        # But we usually have Abstract + Snippets here from MCP.
        
        from core.ai import get_ai_client
        ai = get_ai_client()
        vars_str = ", ".join(variables)
        
        for i, p in enumerate(papers, 1):
            # 优先使用全文内容，否则使用摘要
            if p.get("full_content"):
                content = f"Title: {p.get('title')}\n\nFull Content:\n{p.get('full_content')[:8000]}"  # Truncate for token limit
            else:
                content = f"Title: {p.get('title')}\nAbstract: {p.get('abstract')}\nSnippet: {p.get('snippet')}"
            
            prompt = EVIDENCE_EXTRACTION_PROMPT.format(
                research_object=research_object,
                variables=vars_str,
                content=content
            )
            
            # Quick async call ideally, but here sync
            res = ai.call(prompt, json_mode=True)
            if res.success:
                data = res.data
                if data.get("relevant"):
                    ev = data.get("evidence", {})
                    ev["paper_id"] = i
                    ev["doi"] = p.get("doi")
                    ev["title"] = p.get("title")
                    ev["year"] = p.get("year")
                    evidence_list.append(ev)
        
        self.notify(f"📊 提取完成: 获得 {len(evidence_list)} 条有效证据")
        return evidence_list

# --- Phase A-4: Executor "State-Only" Interface ---
from .types import ResearchState

def extract(state: ResearchState) -> ResearchState:
    """
    [New] 纯状态驱动的证据提取逻辑
    输入: state.paper_pool, state.intermediate_results (decomposition)
    输出: state.evidence
    """
    def temp_notify(msg):
        logger.info(msg)
        
    papers = state.paper_pool
    # Only screen papers that passed screening (if screening info exists)
    # If screening info exists, filter > 0 score? Or just take all?
    # Let's filter if screening exists
    candidates = []
    for p in papers:
        # If 'screening' key exists, check score. If not, assume relevant.
        if "screening" in p:
            if p["screening"].get("total_score", 0) >= 3: # Threshold?
                candidates.append(p)
        else:
            candidates.append(p)
            
    if not candidates:
        logger.warning("No candidate papers for extraction.")
        return state
        
    # Get extraction parameters from state
    # Ideally from decomposition result, or fallback to plan/question
    decomp = state.intermediate_results.get("decomposition", {})
    if decomp:
        # DecomposedGoal struct -> dict?
        # Check if it's dict or object. Since we put it in intermediate_results which is Dict.
        # Assuming it's serialized or dict.
        res_obj = decomp.get("research_object", "")
        # control_variables might be list
        ctrl_vars = decomp.get("control_variables", [])
    else:
        # Fallback
        res_obj = state.question.question
        ctrl_vars = state.plan.key_aspects if state.plan else []
    
    extractor = EvidenceExtractor(temp_notify)
    new_evidence = extractor.extract_evidence(candidates, res_obj, ctrl_vars)
    
    state.evidence.extend(new_evidence)
    
    return state
