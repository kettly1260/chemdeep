"""
Core Data Structures for Iterative Research System
Implements Instructions 1, 3, 5, 7, 9
"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional, Set
from enum import Enum


# P24: 任务取消异常
class JobCancelledError(Exception):
    """Raised when a job is cancelled by user request."""

    pass


# ============================================================
# 指令 1: 科研问题形式化对象 (ProblemSpec)
# ============================================================
@dataclass
class ProblemSpec:
    """
    形式化的科研问题规格
    将用户的一句话目标拆解为可检索的变量空间
    """

    goal: str  # 原始用户目标
    research_object: str = ""  # 研究对象 (如: 邻-碳硼烷荧光探针)
    control_variables: List[str] = field(default_factory=list)  # 可调控变量
    performance_metrics: List[str] = field(default_factory=list)  # 性能指标
    constraints: List[str] = field(default_factory=list)  # 现实约束
    domain: Optional[str] = None  # 研究领域 (如: 有机光电材料)
    refinement_context: Optional[str] = None  # [P54] 之前的研究上下文 (用于深化)

    def to_dict(self) -> dict:
        return {
            "goal": self.goal,
            "research_object": self.research_object,
            "control_variables": self.control_variables,
            "performance_metrics": self.performance_metrics,
            "constraints": self.constraints,
            "domain": self.domain,
            "refinement_context": self.refinement_context,
        }

    @classmethod
    def from_dict(cls, data: dict):
        return cls(
            goal=data.get("goal", ""),
            research_object=data.get("research_object", ""),
            control_variables=data.get("control_variables", []),
            performance_metrics=data.get("performance_metrics", []),
            constraints=data.get("constraints", []),
            domain=data.get("domain"),
            refinement_context=data.get("refinement_context"),
        )


# ============================================================
# 指令 3: 检索查询空间 (SearchQuerySet)
# ============================================================
@dataclass
class SearchQuery:
    """单个检索查询"""

    keywords: str
    source: str = "openalex"  # openalex, crossref, wos, scholar, lanfanshu
    variable_focus: Optional[str] = None  # 该查询针对哪个变量
    metric_focus: Optional[str] = None  # 该查询针对哪个性能指标
    bucket: str = "Broad"  # 查询桶: Broad / Specific / Methodological
    priority: int = 1  # 优先级 (1=高, 2=中, 3=低)
    executed: bool = False  # 是否已执行


@dataclass
class SearchQuerySet:
    """
    可扩展的检索空间
    按 "变量 × 性能" 组织查询
    """

    queries: List[SearchQuery] = field(default_factory=list)
    executed_keywords: Set[str] = field(default_factory=set)  # 已执行的关键词去重
    iteration: int = 0
    max_iterations: int = 3

    def add_query(self, query: SearchQuery) -> bool:
        """添加查询，自动去重"""
        key = f"{query.keywords}:{query.source}"
        if key not in self.executed_keywords:
            self.queries.append(query)
            return True
        return False

    def get_pending_queries(self) -> List[SearchQuery]:
        """获取未执行的查询"""
        return [q for q in self.queries if not q.executed]

    def mark_executed(self, query: SearchQuery):
        """标记查询为已执行"""
        query.executed = True
        self.executed_keywords.add(f"{query.keywords}:{query.source}")

    @classmethod
    def from_dict(cls, data: dict):
        instance = cls(
            executed_keywords=set(data.get("executed_keywords", [])),
            iteration=data.get("iteration", 0),
            max_iterations=data.get("max_iterations", 3),
        )
        for q_data in data.get("queries", []):
            instance.queries.append(SearchQuery(**q_data))
        return instance


# ============================================================
# 指令 5: Evidence 结构
# ============================================================
class ContentLevel(Enum):
    """证据内容深度"""

    FULL_TEXT = "full_text"
    ABSTRACT_ONLY = "abstract"
    TITLE_ONLY = "title"


class StudyType(Enum):
    """研究类型"""

    ORIGINAL = "original"  # 原创研究
    REVIEW = "review"  # 综述
    META_ANALYSIS = "meta"  # 荟萃分析
    COMMENTARY = "commentary"  # 评论
    UNKNOWN = "unknown"


@dataclass
class Evidence:
    """
    从单篇文献提取的结构化证据
    """

    # 主键与来源标识
    evidence_id: str = ""  # 证据条目唯一 ID (UUID)
    paper_id: str = ""  # OpenAlex ID 或其他平台 ID
    doi: str = ""  # DOI (独立字段，用于降级策略)
    paper_title: str = ""
    paper_year: Optional[int] = None
    source_url: str = ""  # 原文 URL
    first_author: str = ""  # 第一作者 (用于哈希兜底)

    # 核心证据字段
    implementation: str = ""  # 实现手段/技术路线
    key_variables: Dict[str, str] = field(default_factory=dict)
    performance_results: Dict[str, str] = field(default_factory=dict)
    limitations: List[str] = field(default_factory=list)
    method_category: str = ""
    category: str = "direct_data"  # [P87] direct_data, methodology, analogy_insight

    # 元信息
    confidence: float = 0.0
    source_type: str = "abstract"  # 兼容旧字段

    # 归一化数据
    normalized_values: Dict[str, float] = field(default_factory=dict)
    unit_map: Dict[str, str] = field(default_factory=dict)

    # 质量分层 (P1)
    content_level: ContentLevel = ContentLevel.ABSTRACT_ONLY
    study_type: StudyType = StudyType.UNKNOWN
    independence_key: str = ""  # 由 get_independence_key() 生成
    quality_weight: float = 1.0  # 用于排序，不替代硬约束
    falsifiable_allowed: bool = (
        False  # 是否允许用于证伪判定 (仅 normalized_values 非空时为 True)
    )

    def to_dict(self) -> dict:
        return {
            "evidence_id": self.evidence_id,
            "paper_id": self.paper_id,
            "doi": self.doi,
            "paper_title": self.paper_title,
            "paper_year": self.paper_year,
            "source_url": self.source_url,
            "first_author": self.first_author,
            "implementation": self.implementation,
            "key_variables": self.key_variables,
            "performance_results": self.performance_results,
            "limitations": self.limitations,
            "method_category": self.method_category,
            "category": self.category,
            "confidence": self.confidence,
            "source_type": self.source_type,
            "normalized_values": self.normalized_values,
            "unit_map": self.unit_map,
            "content_level": self.content_level.value,
            "study_type": self.study_type.value,
            "independence_key": self.independence_key,
            "quality_weight": self.quality_weight,
            "falsifiable_allowed": self.falsifiable_allowed,
        }


# ============================================================
# 指令 7: MethodCluster 定义
# ============================================================
@dataclass
class MethodCluster:
    """
    方法归并后的技术路线簇
    """

    cluster_id: str  # 如 P1, P2
    mechanism_type: str  # 物理/化学机理 (如 ICT, AIE, FRET)
    core_idea: str  # 一句话核心思路

    # 聚合信息
    paper_count: int = 0
    representative_papers: List[str] = field(default_factory=list)  # DOI 列表
    typical_structures: List[str] = field(default_factory=list)
    target_applications: List[str] = field(default_factory=list)

    # 评估维度
    advantages: List[str] = field(default_factory=list)
    limitations: List[str] = field(default_factory=list)
    synthetic_difficulty: str = "medium"  # low / medium / high
    novelty_saturation: bool = False  # 是否已饱和
    innovation_angles: List[str] = field(default_factory=list)

    # 综合评分
    overall_score: float = 0.0  # 0-10


# ============================================================
# 指令 9: 评估结果定义
# ============================================================
class SufficiencyStatus(Enum):
    SUFFICIENT = "sufficient"
    INSUFFICIENT_QUANTITY = "insufficient_quantity"
    INSUFFICIENT_QUALITY = "insufficient_quality"  # 全文原创研究不足
    INSUFFICIENT_DIVERSITY = "insufficient_diversity"
    INSUFFICIENT_COVERAGE = "insufficient_coverage"


@dataclass
class EvaluationResult:
    """
    研究充分性评估结果
    """

    is_sufficient: bool
    status: SufficiencyStatus
    reason: str

    # 详细指标
    total_papers: int = 0
    total_evidence: int = 0
    cluster_count: int = 0
    covered_variables: List[str] = field(default_factory=list)
    missing_variables: List[str] = field(default_factory=list)
    covered_metrics: List[str] = field(default_factory=list)
    missing_metrics: List[str] = field(default_factory=list)

    # 扩展建议
    suggested_expansions: List[str] = field(default_factory=list)


# ============================================================
# 新增: 机理假设层 (Hypothesis Layer)
# ============================================================
class HypothesisStatus(Enum):
    ACTIVE = "active"
    REJECTED = "rejected"
    FROZEN = "frozen"


@dataclass
class Hypothesis:
    """
    机理假设: 解释因果关系的可证伪假设
    """

    hypothesis_id: str  # 假设ID (H1, H2...)
    mechanism_description: str  # 核心机理描述
    required_variables: List[str]  # 该机理下必需的变量
    irrelevant_variables: List[str]  # 该机理下可忽略的变量
    falsifiable_conditions: List[str]  # 证伪条件
    expected_performance_trend: str  # 预期性能趋势 (如: 随X增加先升后降)

    # 状态字段
    status: HypothesisStatus = HypothesisStatus.ACTIVE
    rejection_reason: str = ""
    supporting_evidence_count: int = 0
    conflicting_evidence_count: int = 0

    def to_dict(self) -> dict:
        return {
            "hypothesis_id": self.hypothesis_id,
            "mechanism_description": self.mechanism_description,
            "required_variables": self.required_variables,
            "irrelevant_variables": self.irrelevant_variables,
            "falsifiable_conditions": self.falsifiable_conditions,
            "expected_performance_trend": self.expected_performance_trend,
            "status": self.status.value,
            "rejection_reason": self.rejection_reason,
        }


@dataclass
class HypothesisSet:
    """
    机理假设集合
    """

    hypotheses: List[Hypothesis] = field(default_factory=list)
    selected_hypothesis_ids: List[str] = field(
        default_factory=list
    )  # 选定用于验证的假设

    def get_active_hypotheses(self) -> List[Hypothesis]:
        return [h for h in self.hypotheses if h.status == HypothesisStatus.ACTIVE]

    def get_hypothesis(self, hypothesis_id: str) -> Optional[Hypothesis]:
        """根据 ID 获取假设"""
        for h in self.hypotheses:
            if h.hypothesis_id == hypothesis_id:
                return h
        return None

    @classmethod
    def from_dict(cls, data: dict):
        instance = cls(selected_hypothesis_ids=data.get("selected_hypothesis_ids", []))
        for h_data in data.get("hypotheses", []):
            # Convert status string back to Enum
            if "status" in h_data:
                try:
                    h_data["status"] = HypothesisStatus(h_data["status"])
                except:
                    # Fallback or keep raw string if model mismatch
                    # Ideally default to ACTIVE or remove
                    if h_data["status"] in ["active", "rejected", "frozen"]:
                        h_data["status"] = HypothesisStatus(h_data["status"])
                    else:
                        del h_data["status"]
            instance.hypotheses.append(Hypothesis(**h_data))
        return instance


# ============================================================
# 完整研究状态 (替代旧 ResearchState)
# ============================================================
@dataclass
class IterativeResearchState:
    """
    迭代研究流程的完整状态容器
    """

    # [P45] P45 Job ID
    job_id: str = ""

    # 输入
    problem_spec: Optional[ProblemSpec] = None

    # 机理假设层 (New)
    hypothesis_set: Optional[HypothesisSet] = None

    # 检索空间
    query_set: SearchQuerySet = field(default_factory=SearchQuerySet)

    # 数据池
    paper_pool: List[Dict] = field(default_factory=list)  # 原始论文
    evidence_set: List[Evidence] = field(default_factory=list)  # 提取的证据
    method_clusters: List[MethodCluster] = field(default_factory=list)

    # 评估
    evaluation: Optional[EvaluationResult] = None
    hypothesis_evaluations: Dict[str, EvaluationResult] = field(
        default_factory=dict
    )  # 按假设的评估结果

    # 输出
    final_report: Optional[str] = None
    final_report_path: Optional[str] = None
    recommended_paths: List[str] = field(default_factory=list)
    not_recommended_paths: List[str] = field(default_factory=list)
    score_summary: str = ""

    # 迭代控制
    iteration: int = 0
    max_iterations: int = 3
    min_year: Optional[int] = None
    min_score: float = 0.0
    last_search_stats: List[Dict] = field(default_factory=list)

    # 断点续跑 (P7)
    snowball_seeds_processed: List[str] = field(
        default_factory=list
    )  # 已处理的种子 evidence_id

    # 任务取消标记 (P14)
    cancelled: bool = False

    # [P61] Incremental Knowledge Base
    learnings: List[str] = field(default_factory=list)  # 已确认的知识点 (中文短句)
    query_history: List[str] = field(default_factory=list)  # 已执行过的所有查询字符串

    @classmethod
    def from_dict(cls, data: dict):
        spec = (
            ProblemSpec.from_dict(data["problem_spec"])
            if data.get("problem_spec")
            else None
        )

        # Restore HypothesisSet
        h_set = None
        if data.get("hypothesis_set"):
            h_set = HypothesisSet.from_dict(data["hypothesis_set"])

        # Restore QuerySet
        q_set = SearchQuerySet.from_dict(data.get("query_set", {}))

        state = cls(
            job_id=data.get("job_id", ""),
            problem_spec=spec,
            hypothesis_set=h_set,
            query_set=q_set,
            iteration=data.get("iteration", 0),
            max_iterations=data.get("max_iterations", 3),
            min_year=data.get("min_year"),
            min_score=data.get("min_score", 0.0),
            final_report_path=data.get("final_report_path"),
            score_summary=data.get("score_summary", ""),
            last_search_stats=data.get("last_search_stats", []),
            paper_pool=data.get("paper_pool", []),  # Shallow copy of dicts
            # Evidence restoration if complex logic needed, otherwise default handling?
            # Currently evidence_set is List[Evidence]. We need to reconstruct Evidence objects.
            # Assuming Evidence has default init that matches dict or we map it.
            # For now, let's skip deep evidence restoration if Evidence.from_dict missing,
            # BUT this might break evidence.
            # Wait, Evidence is a dataclass.
            snowball_seeds_processed=data.get("snowball_seeds_processed", []),
            cancelled=data.get("cancelled", False),
            learnings=data.get("learnings", []),
            query_history=data.get("query_history", []),
        )

        # Restore Evidence objects
        if data.get("evidence_set"):
            for ev_data in data["evidence_set"]:
                # Manual reconstruction or need Evidence.from_dict
                # Let's do a simple reconstruction assuming fields match
                try:
                    # Handle Enums
                    if "content_level" in ev_data:
                        try:
                            ev_data["content_level"] = ContentLevel(
                                ev_data["content_level"]
                            )
                        except:
                            del ev_data["content_level"]
                    if "study_type" in ev_data:
                        try:
                            ev_data["study_type"] = StudyType(ev_data["study_type"])
                        except:
                            del ev_data["study_type"]

                    state.evidence_set.append(Evidence(**ev_data))
                except Exception as e:
                    # Log or ignore
                    pass

        return state
