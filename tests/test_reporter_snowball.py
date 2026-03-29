"""
P4/P5 模块测试
- P4: Reporter V2 (MD + JSON 输出)
- P5: Citation Snowballing
"""
import unittest
from unittest.mock import patch, MagicMock
import sys
import json
import tempfile
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

from core.services.research.core_types import (
    Evidence, Hypothesis, HypothesisStatus, HypothesisSet,
    ProblemSpec, IterativeResearchState, ContentLevel, StudyType,
    EvaluationResult, SufficiencyStatus
)
from core.services.research.evidence_extractor import _validate_and_gate


def create_mock_state() -> IterativeResearchState:
    """创建 mock 研究状态"""
    spec = ProblemSpec(
        goal="研究荧光探针的溶剂极性响应机理",
        research_object="荧光探针",
        control_variables=["solvent_polarity", "temperature"],
        performance_metrics=["quantum_yield", "emission_wavelength"],
        constraints=["室温条件"]
    )
    
    state = IterativeResearchState(problem_spec=spec)
    
    # 添加假设
    h1 = Hypothesis(
        hypothesis_id="H1",
        mechanism_description="ICT 机理主导的溶剂极性响应",
        required_variables=["solvent_polarity", "HOMO-LUMO"],
        irrelevant_variables=["viscosity"],
        falsifiable_conditions=["极性增加荧光不猝灭则证伪"],
        expected_performance_trend="随极性增加红移"
    )
    h1.status = HypothesisStatus.ACTIVE
    h1.supporting_evidence_count = 3
    
    h2 = Hypothesis(
        hypothesis_id="H2",
        mechanism_description="AIE 机理主导",
        required_variables=["aggregation_state"],
        irrelevant_variables=[],
        falsifiable_conditions=["单分子态发光则证伪"],
        expected_performance_trend="聚集态增强"
    )
    h2.status = HypothesisStatus.REJECTED
    h2.rejection_reason = "经 2 篇独立论文证伪"
    
    state.hypothesis_set = HypothesisSet(hypotheses=[h1, h2])
    
    # 添加证据
    ev1 = Evidence(
        evidence_id="EV001",
        doi="10.1234/test1",
        paper_title="ICT-based fluorescent probes",
        content_level=ContentLevel.FULL_TEXT,
        study_type=StudyType.ORIGINAL,
        normalized_values={"quantum_yield": 0.85}
    )
    _validate_and_gate(ev1)
    
    ev2 = Evidence(
        evidence_id="EV002",
        paper_id="OA123",
        paper_title="Solvatochromic sensors",
        content_level=ContentLevel.ABSTRACT_ONLY,
        study_type=StudyType.ORIGINAL
    )
    _validate_and_gate(ev2)
    
    state.evidence_set = [ev1, ev2]
    
    # 添加评估结果
    state.evaluation = EvaluationResult(
        is_sufficient=False,
        status=SufficiencyStatus.INSUFFICIENT_COVERAGE,
        reason="变量覆盖不足",
        missing_variables=["HOMO-LUMO"]
    )
    
    return state


class TestReporterV2(unittest.TestCase):
    """P4: Reporter V2 测试"""
    
    def test_generate_report_md_structure(self):
        """测试 MD 报告包含所有必需章节"""
        from core.services.research.reporter_v2 import generate_report_md
        
        state = create_mock_state()
        md = generate_report_md(state)
        
        # 检查章节存在
        self.assertIn("## 1. 研究定义", md)
        self.assertIn("## 2. 机理假设分析", md)
        self.assertIn("## 3. 技术路线分析", md)
        self.assertIn("## 4. 路线推荐", md)
        self.assertIn("## 5. 缺口分析", md)
        self.assertIn("## 6. 证据统计", md)
        
    def test_generate_report_md_contains_spec(self):
        """测试 MD 报告包含 ProblemSpec 信息"""
        from core.services.research.reporter_v2 import generate_report_md
        
        state = create_mock_state()
        md = generate_report_md(state)
        
        self.assertIn("荧光探针", md)
        self.assertIn("solvent_polarity", md)
        self.assertIn("quantum_yield", md)
        
    def test_generate_report_json_structure(self):
        """测试 JSON 报告结构"""
        from core.services.research.reporter_v2 import generate_report_json
        
        state = create_mock_state()
        data = generate_report_json(state)
        
        # 检查顶级键
        self.assertIn("hypotheses", data)
        self.assertIn("routes", data)
        self.assertIn("problem_spec", data)
        self.assertIn("evidence_summary", data)
        self.assertIn("statistics", data)
        
    def test_generate_report_json_evidence_traceable(self):
        """测试 JSON 报告中证据可追溯"""
        from core.services.research.reporter_v2 import generate_report_json
        
        state = create_mock_state()
        data = generate_report_json(state)
        
        # 假设应包含 evidence_chain
        for h in data["hypotheses"]:
            self.assertIn("evidence_chain", h)
            self.assertIn("evidence_ids", h["evidence_chain"])
            self.assertIn("paper_keys", h["evidence_chain"])
        
        # 证据摘要应包含 evidence_id
        for ev in data["evidence_summary"]:
            self.assertIn("evidence_id", ev)
            self.assertIn("independence_key", ev)
            
    def test_generate_report_files(self):
        """测试报告文件生成"""
        from core.services.research.reporter_v2 import generate_report
        
        state = create_mock_state()
        
        with tempfile.TemporaryDirectory() as tmpdir:
            paths = generate_report(state, output_dir=Path(tmpdir))
            
            self.assertTrue(paths["md"].exists())
            self.assertTrue(paths["json"].exists())
            
            # 验证 JSON 可解析
            json_content = json.loads(paths["json"].read_text(encoding="utf-8"))
            self.assertIn("hypotheses", json_content)


