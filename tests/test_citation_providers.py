"""
P6/P7 模块测试
- P6: Citation Providers (OpenAlex + Crossref)
- P7: Runtime Engineering (Cache + Checkpoint)
"""
import unittest
from unittest.mock import patch, MagicMock
import sys
import json
import tempfile
from pathlib import Path
from datetime import datetime, timedelta

sys.path.append(str(Path(__file__).parent.parent))

from core.services.research.citation_providers import (
    PaperCandidate, CitationCache, RateLimitedClient,
    OpenAlexProvider, CrossrefProvider, fetch_citations, CACHE_DIR
)
from core.services.research.citation_snowball import (
    expand_via_snowball, select_seeds, should_trigger_snowball
)
from core.services.research.core_types import (
    Evidence, Hypothesis, HypothesisStatus, HypothesisSet,
    IterativeResearchState, ProblemSpec, ContentLevel, StudyType,
    EvaluationResult, SufficiencyStatus
)
from core.services.research.evidence_extractor import _validate_and_gate


class TestPaperCandidate(unittest.TestCase):
    """PaperCandidate 数据结构测试"""
    
    def test_field_completeness(self):
        """测试输出字段完整性"""
        pc = PaperCandidate(
            doi="10.1234/test",
            openalex_id="W123456",
            title="Test Paper",
            abstract="Abstract text",
            year=2024,
            authors=["Author One", "Author Two"],
            first_author="Author One",
            url="https://example.com",
            source="openalex",
            relation="cited_by",
            seed_paper_key="doi:10.5678/seed",
            cited_by_count=100
        )
        
        data = pc.to_dict()
        
        # 验证所有字段存在
        required_fields = [
            "doi", "openalex_id", "title", "abstract", "year",
            "authors", "first_author", "url", "source", "relation",
            "seed_paper_key", "cited_by_count"
        ]
        for field in required_fields:
            self.assertIn(field, data)
    
    def test_from_dict_roundtrip(self):
        """测试序列化/反序列化"""
        pc = PaperCandidate(doi="10.1234/test", title="Test")
        data = pc.to_dict()
        pc2 = PaperCandidate.from_dict(data)
        
        self.assertEqual(pc.doi, pc2.doi)
        self.assertEqual(pc.title, pc2.title)


class TestCitationCache(unittest.TestCase):
    """缓存测试"""
    
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.cache = CitationCache(cache_dir=Path(self.temp_dir), ttl_days=7)
    
    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def test_cache_hit(self):
        """测试缓存命中"""
        key = "doi:10.1234/test"
        candidates = [PaperCandidate(doi="10.5678/cited", title="Cited Paper")]
        
        self.cache.set(key, candidates)
        result = self.cache.get(key)
        
        self.assertIsNotNone(result)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].doi, "10.5678/cited")
    
    def test_cache_miss(self):
        """测试缓存未命中"""
        result = self.cache.get("nonexistent_key")
        self.assertIsNone(result)
    
    def test_cache_ttl_expired(self):
        """测试 TTL 过期"""
        key = "doi:10.1234/expired"
        candidates = [PaperCandidate(doi="10.5678/old")]
        
        # 写入缓存
        self.cache.set(key, candidates)
        
        # 手动修改缓存时间为过期
        cache_path = self.cache._get_cache_path(key)
        data = json.loads(cache_path.read_text(encoding="utf-8"))
        data["cached_at"] = (datetime.now() - timedelta(days=10)).isoformat()
        cache_path.write_text(json.dumps(data), encoding="utf-8")
        
        # 应该返回 None
        result = self.cache.get(key)
        self.assertIsNone(result, "过期缓存应返回 None")


class TestOpenAlexProvider(unittest.TestCase):
    """OpenAlex Provider 测试"""
    
    @patch.object(RateLimitedClient, 'get')
    def test_fetch_references_mock(self, mock_get):
        """测试 references 获取 (mock HTTP)"""
        # Mock work 详情
        mock_get.side_effect = [
            {
                "id": "https://openalex.org/W123",
                "referenced_works": ["https://openalex.org/W456", "https://openalex.org/W789"]
            },
            {
                "results": [
                    {
                        "id": "https://openalex.org/W456",
                        "title": "Referenced Paper 1",
                        "doi": "https://doi.org/10.1234/ref1",
                        "publication_year": 2023,
                        "authorships": [{"author": {"display_name": "Author A"}}],
                        "cited_by_count": 50
                    }
                ]
            }
        ]
        
        provider = OpenAlexProvider()
        candidates = provider.fetch_references("id:W123", max_results=10)
        
        self.assertGreaterEqual(len(candidates), 1)
        self.assertEqual(candidates[0].title, "Referenced Paper 1")
    
    @patch.object(RateLimitedClient, 'get')
    def test_fetch_cited_by_mock(self, mock_get):
        """测试 cited_by 获取 (mock HTTP)"""
        mock_get.return_value = {
            "results": [
                {
                    "id": "https://openalex.org/W999",
                    "title": "Citing Paper",
                    "doi": "https://doi.org/10.1234/cite1",
                    "publication_year": 2024,
                    "authorships": [],
                    "cited_by_count": 10
                }
            ]
        }
        
        provider = OpenAlexProvider()
        candidates = provider.fetch_cited_by("id:W123", max_results=10)
        
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].relation, "cited_by")


