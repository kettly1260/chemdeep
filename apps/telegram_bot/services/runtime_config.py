"""
Runtime Configuration Service

处理 per-user 配置 (Overriding .env)
优先读取 KV (tg:{user_id}:*)，无则回退到 .env
"""
from dataclasses import dataclass
from typing import Literal
from config.settings import settings
from utils.db import DB
from .crypto import decrypt_key, encrypt_key, mask_key

KEY_PREFIX = "tg:{user_id}:"

@dataclass
class UserConfig:
    user_id: int
    model: str
    base_url: str
    provider: str
    api_key: str  # Decrypted or from env
    
    # Metadata
    model_source: Literal["env", "runtime"]
    base_url_source: Literal["env", "runtime"]
    key_source: Literal["env", "runtime"]
    
    def masked_key(self) -> str:
        return mask_key(self.api_key)

def get_user_config(user_id: int, db: DB = None) -> UserConfig:
    """获取用户最终生效配置"""
    if db is None:
        db = DB()
    
    # 获取全局 ModelState (AI 模块实际使用的配置)
    try:
        from core.ai import ModelState
        model_state = ModelState()
        global_model = model_state.openai_model
        global_base_url = model_state.openai_api_base
    except Exception:
        global_model = settings.OPENAI_MODEL
        global_base_url = settings.OPENAI_API_BASE
        
    p = KEY_PREFIX.format(user_id=user_id)
    
    # Model: 用户覆盖 > 全局 ModelState > settings
    rt_model = db.kv_get(f"{p}model")
    final_model = rt_model if rt_model else global_model
    model_src = "runtime" if rt_model else "env"
    
    # Base URL: 用户覆盖 > 全局 ModelState > settings
    rt_url = db.kv_get(f"{p}base_url")
    final_url = rt_url if rt_url else global_base_url
    url_src = "runtime" if rt_url else "env"
    
    # Provider (Default OpenAI compatible if not set)
    rt_provider = db.kv_get(f"{p}provider")
    final_provider = rt_provider if rt_provider else settings.AI_PROVIDER
    
    # API Key
    rt_key_enc = db.kv_get(f"{p}api_key_enc")
    if rt_key_enc:
        final_key = decrypt_key(rt_key_enc)
        key_src = "runtime"
    else:
        # Fallback based on provider
        if final_provider == "gemini":
            final_key = settings.GEMINI_API_KEY
        else:
            final_key = settings.OPENAI_API_KEY
        key_src = "env"
        
    return UserConfig(
        user_id=user_id,
        model=final_model,
        base_url=final_url,
        provider=final_provider,
        api_key=final_key,
        model_source=model_src,
        base_url_source=url_src,
        key_source=key_src
    )

def set_user_config(user_id: int, key: str, value: str | None, db: DB = None):
    """设置用户配置 (None 表示删除回退到 env)"""
    if db is None:
        db = DB()
    p = KEY_PREFIX.format(user_id=user_id)
    
    if key == "api_key":
        # 特殊处理加密
        if value:
            enc = encrypt_key(value)
            db.kv_set(f"{p}api_key_enc", enc)
        else:
            db.kv_delete(f"{p}api_key_enc")
    else:
        db.kv_set(f"{p}{key}", value)
    
    # 同步到全局 ModelState (确保 AI 模块使用相同配置)
    if key == "model" and value:
        try:
            from core.ai import ModelState
            ModelState().set_openai_model(value)
        except Exception as e:
            import logging
            logging.getLogger('runtime_config').warning(f"同步模型到 ModelState 失败: {e}")
    elif key == "base_url" and value:
        try:
            from core.ai import ModelState
            ModelState().set_openai_api_base(value)
        except Exception as e:
            import logging
            logging.getLogger('runtime_config').warning(f"同步 API Base 到 ModelState 失败: {e}")

def reset_user_config(user_id: int, db: DB = None):
    """重置所有用户配置"""
    if db is None:
        db = DB()
    p = KEY_PREFIX.format(user_id=user_id)
    db.kv_delete(f"{p}model")
    db.kv_delete(f"{p}base_url")
    db.kv_delete(f"{p}provider")
    db.kv_delete(f"{p}api_key_enc")
