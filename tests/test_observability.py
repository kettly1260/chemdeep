"""
P8/P9 模块测试
- P8: Run Artifacts & Metrics
- P9: LLM Cache & Extraction Strategies
"""
import unittest
import sys
import json
import tempfile
import shutil
from pathlib import Path
from datetime import datetime, timedelta

sys.path.append(str(Path(__file__).parent.parent))

from core.services.research.run_manager import (
    RunManager, RunMetrics, StageMetrics, ErrorRecord,
    start_run, end_run, get_current_run
)
from core.services.research.llm_cache import (
    LLMCache, ExtractionStrategy, FetchStrategy,
    cached_llm_call, get_llm_cache
)


class TestRunManager(unittest.TestCase):
    """P8: Run Manager 测试"""
    
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.original_runs_dir = Path("runs")
    
    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)
        # 清理测试生成的 runs
        test_run_dir = self.original_runs_dir / getattr(self, '_test_run_id', 'nonexistent')
        if test_run_dir.exists():
            shutil.rmtree(test_run_dir, ignore_errors=True)
    
    def test_run_directory_creation(self):
        """测试 run 目录生成"""
        import core.services.research.run_manager as rm
        original_dir = rm.RUNS_DIR
        rm.RUNS_DIR = Path(self.temp_dir) / "runs"
        
        try:
            manager = RunManager()
            self._test_run_id = manager.run_id
            
            self.assertTrue(manager.run_dir.exists())
            self.assertIn(manager.run_id, str(manager.run_dir))
        finally:
            rm.RUNS_DIR = original_dir
    
    def test_metrics_field_completeness(self):
        """测试 metrics 字段完整性"""
        metrics = RunMetrics(run_id="test123")
        data = metrics.to_dict()
        
        required_fields = [
            "run_id", "started_at", "ended_at", "total_duration_seconds",
            "stages", "fetch_total", "fetch_success", "fetch_failed", "fetch_cached",
            "evidence_total", "evidence_fulltext", "evidence_abstract", "evidence_original",
            "adjudication_total", "adjudication_confirmed", "adjudication_disputed",
            "snowball_seeds", "snowball_candidates", "snowball_relevant",
            "llm_calls", "llm_cached", "llm_tokens_in", "llm_tokens_out"
        ]
        
        for field in required_fields:
            self.assertIn(field, data, f"Missing field: {field}")
    
    def test_stage_timing(self):
        """测试阶段计时"""
        import core.services.research.run_manager as rm
        rm.RUNS_DIR = Path(self.temp_dir) / "runs"
        
        try:
            manager = RunManager()
            
            with manager.stage("test_stage") as stage:
                import time
                time.sleep(0.05)
            
            self.assertIn("test_stage", manager.metrics.stages)
            self.assertGreater(manager.metrics.stages["test_stage"].duration_seconds, 0.04)
        finally:
            rm.RUNS_DIR = self.original_runs_dir
    
    def test_error_recording(self):
        """测试错误记录写入"""
        import core.services.research.run_manager as rm
        rm.RUNS_DIR = Path(self.temp_dir) / "runs"
        
        try:
            manager = RunManager()
            
            manager.record_error("fetch", "TimeoutError", "Connection timed out", {"url": "http://example.com"})
            
            self.assertEqual(len(manager.errors), 1)
            self.assertEqual(manager.errors[0].stage, "fetch")
            self.assertEqual(manager.errors[0].error_type, "TimeoutError")
            
            # 保存并验证 errors.jsonl
            manager.finalize()
            
            errors_file = manager.run_dir / "errors.jsonl"
            self.assertTrue(errors_file.exists())
            
            with open(errors_file, "r", encoding="utf-8") as f:
                line = f.readline()
                data = json.loads(line)
                self.assertEqual(data["stage"], "fetch")
        finally:
            rm.RUNS_DIR = self.original_runs_dir
    
    def test_finalize_creates_metrics_json(self):
        """测试 finalize 生成 metrics.json"""
        import core.services.research.run_manager as rm
        rm.RUNS_DIR = Path(self.temp_dir) / "runs"
        
        try:
            manager = RunManager()
            manager.update_fetch_stats(success=10, failed=2)
            manager.finalize()
            
            metrics_file = manager.run_dir / "metrics.json"
            self.assertTrue(metrics_file.exists())
            
            data = json.loads(metrics_file.read_text(encoding="utf-8"))
            self.assertEqual(data["fetch_success"], 10)
            self.assertEqual(data["fetch_failed"], 2)
        finally:
            rm.RUNS_DIR = self.original_runs_dir


