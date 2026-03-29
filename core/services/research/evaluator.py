"""
Research Evaluator (Sufficiency Check)
"""
import logging
from typing import Callable
from core.ai import AIClient
from .prompts import SUFFICIENCY_CHECK_PROMPT

logger = logging.getLogger('deep_research')

class ResearchEvaluator:
    def __init__(self, notify: Callable[[str], None]):
        self.notify = notify

    def check_sufficiency(self, goal: str, method_clusters: list[dict], paper_count: int) -> dict:
        """检查研究覆盖度"""
        self.notify("⚖️ 正在评估研究充分性 (Sufficiency Check)...")
        
        categories = [c.get("category") for c in method_clusters]
        
        from core.ai import get_ai_client
        ai = get_ai_client()
        prompt = SUFFICIENCY_CHECK_PROMPT.format(
            goal=goal,
            method_categories=", ".join(categories) if categories else "None",
            paper_count=paper_count
        )
        
        result = ai.call(prompt, json_mode=True)
        
        if result.success:
            return result.data
            
        return {"sufficient": True, "reason": "Evaluation failed, assuming sufficient."}
