"""
证据冲突仲裁模块 (Conflict Adjudicator)
负责审核证伪请求，防止单证据误杀
"""
import logging
import hashlib
from typing import List, Tuple, Dict, Any
from datetime import datetime

from .core_types import Evidence, Hypothesis
from .audit_types import DecisionRecord, DecisionType
from .audit_logger import AuditLogger

logger = logging.getLogger('deep_research')


def get_independence_key(evidence: Evidence) -> str:
    """
    生成证据的独立来源主键，用于判定是否为"不同来源"。
    降级策略: doi > paper_id > source_url > hash(title+year+first_author)
    
    注意: DOI 必须来自 evidence.doi 字段，不得推断
    """
    # 优先级 1: DOI (最可靠)
    if evidence.doi:
        return f"doi:{evidence.doi}"
    
    # 优先级 2: paper_id (OpenAlex ID 或其他平台 ID)
    if evidence.paper_id:
        return f"id:{evidence.paper_id}"
    
    # 优先级 3: source_url
    if evidence.source_url:
        return f"url:{evidence.source_url}"
    
    # 优先级 4: 内容哈希兜底
    content = f"{evidence.paper_title}|{evidence.paper_year or 'unknown'}|{evidence.first_author or 'unknown'}"
    hash_val = hashlib.md5(content.encode()).hexdigest()[:12]
    return f"hash:{hash_val}"


def adjudicate_falsification(
    hypothesis: Hypothesis, 
    refuting_indices: List[int], 
    evidence_batch: List[Evidence],
    triggered_condition: str = "",
    iteration: int = 0
) -> Tuple[bool, str, List[str], List[str]]:
    """
    仲裁证伪请求
    
    Args:
        hypothesis: 待评估假设
        refuting_indices: LLM 标记为反驳的证据索引 (1-based)
        evidence_batch: 提交给 LLM 的证据列表
        triggered_condition: 触发的证伪条件
        iteration: 当前迭代轮次
        
    Returns:
        (is_confirmed_rejected, reason, evidence_ids, paper_keys)
    """
    if not refuting_indices:
        return False, "无反驳证据索引", [], []

    # 1. 映射索引到证据对象
    refuting_evidences = []
    for idx in refuting_indices:
        real_idx = idx - 1
        if 0 <= real_idx < len(evidence_batch):
            refuting_evidences.append(evidence_batch[real_idx])
            
    if not refuting_evidences:
        return False, "索引越界或无效", [], []

    # 2. 收集 evidence_ids 和 independence_keys
    evidence_ids = []
    paper_keys = set()
    normalized_summary: Dict[str, Any] = {}
    
    for ev in refuting_evidences:
        # 确保 evidence_id 存在
        if ev.evidence_id:
            evidence_ids.append(ev.evidence_id)
        
        # 计算或使用已有的 independence_key
        key = ev.independence_key if ev.independence_key else get_independence_key(ev)
        paper_keys.add(key)
        
        # 收集归一化数据摘要
        if ev.normalized_values:
            for k, v in ev.normalized_values.items():
                normalized_summary[f"{ev.evidence_id or 'unknown'}:{k}"] = v
    
    paper_keys_list = list(paper_keys)
    unique_sources = len(paper_keys_list)
    
    # 3. 执行仲裁规则: 必须 >= 2 篇独立来源
    if unique_sources < 2:
        reason = f"证伪证据单一 (仅来自 {unique_sources} 个独立来源)"
        logger.warning(f"⚖️ 仲裁驳回: 假设 {hypothesis.hypothesis_id} - {reason}")
        
        # 记录 DISPUTED 决策
        record = DecisionRecord(
            timestamp=datetime.now().isoformat(),
            decision_type=DecisionType.ADJUDICATION_DISPUTED,
            hypothesis_id=hypothesis.hypothesis_id,
            triggered_falsifiable_condition=triggered_condition,
            evidence_ids=evidence_ids,
            paper_keys=paper_keys_list,
            normalized_values_summary=normalized_summary,
            adjudicator_result="DISPUTED",
            adjudicator_reason=reason,
            iteration=iteration,
            total_evidence_count=len(evidence_batch)
        )
        AuditLogger.log_decision(record)
        
        return False, reason, evidence_ids, paper_keys_list
    
    # 4. 仲裁通过
    confirm_msg = f"经 {unique_sources} 个独立来源 ({', '.join(paper_keys_list[:3])}...) 交叉验证确认证伪"
    logger.info(f"⚖️ 仲裁通过: 假设 {hypothesis.hypothesis_id} -> REJECTED")
    
    # 记录 REJECTED 决策
    record = DecisionRecord(
        timestamp=datetime.now().isoformat(),
        decision_type=DecisionType.HYPOTHESIS_REJECTED,
        hypothesis_id=hypothesis.hypothesis_id,
        triggered_falsifiable_condition=triggered_condition,
        evidence_ids=evidence_ids,
        paper_keys=paper_keys_list,
        normalized_values_summary=normalized_summary,
        adjudicator_result="CONFIRMED",
        adjudicator_reason=confirm_msg,
        iteration=iteration,
        total_evidence_count=len(evidence_batch)
    )
    AuditLogger.log_decision(record)
    
    return True, confirm_msg, evidence_ids, paper_keys_list