class TestLLMCache(unittest.TestCase):
    """P9: LLM Cache 测试"""
    
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.cache = LLMCache(cache_dir=Path(self.temp_dir), ttl_days=30)
    
    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def test_cache_hit(self):
        """测试缓存命中"""
        prompt = "Test prompt"
        response = "Test response"
        
        self.cache.set(prompt, response, model="gpt-4")
        result = self.cache.get(prompt, model="gpt-4")
        
        self.assertEqual(result, response)
    
    def test_cache_miss(self):
        """测试缓存未命中"""
        result = self.cache.get("nonexistent prompt")
        self.assertIsNone(result)
    
    def test_cache_ttl_expired(self):
        """测试 TTL 过期"""
        prompt = "Expired prompt"
        self.cache.set(prompt, "Old response")
        
        # 手动修改缓存时间
        prompt_hash = self.cache._hash_prompt(prompt, "", False)
        cache_path = self.cache._get_cache_path(prompt_hash)
        
        data = json.loads(cache_path.read_text(encoding="utf-8"))
        data["cached_at"] = (datetime.now() - timedelta(days=40)).isoformat()
        cache_path.write_text(json.dumps(data), encoding="utf-8")
        
        result = self.cache.get(prompt)
        self.assertIsNone(result, "过期缓存应返回 None")
    
    def test_cache_stats(self):
        """测试缓存统计"""
        self.cache.set("p1", "r1")
        self.cache.get("p1")  # hit
        self.cache.get("p2")  # miss
        
        stats = self.cache.get_stats()
        
        self.assertEqual(stats["hits"], 1)
        self.assertEqual(stats["misses"], 1)
        self.assertEqual(stats["hit_rate"], 0.5)
    
    def test_different_model_different_cache(self):
        """测试不同模型分开缓存"""
        prompt = "Same prompt"
        
        self.cache.set(prompt, "Response A", model="gpt-4")
        self.cache.set(prompt, "Response B", model="gpt-3.5")
        
        result_a = self.cache.get(prompt, model="gpt-4")
        result_b = self.cache.get(prompt, model="gpt-3.5")
        
        self.assertEqual(result_a, "Response A")
        self.assertEqual(result_b, "Response B")


class TestExtractionStrategy(unittest.TestCase):
    """P9: 抽取分层策略测试"""
    
    def test_light_strategy_for_abstract(self):
        """测试 abstract_only 使用轻抽取"""
        strategy = ExtractionStrategy.get_strategy("abstract")
        self.assertEqual(strategy, ExtractionStrategy.LIGHT)
    
    def test_full_strategy_for_fulltext(self):
        """测试 full_text 使用完整抽取"""
        strategy = ExtractionStrategy.get_strategy("full_text")
        self.assertEqual(strategy, ExtractionStrategy.FULL)
    
    def test_normalize_only_for_full(self):
        """测试只有完整抽取才归一化"""
        self.assertTrue(ExtractionStrategy.should_normalize(ExtractionStrategy.FULL))
        self.assertFalse(ExtractionStrategy.should_normalize(ExtractionStrategy.LIGHT))
    
    def test_content_length_limits(self):
        """测试内容长度限制"""
        full_len = ExtractionStrategy.get_max_content_length(ExtractionStrategy.FULL)
        light_len = ExtractionStrategy.get_max_content_length(ExtractionStrategy.LIGHT)
        
        self.assertGreater(full_len, light_len)
        self.assertEqual(full_len, 8000)
        self.assertEqual(light_len, 2000)


class TestFetchStrategy(unittest.TestCase):
    """P9: 抓取策略测试"""
    
    def test_stage_order(self):
        """测试三段式顺序"""
        stages = FetchStrategy.STAGES
        
        self.assertEqual(stages[0], "api_oa")
        self.assertEqual(stages[1], "html")
        self.assertEqual(stages[2], "browser")
    
    def test_get_next_stage(self):
        """测试获取下一阶段"""
        self.assertEqual(FetchStrategy.get_next_stage(None), "api_oa")
        self.assertEqual(FetchStrategy.get_next_stage("api_oa"), "html")
        self.assertEqual(FetchStrategy.get_next_stage("html"), "browser")
        self.assertIsNone(FetchStrategy.get_next_stage("browser"))
    
    def test_select_fetch_stages_with_doi(self):
        """测试有 DOI 时的抓取顺序"""
        paper = {"doi": "10.1234/test", "url": "https://example.com"}
        stages = FetchStrategy.select_fetch_stages(paper)
        
        self.assertEqual(stages[0], "api_oa")
        self.assertIn("html", stages)
        self.assertEqual(stages[-1], "browser")
    
    def test_select_fetch_stages_no_doi(self):
        """测试无 DOI 时的抓取顺序"""
        paper = {"url": "https://example.com"}
        stages = FetchStrategy.select_fetch_stages(paper)
        
        self.assertNotIn("api_oa", stages)
        self.assertEqual(stages[0], "html")


if __name__ == '__main__':
    unittest.main()
