"""
端到端集成测试 (E2E Pipeline Tests)
覆盖 6 个不变式确保系统完整性
"""
import unittest
from unittest.mock import patch, MagicMock
import sys
import json
import os
from pathlib import Path
from datetime import datetime

sys.path.append(str(Path(__file__).parent.parent))

from core.services.research.core_types import (
    Evidence, Hypothesis, HypothesisStatus, HypothesisSet,
    ProblemSpec, IterativeResearchState, ContentLevel, StudyType
)
from core.services.research.conflict_adjudicator import adjudicate_falsification, get_independence_key
from core.services.research.audit_logger import AuditLogger, LOG_DIR, DECISIONS_FILE
from core.services.research.audit_types import DecisionType
from core.services.research.evidence_extractor import (
    _generate_evidence_id, _classify_study_type, _validate_and_gate, _get_paper_key
)
from core.services.research.evidence_quality import calculate_quality_weight, filter_high_quality_evidence
from core.services.research.data_normalizer import normalize_evidence_set


# ============================================================
# Mock Fixtures
# ============================================================

def create_mock_paper(doi: str = "", paper_id: str = "", title: str = "Test Paper",
                      year: int = 2024, has_fulltext: bool = False, 
                      abstract: str = "Test abstract", first_author: str = "Zhang"):
    """创建 mock paper 对象"""
    paper = {
        "doi": doi,
        "id": paper_id,
        "title": title,
        "year": year,
        "abstract": abstract,
        "authorships": [{"author": {"display_name": first_author}}]
    }
    if has_fulltext:
        paper["full_content"] = "Full text content with experimental details..."
    return paper


def create_mock_evidence(evidence_id: str, doi: str = "", paper_id: str = "",
                         paper_title: str = "Test", content_level: ContentLevel = ContentLevel.ABSTRACT_ONLY,
                         study_type: StudyType = StudyType.ORIGINAL,
                         normalized_values: dict = None, first_author: str = "") -> Evidence:
    """创建 mock Evidence 对象"""
    ev = Evidence(
        evidence_id=evidence_id,
        doi=doi,
        paper_id=paper_id,
        paper_title=paper_title,
        first_author=first_author,
        content_level=content_level,
        study_type=study_type,
        normalized_values=normalized_values or {},
        implementation="Test implementation"
    )
    _validate_and_gate(ev)
    return ev


def create_mock_hypothesis(hypothesis_id: str = "H1") -> Hypothesis:
    """创建 mock Hypothesis 对象"""
    return Hypothesis(
        hypothesis_id=hypothesis_id,
        mechanism_description="Test mechanism",
        required_variables=["var1", "var2"],
        irrelevant_variables=["var3"],
        falsifiable_conditions=["If X happens, this is falsified"],
        expected_performance_trend="Increase with temperature"
    )


