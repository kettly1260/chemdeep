"""
证据质量分层模块 (Evidence Quality Layer)
计算证据质量权重，用于排序和种子选取（不用于替代硬约束）
"""
import logging
import uuid
from typing import List
from .core_types import Evidence, ContentLevel, StudyType
from .conflict_adjudicator import get_independence_key

logger = logging.getLogger('deep_research')


def calculate_quality_weight(evidence: Evidence) -> float:
    """
    计算证据质量权重 (0.0 - 1.0)
    注意: 此权重仅用于排序/选种子，不得替代硬约束
    """
    weight = 1.0
    
    # 内容深度
    if evidence.content_level == ContentLevel.ABSTRACT_ONLY:
        weight *= 0.3
    elif evidence.content_level == ContentLevel.TITLE_ONLY:
        weight *= 0.0
    
    # 研究类型
    if evidence.study_type == StudyType.REVIEW:
        weight *= 0.5
    elif evidence.study_type == StudyType.COMMENTARY:
        weight *= 0.2
    elif evidence.study_type == StudyType.META_ANALYSIS:
        weight *= 0.7  # 荟萃分析有一定价值但仍是二手
    
    # 数据完整性
    if not evidence.normalized_values:
        weight *= 0.7
    
    return round(weight, 2)


def enrich_evidence(evidence: Evidence) -> Evidence:
    """
    填充证据的质量相关字段
    - evidence_id (如果为空)
    - independence_key
    - quality_weight
    """
    # 生成 evidence_id (如果不存在)
    if not evidence.evidence_id:
        evidence.evidence_id = str(uuid.uuid4())[:8]
    
    # 计算 independence_key
    if not evidence.independence_key:
        evidence.independence_key = get_independence_key(evidence)
    
    # 计算 quality_weight
    evidence.quality_weight = calculate_quality_weight(evidence)
    
    return evidence


def enrich_evidence_set(evidence_list: List[Evidence]) -> List[Evidence]:
    """
    批量填充证据质量字段
    """
    count = 0
    for ev in evidence_list:
        if not ev.independence_key:
            enrich_evidence(ev)
            count += 1
    
    if count > 0:
        logger.info(f"🏷️ 已为 {count} 条证据填充质量字段")
    
    return evidence_list


def filter_high_quality_evidence(
    evidence_list: List[Evidence],
    require_fulltext: bool = True,
    require_original: bool = True
) -> List[Evidence]:
    """
    过滤高质量证据用于充分性判断
    
    Args:
        evidence_list: 完整证据列表
        require_fulltext: 是否排除仅摘要
        require_original: 是否仅保留原创研究
    
    Returns:
        过滤后的证据列表
    """
    filtered = []
    for ev in evidence_list:
        # 排除仅摘要
        if require_fulltext and ev.content_level == ContentLevel.ABSTRACT_ONLY:
            continue
        
        # 仅保留原创研究
        if require_original and ev.study_type != StudyType.ORIGINAL:
            if ev.study_type != StudyType.UNKNOWN:  # UNKNOWN 暂时放过
                continue
        
        filtered.append(ev)
    
    return filtered
