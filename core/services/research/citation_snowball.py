"""
Citation Snowballing Module (P5)
引文回溯扩展搜索：基于高质量种子论文的 cited_by/references 扩展
"""
import logging
from typing import List, Dict, Set, Optional, Tuple
from dataclasses import dataclass, field

from .core_types import (
    Evidence, Hypothesis, HypothesisStatus, ProblemSpec,
    IterativeResearchState, SufficiencyStatus, ContentLevel, StudyType
)
from .evidence_quality import filter_high_quality_evidence

logger = logging.getLogger('deep_research')

# ============================================================
# 常量配置
# ============================================================
MAX_SEEDS_PER_HYPOTHESIS = 3        # 每个假设最多种子数
MAX_CITATIONS_PER_SEED = 20         # 每个种子最多引文数
MIN_QUALITY_WEIGHT_FOR_SEED = 0.7   # 种子最低质量权重


@dataclass
class SnowballCandidate:
    """引文回溯候选论文"""
    source: str                         # "cited_by" | "references"
    seed_evidence_id: str               # 种子 evidence_id
    seed_paper_key: str                 # 种子 paper_key
    
    # 候选论文元数据
    doi: str = ""
    paper_id: str = ""                  # OpenAlex ID
    title: str = ""
    year: Optional[int] = None
    abstract: str = ""
    
    # 过滤结果
    relevant_variables: List[str] = field(default_factory=list)
    is_relevant: bool = False


@dataclass
class SnowballResult:
    """引文回溯结果"""
    hypothesis_id: str
    seeds_used: List[str]              # 使用的种子 evidence_id
    candidates_found: int
    candidates_filtered: int
    relevant_candidates: List[SnowballCandidate] = field(default_factory=list)


def should_trigger_snowball(state: IterativeResearchState) -> Tuple[bool, List[str]]:
    """
    判断是否应该触发引文回溯
    
    触发条件:
    1. 存在 Active 假设
    2. 充分性评估 != SUFFICIENT
    
    Returns:
        (should_trigger, list_of_hypothesis_ids_to_expand)
    """
    if not state.hypothesis_set:
        return False, []
    
    active_hypotheses = state.hypothesis_set.get_active_hypotheses()
    if not active_hypotheses:
        return False, []
    
    # 检查整体充分性
    if state.evaluation and state.evaluation.is_sufficient:
        return False, []
    
    # 返回需要扩展的假设 ID
    hypothesis_ids = [h.hypothesis_id for h in active_hypotheses]
    return True, hypothesis_ids


def select_seeds(
    evidence_list: List[Evidence],
    hypothesis: Hypothesis,
    max_seeds: int = MAX_SEEDS_PER_HYPOTHESIS
) -> List[Evidence]:
    """
    选择种子论文
    
    优先: FULL_TEXT + ORIGINAL + high quality_weight
    """
    # 过滤高质量证据
    high_quality = filter_high_quality_evidence(
        evidence_list,
        require_fulltext=True,
        require_original=True
    )
    
    # 进一步筛选质量权重
    qualified = [
        ev for ev in high_quality 
        if ev.quality_weight >= MIN_QUALITY_WEIGHT_FOR_SEED
    ]
    
    # 按 quality_weight 降序排列
    qualified.sort(key=lambda e: e.quality_weight, reverse=True)
    
    # 返回前 N 个
    return qualified[:max_seeds]


def filter_by_relevance(
    candidates: List[SnowballCandidate],
    required_variables: List[str]
) -> List[SnowballCandidate]:
    """
    过滤候选论文：只保留 title/abstract 命中 required_variables 的
    
    注意: 不扩张无关变量
    """
    if not required_variables:
        return candidates
    
    relevant = []
    for candidate in candidates:
        text = (candidate.title + " " + candidate.abstract).lower()
        
        matched_vars = []
        for var in required_variables:
            # 处理下划线和空格的变体匹配
            var_lower = var.lower()
            var_with_space = var_lower.replace("_", " ")
            var_with_underscore = var_lower.replace(" ", "_")
            
            # 任一变体匹配即可
            if var_lower in text or var_with_space in text or var_with_underscore in text:
                matched_vars.append(var)
        
        if matched_vars:
            candidate.relevant_variables = matched_vars
            candidate.is_relevant = True
            relevant.append(candidate)
    
    return relevant


