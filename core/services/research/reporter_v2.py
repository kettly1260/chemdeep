"""
Reporter V2 Module
输出交付层：同时生成 report.md 与 report.json
"""

import json
import logging
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Optional

from .core_types import (
    IterativeResearchState,
    ProblemSpec,
    Evidence,
    Hypothesis,
    HypothesisStatus,
    MethodCluster,
    EvaluationResult,
    SufficiencyStatus,
    ContentLevel,
    StudyType,
)
from .audit_logger import AuditLogger

logger = logging.getLogger("deep_research")

OUTPUT_DIR = Path("output")


def generate_report(
    state: IterativeResearchState, output_dir: Path = None
) -> Dict[str, Path]:
    """
    生成双格式报告 (MD + JSON)

    Returns:
        {"md": Path, "json": Path}
    """
    if output_dir is None:
        output_dir = OUTPUT_DIR

    output_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    md_path = output_dir / f"report_{timestamp}.md"
    json_path = output_dir / f"report_{timestamp}.json"

    # 生成 Markdown 报告
    md_content = generate_report_md(state)
    md_path.write_text(md_content, encoding="utf-8")

    # 生成 JSON 报告
    json_content = generate_report_json(state)
    json_path.write_text(
        json.dumps(json_content, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    logger.info(f"📄 报告已生成: {md_path}, {json_path}")

    return {"md": md_path, "json": json_path}


def generate_report_md(state: IterativeResearchState) -> str:
    """
    生成 Markdown 格式报告
    """
    lines = []
    spec = state.problem_spec

    # Header
    lines.append(f"# 深度研究报告")
    lines.append(f"")
    lines.append(f"*生成时间: {datetime.now().isoformat()}*")
    lines.append(f"")
    lines.append(f"---")
    lines.append(f"")

    # ============================================================
    # Section 1: 研究对象/变量/指标/约束
    # ============================================================
    lines.append(f"## 1. 研究定义 (ProblemSpec)")
    lines.append(f"")
    lines.append(f"**研究目标**: {spec.goal}")
    lines.append(f"")
    lines.append(f"**研究对象**: {spec.research_object}")
    lines.append(f"")

    if spec.control_variables:
        lines.append(f"**控制变量**:")
        for v in spec.control_variables:
            lines.append(f"- {v}")
        lines.append(f"")

    if spec.performance_metrics:
        lines.append(f"**性能指标**:")
        for m in spec.performance_metrics:
            lines.append(f"- {m}")
        lines.append(f"")

    if spec.constraints:
        lines.append(f"**约束条件**:")
        for c in spec.constraints:
            lines.append(f"- {c}")
        lines.append(f"")

    lines.append(f"---")
    lines.append(f"")

    # ============================================================
    # Section 2: 假设列表
    # ============================================================
    lines.append(f"## 2. 机理假设分析")
    lines.append(f"")

    if state.hypothesis_set:
        lines.append(f"| 假设ID | 机理描述 | 状态 | 证伪原因 | 证据链 |")
        lines.append(f"|--------|----------|------|----------|--------|")

        for h in state.hypothesis_set.hypotheses:
            mechanism = (
                h.mechanism_description[:50] + "..."
                if len(h.mechanism_description) > 50
                else h.mechanism_description
            )
            reason = (
                h.rejection_reason[:30] + "..."
                if len(h.rejection_reason) > 30
                else (h.rejection_reason or "-")
            )

            # 获取证据链
            trail = AuditLogger.get_hypothesis_trail(h.hypothesis_id)
            evidence_refs = []
            for record in trail:
                evidence_refs.extend(record.paper_keys[:2])
            evidence_str = ", ".join(evidence_refs[:3]) if evidence_refs else "-"

            lines.append(
                f"| {h.hypothesis_id} | {mechanism} | `{h.status.value}` | {reason} | {evidence_str} |"
            )

        lines.append(f"")
    else:
        lines.append(f"*未生成假设*")
        lines.append(f"")

    lines.append(f"---")
    lines.append(f"")

    # ============================================================
    # Section 3: 技术路线 Clusters
    # ============================================================
    lines.append(f"## 3. 技术路线分析")
    lines.append(f"")

    if state.method_clusters:
        for cluster in state.method_clusters:
            lines.append(f"### {cluster.category}")
            lines.append(f"")
            lines.append(f"- **核心思路**: {cluster.core_idea}")
            lines.append(f"- **代表文献**: {len(cluster.evidence_ids)} 篇")
            lines.append(f"- **综合评分**: {cluster.overall_score}/10")
            lines.append(f"")

            if cluster.advantages:
                lines.append(f"**优势**:")
                for adv in cluster.advantages[:3]:
                    lines.append(f"- {adv}")
                lines.append(f"")

            if cluster.limitations:
                lines.append(f"**局限**:")
                for lim in cluster.limitations[:3]:
                    lines.append(f"- {lim}")
                lines.append(f"")
    else:
        lines.append(f"*未进行路线聚类分析*")
        lines.append(f"")

    lines.append(f"---")
    lines.append(f"")

    # ============================================================
    # Section 4: 推荐/不建议路线
    # ============================================================
    lines.append(f"## 4. 路线推荐")
    lines.append(f"")

    if state.hypothesis_set:
        active = [
            h
            for h in state.hypothesis_set.hypotheses
            if h.status == HypothesisStatus.ACTIVE
        ]
        rejected = [
            h
            for h in state.hypothesis_set.hypotheses
            if h.status == HypothesisStatus.REJECTED
        ]

        if active:
            lines.append(f"### ✅ 推荐路线")
            lines.append(f"")
            for h in active:
                lines.append(f"**{h.hypothesis_id}**: {h.mechanism_description[:100]}")
                lines.append(f"- 支持证据: {h.supporting_evidence_count} 篇")
                lines.append(f"- 预期趋势: {h.expected_performance_trend}")
                lines.append(f"")

        if rejected:
            lines.append(f"### ❌ 不建议路线")
            lines.append(f"")
            for h in rejected:
                lines.append(f"**{h.hypothesis_id}**: {h.mechanism_description[:100]}")
                lines.append(f"- 证伪原因: {h.rejection_reason}")

                # 引用证据链
                trail = AuditLogger.get_hypothesis_trail(h.hypothesis_id)
                if trail:
                    lines.append(f"- 证据来源: {', '.join(trail[0].paper_keys[:3])}")
                lines.append(f"")

    lines.append(f"---")
    lines.append(f"")

    # ============================================================
    # Section 5: 缺口分析
    # ============================================================
    lines.append(f"## 5. 缺口分析与行动建议")
    lines.append(f"")

    if state.evaluation:
        if state.evaluation.missing_variables:
            lines.append(f"### 缺失变量")
            for v in state.evaluation.missing_variables:
                lines.append(f"- {v}")
            lines.append(f"")

        if state.evaluation.missing_metrics:
            lines.append(f"### 缺失指标")
            for m in state.evaluation.missing_metrics:
                lines.append(f"- {m}")
            lines.append(f"")

        if state.evaluation.suggested_expansions:
            lines.append(f"### 下一步行动建议")
            for sugg in state.evaluation.suggested_expansions:
                lines.append(f"- {sugg}")
            lines.append(f"")
    else:
        lines.append(f"*暂无缺口分析*")
        lines.append(f"")

    lines.append(f"---")
    lines.append(f"")

    # ============================================================
    # Section 6: 证据统计
    # ============================================================
    lines.append(f"## 6. 证据统计")
    lines.append(f"")
    lines.append(f"- **总证据数**: {len(state.evidence_set)}")

    fulltext_count = sum(
        1 for e in state.evidence_set if e.content_level == ContentLevel.FULL_TEXT
    )
    abstract_count = sum(
        1 for e in state.evidence_set if e.content_level == ContentLevel.ABSTRACT_ONLY
    )
    original_count = sum(
        1 for e in state.evidence_set if e.study_type == StudyType.ORIGINAL
    )

    lines.append(f"- **全文证据**: {fulltext_count}")
    lines.append(f"- **摘要证据**: {abstract_count}")
    lines.append(f"- **原创研究**: {original_count}")
    lines.append(f"")

    lines.append(f"---")
    lines.append(f"")

    # ============================================================
    # Section 7: 论文评分统计
    # ============================================================
    if state.paper_pool:
        lines.append(f"## 7. 论文评分统计")
        lines.append(f"")

        # 统计评级分布
        s_count = len([p for p in state.paper_pool if p.get("score", 0) >= 8.0])
        a_count = len([p for p in state.paper_pool if 6.5 <= p.get("score", 0) < 8.0])
        b_count = len([p for p in state.paper_pool if 5.0 <= p.get("score", 0) < 6.5])
        c_count = len([p for p in state.paper_pool if 3.5 <= p.get("score", 0) < 5.0])
        d_count = len([p for p in state.paper_pool if p.get("score", 0) < 3.5])

        scores = [p.get("score", 0) for p in state.paper_pool if p.get("score")]
        avg_score = sum(scores) / len(scores) if scores else 0

        lines.append(f"- **总论文数**: {len(state.paper_pool)}")
        lines.append(f"- **平均评分**: {avg_score:.2f}")
        lines.append(f"")
        lines.append(f"**评级分布**:")
        lines.append(f"- S级 (≥8.0): {s_count} 篇")
        lines.append(f"- A级 (6.5-8.0): {a_count} 篇")
        lines.append(f"- B级 (5.0-6.5): {b_count} 篇")
        lines.append(f"- C级 (3.5-5.0): {c_count} 篇")
        lines.append(f"- D级 (<3.5): {d_count} 篇")
        lines.append(f"")

        # 显示 Top 5 论文
        sorted_papers = sorted(
            state.paper_pool, key=lambda x: x.get("score", 0), reverse=True
        )
        lines.append(f"**Top 5 高分论文**:")
        for i, p in enumerate(sorted_papers[:5], 1):
            title = p.get("title", "Unknown")[:80]
            score = p.get("score", 0)
            level = p.get("level", "?")
            lines.append(f"{i}. [{level}级 {score:.1f}分] {title}")
        lines.append(f"")

        lines.append(f"---")

    lines.append(f"*报告由 Deep Research 系统自动生成*")

    return "\n".join(lines)


def generate_report_json(state: IterativeResearchState) -> Dict[str, Any]:
    """
    生成 JSON 格式报告 (用于程序化消费)
    """
    spec = state.problem_spec

    # 假设列表
    hypotheses = []
    if state.hypothesis_set:
        for h in state.hypothesis_set.hypotheses:
            trail = AuditLogger.get_hypothesis_trail(h.hypothesis_id)

            # 收集所有证据引用
            evidence_ids = []
            paper_keys = []
            for record in trail:
                evidence_ids.extend(record.evidence_ids)
                paper_keys.extend(record.paper_keys)

            hypotheses.append(
                {
                    "hypothesis_id": h.hypothesis_id,
                    "mechanism_description": h.mechanism_description,
                    "status": h.status.value,
                    "rejection_reason": h.rejection_reason,
                    "required_variables": h.required_variables,
                    "falsifiable_conditions": h.falsifiable_conditions,
                    "expected_performance_trend": h.expected_performance_trend,
                    "supporting_evidence_count": h.supporting_evidence_count,
                    "conflicting_evidence_count": h.conflicting_evidence_count,
                    "evidence_chain": {
                        "evidence_ids": list(set(evidence_ids)),
                        "paper_keys": list(set(paper_keys)),
                    },
                }
            )

    # 路线列表
    routes = []
    if state.method_clusters:
        for cluster in state.method_clusters:
            routes.append(
                {
                    "category": cluster.category,
                    "core_idea": cluster.core_idea,
                    "overall_score": cluster.overall_score,
                    "evidence_ids": cluster.evidence_ids,
                    "advantages": cluster.advantages,
                    "limitations": cluster.limitations,
                    "synthetic_difficulty": getattr(
                        cluster, "synthetic_difficulty", "unknown"
                    ),
                    "novelty_space": getattr(cluster, "novelty_space", {}),
                }
            )

    # 证据列表 (摘要)
    evidence_summary = []
    for ev in state.evidence_set:
        evidence_summary.append(
            {
                "evidence_id": ev.evidence_id,
                "paper_id": ev.paper_id,
                "doi": ev.doi,
                "paper_title": ev.paper_title,
                "content_level": ev.content_level.value,
                "study_type": ev.study_type.value,
                "independence_key": ev.independence_key,
                "quality_weight": ev.quality_weight,
                "falsifiable_allowed": ev.falsifiable_allowed,
            }
        )

    return {
        "generated_at": datetime.now().isoformat(),
        "problem_spec": {
            "goal": spec.goal,
            "research_object": spec.research_object,
            "control_variables": spec.control_variables,
            "performance_metrics": spec.performance_metrics,
            "constraints": spec.constraints,
        },
        "hypotheses": hypotheses,
        "routes": routes,
        "evidence_summary": evidence_summary,
        "evaluation": {
            "is_sufficient": state.evaluation.is_sufficient
            if state.evaluation
            else None,
            "status": state.evaluation.status.value if state.evaluation else None,
            "reason": state.evaluation.reason if state.evaluation else None,
            "missing_variables": state.evaluation.missing_variables
            if state.evaluation
            else [],
            "missing_metrics": state.evaluation.missing_metrics
            if state.evaluation
            else [],
        },
        "statistics": {
            "total_evidence": len(state.evidence_set),
            "fulltext_count": sum(
                1
                for e in state.evidence_set
                if e.content_level == ContentLevel.FULL_TEXT
            ),
            "original_count": sum(
                1 for e in state.evidence_set if e.study_type == StudyType.ORIGINAL
            ),
            "active_hypotheses": len(
                [
                    h
                    for h in state.hypothesis_set.hypotheses
                    if h.status == HypothesisStatus.ACTIVE
                ]
            )
            if state.hypothesis_set
            else 0,
            "rejected_hypotheses": len(
                [
                    h
                    for h in state.hypothesis_set.hypotheses
                    if h.status == HypothesisStatus.REJECTED
                ]
            )
            if state.hypothesis_set
            else 0,
        },
    }