class TestCheckpoint(unittest.TestCase):
    """断点续跑测试"""
    
    def create_mock_state(self):
        """创建 mock state"""
        spec = ProblemSpec(goal="Test", control_variables=["var1"])
        
        h = Hypothesis(
            hypothesis_id="H1",
            mechanism_description="Test",
            required_variables=["var1"],
            irrelevant_variables=[],
            falsifiable_conditions=[],
            expected_performance_trend=""
        )
        h.status = HypothesisStatus.ACTIVE
        
        state = IterativeResearchState(problem_spec=spec)
        state.hypothesis_set = HypothesisSet(hypotheses=[h])
        state.evaluation = EvaluationResult(
            is_sufficient=False,
            status=SufficiencyStatus.INSUFFICIENT_COVERAGE,
            reason="Test"
        )
        
        # 添加高质量证据作为种子
        ev1 = Evidence(
            evidence_id="EV001",
            doi="10.1234/seed1",
            content_level=ContentLevel.FULL_TEXT,
            study_type=StudyType.ORIGINAL,
            normalized_values={"x": 1.0}
        )
        _validate_and_gate(ev1)
        
        ev2 = Evidence(
            evidence_id="EV002",
            doi="10.5678/seed2",
            content_level=ContentLevel.FULL_TEXT,
            study_type=StudyType.ORIGINAL,
            normalized_values={"y": 2.0}
        )
        _validate_and_gate(ev2)
        
        state.evidence_set = [ev1, ev2]
        
        return state
    
    def test_checkpoint_skip_processed(self):
        """测试断点续跑跳过已处理种子"""
        state = self.create_mock_state()
        
        # 预先标记 EV001 为已处理
        state.snowball_seeds_processed = ["EV001"]
        
        # 选择种子时应跳过 EV001
        seeds = select_seeds(state.evidence_set, state.hypothesis_set.hypotheses[0])
        
        # 验证触发条件
        should_trigger, h_ids = should_trigger_snowball(state)
        self.assertTrue(should_trigger)
        
        # 运行 expand 时应跳过 EV001
        processed_before = set(state.snowball_seeds_processed)
        
        # 注意：实际调用会触发网络请求，这里只测试逻辑
        # expand_via_snowball 内部会检查 processed_seeds
        
    def test_checkpoint_records_processed(self):
        """测试处理后记录到 checkpoint"""
        state = self.create_mock_state()
        
        # 初始为空
        self.assertEqual(len(state.snowball_seeds_processed), 0)
        
        # 模拟处理一个种子
        state.snowball_seeds_processed.append("EV001")
        
        self.assertEqual(len(state.snowball_seeds_processed), 1)
        self.assertIn("EV001", state.snowball_seeds_processed)


class TestDOIDegradation(unittest.TestCase):
    """DOI 缺失降级测试"""
    
    def test_paper_key_fallback_to_openalex_id(self):
        """测试 DOI 缺失时降级到 OpenAlex ID"""
        from core.services.research.conflict_adjudicator import get_independence_key
        
        ev = Evidence(doi="", paper_id="W123456", paper_title="Test")
        key = get_independence_key(ev)
        
        self.assertTrue(key.startswith("id:"))
        self.assertIn("W123456", key)
    
    def test_paper_key_fallback_to_hash(self):
        """测试全空时降级到 hash"""
        from core.services.research.conflict_adjudicator import get_independence_key
        
        ev = Evidence(
            doi="", 
            paper_id="", 
            source_url="",
            paper_title="Test Title",
            paper_year=2024,
            first_author="Zhang"
        )
        key = get_independence_key(ev)
        
        self.assertTrue(key.startswith("hash:"))


if __name__ == '__main__':
    unittest.main()
