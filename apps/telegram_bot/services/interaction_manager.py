"""
Interaction Manager
用于协调后台线程与用户交互 (Blocking Ask)
"""
import threading
from typing import Dict, Any, Optional

class InteractionManager:
    _instance = None
    _lock = threading.Lock()
    
    def __init__(self):
        # chat_id -> { "event": Event, "result": str, "message_id": int }
        self.pending: Dict[int, Dict[str, Any]] = {}
        
    @classmethod
    def get_instance(cls):
        if not cls._instance:
            with cls._lock:
                if not cls._instance:
                    cls._instance = cls()
        return cls._instance

    def request_interaction(self, chat_id: int) -> threading.Event:
        """注册一个交互请求，返回用于等待的 Event"""
        event = threading.Event()
        self.pending[chat_id] = {
            "event": event,
            "result": None
        }
        return event

    def resolve_interaction(self, chat_id: int, result: str):
        """解决交互请求 (由 CallbackHandler 调用)"""
        if chat_id in self.pending:
            self.pending[chat_id]["result"] = result
            self.pending[chat_id]["event"].set()

    def get_result(self, chat_id: int) -> Optional[str]:
        """获取结果并清理"""
        if chat_id in self.pending:
            res = self.pending[chat_id]["result"]
            del self.pending[chat_id]
            return res
        return None

    def has_pending(self, chat_id: int) -> bool:
        return chat_id in self.pending