def fetch_citations_metadata(
    seed: Evidence,
    source_type: str = "both"
) -> List[SnowballCandidate]:
    """
    获取引文元数据 (cited_by / references)
    
    使用 citation_providers 模块 (OpenAlex 优先 + Crossref 兜底)
    """
    from .citation_providers import fetch_citations, PaperCandidate
    
    # 获取种子的 paper_key
    paper_key = seed.independence_key
    if not paper_key:
        from .conflict_adjudicator import get_independence_key
        paper_key = get_independence_key(seed)
    
    logger.info(f"📚 获取引文: {seed.evidence_id} ({source_type}) -> {paper_key}")
    
    # 调用 provider
    paper_candidates = fetch_citations(paper_key, relation=source_type, max_results=MAX_CITATIONS_PER_SEED)
    
    # 转换为 SnowballCandidate
    candidates = []
    for pc in paper_candidates:
        candidates.append(SnowballCandidate(
            source=pc.relation,
            seed_evidence_id=seed.evidence_id,
            seed_paper_key=paper_key,
            doi=pc.doi,
            paper_id=pc.openalex_id,
            title=pc.title,
            year=pc.year,
            abstract=pc.abstract
        ))
    
    return candidates


def expand_via_snowball(
    state: IterativeResearchState,
    hypothesis_ids: List[str] = None
) -> List[SnowballResult]:
    """
    执行引文回溯扩展
    
    支持断点续跑：跳过已处理的种子
    
    Returns:
        各假设的扩展结果
    """
    results = []
    
    if not state.hypothesis_set:
        return results
    
    # 确定要扩展的假设
    if hypothesis_ids is None:
        _, hypothesis_ids = should_trigger_snowball(state)
    
    if not hypothesis_ids:
        logger.info("📚 无假设需要引文回溯扩展")
        return results
    
    # 获取已处理的种子集合
    processed_seeds = set(state.snowball_seeds_processed)
    
    for h_id in hypothesis_ids:
        hypothesis = state.hypothesis_set.get_hypothesis(h_id)
        if not hypothesis:
            continue
        
        logger.info(f"📚 正在为假设 {h_id} 执行引文回溯...")
        
        # 1. 选择种子
        seeds = select_seeds(state.evidence_set, hypothesis)
        if not seeds:
            logger.warning(f"   无高质量种子可用")
            continue
        
        # 2. 过滤已处理的种子 (断点续跑)
        new_seeds = [s for s in seeds if s.evidence_id not in processed_seeds]
        skipped = len(seeds) - len(new_seeds)
        if skipped > 0:
            logger.info(f"   跳过已处理种子: {skipped}")
        
        if not new_seeds:
            logger.info(f"   所有种子已处理，跳过")
            continue
        
        logger.info(f"   新种子数: {len(new_seeds)}")
        
        # 3. 获取引文
        all_candidates = []
        for seed in new_seeds:
            candidates = fetch_citations_metadata(seed, source_type="both")
            all_candidates.extend(candidates)
            
            # 标记为已处理
            state.snowball_seeds_processed.append(seed.evidence_id)
        
        # 4. 过滤相关候选
        relevant = filter_by_relevance(all_candidates, hypothesis.required_variables)
        
        result = SnowballResult(
            hypothesis_id=h_id,
            seeds_used=[s.evidence_id for s in new_seeds],
            candidates_found=len(all_candidates),
            candidates_filtered=len(relevant),
            relevant_candidates=relevant
        )
        results.append(result)
        
        logger.info(f"   候选: {len(all_candidates)} -> 相关: {len(relevant)}")
    
    return results


def snowball(state: IterativeResearchState) -> IterativeResearchState:
    """
    State-based 引文回溯入口
    """
    should_expand, hypothesis_ids = should_trigger_snowball(state)
    
    if not should_expand:
        logger.info("📚 引文回溯: 条件未满足，跳过")
        return state
    
    results = expand_via_snowball(state, hypothesis_ids)
    
    # TODO: 将相关候选添加到 paper_pool 供后续处理
    for result in results:
        for candidate in result.relevant_candidates:
            # 转换为 paper dict 格式
            paper = {
                "doi": candidate.doi,
                "id": candidate.paper_id,
                "title": candidate.title,
                "year": candidate.year,
                "abstract": candidate.abstract,
                "_source": "snowball",
                "_seed": candidate.seed_evidence_id
            }
            state.paper_pool.append(paper)
    
    return state