class TestE2EPipeline(unittest.TestCase):
    """端到端集成测试"""
    
    @classmethod
    def setUpClass(cls):
        """测试前清理日志"""
        if DECISIONS_FILE.exists():
            DECISIONS_FILE.unlink()
    
    def tearDown(self):
        """每个测试后清理"""
        if DECISIONS_FILE.exists():
            DECISIONS_FILE.unlink()
        # 清理 trail 文件
        for f in LOG_DIR.glob("hypothesis_*_trail.md"):
            f.unlink()

    # ==========================================
    # E2E-1: REJECTED 必须有审计记录
    # ==========================================
    def test_E2E_1_rejected_requires_audit_record(self):
        """
        E2E-1: Hypothesis 变 REJECTED 必须存在审计记录
        - adjudicator_result=CONFIRMED
        - paper_keys >= 2
        - triggered_falsifiable_condition 非空
        """
        h = create_mock_hypothesis("H_E2E1")
        
        # 两个独立来源的证据 (不同 DOI)
        ev1 = create_mock_evidence("EV1", doi="10.1234/a", normalized_values={"yield": 0.8})
        ev2 = create_mock_evidence("EV2", doi="10.5678/b", normalized_values={"yield": 0.9})
        
        evidence_batch = [ev1, ev2]
        
        # 触发仲裁
        confirmed, reason, evidence_ids, paper_keys = adjudicate_falsification(
            h, [1, 2], evidence_batch, 
            triggered_condition="If yield < 0.5, falsified",
            iteration=1
        )
        
        self.assertTrue(confirmed, "双独立来源应确认证伪")
        
        # 检查审计记录
        records = AuditLogger.get_hypothesis_trail("H_E2E1")
        self.assertEqual(len(records), 1)
        
        record = records[0]
        self.assertEqual(record.adjudicator_result, "CONFIRMED")
        self.assertGreaterEqual(len(record.paper_keys), 2)
        self.assertTrue(record.triggered_falsifiable_condition, "triggered_condition 不应为空")
        self.assertEqual(record.decision_type, DecisionType.HYPOTHESIS_REJECTED)

    # ==========================================
    # E2E-2: abstract-only 不满足充分性
    # ==========================================
    def test_E2E_2_abstract_only_insufficient(self):
        """
        E2E-2: abstract-only 证据再多也不能让 sufficiency=True
        FULL_TEXT ORIGINAL < 2 时必须 INSUFFICIENT_QUALITY
        """
        # 5 个 abstract-only 证据
        evidence_list = [
            create_mock_evidence(f"EV{i}", paper_id=f"P{i}", 
                                 content_level=ContentLevel.ABSTRACT_ONLY,
                                 study_type=StudyType.ORIGINAL)
            for i in range(5)
        ]
        
        # 过滤高质量证据
        high_quality = filter_high_quality_evidence(
            evidence_list, 
            require_fulltext=True, 
            require_original=True
        )
        
        self.assertEqual(len(high_quality), 0, "abstract-only 应全部被过滤")
        
        # 添加 1 个 full-text (仍不足 2)
        ev_ft = create_mock_evidence("EV_FT", paper_id="P_FT",
                                     content_level=ContentLevel.FULL_TEXT,
                                     study_type=StudyType.ORIGINAL)
        evidence_list.append(ev_ft)
        
        high_quality = filter_high_quality_evidence(
            evidence_list,
            require_fulltext=True,
            require_original=True
        )
        
        self.assertEqual(len(high_quality), 1, "仅 1 个 full-text")
        # 按要求 MIN_FULLTEXT_ORIGINAL_COUNT=2，1 个不满足

    # ==========================================
    # E2E-3: falsifiable_allowed=False 不进入仲裁
    # ==========================================
    def test_E2E_3_falsifiable_filter(self):
        """
        E2E-3: falsifiable_allowed=False 的证据不得进入 adjudicator 输入集合
        """
        # 创建无归一化数据的证据
        ev1 = Evidence(evidence_id="EV1", doi="10.1234/a", paper_title="P1")
        ev1.normalized_values = {}  # 空
        _validate_and_gate(ev1)
        
        ev2 = Evidence(evidence_id="EV2", doi="10.5678/b", paper_title="P2")
        ev2.normalized_values = {}  # 空
        _validate_and_gate(ev2)
        
        self.assertFalse(ev1.falsifiable_allowed)
        self.assertFalse(ev2.falsifiable_allowed)
        
        # 过滤逻辑应排除这些证据
        full_batch = [ev1, ev2]
        falsifiable_batch = [ev for ev in full_batch if ev.falsifiable_allowed]
        
        self.assertEqual(len(falsifiable_batch), 0, "无归一化数据的证据应被排除")

    # ==========================================
    # E2E-4: 审计 trail 文件生成
    # ==========================================
    def test_E2E_4_trail_file_generated(self):
        """
        E2E-4: 每个 hypothesis 必须生成 logs/hypothesis_<id>_trail.md
        且包含证据链表格至少一行
        """
        h = create_mock_hypothesis("H_E2E4")
        
        # 触发一次决策 (DISPUTED)
        ev1 = create_mock_evidence("EV1", doi="10.1234/a", normalized_values={"yield": 0.8})
        
        adjudicate_falsification(
            h, [1], [ev1],
            triggered_condition="Test condition",
            iteration=1
        )
        
        # 生成 trail 文件
        trail_path = AuditLogger.generate_hypothesis_trail_md("H_E2E4")
        
        self.assertTrue(trail_path.exists(), "Trail 文件应存在")
        
        content = trail_path.read_text(encoding="utf-8")
        self.assertIn("H_E2E4", content)
        self.assertIn("证据链", content)
        self.assertIn("|", content, "应包含表格")

    # ==========================================
    # E2E-5: 确定性/幂等性
    # ==========================================
    def test_E2E_5_deterministic_evidence_id(self):
        """
        E2E-5: 同一输入运行两次，evidence_id 集合与决策数量稳定
        """
        paper = create_mock_paper(doi="10.1234/test", title="Test Paper")
        spec = ProblemSpec(goal="Test research goal")
        
        impl = "This is a test implementation with some whitespace"
        key_vars = {"concentration": "0.5 mM", "temperature": "25C"}
        
        # 运行两次
        id1 = _generate_evidence_id(paper, impl, key_vars, spec)
        id2 = _generate_evidence_id(paper, impl, key_vars, spec)
        
        self.assertEqual(id1, id2, "相同输入应产生相同 ID")
        
        # 空白变化不影响
        impl_with_spaces = "  This   is  a  test   implementation   with  some   whitespace  "
        id3 = _generate_evidence_id(paper, impl_with_spaces, key_vars, spec)
        
        self.assertEqual(id1, id3, "空白归一化后 ID 应一致")

    # ==========================================
    # E2E-6: independence_key 降级与合并
    # ==========================================
    def test_E2E_6_independence_key_degradation(self):
        """
        E2E-6: 无 DOI 论文场景
        - independence_key 降级正确
        - 同源合并、异源不误合并
        """
        # 场景 1: 有 DOI
        ev_doi = Evidence(doi="10.1234/test", paper_id="", paper_title="P1")
        key_doi = get_independence_key(ev_doi)
        self.assertTrue(key_doi.startswith("doi:"))
        
        # 场景 2: 无 DOI，有 paper_id
        ev_id = Evidence(doi="", paper_id="OA12345", paper_title="P2")
        key_id = get_independence_key(ev_id)
        self.assertTrue(key_id.startswith("id:"))
        
        # 场景 3: 无 DOI/paper_id，有 source_url
        ev_url = Evidence(doi="", paper_id="", source_url="https://example.com/paper")
        key_url = get_independence_key(ev_url)
        self.assertTrue(key_url.startswith("url:"))
        
        # 场景 4: 全无，使用 hash 兜底
        ev_hash = Evidence(doi="", paper_id="", paper_title="Test Title", 
                           paper_year=2024, first_author="Zhang")
        key_hash = get_independence_key(ev_hash)
        self.assertTrue(key_hash.startswith("hash:"))
        
        # 场景 5: 同源合并 (同 paper_id)
        ev_same1 = Evidence(doi="", paper_id="OA999", paper_title="Same Paper")
        ev_same2 = Evidence(doi="", paper_id="OA999", paper_title="Same Paper (Fig2)")
        
        key_same1 = get_independence_key(ev_same1)
        key_same2 = get_independence_key(ev_same2)
        
        self.assertEqual(key_same1, key_same2, "同 paper_id 应合并")
        
        # 场景 6: 异源不误合并 (不同 paper_id)
        ev_diff1 = Evidence(doi="", paper_id="OA111", paper_title="Paper A")
        ev_diff2 = Evidence(doi="", paper_id="OA222", paper_title="Paper B")
        
        key_diff1 = get_independence_key(ev_diff1)
        key_diff2 = get_independence_key(ev_diff2)
        
        self.assertNotEqual(key_diff1, key_diff2, "不同 paper_id 不应合并")


