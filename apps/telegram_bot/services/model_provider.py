"""
Model Provider Service

负责拉取模型列表、缓存、过滤
"""
import hashlib
import json
import time
import logging
from pathlib import Path
from typing import List, Dict, Any
import httpx
from .runtime_config import UserConfig

logger = logging.getLogger("bot")
CACHE_DIR = Path("cache/models")
CACHE_DIR.mkdir(parents=True, exist_ok=True)

NON_CHAT_KEYWORDS = ["embedding", "moderation", "tts", "whisper", "dall-e", "image", "audio"]

def _get_cache_path(base_url: str, provider: str, user_id: int) -> Path:
    """生成缓存路径 (Scope by User + Endpoint)"""
    # 虽然不同用户可能用同一 Endpoint，但 Key 可能不同，导致权限不同
    # 安全起见，缓存按 (API_KEY hash + Endpoint) 或 (User + Endpoint) 隔离
    # 这里简单按 (User + Endpoint) 隔离
    sig = f"{user_id}:{base_url}:{provider}"
    h = hashlib.md5(sig.encode()).hexdigest()
    return CACHE_DIR / f"{h}.json"

def fetch_models(config: UserConfig, force_refresh: bool = False) -> List[str]:
    """
    拉取模型列表
    1. 尝试 24h 内有效缓存
    2. force_refresh=True 或缓存失效 -> 请求 API
    3. API 失败 -> 尝试过期缓存
    4. 均失败 -> 返回空列表 (或 basic fallback)
    """
    cache_path = _get_cache_path(config.base_url, config.provider, config.user_id)
    now = time.time()
    
    # 1. 尝试读取有效缓存
    if not force_refresh and cache_path.exists():
        try:
            data = json.loads(cache_path.read_text("utf-8"))
            if now - data["ts"] < 86400: # 24h
                return data["models"]
        except Exception:
            pass # Cache corrupted
            
    # 2. Fetch from API
    try:
        models = _fetch_from_api(config)
        # 写入缓存
        cache_path.write_text(json.dumps({
            "ts": now,
            "models": models
        }), "utf-8")
        return models
    except Exception as e:
        logger.error(f"Fetch models failed: {e}")
        
    # 3. Fallback to stale cache
    if cache_path.exists():
        try:
            data = json.loads(cache_path.read_text("utf-8"))
            return data["models"]
        except Exception:
            pass
            
    # 4. Final Fallback (Empty)
    return []

def _fetch_from_api(config: UserConfig) -> List[str]:
    """实际 HTTP 请求"""
    if config.provider == "gemini":
        # Gemini 暂未标准化 list models via OpenAI compat in some proxies
        # 简单假设它支持标准 /v1/models (如果是通过 OneAPI/NewAPI 转接)
        # 否则如果是原生 SDK，逻辑较复杂，这里假设走 OpenAI 兼容层
        pass
        
    url = f"{config.base_url.rstrip('/')}/models"
    headers = {"Authorization": f"Bearer {config.api_key}"}
    
    with httpx.Client(timeout=10.0) as client:
        r = client.get(url, headers=headers)
        r.raise_for_status()
        data = r.json()
        
    raw_list = data.get("data", [])
    models = []
    
    for item in raw_list:
        mid = item.get("id", "")
        if not mid:
            continue
        # Filter Logic
        if any(k in mid.lower() for k in NON_CHAT_KEYWORDS):
            continue
        models.append(mid)
        
    return sorted(models)
