import json
import time
import logging
from dataclasses import dataclass
from typing import Any, Callable
from pathlib import Path
from config.settings import settings

# 配置日志
log_dir = Path("logs")
log_dir.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(log_dir / 'chemdeep_debug.log', encoding='utf-8')
    ]
)
logger = logging.getLogger('ai')


import threading

# 模型状态持久化文件路径
MODEL_STATE_FILE = Path("data/model_state.json")

# 全局模型状态（跨线程共享）
class ModelState:
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    # 尝试从持久化文件加载
                    saved_state = cls._load_state()
                    cls._instance.openai_model = saved_state.get("openai_model", settings.OPENAI_MODEL)
                    cls._instance.gemini_model = saved_state.get("gemini_model", settings.GEMINI_MODEL)
                    cls._instance.openai_api_base = saved_state.get("openai_api_base", settings.OPENAI_API_BASE)
                    cls._instance.openai_api_key = settings.OPENAI_API_KEY  # API Key 不持久化
                    if saved_state:
                        logger.info(f"已从文件加载模型状态: {cls._instance.openai_model}")
        return cls._instance
    
    @staticmethod
    def _load_state() -> dict:
        """从文件加载模型状态"""
        try:
            if MODEL_STATE_FILE.exists():
                return json.loads(MODEL_STATE_FILE.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning(f"加载模型状态失败: {e}")
        return {}
    
    def _save_state(self):
        """保存模型状态到文件"""
        try:
            MODEL_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
            state = {
                "openai_model": self.openai_model,
                "gemini_model": self.gemini_model,
                "openai_api_base": self.openai_api_base,
            }
            MODEL_STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
            logger.debug(f"模型状态已保存: {state}")
        except Exception as e:
            logger.warning(f"保存模型状态失败: {e}")
    
    def set_openai_model(self, model: str):
        with self._lock:
            self.openai_model = model
            self._save_state()
            logger.info(f"全局 OpenAI 模型已设置为: {model}")
    
    def set_gemini_model(self, model: str):
        with self._lock:
            self.gemini_model = model
            self._save_state()
            logger.info(f"全局 Gemini 模型已设置为: {model}")
    
    def set_openai_api_base(self, api_base: str):
        with self._lock:
            self.openai_api_base = api_base
            self._save_state()
            logger.info(f"全局 OpenAI API 地址已设置为: {api_base}")
    
    def set_openai_api_key(self, api_key: str):
        with self._lock:
            self.openai_api_key = api_key
            # API Key 不持久化
            logger.info("全局 OpenAI API Key 已更新")
    
    def get_openai_model(self) -> str:
        with self._lock:
            return self.openai_model
    
    def get_gemini_model(self) -> str:
        with self._lock:
            return self.gemini_model


MODEL_STATE = ModelState()


@dataclass
class AIResponse:
    success: bool
    data: dict | None = None
    error: str | None = None
    provider: str | None = None
    model: str | None = None
    raw_response: str | None = None


@dataclass
class LLMConfig:
    provider: str | None = None
    model: str | None = None
    base_url: str | None = None
    api_key: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> 'LLMConfig | None':
        if not data:
            return None

        normalized: dict[str, str | None] = {}
        for key in ["provider", "model", "base_url", "api_key"]:
            value = data.get(key)
            if value is None:
                normalized[key] = None
                continue
            value_str = str(value).strip()
            normalized[key] = value_str or None

        if not any(normalized.values()):
            return None

        provider = normalized["provider"]
        if provider:
            provider = provider.lower()

        return cls(
            provider=provider,
            model=normalized["model"],
            base_url=normalized["base_url"],
            api_key=normalized["api_key"],
        )


class AIClient:
    def __init__(
        self,
        notify_callback: Callable[[str], None] | None = None,
        llm_config: LLMConfig | dict[str, Any] | None = None,
    ):
        self.notify = notify_callback or (lambda x: print(x))
        self.timeout = settings.AI_TIMEOUT
        self.max_retries = settings.AI_MAX_RETRIES
        self.llm_config = (
            llm_config
            if isinstance(llm_config, LLMConfig)
            else LLMConfig.from_dict(llm_config)
        )

        logger.info("初始化 AIClient")
        logger.info(f"  当前 OpenAI 模型: {self.current_openai_model}")
        logger.info(f"  当前 API: {self.current_openai_base_url}")
        if self.llm_config:
            logger.info(
                "  请求级 llm_config 已启用: provider=%s, model=%s, base_url=%s",
                self.llm_config.provider,
                self.llm_config.model,
                self.llm_config.base_url,
            )

        self._openai_client = None
        self._init_openai_client()
        
    def _init_openai_client(self):
        """初始化或重新初始化 OpenAI 客户端"""
        api_key = (
            (self.llm_config.api_key if self.llm_config else None)
            or MODEL_STATE.openai_api_key
            or settings.OPENAI_API_KEY
        )
        api_base = self.current_openai_base_url
        
        if api_key:
            try:
                import openai
                import httpx
                
                http_client = None
                if settings.OPENAI_PROXY:
                    logger.info(f"使用 OpenAI 代理: {settings.OPENAI_PROXY}")
                    http_client = httpx.Client(
                        proxy=settings.OPENAI_PROXY,
                        timeout=self.timeout
                    )
                
                self._openai_client = openai.OpenAI(
                    api_key=api_key,
                    base_url=api_base,
                    timeout=self.timeout,
                    http_client=http_client
                )
                logger.info(f"OpenAI 客户端初始化成功: {api_base}")
            except Exception as e:
                logger.error(f"OpenAI 客户端初始化失败: {e}")
        
        self._gemini_client = None
        gemini_api_key = (
            (self.llm_config.api_key if self.llm_config else None)
            or settings.GEMINI_API_KEY
        )
        if gemini_api_key:
            try:
                from google import genai
                
                # Google GenAI 代理配置
                http_options: Any = None
                if settings.GEMINI_PROXY:
                    logger.info(f"使用 Gemini 代理: {settings.GEMINI_PROXY}")
                    # 假设 httpx 格式
                    http_options = {'proxy': settings.GEMINI_PROXY}

                # 尝试初始化
                if http_options:
                     try:
                         self._gemini_client = genai.Client(api_key=gemini_api_key, http_options=http_options)
                     except TypeError:
                         logger.warning("当前 google-genai 版本不支持 http_options 代理配置，尝试默认初始化")
                         self._gemini_client = genai.Client(api_key=gemini_api_key)
                else:
                    self._gemini_client = genai.Client(api_key=gemini_api_key)

                logger.info("Gemini 客户端初始化成功")
            except Exception as e:
                logger.error(f"Gemini 客户端初始化失败: {e}")
    
    @property
    def current_openai_model(self) -> str:
        if self.llm_config and self.llm_config.model and self.llm_config.provider != "gemini":
            return self.llm_config.model
        return MODEL_STATE.openai_model

    @property
    def current_openai_base_url(self) -> str:
        if self.llm_config and self.llm_config.base_url:
            return self.llm_config.base_url
        return MODEL_STATE.openai_api_base or settings.OPENAI_API_BASE
    
    @current_openai_model.setter
    def current_openai_model(self, value: str):
        MODEL_STATE.set_openai_model(value)
    
    @property
    def current_gemini_model(self) -> str:
        if self.llm_config and self.llm_config.model and self.llm_config.provider == "gemini":
            return self.llm_config.model
        return MODEL_STATE.gemini_model
    
    @current_gemini_model.setter
    def current_gemini_model(self, value: str):
        MODEL_STATE.set_gemini_model(value)
    
    def set_model(self, provider: str, model: str) -> bool:
        provider = provider.lower()
        if provider == "openai":
            MODEL_STATE.set_openai_model(model)
            return True
        elif provider == "gemini":
            MODEL_STATE.set_gemini_model(model)
            return True
        return False
    
    def get_current_models(self) -> dict[str, str]:
        return {
            "openai": self.current_openai_model,
            "gemini": self.current_gemini_model,
            "provider": self.llm_config.provider if self.llm_config and self.llm_config.provider else settings.AI_PROVIDER
        }
    
    def fetch_openai_models(self) -> list[dict[str, Any]]:
        """获取全部模型列表"""
        if not self._openai_client:
            return []
        
        try:
            logger.info(f"正在获取模型列表: {self.current_openai_base_url}/models")
            models = self._openai_client.models.list()
            
            model_list = []
            for m in models.data:
                model_list.append({
                    "id": m.id,
                    "owned_by": getattr(m, "owned_by", "unknown"),
                    "object": getattr(m, "object", "model")
                })
            
            logger.info(f"获取到 {len(model_list)} 个模型")
            return model_list
        except Exception as e:
            logger.error(f"获取模型列表失败: {e}")
            return []
    
    def list_models(self, provider: str = "all", show_all: bool = False) -> str:
        """获取可用模型列表"""
        lines = ["🤖 AI 模型状态:\n"]
        
        if provider in ("all", "openai"):
            lines.append("【OpenAI 兼容 API】")
            if self._openai_client:
                try:
                    models = self.fetch_openai_models()
                    if models:
                        lines.append(f"  ✅ 连接正常 ({len(models)} 个模型)")
                        lines.append(f"  📍 API: {self.current_openai_base_url}")
                        lines.append(f"  🎯 当前: {self.current_openai_model}")
                        lines.append("  📋 可用模型:")
                        
                        # 显示全部或部分
                        display_count = len(models) if show_all else min(15, len(models))
                        for m in models[:display_count]:
                            marker = "→" if m["id"] == self.current_openai_model else " "
                            lines.append(f"    {marker} {m['id']}")
                        
                        if not show_all and len(models) > 15:
                            lines.append(f"    ... 还有 {len(models) - 15} 个")
                            lines.append("  💡 使用 /models all 查看全部")
                    else:
                        lines.append("  ⚠️ 无法获取模型列表")
                except Exception as e:
                    lines.append(f"  ❌ 连接失败: {e}")
            else:
                lines.append("  ⚪ 未配置")
            lines.append("")
        
        if provider in ("all", "gemini"):
            lines.append("【Google Gemini】")
            if self._gemini_client:
                try:
                    models = list(self._gemini_client.models.list())
                    gemini_models = [m.name for m in models if m.name and "gemini" in m.name.lower()]
                    lines.append(f"  ✅ 连接正常 ({len(gemini_models)} 个模型)")
                    lines.append(f"  🎯 当前: {self.current_gemini_model}")
                    lines.append("  📋 可用模型:")
                    for name in gemini_models[:10]:
                        marker = "→" if name == self.current_gemini_model else " "
                        lines.append(f"    {marker} {name}")
                except Exception as e:
                    lines.append(f"  ❌ 连接失败: {e}")
            else:
                lines.append("  ⚪ 未配置")
            lines.append("")
        
        return "\n".join(lines)
    
    def test_connection(self) -> dict[str, Any]:
        results: dict[str, Any] = {
            "openai": {"status": "not_configured"},
            "gemini": {"status": "not_configured"},
        }
        
        if self._openai_client:
            try:
                models = self.fetch_openai_models()
                if models:
                    results["openai"] = {
                        "status": "ok",
                        "models": [m["id"] for m in models],
                        "base_url": self.current_openai_base_url,
                        "current_model": self.current_openai_model
                    }
                else:
                    results["openai"] = {"status": "error", "error": "无法获取模型列表"}
            except Exception as e:
                results["openai"] = {"status": "error", "error": str(e)}
        
        if self._gemini_client:
            try:
                models = list(self._gemini_client.models.list())
                results["gemini"] = {
                    "status": "ok",
                    "models": [m.name for m in models if m.name and "gemini" in m.name.lower()][:10],
                    "current_model": self.current_gemini_model
                }
            except Exception as e:
                results["gemini"] = {"status": "error", "error": str(e)}
        
        return results
    
    def _call_openai(self, prompt: str, json_mode: bool = True) -> AIResponse:
        if not self._openai_client:
            return AIResponse(success=False, error="OpenAI 未配置")
        
        current_model = self.current_openai_model
        logger.info(f"调用 OpenAI: model={current_model}, json_mode={json_mode}")
        
        for attempt in range(self.max_retries):
            try:
                kwargs = {
                    "model": current_model,
                    "messages": [{"role": "user", "content": prompt}]
                }
                
                if json_mode:
                    kwargs["response_format"] = {"type": "json_object"}
                
                response = self._openai_client.chat.completions.create(**kwargs)
                content = response.choices[0].message.content
                
                logger.info(f"收到响应: {len(content or '')} 字符")
                logger.debug(f"原始响应: {content[:500] if content else 'None'}...")
                
                if not content:
                    return AIResponse(success=False, error="AI 返回空响应", provider="openai", model=current_model)
                
                if json_mode:
                    json_str = self._extract_json(content)
                    if json_str:
                        try:
                            data = json.loads(json_str)
                            return AIResponse(success=True, data=data, provider="openai", model=current_model, raw_response=content)
                        except json.JSONDecodeError as e:
                            logger.error(f"JSON 解析失败: {e}")
                            
                            # [P67] Auto Repair
                            if settings.JSON_REPAIR_RETRIES > 0:
                                logger.warning(f"  [Auto-Repair] 尝试使用 LLM 修复 JSON...")
                                repaired_str = self._repair_json_with_llm(content, "openai", current_model)
                                if repaired_str:
                                    try:
                                        data = json.loads(repaired_str)
                                        logger.info("  ✅ JSON 修复成功")
                                        return AIResponse(success=True, data=data, provider="openai", model=current_model, raw_response=content)
                                    except:
                                        logger.error("  ❌ 修复后仍无法解析")

                    return AIResponse(success=True, data={"text": content, "_parse_failed": True}, provider="openai", model=current_model, raw_response=content)
                else:
                    return AIResponse(success=True, data={"text": content}, provider="openai", model=current_model, raw_response=content)
            
            except Exception as e:
                err = str(e)
                logger.error(f"OpenAI 调用失败 ({attempt+1}/{self.max_retries}): {err}")
                
                if "timeout" in err.lower() or "10060" in err:
                    if attempt < self.max_retries - 1:
                        time.sleep(2 ** attempt)
                        continue
                    return AIResponse(success=False, error="请求超时", provider="openai", model=current_model)
                
                elif "does not support" in err.lower() or "response_format" in err.lower():
                    if json_mode:
                        logger.warning("模型不支持 JSON mode，尝试普通模式")
                        return self._call_openai(prompt, json_mode=False)
                
                return AIResponse(success=False, error=err, provider="openai", model=current_model)
        
        return AIResponse(success=False, error="未知错误", provider="openai", model=current_model)
    
    def _call_gemini(self, prompt: str) -> AIResponse:
        if not self._gemini_client:
            return AIResponse(success=False, error="Gemini 未配置")
        
        current_model = self.current_gemini_model
        logger.info(f"调用 Gemini: model={current_model}")
        
        for attempt in range(self.max_retries):
            try:
                response = self._gemini_client.models.generate_content(model=current_model, contents=prompt)
                content = response.text
                
                if not content:
                    return AIResponse(success=False, error="AI 返回空响应", provider="gemini", model=current_model)
                
                json_str = self._extract_json(content)
                if json_str:
                    try:
                        data = json.loads(json_str)
                        return AIResponse(success=True, data=data, provider="gemini", model=current_model, raw_response=content)
                    except json.JSONDecodeError:
                        pass
                
                return AIResponse(success=True, data={"text": content}, provider="gemini", model=current_model, raw_response=content)
            
            except Exception as e:
                if "timeout" in str(e).lower() and attempt < self.max_retries - 1:
                    time.sleep(2 ** attempt)
                    continue
                return AIResponse(success=False, error=str(e), provider="gemini", model=current_model)
        
        return AIResponse(success=False, error="未知错误", provider="gemini", model=current_model)
    
    
    def _repair_json_with_llm(self, malformed_json: str, provider: str, model: str) -> str | None:
        """[P67] 使用 LLM 修复恶意/格式错误的 JSON"""
        try:
            prompt = (
                "下面是一段本应为 JSON 的文本，但格式不合法。请只输出修复后的 JSON（不输出任何解释/markdown），保持原意。\n\n"
                f"{malformed_json}"
            )
            
            # Use direct calls to avoid recursion loops
            if provider == "openai" and self._openai_client:
                resp = self._openai_client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": prompt}],
                    response_format={"type": "json_object"}
                )
                text = resp.choices[0].message.content or ""
                return self._extract_json(text)
                
            elif provider == "gemini" and self._gemini_client:
                 resp = self._gemini_client.models.generate_content(
                     model=model,
                     contents=prompt
                 )
                 return self._extract_json(resp.text or "")
                 
        except Exception as e:
            logger.error(f"  [Auto-Repair] 修复过程出错: {e}")
            
        return None

    def _extract_json(self, text: str) -> str | None:
        if not text:
            return None
        
        text = text.strip()
        
        if text.startswith("{") or text.startswith("["):
            return text
        
        if "```json" in text:
            try:
                return text.split("```json")[1].split("```")[0].strip()
            except IndexError:
                pass
        
        if "```" in text:
            try:
                json_str = text.split("```")[1].split("```")[0].strip()
                if json_str.startswith("{") or json_str.startswith("["):
                    return json_str
            except IndexError:
                pass
        
        start = text.find("{")
        if start != -1:
            depth = 0
            for i, c in enumerate(text[start:], start):
                if c == "{":
                    depth += 1
                elif c == "}":
                    depth -= 1
                    if depth == 0:
                        return text[start:i+1]
        
        return None
    
    def call(self, prompt: str, provider: str | None = None, json_mode: bool = True) -> AIResponse:
        provider = provider or (self.llm_config.provider if self.llm_config else None) or settings.AI_PROVIDER
        logger.info(f"AI 调用: provider={provider}, model={self.current_openai_model}")
        
        if provider == "gemini":
            return self._call_gemini(prompt)
        elif provider == "openai":
            return self._call_openai(prompt, json_mode)
        elif provider == "auto":
            result = self._call_openai(prompt, json_mode)
            if not result.success and self._gemini_client:
                result = self._call_gemini(prompt)
            return result
        
        return AIResponse(success=False, error=f"未知provider: {provider}")
    
    def generate_search_strategy(self, user_query: str) -> AIResponse:
        prompt = f"""你是一个化学研究专家。请分析以下研究需求并生成文献检索策略。

用户需求：{user_query}

请严格按照以下 JSON 格式返回：
{{
    "keywords": ["关键词1", "关键词2", "关键词3"],
    "boolean_query": "TS=(关键词1 OR 关键词2) AND TS=(关键词3)",
    "google_scholar_query": "搜索词",
    "max_results": 50,
    "goal": "synthesis",
    "databases": ["WoS", "Google Scholar"],
    "rationale": "简要说明检索策略设计思路"
}}"""
        
        logger.info(f"生成搜索策略，使用模型: {self.current_openai_model}")
        
        result = self.call(prompt, json_mode=True)
        
        if result.success and result.data and result.data.get("_parse_failed"):
            result.data = self._fallback_strategy(user_query)
        
        if not result.success:
            result.data = self._fallback_strategy(user_query)
        
        return result
    
    def _fallback_strategy(self, user_query: str) -> dict:
        return {
            "keywords": [user_query],
            "boolean_query": f'TS=("{user_query}")',
            "google_scholar_query": user_query,
            "max_results": 20,
            "goal": "synthesis",
            "databases": ["WoS"],
            "rationale": "使用基本检索策略"
        }

