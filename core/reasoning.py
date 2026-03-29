"""
推理模块 - 通过文献分析推断用户需求
支持从文献中提取关键信息，推断研究方向和潜在需求
"""

import json
import logging
from pathlib import Path
from typing import Any, Callable
from dataclasses import dataclass, field

logger = logging.getLogger("reasoning")


@dataclass
class ReasoningResult:
    """推理结果"""

    success: bool
    user_query: str
    inferred_needs: list[str] = field(default_factory=list)
    research_directions: list[str] = field(default_factory=list)
    key_findings: list[str] = field(default_factory=list)
    gaps_identified: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)
    confidence_score: float = 0.0
    supporting_papers: list[dict] = field(default_factory=list)
    error: str | None = None


class NeedInferenceEngine:
    """
    需求推理引擎
    通过分析文献来推断用户的潜在需求
    """

    def __init__(
        self, ai_client=None, notify_callback: Callable[[str], None] | None = None
    ):
        self.ai = ai_client
        self.notify = notify_callback or (lambda x: logger.info(x))

    def infer_from_papers(
        self, user_query: str, papers: list[dict], goal: str = "general"
    ) -> ReasoningResult:
        """
        从文献中推断用户需求

        Args:
            user_query: 用户原始查询
            papers: 搜索到的论文列表
            goal: 研究目标 (synthesis, performance, general)

        Returns:
            ReasoningResult: 推理结果
        """
        if not papers:
            return ReasoningResult(
                success=False, user_query=user_query, error="没有可用的论文进行分析"
            )

        self.notify("🧠 正在分析文献，推断研究需求...")

        try:
            # 准备文献摘要数据
            papers_summary = self._prepare_papers_summary(papers)

            # 调用 AI 进行推理
            inference_result = self._call_ai_for_inference(
                user_query, papers_summary, goal
            )

            if not inference_result:
                return ReasoningResult(
                    success=False, user_query=user_query, error="AI 推理失败"
                )

            # 构建结果
            result = ReasoningResult(
                success=True,
                user_query=user_query,
                inferred_needs=inference_result.get("inferred_needs", []),
                research_directions=inference_result.get("research_directions", []),
                key_findings=inference_result.get("key_findings", []),
                gaps_identified=inference_result.get("gaps_identified", []),
                recommendations=inference_result.get("recommendations", []),
                confidence_score=inference_result.get("confidence_score", 0.0),
                supporting_papers=papers[:10],  # 保存前10篇作为支撑
            )

            self.notify(f"✅ 推理完成，置信度: {result.confidence_score:.0%}")

            return result

        except Exception as e:
            logger.error(f"推理过程出错: {e}")
            return ReasoningResult(success=False, user_query=user_query, error=str(e))

    def _prepare_papers_summary(self, papers: list[dict]) -> str:
        """准备文献摘要信息"""
        summaries = []

        for i, paper in enumerate(papers[:20], 1):  # 最多处理20篇
            title = paper.get("title", "未知标题")
            authors = paper.get("authors", "")
            year = paper.get("year", "")
            abstract = paper.get("abstract", "")

            # 截断过长的摘要
            if abstract and len(abstract) > 500:
                abstract = abstract[:500] + "..."

            summary = f"""论文 {i}:
标题: {title}
作者: {authors}
年份: {year}
摘要: {abstract or "无摘要"}
"""
            summaries.append(summary)

        return "\n---\n".join(summaries)

    def _call_ai_for_inference(
        self, user_query: str, papers_summary: str, goal: str
    ) -> dict | None:
        """调用 AI 进行需求推理"""

        if not self.ai:
            from core.ai import get_ai_client

            self.ai = get_ai_client()

        prompt = f"""你是一个化学研究专家，擅长从文献中分析研究趋势和推断研究需求。

用户原始需求：{user_query}

研究目标：{goal}

以下是搜索到的相关文献摘要：

{papers_summary}

请基于以上文献，分析并推断用户的潜在需求。请返回以下 JSON 格式：

{{
    "inferred_needs": [
        "推断的需求1",
        "推断的需求2",
        "推断的需求3"
    ],
    "research_directions": [
        "研究方向1",
        "研究方向2"
    ],
    "key_findings": [
        "关键发现1",
        "关键发现2",
        "关键发现3"
    ],
    "gaps_identified": [
        "研究空白1",
        "研究空白2"
    ],
    "recommendations": [
        "建议1",
        "建议2",
        "建议3"
    ],
    "confidence_score": 0.85
}}

分析要求：
1. inferred_needs: 基于文献分析，推断用户可能的深层次需求
2. research_directions: 从文献中识别的主要研究方向
3. key_findings: 文献中的关键发现和创新点
4. gaps_identified: 识别的研究空白或不足之处
5. recommendations: 基于分析给出的研究建议
6. confidence_score: 推理的置信度（0-1之间）

请用中文回答，只返回 JSON 格式。"""

        try:
            response = self.ai.call(prompt, json_mode=True)

            if response.success and response.data:
                return response.data

            return None

        except Exception as e:
            logger.error(f"AI 推理调用失败: {e}")
            return None

    def generate_inference_report(self, result: ReasoningResult) -> str:
        """生成推理报告"""

        if not result.success:
            return f"❌ 推理失败: {result.error}"

        lines = [
            "# 📊 需求推理报告",
            "",
            f"**原始查询**: {result.user_query}",
            f"**置信度**: {result.confidence_score:.0%}",
            "",
            "## 🔍 推断的潜在需求",
        ]

        for i, need in enumerate(result.inferred_needs, 1):
            lines.append(f"{i}. {need}")

        lines.extend(
            [
                "",
                "## 🎯 研究方向",
            ]
        )

        for direction in result.research_directions:
            lines.append(f"- {direction}")

        lines.extend(
            [
                "",
                "## 💡 关键发现",
            ]
        )

        for finding in result.key_findings:
            lines.append(f"- {finding}")

        lines.extend(
            [
                "",
                "## 🔬 识别的研究空白",
            ]
        )

        for gap in result.gaps_identified:
            lines.append(f"- {gap}")

        lines.extend(
            [
                "",
                "## 📝 研究建议",
            ]
        )

        for rec in result.recommendations:
            lines.append(f"- {rec}")

        lines.extend(
            ["", f"---", f"*基于 {len(result.supporting_papers)} 篇文献分析生成*"]
        )

        return "\n".join(lines)


