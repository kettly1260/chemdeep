"""
Bot 运行器

负责启动和运行 Telegram Bot 主循环
"""
import time
import logging
from pathlib import Path

from .client import TelegramClient
from core.ai import AIClient
from utils.db import DB
from utils.notifier import Notifier
from config.settings import settings

from .handlers.callback_handler import handle_callback_query
from .handlers.message_router import route_message, handle_file_upload

logger = logging.getLogger('main')


class BotRunner:
    """Bot 运行器"""
    
    def __init__(self):
        self.tg = None
        self.db = None
        self.notifier = None
        self.global_ai = None
        self.download_dir = None
    
    def run(self):
        """启动 Bot 主循环"""
        import typer
        
        # 验证配置
        errors = settings.validate()
        if errors:
            for e in errors:
                typer.echo(f"❌ {e}")
            raise typer.Exit(1)
        
        self.tg = TelegramClient()
        self.db = DB()
        self.notifier = Notifier(self.tg, settings.TELEGRAM_CHAT_ID)
        self.global_ai = AIClient(notify_callback=lambda x: logger.info(x))
        
        self.download_dir = settings.LIBRARY_DIR / "uploads"
        self.download_dir.mkdir(parents=True, exist_ok=True)
        
        offset = self.db.kv_get_int("telegram_offset")
        
        typer.echo("=" * 50)
        typer.echo("Deep Research Bot running... (Ctrl+C to stop)")
        typer.echo("=" * 50)
        typer.echo(settings.summary())
        typer.echo("=" * 50)
        logger.info("Bot 启动")
        
        self._main_loop(offset)
    
    def _main_loop(self, offset: int):
        """主消息处理循环"""
        while True:
            try:
                updates = self.tg.get_updates(offset=offset, timeout=25)
            except Exception as e:
                import httpx
                # [P55] Handle common network flakes gracefully
                if isinstance(e, (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError)):
                    logger.warning(f"网络连接不稳定 (重试中): {e}")
                    time.sleep(10) # Longer backoff
                else:
                    logger.error(f"获取更新失败: {e}")
                    time.sleep(10)
                continue
            
            for u in updates:
                offset = int(u["update_id"]) + 1
                self.db.kv_set("telegram_offset", str(offset))
                
                try:
                    self._handle_update(u)
                except Exception as e:
                    logger.error(f"处理更新失败: {e}", exc_info=True)
            
            time.sleep(0.2)
    
    def _handle_update(self, u: dict):
        """处理单个更新"""
        
        # 处理 callback_query (按钮点击)
        callback_query = u.get("callback_query")
        if callback_query:
            handle_callback_query(callback_query, self.tg, self.db, settings)
            return
        
        msg = u.get("message") or u.get("edited_message")
        if not msg:
            return
        
        chat = msg.get("chat", {})
        chat_id = chat.get("id")
        text = (msg.get("text") or "").strip()
        
        if not chat_id or chat_id not in settings.TELEGRAM_ALLOWED_CHAT_IDS:
            return
        
        # 处理文件上传
        if msg.get("document"):
            handle_file_upload(msg, chat_id, self.tg, self.db, self.download_dir)
            return
        
        if not text:
            return
        
        logger.info(f"收到消息 [{chat_id}]: {text[:100]}...")
        
        # 路由到命令处理器
        handled = route_message(chat_id, text, self.tg, self.db, self.download_dir)
        
        if not handled:
            # 未识别的命令 - 可以添加默认处理
            pass
