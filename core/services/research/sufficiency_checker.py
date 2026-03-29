"""
Evaluation and Sufficiency Check Module
Implements Instruction 10: 评估函数
Implements Instruction 11: 充分性判断模块

P3 更新: 质量过滤硬门槛 (数量 → 覆盖 → 多样性)
"""
import logging
from typing import List, Tuple, Set
from core.ai import AIClient
from .core_types import (
    ProblemSpec, Evidence, MethodCluster, 
    EvaluationResult, SufficiencyStatus, IterativeResearchState,
    Hypothesis, HypothesisStatus, ContentLevel, StudyType
)
from .evidence_quality import filter_high_quality_evidence, calculate_quality_weight

logger = logging.getLogger('deep_research')

# ============================================================
# 硬门槛常量 (Hard Thresholds)
# ============================================================
MIN_EVIDENCE_COUNT = 3              # 单个假设最少证据数
MIN_FULLTEXT_ORIGINAL_COUNT = 2     # 至少 2 篇全文原创研究
MIN_VARIABLE_COVERAGE = 0.6         # 变量覆盖率阈值
MIN_METHOD_DIVERSITY = 2            # 至少 2 种不同方法类别


def calculate_coverage(
    spec: ProblemSpec,
    evidence_list: List[Evidence],
    required_variables: List[str] = None
) -> Tuple[List[str], List[str], List[str], List[str]]:
    """
    计算变量和指标的覆盖情况
    """
    target_vars = required_variables if required_variables else spec.control_variables
    target_metrics = spec.performance_metrics
    
    covered_vars = set()
    covered_metrics = set()
    
    for ev in evidence_list:
        for var_name in ev.key_variables.keys():
            for tv in target_vars:
                if tv.lower() in var_name.lower() or var_name.lower() in tv.lower():
                    covered_vars.add(tv)
        
        for metric_name in ev.performance_results.keys():
            for tm in target_metrics:
                if tm.lower() in metric_name.lower() or metric_name.lower() in tm.lower():
                    covered_metrics.add(tm)
    
    missing_vars = [v for v in target_vars if v not in covered_vars]
    missing_metrics = [m for m in target_metrics if m not in covered_metrics]
    
    return list(covered_vars), missing_vars, list(covered_metrics), missing_metrics


def calculate_method_diversity(evidence_list: List[Evidence]) -> Set[str]:
    """
    计算方法多样性 (不同 method_category)
    """
    categories = set()
    for ev in evidence_list:
        if ev.method_category:
            # 归一化分类名称
            cat = ev.method_category.strip().lower()
            if cat:
                categories.add(cat)
    return categories


def evaluate_sufficiency(
    hypothesis: Hypothesis, 
    evidence_list: List[Evidence],
    spec: ProblemSpec
) -> EvaluationResult:
    """
    针对单个假设的充分性判断
    
    硬门槛顺序:
    1. 质量门槛: MIN_FULLTEXT_ORIGINAL_COUNT (全文原创研究数量)
    2. 数量门槛: MIN_EVIDENCE_COUNT (总证据数)
    3. 覆盖门槛: required_variables 覆盖率
    4. 多样性门槛: method_category 多样性
    
    quality_weight 仅用于排序，不参与门槛判断
    """
    # 如果假设已 Rejected
    if hypothesis.status == HypothesisStatus.REJECTED:
        return EvaluationResult(
            is_sufficient=False,
            status=SufficiencyStatus.INSUFFICIENT_QUANTITY,
            reason=f"假设已被证伪: {hypothesis.rejection_reason}"
        )

    # ============================================================
    # Step 1: 质量门槛 (INSUFFICIENT_QUALITY)
    # ============================================================
    high_quality_evidence = filter_high_quality_evidence(
        evidence_list,
        require_fulltext=True,
        require_original=True
    )
    
    fulltext_original_count = len(high_quality_evidence)
    
    if fulltext_original_count < MIN_FULLTEXT_ORIGINAL_COUNT:
        return EvaluationResult(
            is_sufficient=False,
            status=SufficiencyStatus.INSUFFICIENT_QUALITY,
            reason=f"全文原创研究不足 ({fulltext_original_count}/{MIN_FULLTEXT_ORIGINAL_COUNT})",
            total_evidence=len(evidence_list),
            suggested_expansions=[f"需补充 {hypothesis.hypothesis_id} 相关的全文原创研究"]
        )

    # ============================================================
    # Step 2: 数量门槛 (INSUFFICIENT_QUANTITY)
    # ============================================================
    total_relevant = hypothesis.supporting_evidence_count + hypothesis.conflicting_evidence_count
    
    # 如果假设计数未更新，使用证据列表长度
    if total_relevant == 0:
        total_relevant = len(evidence_list)
    
    if total_relevant < MIN_EVIDENCE_COUNT:
        return EvaluationResult(
            is_sufficient=False,
            status=SufficiencyStatus.INSUFFICIENT_QUANTITY,
            reason=f"相关证据不足 ({total_relevant}/{MIN_EVIDENCE_COUNT})",
            total_evidence=total_relevant,
            suggested_expansions=[f"增加针对机理 {hypothesis.mechanism_description[:30]}... 的验证检索"]
        )

    # ============================================================
    # Step 3: 覆盖门槛 (INSUFFICIENT_COVERAGE)
    # ============================================================
    covered_vars, missing_vars, covered_metrics, missing_metrics = calculate_coverage(
        spec, evidence_list, hypothesis.required_variables
    )
    
    if missing_vars:
        return EvaluationResult(
            is_sufficient=False,
            status=SufficiencyStatus.INSUFFICIENT_COVERAGE,
            reason=f"必需变量未覆盖: {', '.join(missing_vars)}",
            total_evidence=total_relevant,
            missing_variables=missing_vars,
            missing_metrics=missing_metrics,
            suggested_expansions=[f"检索 {v} (基于假设 {hypothesis.hypothesis_id})" for v in missing_vars]
        )

    # ============================================================
    # Step 4: 多样性门槛 (可选，作为警告)
    # ============================================================
    method_categories = calculate_method_diversity(evidence_list)
    
    suggestions = []
    if len(method_categories) < MIN_METHOD_DIVERSITY:
        suggestions.append(f"方法多样性不足 ({len(method_categories)}/{MIN_METHOD_DIVERSITY})，建议探索其他技术路线")

    # ============================================================
    # 充分性达成
    # ============================================================
    return EvaluationResult(
        is_sufficient=True,
        status=SufficiencyStatus.SUFFICIENT,
        reason="假设验证充分",
        total_evidence=total_relevant,
        missing_variables=[],
        missing_metrics=missing_metrics,
        suggested_expansions=suggestions
    )


