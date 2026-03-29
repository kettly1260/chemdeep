"""
Method Synthesizer
"""
import json
import logging
from typing import Callable, Any
from core.ai import AIClient
from .prompts import METHOD_SYNTHESIS_PROMPT

logger = logging.getLogger('deep_research')

class MethodSynthesizer:
    def __init__(self, notify: Callable[[str], None]):
        self.notify = notify

    def synthesize(self, goal: str, evidence_list: list[dict]) -> dict:
        """归并方法并评估 (生成决策表)"""
        if not evidence_list:
            return {"decision_table": [], "synthesis_text": "无足够证据进行合成。"}
            
        self.notify("🧠 正在构建路径决策表 (Decision Table)...")
        
        # Prepare evidence summary for prompt
        evidence_text = ""
        for i, ev in enumerate(evidence_list, 1):
            evidence_text += (
                f"[{i}] {ev.get('title')}\n"
                f"   Route: {ev.get('implementation')}\n"
                f"   Vars: {ev.get('key_variables')}\n"
                f"   Perf: {ev.get('performance_results')}\n"
                f"   Cat: {ev.get('method_category')}\n\n"
            )
        
        from core.ai import get_ai_client
    
        # [P30] Use singleton
        ai = get_ai_client()
        prompt = METHOD_SYNTHESIS_PROMPT.format(goal=goal, evidence_list=evidence_text)
        
        result = ai.call(prompt, json_mode=True)
        
        if result.success:
            try:
                data = result.data
                # data corresponds to the Decision Table JSON
                
                # Generate Markdown Report manually
                report_md = self._generate_markdown_report(data)
                
                # Combine for caller
                data["synthesis_text"] = report_md
                # Map old keys to new for compatibility if needed? 
                # Evaluator uses "method_clusters". We should update Evaluator or map here.
                # Let's map "decision_table" to "method_clusters" structure lightly to keep Evaluator working.
                data["method_clusters"] = self._map_to_clusters(data.get("decision_table", []))
                
                return data
            except Exception as e:
                logger.error(f"Synthesis parsing failed: {e}")
                import traceback
                traceback.print_exc()
                
        return {"decision_table": [], "synthesis_text": "合成分析失败"}

    def _generate_markdown_report(self, data: dict) -> str:
        """Generate human-readable report from Decision Table JSON"""
        lines = []
        lines.append(f"# 研究路径决策表: {data.get('research_question', 'Unknown')}")
        lines.append("")
        
        summary = data.get("path_summary", {})
        lines.append(f"**路径总数**: {summary.get('total_paths', 0)} | **机制分类**: {', '.join(summary.get('mechanism_categories', []))}")
        lines.append("")
        lines.append("## 1. 路径决策详情")
        
        for path in data.get("decision_table", []):
            pid = path.get("path_id", "?")
            score = path.get("overall_score", 0)
            mech = path.get("mechanism_type", "")
            novelty = path.get("novelty_space", {})
            feas = path.get("synthetic_feasibility", {})
            
            # Header
            lines.append(f"### {pid}: {mech} (评分: {score}/10)")
            lines.append(f"**核心思路**: {path.get('core_idea', '')}")
            lines.append("")
            
            # Attributes
            lines.append(f"- **典型结构**: {', '.join(path.get('typical_structure_features', []))}")
            lines.append(f"- **目标应用**: {', '.join(path.get('target_application', []))}")
            lines.append(f"- **文献支持**: {path.get('literature_support', {}).get('paper_count', 0)} 篇 (e.g. {', '.join(path.get('literature_support', {}).get('representative_examples', []))})")
            
            # Pros/Cons
            lines.append(f"- **优势**: {', '.join(path.get('advantages', []))}")
            lines.append(f"- **局限**: {', '.join(path.get('limitations', []))}")
            
            # Feasibility & Novelty
            lines.append(f"- **合成难度**: {feas.get('difficulty_level')} (风险: {', '.join(feas.get('key_risk_steps', []))})")
            sat = "饱和" if novelty.get("is_saturated") else "未饱和"
            lines.append(f"- **创新空间**: {sat} (切入点: {', '.join(novelty.get('possible_innovation_angles', []))})")
            lines.append("")
            
        # Recommendation
        rec = data.get("overall_recommendation", {})
        lines.append("## 2. 最终推荐")
        lines.append(f"🌟 **推荐路径**: {', '.join(rec.get('recommended_path_ids', []))}")
        lines.append(f"💡 **理由**: {rec.get('reason')}")
        lines.append(f"⚠️ **风险提示**: {rec.get('risk_warning')}")
        
        return "\n".join(lines)

    def _map_to_clusters(self, table: list) -> list:
        # Map decision table rows to old cluster format for Evaluator
        clusters = []
        for row in table:
            clusters.append({
                "category": row.get("mechanism_type"),
                "description": row.get("core_idea"),
                "papers": [], # We don't have exact IDs here easily mapped back without more logic
                "assessment": {
                    "maturity": "N/A",
                    "performance_range": str(row.get("key_performance_metrics")),
                    "risks": str(row.get("synthetic_feasibility"))
                }
            })
        return clusters

# --- Phase A-4: Executor "State-Only" Interface ---
from .types import ResearchState

def synthesize(state: ResearchState) -> ResearchState:
    """
    [New] 纯状态驱动的方法归并逻辑
    输入: state.evidence, state.question
    输出: state.intermediate_results["synthesis"], state.final_report
    """
    def temp_notify(msg):
        logger.info(msg)
        
    evidence_list = state.evidence
    if not evidence_list:
        logger.warning("No evidence to synthesize.")
        return state
        
    goal = state.question.question
    
    synthesizer = MethodSynthesizer(temp_notify)
    result = synthesizer.synthesize(goal, evidence_list)
    
    # Store result
    state.intermediate_results["synthesis"] = result
    
    # Also set final report
    state.final_report = result.get("synthesis_text", "")
    
    return state
