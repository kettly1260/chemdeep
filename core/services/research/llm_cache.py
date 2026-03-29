"""
LLM Cache Module (P9)
成本优化：LLM 调用缓存 (TTL = 30 天)
"""
import json
import logging
import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, Any, Tuple

logger = logging.getLogger('deep_research')

# ============================================================
# 常量配置
# ============================================================
LLM_CACHE_DIR = Path("cache/llm")
LLM_CACHE_TTL_DAYS = 30


@dataclass
class CacheEntry:
    """缓存条目"""
    prompt_hash: str
    response: str
    model: str
    cached_at: str
    tokens_in: int = 0
    tokens_out: int = 0


class LLMCache:
    """LLM 调用缓存"""
    
    def __init__(self, cache_dir: Path = None, ttl_days: int = LLM_CACHE_TTL_DAYS):
        self.cache_dir = cache_dir or LLM_CACHE_DIR
        self.ttl = timedelta(days=ttl_days)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        
        # 统计
        self.hits = 0
        self.misses = 0
    
    def _hash_prompt(self, prompt: str, model: str = "", json_mode: bool = False) -> str:
        """生成 prompt 哈希"""
        content = f"{model}|{json_mode}|{prompt}"
        return hashlib.sha256(content.encode()).hexdigest()[:16]
    
    def _get_cache_path(self, prompt_hash: str) -> Path:
        return self.cache_dir / f"{prompt_hash}.json"
    
    def get(self, prompt: str, model: str = "", json_mode: bool = False) -> Optional[str]:
        """获取缓存的响应"""
        prompt_hash = self._hash_prompt(prompt, model, json_mode)
        path = self._get_cache_path(prompt_hash)
        
        if not path.exists():
            self.misses += 1
            return None
        
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            cached_at = datetime.fromisoformat(data.get("cached_at", ""))
            
            if datetime.now() - cached_at > self.ttl:
                logger.debug(f"LLM 缓存过期: {prompt_hash}")
                path.unlink()
                self.misses += 1
                return None
            
            self.hits += 1
            logger.debug(f"LLM 缓存命中: {prompt_hash}")
            return data.get("response")
            
        except Exception as e:
            logger.warning(f"LLM 缓存读取失败: {e}")
            self.misses += 1
            return None
    
    def set(self, prompt: str, response: str, model: str = "", json_mode: bool = False,
            tokens_in: int = 0, tokens_out: int = 0) -> None:
        """写入缓存"""
        prompt_hash = self._hash_prompt(prompt, model, json_mode)
        path = self._get_cache_path(prompt_hash)
        
        data = {
            "prompt_hash": prompt_hash,
            "response": response,
            "model": model,
            "json_mode": json_mode,
            "cached_at": datetime.now().isoformat(),
            "tokens_in": tokens_in,
            "tokens_out": tokens_out
        }
        
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.debug(f"LLM 缓存写入: {prompt_hash}")
    
    def get_stats(self) -> Dict[str, Any]:
        """获取缓存统计"""
        total = self.hits + self.misses
        hit_rate = self.hits / total if total > 0 else 0.0
        return {
            "hits": self.hits,
            "misses": self.misses,
            "total": total,
            "hit_rate": round(hit_rate, 3)
        }
    
    def clear(self) -> int:
        """清空缓存"""
        count = 0
        for f in self.cache_dir.glob("*.json"):
            f.unlink()
            count += 1
        return count
    
    def prune_expired(self) -> int:
        """清理过期缓存"""
        count = 0
        for f in self.cache_dir.glob("*.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                cached_at = datetime.fromisoformat(data.get("cached_at", ""))
                if datetime.now() - cached_at > self.ttl:
                    f.unlink()
                    count += 1
            except Exception:
                pass
        return count


# ============================================================
# 全局缓存实例
# ============================================================
_llm_cache: Optional[LLMCache] = None


def get_llm_cache() -> LLMCache:
    """获取全局 LLM 缓存"""
    global _llm_cache
    if _llm_cache is None:
        _llm_cache = LLMCache()
    return _llm_cache


def cached_llm_call(prompt: str, model: str = "", json_mode: bool = False,
                    call_fn=None) -> Tuple[str, bool]:
    """
    带缓存的 LLM 调用
    
    Args:
        prompt: 提示词
        model: 模型名称
        json_mode: 是否 JSON 模式
        call_fn: 实际调用函数 () -> str
    
    Returns:
        (response, cache_hit)
    """
    cache = get_llm_cache()
    
    # 检查缓存
    cached = cache.get(prompt, model, json_mode)
    if cached is not None:
        return cached, True
    
    # 实际调用
    if call_fn is None:
        raise ValueError("call_fn is required for cache miss")
    
    response = call_fn()
    
    # 写入缓存
    cache.set(prompt, response, model, json_mode)
    
    return response, False


# ============================================================
# 抽取分层策略 (P9)
# ============================================================
class ExtractionStrategy:
    """抽取策略"""
    
    LIGHT = "light"       # 轻抽取 (abstract_only)
    FULL = "full"         # 完整抽取 (full_text)
    
    @staticmethod
    def get_strategy(content_level: str) -> str:
        """根据内容级别选择策略"""
        if content_level in ("full_text", "FULL_TEXT"):
            return ExtractionStrategy.FULL
        return ExtractionStrategy.LIGHT
    
    @staticmethod
    def should_normalize(strategy: str) -> bool:
        """是否进行归一化"""
        return strategy == ExtractionStrategy.FULL
    
    @staticmethod
    def get_max_content_length(strategy: str) -> int:
        """获取最大内容长度"""
        if strategy == ExtractionStrategy.FULL:
            return 8000
        return 2000  # 轻抽取限制更短


# ============================================================
# 抓取策略 (P9)
# ============================================================
class FetchStrategy:
    """抓取三段式策略"""
    
    # 优先级顺序
    STAGES = [
        "api_oa",      # 1. API / Open Access PDF
        "html",        # 2. HTML 解析
        "browser"      # 3. 浏览器抓取
    ]
    
    @staticmethod
    def get_next_stage(current: str = None) -> Optional[str]:
        """获取下一个抓取阶段"""
        if current is None:
            return FetchStrategy.STAGES[0]
        
        try:
            idx = FetchStrategy.STAGES.index(current)
            if idx + 1 < len(FetchStrategy.STAGES):
                return FetchStrategy.STAGES[idx + 1]
        except ValueError:
            pass
        
        return None
    
    @staticmethod
    def should_try_api(paper: dict) -> bool:
        """是否尝试 API 抓取"""
        # 有 DOI 或 OpenAlex ID 时优先 API
        return bool(paper.get("doi") or paper.get("id"))
    
    @staticmethod
    def should_try_html(paper: dict) -> bool:
        """是否尝试 HTML 抓取"""
        return bool(paper.get("url") or paper.get("primary_location", {}).get("landing_page_url"))
    
    @staticmethod
    def select_fetch_stages(paper: dict) -> list:
        """选择抓取阶段顺序"""
        stages = []
        
        if FetchStrategy.should_try_api(paper):
            stages.append("api_oa")
        
        if FetchStrategy.should_try_html(paper):
            stages.append("html")
        
        stages.append("browser")  # 浏览器作为最后手段
        
        return stages
