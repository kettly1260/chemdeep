"""
Result Generator Module
Generates final research report from IterativeResearchState
"""
import logging
import json
from dataclasses import asdict, is_dataclass
from enum import Enum
from typing import Any
from .core_types import IterativeResearchState, MethodCluster

logger = logging.getLogger('deep_research')


def generate_result(state: IterativeResearchState) -> IterativeResearchState:
    """
    生成最终研究结果报告
    """
    logger.info("📝 正在生成研究报告...")
    
    spec = state.problem_spec
    clusters = state.method_clusters
    evaluation = state.evaluation
    
    # 按评分排序
    sorted_clusters = sorted(clusters, key=lambda c: c.overall_score, reverse=True)
    
    # 分类推荐与不推荐
    recommended = [c for c in sorted_clusters if c.overall_score >= 7.0]
    not_recommended = [c for c in sorted_clusters if c.overall_score < 5.0]
    
    state.recommended_paths = [c.cluster_id for c in recommended]
    state.not_recommended_paths = [c.cluster_id for c in not_recommended]
    
    # 生成 Markdown 报告
    report_lines = []
    
    # 标题
    report_lines.append(f"# 研究路径决策表: {spec.goal}")
    report_lines.append("")
    
    # 摘要
    report_lines.append("## 研究摘要")
    report_lines.append(f"- **研究对象**: {spec.research_object}")
    report_lines.append(f"- **可调控变量**: {', '.join(spec.control_variables)}")
    report_lines.append(f"- **性能指标**: {', '.join(spec.performance_metrics)}")
    report_lines.append(f"- **论文数量**: {len(state.paper_pool)}")
    report_lines.append(f"- **有效证据**: {len(state.evidence_set)}")
    report_lines.append(f"- **技术路线**: {len(clusters)}")
    report_lines.append("")
    
    # 路径决策详情
    report_lines.append("## 技术路线分析")
    report_lines.append("")
    
    for cluster in sorted_clusters:
        report_lines.extend(_format_cluster(cluster))
        report_lines.append("")
    
    # 推荐
    report_lines.append("## 最终推荐")
    report_lines.append("")
    
    if recommended:
        report_lines.append(f"🌟 **推荐路径**: {', '.join([c.cluster_id for c in recommended])}")
        top = recommended[0]
        report_lines.append(f"💡 **首选理由**: {top.mechanism_type} - {top.core_idea}")
        if top.advantages:
            report_lines.append(f"- 优势: {', '.join(top.advantages[:3])}")
    else:
        report_lines.append("⚠️ 暂无明确推荐路径，建议进一步调研。")
    
    report_lines.append("")
    
    if not_recommended:
        report_lines.append(f"❌ **不推荐路径**: {', '.join([c.cluster_id for c in not_recommended])}")
        for c in not_recommended:
            if c.limitations:
                report_lines.append(f"- {c.cluster_id}: {', '.join(c.limitations[:2])}")
    
    report_lines.append("")
    
    # 覆盖分析
    if evaluation:
        report_lines.append("## 覆盖分析")
        if evaluation.covered_variables:
            report_lines.append(f"✓ 已覆盖变量: {', '.join(evaluation.covered_variables)}")
        if evaluation.missing_variables:
            report_lines.append(f"⚠️ 未覆盖变量: {', '.join(evaluation.missing_variables)}")
        if evaluation.covered_metrics:
            report_lines.append(f"✓ 已覆盖指标: {', '.join(evaluation.covered_metrics)}")
        if evaluation.missing_metrics:
            report_lines.append(f"⚠️ 未覆盖指标: {', '.join(evaluation.missing_metrics)}")
    
    state.final_report = "\n".join(report_lines)
    
    logger.info("✅ 报告生成完成")
    return state


# ============================================================
# [P32] Chinese Reporting & Dynamic Filename
# ============================================================
import re
from datetime import datetime

# [P102] Helper for JSON serialization
def _serialize_value(obj: Any) -> Any:
    """Recursively serialize complex objects (Enum, Dataclass)"""
    if obj is None:
        return None
    if isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, (list, tuple)):
        return [_serialize_value(item) for item in obj]
    if isinstance(obj, set):
        return list(obj)
    if isinstance(obj, dict):
        return {k: _serialize_value(v) for k, v in obj.items()}
    if is_dataclass(obj) and not isinstance(obj, type):
        return {k: _serialize_value(v) for k, v in asdict(obj).items()}
    if hasattr(obj, 'to_dict'):
        return obj.to_dict()
    return str(obj)

def generate_report_filename(goal: str) -> str:
    """
    [P32] Generate a Chinese filename based on research goal.
    
    Example: 深度研究_碳硼烷探针_20260106.md
    """
    # Extract key terms, keep Chinese and alphanumeric
    safe_goal = re.sub(r'[^\w\u4e00-\u9fff]', '_', goal[:20]).strip('_')
    if not safe_goal:
        safe_goal = "研究报告"
    
    date_str = datetime.now().strftime("%Y%m%d")
    
    return f"深度研究_{safe_goal}_{date_str}.md"


def save_report_with_chinese_name(state: IterativeResearchState, output_dir) -> str:
    """
    [P32] Save report with dynamically generated Chinese filename.
    
    Returns: Absolute path to saved file
    """
    from pathlib import Path
    
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    goal = state.problem_spec.goal if state.problem_spec else ""
    filename = generate_report_filename(goal)
    
    file_path = output_path / filename
    
    if state.final_report:
        file_path.write_text(state.final_report, encoding='utf-8')
        logger.info(f"[P32] 📄 报告已保存: {file_path}")
        
    # [P102] Also save JSON report for /analyze command
    try:
        json_path = output_path / "report.json"
        state_dict = _serialize_value(state)
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(state_dict, f, ensure_ascii=False, indent=2)
        logger.info(f"[P102] 📊 JSON 报告已保存: {json_path}")
    except Exception as e:
        logger.error(f"[P102] Failed to save report.json: {e}")
    
    return str(file_path)


def _format_cluster(cluster: MethodCluster) -> list:
    """格式化单个技术路线簇"""
    lines = []
    
    score_emoji = "🌟" if cluster.overall_score >= 8 else "⭐" if cluster.overall_score >= 6 else "📌"
    
    lines.append(f"### {cluster.cluster_id}: {cluster.mechanism_type} {score_emoji} ({cluster.overall_score:.1f}/10)")
    lines.append(f"**核心思路**: {cluster.core_idea}")
    lines.append("")
    
    if cluster.typical_structures:
        lines.append(f"- **典型结构**: {', '.join(cluster.typical_structures)}")
    if cluster.target_applications:
        lines.append(f"- **目标应用**: {', '.join(cluster.target_applications)}")
    lines.append(f"- **文献支持**: {cluster.paper_count} 篇")
    
    if cluster.advantages:
        lines.append(f"- **优势**: {', '.join(cluster.advantages)}")
    if cluster.limitations:
        lines.append(f"- **局限**: {', '.join(cluster.limitations)}")
    
    lines.append(f"- **合成难度**: {cluster.synthetic_difficulty}")
    
    sat_label = "饱和" if cluster.novelty_saturation else "有创新空间"
    lines.append(f"- **创新空间**: {sat_label}")
    if cluster.innovation_angles:
        lines.append(f"  - 可能切入点: {', '.join(cluster.innovation_angles)}")
    
    return lines
