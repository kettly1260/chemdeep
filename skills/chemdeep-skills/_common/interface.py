"""
通用Skill接口层，支持多语言/多领域、API、plugin、hook三类扩展。
"""
from typing import Any, Dict, Callable

class SkillInterface:
    def __init__(self, name: str, supported_languages=None, supported_fields=None):
        self.name = name
        self.supported_languages = supported_languages or ['zh', 'en']
        self.supported_fields = supported_fields or ['chemistry', 'materials']
        self.hooks = {}

    def register_hook(self, event: str, func: Callable):
        self.hooks[event] = func

    def call_hook(self, event: str, *args, **kwargs):
        if event in self.hooks:
            return self.hooks[event](*args, **kwargs)
        return None

    def run(self, query: str, language: str = 'zh', field: str = 'chemistry', mode: str = 'api', **kwargs) -> Dict[str, Any]:
        """
        主入口，支持API、plugin、hook三类调用。
        """
        # 预留hook
        self.call_hook('before_run', query, language, field, mode, **kwargs)
        # 具体实现由子类覆盖
        result = self._run(query, language, field, mode, **kwargs)
        self.call_hook('after_run', result)
        return result

    def _run(self, query: str, language: str, field: str, mode: str, **kwargs) -> Dict[str, Any]:
        raise NotImplementedError("Skill需实现_run方法")
