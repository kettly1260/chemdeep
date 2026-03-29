"""
Method Clustering Module
Implements Instruction 8: 方法归并逻辑
"""
import logging
from typing import List
from core.ai import AIClient
from .core_types import Evidence, MethodCluster, IterativeResearchState

logger = logging.getLogger('deep_research')

CLUSTERING_PROMPT = '''根据提取的证据，按"实现机理/技术路线"对方法进行归并分类。

提取的证据集合:
{evidence_text}

请分析并返回方法簇（JSON数组），每个簇代表一类技术路线:
[
  {{
    "cluster_id": "P1",
    "mechanism_type": "物理/化学机理名称 (如: ICT机制, AIE效应)",
    "core_idea": "一句话核心思路",
    "paper_count": 3,
    "representative_papers": ["DOI1", "DOI2"],
    "typical_structures": ["结构特征1", "结构特征2"],
    "target_applications": ["应用1", "应用2"],
    "advantages": ["优势1", "优势2"],
    "limitations": ["局限1", "局限2"],
    "synthetic_difficulty": "low/medium/high",
    "novelty_saturation": false,
    "innovation_angles": ["创新切入点1"],
    "overall_score": 8.5
  }}
]

要求:
1. 按机理/路线分类，不是按论文分
2. 相似机理的证据归入同一簇
3. 综合评分考虑: 文献支持度、性能表现、可行性、创新空间'''


def cluster_methods(evidence_list: List[Evidence]) -> List[MethodCluster]:
    """
    将 Evidence 列表归并为 MethodCluster 列表
    """
    if not evidence_list:
        return []
    
    logger.info(f"🔄 正在归并 {len(evidence_list)} 条证据为技术路线簇...")
    
    # 构建证据文本
    evidence_text = ""
    for i, ev in enumerate(evidence_list, 1):
        evidence_text += f"[{i}] {ev.paper_title}\n"
        evidence_text += f"   技术路线: {ev.implementation}\n"
        evidence_text += f"   方法类别: {ev.method_category}\n"
        evidence_text += f"   关键变量: {ev.key_variables}\n"
        evidence_text += f"   性能结果: {ev.performance_results}\n"
        evidence_text += f"   局限: {ev.limitations}\n\n"
    
    from core.ai import get_ai_client
    ai = get_ai_client()
    result = ai.call(CLUSTERING_PROMPT.format(evidence_text=evidence_text), json_mode=True)
    
    clusters = []
    if result.success and isinstance(result.data, list):
        for item in result.data:
            cluster = MethodCluster(
                cluster_id=item.get("cluster_id", f"P{len(clusters)+1}"),
                mechanism_type=item.get("mechanism_type", "Unknown"),
                core_idea=item.get("core_idea", ""),
                paper_count=item.get("paper_count", 0),
                representative_papers=item.get("representative_papers", []),
                typical_structures=item.get("typical_structures", []),
                target_applications=item.get("target_applications", []),
                advantages=item.get("advantages", []),
                limitations=item.get("limitations", []),
                synthetic_difficulty=item.get("synthetic_difficulty", "medium"),
                novelty_saturation=item.get("novelty_saturation", False),
                innovation_angles=item.get("innovation_angles", []),
                overall_score=item.get("overall_score", 0.0)
            )
            clusters.append(cluster)
        
        logger.info(f"✅ 归并为 {len(clusters)} 个技术路线簇")
        for c in clusters:
            logger.info(f"   {c.cluster_id}: {c.mechanism_type} (评分: {c.overall_score})")
    else:
        logger.warning("⚠️ 方法归并失败")
        # Fallback: 按 method_category 简单分组
        categories = {}
        for ev in evidence_list:
            cat = ev.method_category or "Other"
            if cat not in categories:
                categories[cat] = []
            categories[cat].append(ev)
        
        for i, (cat, evs) in enumerate(categories.items(), 1):
            clusters.append(MethodCluster(
                cluster_id=f"P{i}",
                mechanism_type=cat,
                core_idea=evs[0].implementation if evs else "",
                paper_count=len(evs),
                representative_papers=[e.paper_id for e in evs[:3]]
            ))
    
    return clusters


# State-based interface
def cluster(state: IterativeResearchState) -> IterativeResearchState:
    """
    State-based method clustering
    输入: state.evidence_set
    输出: state.method_clusters
    """
    state.method_clusters = cluster_methods(state.evidence_set)
    return state
