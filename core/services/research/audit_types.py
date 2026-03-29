"""
审计类型定义 (Audit Types)
用于记录关键决策的审计日志
"""
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from datetime import datetime
from enum import Enum
import json


class DecisionType(Enum):
    """决策类型"""
    HYPOTHESIS_REJECTED = "hypothesis_rejected"
    HYPOTHESIS_FROZEN = "hypothesis_frozen"
    HYPOTHESIS_ACTIVATED = "hypothesis_activated"
    ADJUDICATION_DISPUTED = "adjudication_disputed"
    SUFFICIENCY_REACHED = "sufficiency_reached"


@dataclass
class DecisionRecord:
    """
    单条决策审计记录
    """
    timestamp: str                              # ISO 8601
    decision_type: DecisionType
    hypothesis_id: str
    
    # 触发条件
    triggered_falsifiable_condition: str = ""
    
    # 证据链追溯
    evidence_ids: List[str] = field(default_factory=list)      # 证据条目自身的 evidence_id
    paper_keys: List[str] = field(default_factory=list)        # 论文级 independence_key
    
    # 归一化数据摘要
    normalized_values_summary: Dict[str, Any] = field(default_factory=dict)
    
    # 仲裁结果
    adjudicator_result: str = ""   # "CONFIRMED" / "DISPUTED" / "DISMISSED"
    adjudicator_reason: str = ""
    
    # 元信息
    iteration: int = 0
    total_evidence_count: int = 0
    
    def to_jsonl(self) -> str:
        """
        序列化为 JSONL 格式
        Enum 字段输出 .value 确保稳定性
        """
        data = {
            "timestamp": self.timestamp,
            "decision_type": self.decision_type.value,  # 使用 .value
            "hypothesis_id": self.hypothesis_id,
            "triggered_falsifiable_condition": self.triggered_falsifiable_condition,
            "evidence_ids": self.evidence_ids,
            "paper_keys": self.paper_keys,
            "normalized_values_summary": self.normalized_values_summary,
            "adjudicator_result": self.adjudicator_result,
            "adjudicator_reason": self.adjudicator_reason,
            "iteration": self.iteration,
            "total_evidence_count": self.total_evidence_count
        }
        return json.dumps(data, ensure_ascii=False, default=str)
    
    @classmethod
    def from_jsonl(cls, line: str) -> "DecisionRecord":
        """从 JSONL 行反序列化"""
        data = json.loads(line)
        data["decision_type"] = DecisionType(data["decision_type"])
        return cls(**data)