def simple_chat(prompt: str, json_mode: bool = False) -> str:
    """
    简易对话接口，返回原始文本响应
    """
    client = get_ai_client()
    # 使用 auto provider 或默认
    resp = client.call(prompt, json_mode=json_mode)
    
    if not resp.success:
        logger.error(f"simple_chat failed: {resp.error}")
        raise Exception(f"AI call failed: {resp.error}")
        
    # 优先返回原始响应，以便调用方使用自己的 parser (如 _parse_json)
    if resp.raw_response:
        return resp.raw_response
        
    # Fallback
    if resp.data and "text" in resp.data:
        return resp.data["text"]
    
    return json.dumps(resp.data, ensure_ascii=False) if resp.data else ""


# ============================================================
# [P30] Singleton AI Client Pattern
# ============================================================
_ai_client_instance: AIClient | None = None
_ai_client_lock = threading.Lock()

def get_ai_client(notify_callback: Callable[[str], None] | None = None) -> AIClient:
    """
    [P30] Get or create singleton AIClient instance.
    
    Ensures AI is initialized only once, reducing overhead and log spam.
    Thread-safe via lock.
    
    Usage:
        from core.ai import get_ai_client
        ai = get_ai_client()
        response = ai.call(prompt)
    """
    global _ai_client_instance
    
    with _ai_client_lock:
        if _ai_client_instance is None:
            logger.info("[P30] Initializing singleton AIClient...")
            _ai_client_instance = AIClient(notify_callback=notify_callback)
        return _ai_client_instance


def create_ai_client(
    llm_config: dict[str, Any] | LLMConfig | None = None,
    notify_callback: Callable[[str], None] | None = None,
) -> AIClient:
    """根据 llm_config 创建请求级 AIClient；未传时复用现有单例。"""
    normalized = (
        llm_config
        if isinstance(llm_config, LLMConfig)
        else LLMConfig.from_dict(llm_config)
    )
    if normalized is None:
        return get_ai_client(notify_callback=notify_callback)
    return AIClient(notify_callback=notify_callback, llm_config=normalized)


def reset_ai_client():
    """Reset singleton for testing or reconfiguration."""
    global _ai_client_instance
    with _ai_client_lock:
        _ai_client_instance = None
        logger.info("[P30] AIClient singleton reset")