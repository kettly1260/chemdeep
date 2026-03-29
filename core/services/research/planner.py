"""
Research Planner
"""
import json
import logging
from typing import Callable
from core.ai import AIClient
from .types import ResearchPlan, ResearchPlanV2
from .prompts import PLAN_GENERATION_PROMPT
import logging

logger = logging.getLogger('deep_research')

class ResearchPlanner:
    def __init__(self, notify: Callable[[str], None]):
        self.notify = notify
    
    # [P60] Clarification Phase
    def generate_clarifying_questions(self, topic: str) -> list[str]:
        """生成 3 个澄清问题以明确研究意图 (中文)"""
        self.notify(f"🤔 正在生成澄清问题: {topic}...")
        
        from core.ai import get_ai_client
        ai = get_ai_client()
        
        prompt = f"""
        用户希望研究: "{topic}"
        
        请生成 3 个具体的澄清问题，帮助明确研究范围。
        关注点建议: 具体应用场景、特定材料体系、关注的性能指标、是否需要合成路线等。
        
        要求:
        1. 必须生成 3 个问题。
        2. 使用简体中文。
        3. 问题要简短专业。
        4. 返回 JSON 格式: {{"questions": ["问题1", "问题2", "问题3"]}}
        """
        
        result = ai.call(prompt, json_mode=True)
        
        default_questions = [
            f"您具体关注 '{topic}' 的哪些应用领域？",
            "是否需要关注特定的化学结构或材料体系？",
            "您最关心的性能指标有哪些？"
        ]
        
        if not result.success:
            return default_questions
            
        try:
            questions = result.data.get("questions", [])
            if len(questions) < 3:
                return default_questions
            return questions[:3]
        except Exception:
            return default_questions
    
    # [P108] Investigation Dimensions Phase
    def generate_investigation_dimensions(self, goal: str, clarifications: str = "") -> dict:
        """生成研究维度计划 (Investigation Dimensions)"""
        self.notify("📊 正在分析研究维度...")
        
        from core.ai import get_ai_client
        ai = get_ai_client()
        
        clarification_text = f"\n用户补充信息: {clarifications}" if clarifications else ""
        
        prompt = f"""你是资深研究顾问。用户提出研究目标: "{goal}"{clarification_text}

将此目标拆解为 3-5 个具体的"调查维度 (Investigation Dimensions)"。

要求:
1. 分析用户需求并提取关键点
2. 识别用户已明确提出的具体要求
3. 生成 3-5 个调查维度
4. 如果找不到精确匹配，说明备选策略

返回 JSON:
{{
  "analysis": "对用户需求的理解摘要 (1-2句话)",
  "dimensions": [
    {{"type": "theoretical", "focus": "具体理论/计算方法", "icon": "💻"}},
    {{"type": "experimental", "focus": "具体实验手段", "icon": "🧪"}},
    {{"type": "literature", "focus": "文献检索策略", "icon": "🔍"}}
  ],
  "recognized_requirements": ["用户明确提出的具体要求1", "要求2"],
  "missing_info_strategy": "如果找不到精确匹配，将如何处理"
}}

注意:
- type 可选: theoretical, experimental, literature, computational, comparison, application
- 使用简体中文
- icon 使用 emoji
"""
        
        result = ai.call(prompt, json_mode=True)
        
        default_plan = {
            "analysis": f"分析目标: {goal[:50]}...",
            "dimensions": [
                {"type": "literature", "focus": "搜索相关文献和研究进展", "icon": "🔍"},
                {"type": "theoretical", "focus": "关注理论预测和计算方法", "icon": "💻"},
                {"type": "experimental", "focus": "了解实验表征手段", "icon": "🧪"}
            ],
            "recognized_requirements": [],
            "missing_info_strategy": "如未找到精确匹配，将检索同类材料体系"
        }
        
        if not result.success:
            return default_plan
            
        try:
            data = result.data
            # Validate required fields
            if not data.get("dimensions"):
                return default_plan
            return data
        except Exception:
            return default_plan
    
    def generate_plan(self, question: str) -> ResearchPlanV2:
        """使用 AI 生成研究计划 (V2 compatible)"""
        self.notify("🔬 正在分析研究问题...")
        
        from core.ai import get_ai_client
        ai = get_ai_client()
        prompt = PLAN_GENERATION_PROMPT.format(question=question)
        result = ai.call(prompt, json_mode=True)
        
        if not result.success:
            self.notify(f"❌ 生成计划失败: {result.error}")
            return self._create_fallback_plan_v2(question)
        
        # Parse logic same as before but map to V2
        try:
            data = result.data
            # Convert dictionary keys if necessary to match V2 fields
            # V1: objectives, criteria, search_queries, analysis_focus, key_aspects
            # V2: same fields
            return ResearchPlanV2(
                objectives=data.get("objectives", []),
                key_aspects=data.get("key_aspects", []),
                criteria=data.get("criteria", {}),
                analysis_focus=data.get("analysis_focus", "general"),
                search_queries=data.get("search_queries", [])
            )
        except Exception:
            return self._create_fallback_plan_v2(question)

    def _create_fallback_plan_v2(self, question: str) -> ResearchPlanV2:
        return ResearchPlanV2(
            objectives=["搜索相关文献"],
            key_aspects=["相关方法", "实验条件", "结果数据"],
            criteria={},
            analysis_focus="general",
            search_queries=[
                {"keywords": question, "source": "openalex"},
                {"keywords": question, "source": "crossref"}
            ]
        )

    def format_plan_text(self, plan: ResearchPlan) -> str:
        """格式化研究计划"""
        lines = [
            "📋 **研究计划**", "",
            "**【研究目标】**"
        ]
        for i, obj in enumerate(plan.objectives, 1):
            lines.append(f"  {i}. {obj}")
        
        lines.extend([
            "",
            "**【筛选标准】**"
        ])
        
        criteria = plan.criteria
        if criteria:
            must = criteria.get("must_haves", {})
            if must:
                lines.append("  🔍 **必须满足**:")
                for k, v in must.items():
                    label = k.replace("_", " ").title()
                    lines.append(f"    - {label}: {v}")
            
            bonus = criteria.get("bonus", [])
            if bonus:
                lines.append("  ➕ **加分项**:")
                for b in bonus:
                    lines.append(f"    - {b}")
                    
            exclude = criteria.get("exclude", [])
            if exclude:
                lines.append("  ❌ **排除**:")
                for e in exclude:
                    lines.append(f"    - {e}")

        lines.extend([
            "",
            "**【搜索策略】**"
        ])
        for q in plan.search_queries:
            src = q.get("source", "unknown").upper()
            kw = q.get("keywords", "")
            lines.append(f"  • {src}: {kw}")
            
        lines.extend([
            "", f"**【分析重点】** {plan.analysis_focus}", "",
            "**【关注方面】**"
        ])
        for aspect in plan.key_aspects:
            lines.append(f"  • {aspect}")
            
        lines.extend(["", "---", "✅ 确认执行？回复 `/confirm` 开始搜索"])
        return "\n".join(lines)

# --- Phase A-2: Planner "State-Only" Interface ---
from .types import ResearchQuestion

def build_plan(question: ResearchQuestion) -> ResearchPlanV2:
    """
    [New] 纯函数式构建计划
    """
    # Use logger as notify for now since pure function doesn't take callback easily without param
    def temp_notify(msg):
        logger.info(msg)
        
    planner = ResearchPlanner(temp_notify)
    # generate_plan expects str
    return planner.generate_plan(question.question)