def sort_evidence_by_quality(evidence_list: List[Evidence]) -> List[Evidence]:
    """
    按 quality_weight 降序排列证据 (仅用于排序/选种子)
    """
    return sorted(evidence_list, key=lambda e: e.quality_weight, reverse=True)


def evaluate(state: IterativeResearchState) -> IterativeResearchState:
    """
    State-based evaluation orchestrator
    """
    if state.problem_spec is None:
        raise ValueError("problem_spec must be set first")
    
    if not state.hypothesis_set:
        logger.warning("未找到假设集，跳过假设评估")
        return state

    active_hypotheses = state.hypothesis_set.get_active_hypotheses()
    
    if not active_hypotheses:
        logger.warning("⚠️ 所有假设均被证伪/冻结！")
        state.evaluation = EvaluationResult(
            is_sufficient=True,
            status=SufficiencyStatus.SUFFICIENT,
            reason="所有路径探索完毕（全部证伪）"
        )
        return state

    # 评估每个活跃假设
    all_sufficient = True
    combined_suggestions = []
    combined_missing_vars = []
    insufficient_reasons = []
    
    for h in active_hypotheses:
        res = evaluate_sufficiency(h, state.evidence_set, state.problem_spec)
        state.hypothesis_evaluations[h.hypothesis_id] = res
        
        if not res.is_sufficient:
            all_sufficient = False
            combined_suggestions.extend(res.suggested_expansions)
            combined_missing_vars.extend(res.missing_variables or [])
            insufficient_reasons.append(f"[{h.hypothesis_id}] {res.reason}")
        
        logger.info(f"   [{h.hypothesis_id}] status={h.status.value}, sufficient={res.is_sufficient}, reason={res.reason}")

    # 全局状态更新
    if all_sufficient:
        state.evaluation = EvaluationResult(
            is_sufficient=True,
            status=SufficiencyStatus.SUFFICIENT,
            reason="所有活跃假设均已充分验证"
        )
    else:
        # 确定最严重的不充分状态
        worst_status = SufficiencyStatus.INSUFFICIENT_COVERAGE
        for h_id, eval_res in state.hypothesis_evaluations.items():
            if eval_res.status == SufficiencyStatus.INSUFFICIENT_QUALITY:
                worst_status = SufficiencyStatus.INSUFFICIENT_QUALITY
                break
            elif eval_res.status == SufficiencyStatus.INSUFFICIENT_QUANTITY:
                worst_status = SufficiencyStatus.INSUFFICIENT_QUANTITY
        
        state.evaluation = EvaluationResult(
            is_sufficient=False,
            status=worst_status,
            reason="; ".join(insufficient_reasons),
            missing_variables=list(set(combined_missing_vars)),
            suggested_expansions=list(set(combined_suggestions))
        )

    return state