class TestE2EEdgeCases(unittest.TestCase):
    """E2E 边界情况测试"""
    
    def test_empty_evidence_batch(self):
        """空证据批次仲裁"""
        h = create_mock_hypothesis("H_EMPTY")
        confirmed, reason, _, _ = adjudicate_falsification(h, [], [])
        self.assertFalse(confirmed)
        
    def test_invalid_indices(self):
        """无效索引处理"""
        h = create_mock_hypothesis("H_INVALID")
        ev = create_mock_evidence("EV1", doi="10.1234/a", normalized_values={"x": 1.0})
        
        # 索引越界
        confirmed, reason, _, _ = adjudicate_falsification(h, [99], [ev])
        self.assertFalse(confirmed)
        self.assertIn("无效", reason)
        
    def test_quality_weight_ordering(self):
        """质量权重用于排序"""
        ev_full = create_mock_evidence("EV1", doi="10.1/a", 
                                       content_level=ContentLevel.FULL_TEXT,
                                       study_type=StudyType.ORIGINAL,
                                       normalized_values={"x": 1.0})
        
        ev_abstract = create_mock_evidence("EV2", doi="10.1/b",
                                           content_level=ContentLevel.ABSTRACT_ONLY,
                                           study_type=StudyType.ORIGINAL,
                                           normalized_values={"x": 1.0})
        
        self.assertGreater(ev_full.quality_weight, ev_abstract.quality_weight)


