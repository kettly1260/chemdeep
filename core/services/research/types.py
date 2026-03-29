"""
Research data types
"""
from dataclasses import dataclass, field

@dataclass
class ResearchPlan:
    """研究计划"""
    question: str                           # 用户原始问题
    objectives: list[str] = field(default_factory=list)  # 研究目标
    search_queries: list[dict] = field(default_factory=list)  # 搜索查询
    analysis_focus: str = "general"         # 分析重点
    key_aspects: list[str] = field(default_factory=list)  # 关键方面
    criteria: dict = field(default_factory=dict) # 筛选标准 (Must/Plus/Exclude)
    
    def to_dict(self) -> dict:
        return {
            "question": self.question,
            "objectives": self.objectives,
            "search_queries": self.search_queries,
            "analysis_focus": self.analysis_focus,
            "key_aspects": self.key_aspects,
            "criteria": self.criteria
        }
    
    @staticmethod
    def from_dict(data: dict) -> "ResearchPlan":
        return ResearchPlan(
            question=data.get("question", ""),
            objectives=data.get("objectives", []),
            search_queries=data.get("search_queries", []),
            analysis_focus=data.get("analysis_focus", "general"),
            key_aspects=data.get("key_aspects", []),
            criteria=data.get("criteria", {})
        )


@dataclass
class DecomposedGoal:
    """拆解后的研究目标"""
    research_object: str = ""               # 研究对象
    control_variables: list[str] = field(default_factory=list)    # 可调控变量
    performance_metrics: list[str] = field(default_factory=list)  # 性能指标
    constraints: list[str] = field(default_factory=list)          # 现实约束
    
    def to_dict(self) -> dict:
        return {
            "research_object": self.research_object,
            "control_variables": self.control_variables,
            "performance_metrics": self.performance_metrics,
            "constraints": self.constraints
        }
    
    @staticmethod
    def from_dict(data: dict) -> "DecomposedGoal":
        return DecomposedGoal(
            research_object=data.get("research_object", ""),
            control_variables=data.get("control_variables", []),
            performance_metrics=data.get("performance_metrics", []),
            constraints=data.get("constraints", [])
        )

# --- Phase A-1: New Strict Data Models ---
from typing import List, Dict, Optional

@dataclass(frozen=True)
class ResearchQuestion:
    """[New] 纯粹的用户问题"""
    question: str
    domain: Optional[str] = None
    intent: Optional[str] = None

@dataclass
class ResearchPlanV2:
    """[New] 纯粹的研究方案 (rename to avoid conflict for now)"""
    objectives: List[str]
    key_aspects: List[str]
    criteria: Dict[str, List[str]]
    analysis_focus: str
    # Keep search_queries compatibility or move it? 
    # Plan usually includes queries. Let's add it back if needed by planner.
    search_queries: List[Dict] = field(default_factory=list) 

@dataclass
class ResearchState:
    """[New] 全局执行状态容器"""
    question: ResearchQuestion
    plan: Optional[ResearchPlanV2] = None
    evidence: List[Dict] = field(default_factory=list)
    intermediate_results: Dict = field(default_factory=dict) # e.g. screening scope
    final_report: Optional[str] = None
    
    # Store dynamic workflow data
    paper_pool: List[Dict] = field(default_factory=list) # Fetched papers
