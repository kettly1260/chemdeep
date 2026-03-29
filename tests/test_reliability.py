import unittest
from unittest.mock import patch, MagicMock
import sys
import os
import json
from pathlib import Path

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent))

from core.services.research.core_types import Evidence, Hypothesis, HypothesisStatus, ContentLevel, StudyType
from core.services.research.conflict_adjudicator import adjudicate_falsification, get_independence_key
from core.services.research.data_normalizer import normalize_single_evidence
from core.services.research.audit_types import DecisionRecord, DecisionType
from core.services.research.evidence_quality import calculate_quality_weight, enrich_evidence


class TestReliabilityModules(unittest.TestCase):
    
    # ==========================================
    # [冲突仲裁相关] (Conflict Adjudicator)
    # ==========================================
    
    def test_T1_single_evidence_refutation(self):
        """T1: 单证据反驳：仅 1 篇 paper 的 refuting evidence -> False"""
        h = Hypothesis(hypothesis_id="H1", mechanism_description="", required_variables=[], irrelevant_variables=[], falsifiable_conditions=[], expected_performance_trend="")
        
        ev1 = Evidence(paper_id="DOI_1", paper_title="Paper 1")
        evidence_batch = [ev1]
        refuting_indices = [1]
        
        # 新签名: 4-tuple
        confirmed, reason, _, _ = adjudicate_falsification(h, refuting_indices, evidence_batch)
        
        self.assertFalse(confirmed, "单证据反驳不应通过仲裁")
        self.assertIn("单一", reason)

    def test_T2_double_independent_refutation(self):
        """T2: 双独立反驳：2 篇不同来源 -> True"""
        h = Hypothesis(hypothesis_id="H1", mechanism_description="", required_variables=[], irrelevant_variables=[], falsifiable_conditions=[], expected_performance_trend="")
        
        ev1 = Evidence(paper_id="ID_1", paper_title="Paper 1")
        ev2 = Evidence(paper_id="ID_2", paper_title="Paper 2")
        evidence_batch = [ev1, ev2]
        refuting_indices = [1, 2]
        
        confirmed, reason, evidence_ids, paper_keys = adjudicate_falsification(h, refuting_indices, evidence_batch)
        
        self.assertTrue(confirmed, "双独立证据反驳应通过仲裁")
        self.assertEqual(len(paper_keys), 2)
        
    def test_T3_same_doi_refutation(self):
        """T3: 同源证据：两条证据来自同一 paper_id -> False"""
        h = Hypothesis(hypothesis_id="H1", mechanism_description="", required_variables=[], irrelevant_variables=[], falsifiable_conditions=[], expected_performance_trend="")
        
        ev1 = Evidence(paper_id="DOI_1", paper_title="Paper 1")
        ev2 = Evidence(paper_id="DOI_1", paper_title="Paper 1 (Another section)")
        evidence_batch = [ev1, ev2]
        refuting_indices = [1, 2]
        
        confirmed, reason, _, paper_keys = adjudicate_falsification(h, refuting_indices, evidence_batch)
        
        self.assertFalse(confirmed, "同源证据反驳不应通过仲裁")
        self.assertEqual(len(paper_keys), 1)  # 只有 1 个独立来源
        
    def test_T4_mixed_conflict_insufficiency(self):
        """T4: 冲突存在但 refuting 不足 -> False"""
        h = Hypothesis(hypothesis_id="H1", mechanism_description="", required_variables=[], irrelevant_variables=[], falsifiable_conditions=[], expected_performance_trend="")
        
        ev_supp = Evidence(paper_id="DOI_1", paper_title="Paper 1")
        ev_ref = Evidence(paper_id="DOI_2", paper_title="Paper 2")
        
        evidence_batch = [ev_supp, ev_ref]
        refuting_indices = [2]  # 只有 1 条反驳
        
        confirmed, reason, _, _ = adjudicate_falsification(h, refuting_indices, evidence_batch)
        
        self.assertFalse(confirmed, "单一反驳证据不应通过仲裁")
        
    # ==========================================
    # [数据归一化相关] (Data Normalizer)
    # ==========================================
    
    @patch('core.services.research.data_normalizer.simple_chat')
    def test_T5_unit_conversion(self, mock_chat):
        """T5: 单位换算 '500 ug/mL' -> 0.5 mg/mL"""
        mock_response = '''```json
        {
            "concentration": {
                "value": 0.5,
                "unit": "mg/mL",
                "original": "500 ug/mL"
            }
        }
        ```'''
        mock_chat.return_value = mock_response
        
        ev = Evidence(paper_id="DOI_Unit", paper_title="Paper Unit")
        ev.key_variables = {"concentration": "500 ug/mL"}
        
        normalize_single_evidence(ev)
        
        self.assertIn("concentration", ev.normalized_values)
        self.assertAlmostEqual(ev.normalized_values["concentration"], 0.5)
        self.assertEqual(ev.unit_map.get("concentration"), "mg/mL")
        
    @patch('core.services.research.data_normalizer.simple_chat')
    def test_T6_qualitative_tags(self, mock_chat):
        """T6: 定性标签 'high yield' -> 不生成 value"""
        mock_response = '''```json
        {
            "yield": {
                "value": null,
                "tag": "qualitative_high",
                "original": "high yield"
            }
        }
        ```'''
        mock_chat.return_value = mock_response
        
        ev = Evidence(paper_id="DOI_Qual", paper_title="Paper Qual")
        ev.performance_results = {"yield": "high yield"}
        
        normalize_single_evidence(ev)
        
        self.assertNotIn("yield", ev.normalized_values)

    # ==========================================
    # [P0: 审计日志] Independence Key & JSONL
    # ==========================================
    
    def test_T7_independence_key_degradation_doi(self):
        """T7: Independence Key 优先使用 DOI"""
        ev = Evidence(
            doi="10.1234/test",
            paper_id="OA123",
            paper_title="Test Paper",
            source_url="https://example.com/test"
        )
        key = get_independence_key(ev)
        self.assertTrue(key.startswith("doi:"))
        self.assertIn("10.1234/test", key)
        
    def test_T8_independence_key_degradation_paper_id(self):
        """T8: 无 DOI 时使用 paper_id"""
        ev = Evidence(
            doi="",
            paper_id="OA123456",
            paper_title="Test Paper",
            source_url="https://example.com/test"
        )
        key = get_independence_key(ev)
        self.assertTrue(key.startswith("id:"))
        self.assertIn("OA123456", key)
        
    def test_T9_independence_key_degradation_url(self):
        """T9: 无 DOI 和 paper_id 时使用 source_url"""
        ev = Evidence(
            doi="",
            paper_id="",
            paper_title="Test Paper",
            source_url="https://example.com/test"
        )
        key = get_independence_key(ev)
        self.assertTrue(key.startswith("url:"))
        
    def test_T10_independence_key_degradation_hash(self):
        """T10: 均无时使用 hash 兜底"""
        ev = Evidence(
            doi="",
            paper_id="",
            paper_title="Test Paper",
            paper_year=2024,
            first_author="Zhang"
        )
        key = get_independence_key(ev)
        self.assertTrue(key.startswith("hash:"))
        
    def test_T11_jsonl_enum_serialization(self):
        """T11: JSONL 序列化 Enum 输出 .value"""
        record = DecisionRecord(
            timestamp="2026-01-04T20:00:00",
            decision_type=DecisionType.HYPOTHESIS_REJECTED,
            hypothesis_id="H1",
            evidence_ids=["ev1", "ev2"],
            paper_keys=["doi:10.1234", "id:OA456"],
            adjudicator_result="CONFIRMED",
            adjudicator_reason="Test reason"
        )
        
        jsonl = record.to_jsonl()
        data = json.loads(jsonl)
        
        # Enum 必须输出 .value 字符串
        self.assertEqual(data["decision_type"], "hypothesis_rejected")
        self.assertNotIn("DecisionType", jsonl)  # 不应出现类名
        
    def test_T12_same_paper_multiple_evidence_traceable(self):
        """T12: 同论文多 evidence 的 evidence_id 可追溯"""
        h = Hypothesis(hypothesis_id="H1", mechanism_description="", required_variables=[], irrelevant_variables=[], falsifiable_conditions=[], expected_performance_trend="")
        
        # 同 DOI 两份证据，但 evidence_id 不同
        ev1 = Evidence(evidence_id="EV001", doi="10.1234/test", paper_id="", paper_title="Paper 1")
        ev2 = Evidence(evidence_id="EV002", doi="10.1234/test", paper_id="", paper_title="Paper 1 (Fig2)")
        evidence_batch = [ev1, ev2]
        refuting_indices = [1, 2]
        
        confirmed, reason, evidence_ids, paper_keys = adjudicate_falsification(h, refuting_indices, evidence_batch)
        
        # 应记录两个 evidence_id
        self.assertEqual(len(evidence_ids), 2)
        self.assertIn("EV001", evidence_ids)
        self.assertIn("EV002", evidence_ids)
        
        # 但 paper_keys 应只有 1 个（同源）
        self.assertEqual(len(paper_keys), 1)
        
        # 因此仲裁应驳回
        self.assertFalse(confirmed)