class TestSufficiencyChecker(unittest.TestCase):
    """P3: Sufficiency Checker 质量过滤测试"""
    
    def test_quality_gate_blocks_abstract_only(self):
        """质量门槛: 仅摘要不满足 MIN_FULLTEXT_ORIGINAL_COUNT"""
        from core.services.research.sufficiency_checker import evaluate_sufficiency, MIN_FULLTEXT_ORIGINAL_COUNT
        from core.services.research.core_types import SufficiencyStatus
        
        h = create_mock_hypothesis("H_QUAL")
        h.supporting_evidence_count = 5
        
        # 5 个 abstract-only 证据
        evidence = [
            create_mock_evidence(f"EV{i}", paper_id=f"P{i}",
                                 content_level=ContentLevel.ABSTRACT_ONLY,
                                 study_type=StudyType.ORIGINAL)
            for i in range(5)
        ]
        
        spec = ProblemSpec(goal="Test", control_variables=[], performance_metrics=[])
        
        result = evaluate_sufficiency(h, evidence, spec)
        
        self.assertFalse(result.is_sufficient)
        self.assertEqual(result.status, SufficiencyStatus.INSUFFICIENT_QUALITY)
        
    def test_quantity_gate_after_quality(self):
        """数量门槛: 质量达标后检查数量"""
        from core.services.research.sufficiency_checker import evaluate_sufficiency, MIN_EVIDENCE_COUNT
        from core.services.research.core_types import SufficiencyStatus
        
        h = create_mock_hypothesis("H_QUANT")
        h.supporting_evidence_count = 1  # 低于 MIN_EVIDENCE_COUNT
        h.conflicting_evidence_count = 0
        
        # 2 个 full-text original (满足质量门槛)
        evidence = [
            create_mock_evidence(f"EV{i}", paper_id=f"P{i}",
                                 content_level=ContentLevel.FULL_TEXT,
                                 study_type=StudyType.ORIGINAL)
            for i in range(2)
        ]
        
        spec = ProblemSpec(goal="Test", control_variables=[], performance_metrics=[])
        
        result = evaluate_sufficiency(h, evidence, spec)
        
        # 质量达标但数量不足
        self.assertFalse(result.is_sufficient)
        self.assertEqual(result.status, SufficiencyStatus.INSUFFICIENT_QUANTITY)
        
    def test_coverage_gate_after_quantity(self):
        """覆盖门槛: 数量达标后检查覆盖"""
        from core.services.research.sufficiency_checker import evaluate_sufficiency
        from core.services.research.core_types import SufficiencyStatus
        
        h = create_mock_hypothesis("H_COV")
        h.required_variables = ["temperature", "pressure", "concentration"]
        h.supporting_evidence_count = 5
        
        # 足够证据但变量未覆盖
        evidence = [
            create_mock_evidence(f"EV{i}", paper_id=f"P{i}",
                                 content_level=ContentLevel.FULL_TEXT,
                                 study_type=StudyType.ORIGINAL)
            for i in range(5)
        ]
        
        spec = ProblemSpec(goal="Test", control_variables=["temperature", "pressure", "concentration"], performance_metrics=[])
        
        result = evaluate_sufficiency(h, evidence, spec)
        
        self.assertFalse(result.is_sufficient)
        self.assertEqual(result.status, SufficiencyStatus.INSUFFICIENT_COVERAGE)
        self.assertTrue(len(result.missing_variables) > 0)
        
    def test_sufficient_when_all_gates_pass(self):
        """所有门槛通过时充分"""
        from core.services.research.sufficiency_checker import evaluate_sufficiency
        from core.services.research.core_types import SufficiencyStatus
        
        h = create_mock_hypothesis("H_SUFF")
        h.required_variables = ["temperature"]
        h.supporting_evidence_count = 5
        
        # 足够证据且覆盖变量
        evidence = []
        for i in range(5):
            ev = create_mock_evidence(f"EV{i}", paper_id=f"P{i}",
                                     content_level=ContentLevel.FULL_TEXT,
                                     study_type=StudyType.ORIGINAL)
            ev.key_variables = {"temperature": "25C"}
            evidence.append(ev)
        
        spec = ProblemSpec(goal="Test", control_variables=["temperature"], performance_metrics=[])
        
        result = evaluate_sufficiency(h, evidence, spec)
        
        self.assertTrue(result.is_sufficient)
        self.assertEqual(result.status, SufficiencyStatus.SUFFICIENT)


if __name__ == '__main__':
    unittest.main()