class TestCitationSnowball(unittest.TestCase):
    """P5: Citation Snowballing 测试"""
    
    def test_trigger_condition_active_insufficient(self):
        """测试触发条件: Active 假设且 insufficient"""
        from core.services.research.citation_snowball import should_trigger_snowball
        
        state = create_mock_state()
        state.evaluation.is_sufficient = False
        
        should_trigger, h_ids = should_trigger_snowball(state)
        
        self.assertTrue(should_trigger)
        self.assertIn("H1", h_ids)  # H1 是 ACTIVE
        self.assertNotIn("H2", h_ids)  # H2 是 REJECTED
        
    def test_trigger_condition_sufficient_blocks(self):
        """测试触发条件: sufficient 时不触发"""
        from core.services.research.citation_snowball import should_trigger_snowball
        
        state = create_mock_state()
        state.evaluation.is_sufficient = True
        
        should_trigger, h_ids = should_trigger_snowball(state)
        
        self.assertFalse(should_trigger)
        
    def test_seed_selection_quality_priority(self):
        """测试种子选择: 优先高质量"""
        from core.services.research.citation_snowball import select_seeds
        
        state = create_mock_state()
        h = state.hypothesis_set.hypotheses[0]
        
        # 添加更多证据
        ev_low = Evidence(
            evidence_id="EV_LOW",
            paper_id="P_LOW",
            content_level=ContentLevel.ABSTRACT_ONLY,
            study_type=StudyType.ORIGINAL
        )
        _validate_and_gate(ev_low)
        
        ev_high = Evidence(
            evidence_id="EV_HIGH",
            doi="10.5678/high",
            content_level=ContentLevel.FULL_TEXT,
            study_type=StudyType.ORIGINAL,
            normalized_values={"x": 1.0}
        )
        _validate_and_gate(ev_high)
        
        evidence = [ev_low, ev_high]
        seeds = select_seeds(evidence, h, max_seeds=1)
        
        # 应选择高质量的
        self.assertEqual(len(seeds), 1)
        self.assertEqual(seeds[0].evidence_id, "EV_HIGH")
        
    def test_filter_relevance_matches_variables(self):
        """测试过滤: 只保留匹配 required_variables 的"""
        from core.services.research.citation_snowball import (
            filter_by_relevance, SnowballCandidate
        )
        
        candidates = [
            SnowballCandidate(
                source="cited_by",
                seed_evidence_id="EV1",
                seed_paper_key="doi:10.1234",
                title="Solvent polarity effects on fluorescence",
                abstract="We study solvent polarity..."
            ),
            SnowballCandidate(
                source="references",
                seed_evidence_id="EV1",
                seed_paper_key="doi:10.1234",
                title="Unrelated topic about catalysis",
                abstract="Catalyst performance..."
            )
        ]
        
        required_vars = ["solvent_polarity", "temperature"]
        
        relevant = filter_by_relevance(candidates, required_vars)
        
        self.assertEqual(len(relevant), 1)
        self.assertIn("solvent_polarity", relevant[0].relevant_variables)
        
    def test_filter_no_irrelevant_expansion(self):
        """测试: 不扩张无关变量"""
        from core.services.research.citation_snowball import (
            filter_by_relevance, SnowballCandidate
        )
        
        candidates = [
            SnowballCandidate(
                source="cited_by",
                seed_evidence_id="EV1",
                seed_paper_key="doi:10.1234",
                title="Viscosity effects on emission",  # 无关变量
                abstract="Viscosity study..."
            )
        ]
        
        required_vars = ["solvent_polarity", "temperature"]  # 不包含 viscosity
        
        relevant = filter_by_relevance(candidates, required_vars)
        
        self.assertEqual(len(relevant), 0, "不应扩张无关变量")
        
    def test_empty_candidates_handled(self):
        """测试: 空候选处理"""
        from core.services.research.citation_snowball import expand_via_snowball
        
        state = create_mock_state()
        
        # 清空证据使种子选择失败
        state.evidence_set = []
        
        results = expand_via_snowball(state, ["H1"])
        
        # 应该正常返回空结果
        self.assertEqual(len(results), 0)


if __name__ == '__main__':
    unittest.main()
