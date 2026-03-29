"""
审计日志模块 (Audit Logger)
记录关键决策并生成可追溯的证据链
"""
import logging
from pathlib import Path
from typing import List, Optional
from datetime import datetime

from .audit_types import DecisionRecord, DecisionType

logger = logging.getLogger('deep_research')

LOG_DIR = Path("logs")
DECISIONS_FILE = LOG_DIR / "decisions.jsonl"


class AuditLogger:
    """审计日志管理器"""
    
    @classmethod
    def log_decision(cls, record: DecisionRecord) -> None:
        """追加一条决策记录到 JSONL"""
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        
        with open(DECISIONS_FILE, "a", encoding="utf-8") as f:
            f.write(record.to_jsonl() + "\n")
        
        logger.info(f"📝 审计日志: {record.decision_type.value} -> {record.hypothesis_id}")
    
    @classmethod
    def get_all_records(cls) -> List[DecisionRecord]:
        """读取所有决策记录"""
        if not DECISIONS_FILE.exists():
            return []
        
        records = []
        with open(DECISIONS_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        records.append(DecisionRecord.from_jsonl(line))
                    except Exception as e:
                        logger.warning(f"解析审计记录失败: {e}")
        return records
    
    @classmethod
    def get_hypothesis_trail(cls, hypothesis_id: str) -> List[DecisionRecord]:
        """获取某假设的完整决策链"""
        all_records = cls.get_all_records()
        return [r for r in all_records if r.hypothesis_id == hypothesis_id]
    
    @classmethod
    def generate_evidence_chain_table(cls, hypothesis_id: str) -> str:
        """
        生成该假设的证据链 Markdown 表格
        """
        records = cls.get_hypothesis_trail(hypothesis_id)
        
        if not records:
            return f"*假设 {hypothesis_id} 无决策记录*"
        
        lines = [
            f"## 假设 {hypothesis_id} 证据链",
            "",
            "| 时间 | 决策类型 | 证伪条件 | 证据ID | 论文来源 | 仲裁结果 | 理由 |",
            "|------|----------|----------|--------|----------|----------|------|"
        ]
        
        for r in records:
            time_short = r.timestamp[:19] if len(r.timestamp) >= 19 else r.timestamp
            evidence_ids = ", ".join(r.evidence_ids[:3]) + ("..." if len(r.evidence_ids) > 3 else "")
            paper_keys = ", ".join(r.paper_keys[:3]) + ("..." if len(r.paper_keys) > 3 else "")
            condition = r.triggered_falsifiable_condition[:30] + "..." if len(r.triggered_falsifiable_condition) > 30 else r.triggered_falsifiable_condition
            reason = r.adjudicator_reason[:40] + "..." if len(r.adjudicator_reason) > 40 else r.adjudicator_reason
            
            lines.append(
                f"| {time_short} | {r.decision_type.value} | {condition} | {evidence_ids} | {paper_keys} | {r.adjudicator_result} | {reason} |"
            )
        
        return "\n".join(lines)
    
    @classmethod
    def generate_hypothesis_trail_md(cls, hypothesis_id: str) -> Path:
        """
        生成假设的完整审计 Markdown 文件
        """
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        trail_file = LOG_DIR / f"hypothesis_{hypothesis_id}_trail.md"
        
        records = cls.get_hypothesis_trail(hypothesis_id)
        
        lines = [
            f"# 假设 {hypothesis_id} 决策审计报告",
            f"",
            f"*生成时间: {datetime.now().isoformat()}*",
            f"",
            f"---",
            f"",
        ]
        
        # 摘要
        rejected_count = sum(1 for r in records if r.decision_type == DecisionType.HYPOTHESIS_REJECTED)
        disputed_count = sum(1 for r in records if r.decision_type == DecisionType.ADJUDICATION_DISPUTED)
        
        lines.extend([
            f"## 摘要",
            f"",
            f"- **总决策次数**: {len(records)}",
            f"- **REJECTED 次数**: {rejected_count}",
            f"- **DISPUTED (仲裁驳回)**: {disputed_count}",
            f""
        ])
        
        # 证据链表格
        lines.append(cls.generate_evidence_chain_table(hypothesis_id))
        lines.append("")
        
        # 详细记录
        lines.extend([
            f"",
            f"## 详细记录",
            f""
        ])
        
        for i, r in enumerate(records, 1):
            lines.extend([
                f"### 记录 {i}",
                f"",
                f"- **时间**: {r.timestamp}",
                f"- **决策类型**: `{r.decision_type.value}`",
                f"- **触发条件**: {r.triggered_falsifiable_condition or 'N/A'}",
                f"- **证据ID**: {r.evidence_ids}",
                f"- **论文来源**: {r.paper_keys}",
                f"- **仲裁结果**: {r.adjudicator_result}",
                f"- **仲裁理由**: {r.adjudicator_reason}",
                f"- **归一化数据**: `{r.normalized_values_summary}`",
                f""
            ])
        
        with open(trail_file, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        
        logger.info(f"📄 已生成假设审计报告: {trail_file}")
        return trail_file