class LiteratureGapAnalyzer:
    """
    文献空白分析器
    识别研究领域中的空白和机会
    """

    def __init__(
        self, ai_client=None, notify_callback: Callable[[str], None] | None = None
    ):
        self.ai = ai_client
        self.notify = notify_callback or (lambda x: logger.info(x))

    def analyze_gaps(self, research_topic: str, papers: list[dict]) -> dict[str, Any]:
        """
        分析研究空白

        Returns:
            {
                "success": bool,
                "gaps": [{"description": str, "evidence": str, "opportunity": str}],
                "trends": [str],
                "emerging_areas": [str]
            }
        """
        if not papers:
            return {"success": False, "error": "没有可用的论文"}

        self.notify("🔍 正在分析文献空白...")

        try:
            # 准备文献数据
            papers_data = []
            for p in papers[:15]:
                papers_data.append(
                    {
                        "title": p.get("title", ""),
                        "abstract": (p.get("abstract", "") or "")[:300],
                        "year": p.get("year", ""),
                    }
                )

            if not self.ai:
                from core.ai import get_ai_client

                self.ai = get_ai_client()

            prompt = f"""研究主题：{research_topic}

文献数据：
{json.dumps(papers_data, ensure_ascii=False, indent=2)}

请分析这些文献，识别：
1. 研究空白 - 尚未被充分研究的领域
2. 研究趋势 - 当前的研究热点和发展方向
3. 新兴领域 - 值得关注的新研究方向

返回 JSON 格式：
{{
    "gaps": [
        {{
            "description": "空白描述",
            "evidence": "支持证据",
            "opportunity": "研究机会"
        }}
    ],
    "trends": ["趋势1", "趋势2"],
    "emerging_areas": ["新兴领域1", "新兴领域2"]
}}"""

            response = self.ai.call(prompt, json_mode=True)

            if response.success and response.data:
                return {"success": True, **response.data}

            return {"success": False, "error": "AI 分析失败"}

        except Exception as e:
            logger.error(f"空白分析失败: {e}")
            return {"success": False, "error": str(e)}


class RequirementRefiner:
    """
    需求细化器
    通过文献分析帮助用户细化和明确研究需求
    """

    def __init__(
        self, ai_client=None, notify_callback: Callable[[str], None] | None = None
    ):
        self.ai = ai_client
        self.notify = notify_callback or (lambda x: logger.info(x))

    def refine_requirement(
        self, original_query: str, papers: list[dict], user_context: dict | None = None
    ) -> dict[str, Any]:
        """
        细化用户需求

        Returns:
            {
                "success": bool,
                "refined_query": str,
                "sub_questions": [str],
                "search_keywords": [str],
                "scope_definition": str
            }
        """
        if not papers:
            return {"success": False, "error": "没有可用的论文"}

        self.notify("📝 正在细化研究需求...")

        try:
            # 准备上下文
            context = ""
            if user_context:
                context = f"\n用户背景: {json.dumps(user_context, ensure_ascii=False)}"

            # 准备文献摘要
            papers_summary = []
            for p in papers[:10]:
                papers_summary.append(
                    f"- {p.get('title', '')}: {(p.get('abstract', '') or '')[:200]}"
                )

            if not self.ai:
                from core.ai import get_ai_client

                self.ai = get_ai_client()

            prompt = f"""原始研究需求：{original_query}
{context}

相关文献摘要：
{chr(10).join(papers_summary)}

请基于文献分析，帮助细化用户的研究需求。返回 JSON 格式：

{{
    "refined_query": "细化后的研究问题",
    "sub_questions": [
        "子问题1",
        "子问题2",
        "子问题3"
    ],
    "search_keywords": [
        "关键词1",
        "关键词2",
        "关键词3",
        "关键词4"
    ],
    "scope_definition": "研究范围定义"
}}"""

            response = self.ai.call(prompt, json_mode=True)

            if response.success and response.data:
                return {"success": True, **response.data}

            return {"success": False, "error": "AI 细化失败"}

        except Exception as e:
            logger.error(f"需求细化失败: {e}")
            return {"success": False, "error": str(e)}
