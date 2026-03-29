"""
Run Manager Module (P8)
可观测性：运行产物管理、指标收集、错误记录
"""
import json
import logging
import uuid
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional
from contextlib import contextmanager

logger = logging.getLogger('deep_research')

# ============================================================
# 常量配置
# ============================================================
RUNS_DIR = Path("runs")


# ============================================================
# 指标数据结构
# ============================================================
@dataclass
class StageMetrics:
    """单阶段指标"""
    name: str
    start_time: float = 0.0
    end_time: float = 0.0
    duration_seconds: float = 0.0
    success: bool = True
    error_count: int = 0
    items_processed: int = 0
    items_successful: int = 0


@dataclass
class RunMetrics:
    """运行指标"""
    run_id: str
    started_at: str = ""
    ended_at: str = ""
    total_duration_seconds: float = 0.0
    
    # 阶段耗时
    stages: Dict[str, StageMetrics] = field(default_factory=dict)
    
    # 抓取统计
    fetch_total: int = 0
    fetch_success: int = 0
    fetch_failed: int = 0
    fetch_cached: int = 0
    
    # 证据统计
    evidence_total: int = 0
    evidence_fulltext: int = 0
    evidence_abstract: int = 0
    evidence_original: int = 0
    
    # 仲裁统计
    adjudication_total: int = 0
    adjudication_confirmed: int = 0
    adjudication_disputed: int = 0
    
    # Snowball 统计
    snowball_seeds: int = 0
    snowball_candidates: int = 0
    snowball_relevant: int = 0
    
    # LLM 统计
    llm_calls: int = 0
    llm_cached: int = 0
    llm_tokens_in: int = 0
    llm_tokens_out: int = 0
    
    def to_dict(self) -> dict:
        data = asdict(self)
        data["stages"] = {k: asdict(v) for k, v in self.stages.items()}
        return data


@dataclass
class ErrorRecord:
    """错误记录"""
    timestamp: str
    stage: str
    error_type: str
    error_message: str
    context: Dict[str, Any] = field(default_factory=dict)
    
    def to_jsonl(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)


# ============================================================
# Run Manager
# ============================================================
class RunManager:
    """运行管理器"""
    
    def __init__(self, run_id: str = None):
        self.run_id = run_id or datetime.now().strftime("%Y%m%d_%H%M%S_") + uuid.uuid4().hex[:6]
        self.run_dir = RUNS_DIR / self.run_id
        self.run_dir.mkdir(parents=True, exist_ok=True)
        
        self.metrics = RunMetrics(run_id=self.run_id)
        self.errors: List[ErrorRecord] = []
        self.config: Dict[str, Any] = {}
        
        self._start_time = time.time()
        self.metrics.started_at = datetime.now().isoformat()
        
        logger.info(f"🚀 Run started: {self.run_id}")
    
    @contextmanager
    def stage(self, name: str):
        """阶段计时上下文管理器"""
        stage = StageMetrics(name=name, start_time=time.time())
        self.metrics.stages[name] = stage
        
        try:
            yield stage
            stage.success = True
        except Exception as e:
            stage.success = False
            self.record_error(name, type(e).__name__, str(e))
            raise
        finally:
            stage.end_time = time.time()
            stage.duration_seconds = stage.end_time - stage.start_time
    
    def record_error(self, stage: str, error_type: str, message: str, context: dict = None):
        """记录错误"""
        error = ErrorRecord(
            timestamp=datetime.now().isoformat(),
            stage=stage,
            error_type=error_type,
            error_message=message,
            context=context or {}
        )
        self.errors.append(error)
        
        if stage in self.metrics.stages:
            self.metrics.stages[stage].error_count += 1
    
    def set_config(self, config: dict):
        """设置配置快照"""
        self.config = config
    
    def update_fetch_stats(self, success: int = 0, failed: int = 0, cached: int = 0):
        """更新抓取统计"""
        self.metrics.fetch_success += success
        self.metrics.fetch_failed += failed
        self.metrics.fetch_cached += cached
        self.metrics.fetch_total += success + failed
    
    def update_evidence_stats(self, total: int = 0, fulltext: int = 0, abstract: int = 0, original: int = 0):
        """更新证据统计"""
        self.metrics.evidence_total = total
        self.metrics.evidence_fulltext = fulltext
        self.metrics.evidence_abstract = abstract
        self.metrics.evidence_original = original
    
    def update_adjudication_stats(self, confirmed: int = 0, disputed: int = 0):
        """更新仲裁统计"""
        self.metrics.adjudication_confirmed += confirmed
        self.metrics.adjudication_disputed += disputed
        self.metrics.adjudication_total += confirmed + disputed
    
    def update_snowball_stats(self, seeds: int = 0, candidates: int = 0, relevant: int = 0):
        """更新 Snowball 统计"""
        self.metrics.snowball_seeds += seeds
        self.metrics.snowball_candidates += candidates
        self.metrics.snowball_relevant += relevant
    
    def update_llm_stats(self, calls: int = 0, cached: int = 0, tokens_in: int = 0, tokens_out: int = 0):
        """更新 LLM 统计"""
        self.metrics.llm_calls += calls
        self.metrics.llm_cached += cached
        self.metrics.llm_tokens_in += tokens_in
        self.metrics.llm_tokens_out += tokens_out
    
    def save_artifacts(self, report_md: str = None, report_json: dict = None, 
                       decisions_jsonl: str = None, hypothesis_trails: Dict[str, str] = None):
        """保存运行产物"""
        # 保存报告
        if report_md:
            (self.run_dir / "report.md").write_text(report_md, encoding="utf-8")
        
        if report_json:
            (self.run_dir / "report.json").write_text(
                json.dumps(report_json, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        
        # 复制决策日志
        if decisions_jsonl:
            (self.run_dir / "decisions.jsonl").write_text(decisions_jsonl, encoding="utf-8")
        
        # 保存假设 trail
        if hypothesis_trails:
            for h_id, trail_content in hypothesis_trails.items():
                (self.run_dir / f"hypothesis_{h_id}_trail.md").write_text(trail_content, encoding="utf-8")
    
    def finalize(self):
        """完成运行，保存指标和错误"""
        self.metrics.ended_at = datetime.now().isoformat()
        self.metrics.total_duration_seconds = time.time() - self._start_time
        
        # 保存 metrics.json
        (self.run_dir / "metrics.json").write_text(
            json.dumps(self.metrics.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        
        # 保存 errors.jsonl
        if self.errors:
            with open(self.run_dir / "errors.jsonl", "w", encoding="utf-8") as f:
                for error in self.errors:
                    f.write(error.to_jsonl() + "\n")
        
        # 保存 config.json
        if self.config:
            (self.run_dir / "config.json").write_text(
                json.dumps(self.config, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        
        logger.info(f"✅ Run completed: {self.run_id} ({self.metrics.total_duration_seconds:.1f}s)")
        
        return self.run_dir


# ============================================================
# 全局 Run Manager (单例模式)
# ============================================================
_current_run: Optional[RunManager] = None


def get_current_run() -> Optional[RunManager]:
    """获取当前 run"""
    return _current_run


def start_run(run_id: str = None) -> RunManager:
    """启动新 run"""
    global _current_run
    _current_run = RunManager(run_id)
    return _current_run


def end_run() -> Optional[Path]:
    """结束当前 run"""
    global _current_run
    if _current_run:
        path = _current_run.finalize()
        _current_run = None
        return path
    return None
