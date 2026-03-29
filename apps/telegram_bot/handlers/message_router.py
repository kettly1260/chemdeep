"""
消息路由器

使用 CommandRegistry 分发命令
"""
import logging
from pathlib import Path
from apps.telegram_bot.command_registry import CommandRegistry
from apps.telegram_bot.commands import register_all

logger = logging.getLogger('main')

# Initialize Singleton Registry for this process
registry = CommandRegistry()
register_all(registry)

def route_message(chat_id: int, text: str, tg, db, download_dir: Path) -> bool:
    """
    将消息路由到对应的命令处理器
    """
    if not text:
        return False
        
    user_id = chat_id # Implicitly assume private chat or check from update
    # Note: route_message signature in runner might need update to pass full message object
    # for cleaner user_id extraction. But usually chat_id == user_id in private chats.
    # For now, use chat_id as user_id.

    ctx = {
        "tg": tg,
        "db": db,
        "chat_id": chat_id,
        "user_id": user_id, 
        "download_dir": download_dir,
        "registry": registry
    }
    
    # Try Dispatch
    if registry.dispatch(text, ctx):
        return True
        
    # [P60] Clarification Answer Capture
    # If not a command, check if we are in a clarification session
    if not text.startswith("/"):
        session_key = f"clarify_session_{chat_id}"
        session_json = db.kv_get(session_key)
        if session_json:
            import json
            try:
                session = json.loads(session_json)
                answers = session.get("answers", [])
                answers.append(text)
                session["answers"] = answers
                db.kv_set(session_key, json.dumps(session))
                
                tg.send_message(chat_id, f"✅ 已记录回答 ({len(answers)}). 请回复下一条或点击 [开始研究]")
                return True
            except Exception as e:
                logger.error(f"Clarification capture error: {e}")
                
    # Unknown command handling
    if text.startswith("/"):
        tg.send_message(chat_id, "⚠️ 未知命令，请发送 /help 查看可用命令")
        return True
        
    return False

def handle_file_upload(msg: dict, chat_id: int, tg, db, download_dir: Path) -> None:
    """处理文件上传"""
    import threading
    
    doc = msg["document"]
    file_name = doc.get("file_name", "uploaded_file")
    file_id = doc.get("file_id")
    
    if not file_name.lower().endswith(('.txt', '.csv', '.ris')):
        tg.send_message(chat_id, "⚠️ 请上传 .txt, .csv 或 .ris 格式的文献导出文件")
        return
    
    logger.info(f"收到文件上传: {file_name}")
    tg.send_message(chat_id, f"📥 正在下载文件: {file_name}")
    
    def handle_upload():
        try:
            file_path = tg.download_file(file_id, download_dir / file_name)
            if file_path and file_path.exists():
                tg.send_message(chat_id, 
                    f"✅ 文件已保存: {file_path.name}\n\n"
                    f"使用以下命令开始分析:\n"
                    f"/run --last --max 50"
                )
                db.kv_set(f"last_upload_{chat_id}", str(file_path))
            else:
                tg.send_message(chat_id, "❌ 文件下载失败")
        except Exception as e:
            logger.error(f"文件处理失败: {e}")
            tg.send_message(chat_id, f"❌ 文件处理失败: {e}")
    
    threading.Thread(target=handle_upload, daemon=True).start()
