from apps.telegram_bot.client import TelegramClient


class Notifier:
    def __init__(self, tg: TelegramClient | None, chat_id: int | None):
        self._tg = tg
        self._chat_id = chat_id
        self._last_pct = None
        self._last_msg = None
        # 用于消息编辑的状态
        self._progress_message_id: int | None = None
    
    def send(self, text: str) -> int | None:
        """发送新消息，返回 message_id"""
        if not self._tg or not self._chat_id:
            return None
        result = self._tg.send_message(self._chat_id, text)
        if result:
            return result.get("message_id")
        return None
    
    def send_or_update(self, text: str, message_id: int | None = None) -> int | None:
        """发送新消息或更新已有消息"""
        if not self._tg or not self._chat_id:
            return None
        
        if message_id:
            # 尝试编辑已有消息
            if self._tg.edit_message(self._chat_id, message_id, text):
                return message_id
        
        # 发送新消息
        return self.send(text)
    
    def progress_update(self, text: str) -> None:
        """更新进度消息（在原消息上编辑）"""
        if not self._tg or not self._chat_id:
            return
        
        if self._progress_message_id:
            # 编辑已有的进度消息
            self._tg.edit_message(self._chat_id, self._progress_message_id, text)
        else:
            # 发送新消息并保存 ID
            self._progress_message_id = self.send(text)
    
    def reset_progress(self) -> None:
        """重置进度消息 ID（开始新任务时调用）"""
        self._progress_message_id = None
        self._last_pct = None
        self._last_msg = None
    
    def progress(self, pct: float, msg: str):
        """兼容旧的进度接口"""
        pct_i = max(0, min(100, int(pct)))
        if self._last_pct is None or pct_i >= self._last_pct + 5 or msg != self._last_msg:
            self._last_pct = pct_i
            self._last_msg = msg
            self.progress_update(f"[{pct_i}%] {msg}")