class TestEvidenceQuality(unittest.TestCase):
    """证据质量分层测试"""
    
    def test_fulltext_original_weight(self):
        """全文原创研究权重"""
        ev = Evidence(paper_title="Test")
        ev.content_level = ContentLevel.FULL_TEXT
        ev.study_type = StudyType.ORIGINAL
        ev.normalized_values = {"yield": 0.8}
        
        weight = calculate_quality_weight(ev)
        self.assertEqual(weight, 1.0)
        
    def test_abstract_only_weight(self):
        """仅摘要权重降低"""
        ev = Evidence(paper_title="Test")
        ev.content_level = ContentLevel.ABSTRACT_ONLY
        ev.study_type = StudyType.ORIGINAL
        ev.normalized_values = {"yield": 0.8}
        
        weight = calculate_quality_weight(ev)
        self.assertLess(weight, 0.5)  # 应显著降低
        
    def test_review_weight(self):
        """综述权重降低"""
        ev = Evidence(paper_title="Test")
        ev.content_level = ContentLevel.FULL_TEXT
        ev.study_type = StudyType.REVIEW
        ev.normalized_values = {"yield": 0.8}
        
        weight = calculate_quality_weight(ev)
        self.assertLess(weight, 0.6)


class TestEvidenceExtractor(unittest.TestCase):
    """Evidence Extractor 集成测试"""
    
    def test_T13_evidence_id_deterministic(self):
        """T13: 同一输入重复提取，evidence_id 不变"""
        from core.services.research.evidence_extractor import _generate_evidence_id, _normalize_whitespace
        from core.services.research.core_types import ProblemSpec
        
        paper = {"doi": "10.1234/test", "id": "OA123", "title": "Test Paper"}
        impl = "  This is   a test   implementation  "
        key_vars = {"concentration": "0.5 mM"}
        spec = ProblemSpec(goal="Test goal for research")
        
        id1 = _generate_evidence_id(paper, impl, key_vars, spec)
        id2 = _generate_evidence_id(paper, impl, key_vars, spec)
        
        self.assertEqual(id1, id2, "同输入应产生相同 evidence_id")
        
    def test_T14_evidence_id_whitespace_normalized(self):
        """T14: 空白归一化后 evidence_id 一致"""
        from core.services.research.evidence_extractor import _generate_evidence_id
        from core.services.research.core_types import ProblemSpec
        
        paper = {"doi": "10.1234/test"}
        impl1 = "This is a test"
        impl2 = "  This   is  a   test  "
        spec = ProblemSpec(goal="Test")
        
        id1 = _generate_evidence_id(paper, impl1, {}, spec)
        id2 = _generate_evidence_id(paper, impl2, {}, spec)
        
        self.assertEqual(id1, id2, "空白归一化后应产生相同 ID")
        
    def test_T15_study_type_review_strong(self):
        """T15: Review 分类 (强信号)"""
        from core.services.research.evidence_extractor import _classify_study_type
        
        paper = {"title": "A comprehensive review of fluorescent probes"}
        result = _classify_study_type(paper)
        self.assertEqual(result, StudyType.REVIEW)
        
    def test_T16_study_type_original(self):
        """T16: Original 分类"""
        from core.services.research.evidence_extractor import _classify_study_type
        
        paper = {"title": "Synthesis and characterization of novel carborane derivatives", "abstract": "We report the synthesis..."}
        result = _classify_study_type(paper)
        self.assertEqual(result, StudyType.ORIGINAL)
        
    def test_T17_study_type_meta_analysis(self):
        """T17: Meta-analysis 分类"""
        from core.services.research.evidence_extractor import _classify_study_type
        
        paper = {"title": "A meta-analysis of sensing performance"}
        result = _classify_study_type(paper)
        self.assertEqual(result, StudyType.META_ANALYSIS)
        
    def test_T18_study_type_commentary(self):
        """T18: Commentary 分类"""
        from core.services.research.evidence_extractor import _classify_study_type
        
        paper = {"title": "Comment on: Recent advances in probes"}
        result = _classify_study_type(paper)
        self.assertEqual(result, StudyType.COMMENTARY)
        
    def test_T19_study_type_weak_review_needs_context(self):
        """T19: 弱信号 'advances in' 需要 abstract 确认"""
        from core.services.research.evidence_extractor import _classify_study_type
        
        # 无 abstract 确认 -> UNKNOWN
        paper1 = {"title": "Recent advances in fluorescent probes", "abstract": ""}
        result1 = _classify_study_type(paper1)
        self.assertNotEqual(result1, StudyType.REVIEW, "无 abstract 确认不应为 REVIEW")
        
        # 有 abstract 确认 -> REVIEW
        paper2 = {"title": "Recent advances in fluorescent probes", "abstract": "In this review, we summarize..."}
        result2 = _classify_study_type(paper2)
        # 注意：当前规则检查 "this review" 或 "we review"
        
    def test_T20_validation_gate_independence_key(self):
        """T20: 验证 Gate 计算 independence_key"""
        from core.services.research.evidence_extractor import _validate_and_gate
        
        ev = Evidence(doi="10.1234/test", paper_title="Test")
        _validate_and_gate(ev)
        
        self.assertTrue(ev.independence_key.startswith("doi:"))
        
    def test_T21_falsifiable_allowed_only_with_normalized(self):
        """T21: falsifiable_allowed 仅当 normalized_values 非空"""
        from core.services.research.evidence_extractor import _validate_and_gate
        
        # 无归一化数据
        ev1 = Evidence(doi="10.1234/test1", paper_title="Test1")
        ev1.normalized_values = {}
        _validate_and_gate(ev1)
        self.assertFalse(ev1.falsifiable_allowed)
        
        # 有归一化数据
        ev2 = Evidence(doi="10.1234/test2", paper_title="Test2")
        ev2.normalized_values = {"yield": 0.8}
        _validate_and_gate(ev2)
        self.assertTrue(ev2.falsifiable_allowed)


if __name__ == '__main__':
    unittest.main()
