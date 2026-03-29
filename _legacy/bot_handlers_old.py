"""
Bot 消息处理模块

包含 Telegram Bot 主循环和消息处理逻辑

注意：此文件包含从 main.py 提取的 run_bot() 主循环逻辑
建议后续进一步拆分为更小的处理器类
"""
import threading
import time
import json
import logging
from pathlib import Path

from core.bot import TelegramClient
from core.ai import AIClient, MODEL_STATE
from utils.db import DB
from utils.notifier import Notifier
from config.settings import settings

logger = logging.getLogger('main')


def run_bot_loop(tg: TelegramClient, db: DB, notifier: Notifier, 
                 global_ai: AIClient, download_dir: Path, offset: int):
    """
    主消息处理循环
    
    此函数包含原 main.py run_bot() 的核心逻辑
    由于代码量巨大，暂时保持原样，后续可进一步重构
    """
    # 为了避免复制 1800+ 行代码，我们在这里做一个导入包装
    # 实际使用时，应该将 main.py 重命名为 main_legacy.py
    # 然后这里调用其中的逻辑
    
    # 临时方案：直接在此实现循环
    # 后续迭代时再将处理器逻辑分离到独立类
    
    from core.search import SearchOrchestrator
    from core.scholar_search import UnifiedSearcher
    
    search_orchestrator = SearchOrchestrator(db)
    
    while True:
        try:
            updates = tg.get_updates(offset=offset, timeout=25)
        except Exception as e:
            logger.error(f"获取更新失败: {e}")
            time.sleep(5)
            continue
        
        for u in updates:
            offset = int(u["update_id"]) + 1
            db.kv_set("telegram_offset", str(offset))
            
            try:
                _handle_update(u, tg, db, notifier, global_ai, download_dir, search_orchestrator)
            except Exception as e:
                logger.error(f"处理更新失败: {e}", exc_info=True)
        
        time.sleep(0.2)


def _handle_update(u: dict, tg: TelegramClient, db: DB, notifier: Notifier,
                   global_ai: AIClient, download_dir: Path, search_orchestrator):
    """处理单个更新"""
    
    # ========== 处理 callback_query (按钮点击) ==========
    callback_query = u.get("callback_query")
    if callback_query:
        _handle_callback_query(callback_query, tg, db)
        return
    
    msg = u.get("message") or u.get("edited_message")
    if not msg:
        return
    
    chat = msg.get("chat", {})
    chat_id = chat.get("id")
    text = (msg.get("text") or "").strip()
    
    if not chat_id:
        return
    
    if chat_id not in settings.TELEGRAM_ALLOWED_CHAT_IDS:
        return
    
    # ========== 处理文件上传 ==========
    if msg.get("document"):
        _handle_file_upload(msg, chat_id, tg, db, download_dir)
        return
    
    if not text:
        return
    
    logger.info(f"收到消息 [{chat_id}]: {text[:100]}...")
    
    # ========== 命令路由 ==========
    # 注意：以下是简化版本，完整实现应从 main.py 移植
    # 暂时提供基本命令支持，复杂命令需要后续迁移
    
    if text.startswith("/help"):
        _handle_help(chat_id, tg)
    elif text.startswith("/models"):
        _handle_models(chat_id, text, tg)
    elif text.startswith("/currentmodel"):
        _handle_currentmodel(chat_id, tg)
    elif text.startswith("/setmodel"):
        _handle_setmodel(chat_id, text, tg)
    else:
        # 对于其他命令，提示用户此版本为重构测试版
        # 完整功能请使用原始 main.py
        pass


def _handle_callback_query(callback_query: dict, tg: TelegramClient, db: DB):
    """处理按钮点击回调"""
    cb_id = callback_query.get("id")
    cb_data = callback_query.get("data", "")
    cb_chat = callback_query.get("message", {}).get("chat", {})
    cb_chat_id = cb_chat.get("id")
    
    if not cb_chat_id or cb_chat_id not in settings.TELEGRAM_ALLOWED_CHAT_IDS:
        return
    
    logger.info(f"收到按钮点击 [{cb_chat_id}]: {cb_data}")
    tg.answer_callback_query(cb_id)
    
    if cb_data.startswith("run:"):
        papers_file = Path(cb_data[4:])
        if not papers_file.exists():
            tg.send_message(cb_chat_id, f"❌ 文件不存在: {papers_file}")
        else:
            goal = "synthesis"
            max_papers = 50
            job_id = db.create_job(goal=goal, args={
                "wos_file": str(papers_file),
                "max_papers": max_papers,
                "goal": goal
            })
            tg.send_message(cb_chat_id, f"📚 任务已创建: {job_id}\n正在启动抓取...")
            
            def run_fetch_task():
                try:
                    from core.fetcher import run_fetch_job
                    from utils.db import DB as WorkerDB
                    from utils.notifier import Notifier as WorkerNotifier
                    from core.bot import TelegramClient as WorkerTG
                    
                    worker_db = WorkerDB()
                    worker_tg = WorkerTG()
                    worker_notifier = WorkerNotifier(worker_tg, cb_chat_id)
                    
                    run_fetch_job(
                        db=worker_db,
                        notifier=worker_notifier,
                        job_id=job_id,
                        wos_file=papers_file,
                        goal=goal,
                        max_papers=max_papers
                    )
                except Exception as e:
                    logger.error(f"任务失败: {e}", exc_info=True)
                    tg.send_message(cb_chat_id, f"❌ 任务失败: {e}")
            
            threading.Thread(target=run_fetch_task, daemon=True).start()
    
    elif cb_data.startswith("setmodel:"):
        new_model = cb_data[9:]
        old_model = MODEL_STATE.openai_model
        MODEL_STATE.set_openai_model(new_model)
        tg.send_message(cb_chat_id, f"✅ 模型已切换\n\n旧模型: {old_model}\n新模型: {new_model}")


def _handle_file_upload(msg: dict, chat_id: int, tg: TelegramClient, db: DB, download_dir: Path):
    """处理文件上传"""
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
                tg.send_message(chat_id, f"✅ 文件已保存: {file_path.name}\n\n使用以下命令开始分析:\n/run {file_path} goal=synthesis max=50")
                db.kv_set(f"last_upload_{chat_id}", str(file_path))
            else:
                tg.send_message(chat_id, "❌ 文件下载失败")
        except Exception as e:
            logger.error(f"文件处理失败: {e}")
            tg.send_message(chat_id, f"❌ 文件处理失败: {e}")
    
    threading.Thread(target=handle_upload, daemon=True).start()


def _handle_help(chat_id: int, tg: TelegramClient):
    """处理 /help 命令"""
    help_text = (
        f"🔬 Deep Research Bot\n\n"
        f"📋 命令列表:\n\n"
        f"【深度研究】\n"
        f"/deepresearch <问题> - AI 深度研究\n"
        f"/dr <问题> - 同上（简写）\n\n"
        f"【搜索】\n"
        f"/search <关键词> - 多源搜索\n"
        f"/scholar <关键词> - Google Scholar\n"
        f"/wos <检索式> - WoS 搜索\n\n"
        f"【AI 模型】\n"
        f"/models - 查看全部可用模型\n"
        f"/currentmodel - 查看模型配置\n"
        f"/setmodel <model> - 切换模型\n\n"
        f"【论文分析】\n"
        f"/analyze [job_id] [cloud] - 分析\n"
        f"/report [job_id] - 生成报告\n\n"
        f"【任务管理】\n"
        f"/autorun - 自动抓取论文\n"
        f"/status - 查看任务状态\n"
        f"/stop - 终止任务\n\n"
        f"【浏览器】\n"
        f"/startedge - 启动真实 Edge\n\n"
        f"⚙️ 模型: {MODEL_STATE.openai_model}"
    )
    tg.send_message(chat_id, help_text)


def _handle_models(chat_id: int, text: str, tg: TelegramClient):
    """处理 /models 命令"""
    show_all = "all" in text.lower()
    tg.send_message(chat_id, "🔍 正在获取模型列表...")
    
    def fetch_models():
        try:
            ai = AIClient(notify_callback=lambda x: tg.send_message(chat_id, x))
            models = ai.fetch_openai_models()
            current_model = MODEL_STATE.openai_model
            
            if not models:
                tg.send_message(chat_id, "❌ 无法获取模型列表")
                return
            
            model_ids = [m["id"] for m in models]
            display_models = model_ids if show_all else model_ids[:20]
            
            text_lines = [
                f"🤖 可用模型 ({len(model_ids)} 个)\n",
                f"📍 当前: {current_model}\n",
                "━" * 20
            ]
            
            for m in display_models:
                marker = "→ " if m == current_model else "  "
                text_lines.append(f"{marker}{m}")
            
            if not show_all and len(model_ids) > 20:
                text_lines.append(f"\n... 还有 {len(model_ids) - 20} 个")
                text_lines.append("💡 使用 /models all 查看全部")
            
            # 创建 inline keyboard
            button_models = display_models[:10]
            keyboard_rows = []
            for i in range(0, len(button_models), 2):
                row = []
                for m in button_models[i:i+2]:
                    label = m[:20] + "..." if len(m) > 20 else m
                    if m == current_model:
                        label = "✓ " + label
                    row.append({"text": label, "callback_data": f"setmodel:{m}"})
                keyboard_rows.append(row)
            
            inline_keyboard = {"inline_keyboard": keyboard_rows}
            tg.send_message(chat_id, "\n".join(text_lines), reply_markup=inline_keyboard)
            
        except Exception as e:
            logger.error(f"/models 失败: {e}")
            tg.send_message(chat_id, f"❌ 获取模型失败: {e}")
    
    threading.Thread(target=fetch_models, daemon=True).start()


def _handle_currentmodel(chat_id: int, tg: TelegramClient):
    """处理 /currentmodel 命令"""
    info = (
        f"🤖 当前模型配置:\n\n"
        f"OpenAI 模型: {MODEL_STATE.openai_model}\n"
        f"Gemini 模型: {MODEL_STATE.gemini_model}\n"
        f"API Base: {settings.OPENAI_API_BASE}\n"
        f"Provider: {settings.AI_PROVIDER}"
    )
    tg.send_message(chat_id, info)


def _handle_setmodel(chat_id: int, text: str, tg: TelegramClient):
    """处理 /setmodel 命令"""
    parts = text.split(maxsplit=1)
    if len(parts) < 2:
        current = MODEL_STATE.openai_model
        help_text = (
            f"用法: /setmodel <model_id>\n\n"
            f"当前模型: {current}\n\n"
            f"示例:\n"
            f"/setmodel gpt-4-turbo\n"
            f"/setmodel gemini-3-flash-preview\n"
            f"/setmodel deepseek-v3.2\n\n"
            f"💡 使用 /models all 查看全部可用模型"
        )
        tg.send_message(chat_id, help_text)
        return
    
    new_model = parts[1].strip()
    old_model = MODEL_STATE.openai_model
    
    def validate_and_set():
        try:
            ai = AIClient(notify_callback=lambda x: tg.send_message(chat_id, x))
            models = ai.fetch_openai_models()
            model_ids = [m["id"] for m in models]
            
            if new_model in model_ids:
                MODEL_STATE.set_openai_model(new_model)
                tg.send_message(chat_id, f"✅ 模型已切换\n\n旧模型: {old_model}\n新模型: {new_model}\n\n使用 /testai 测试新模型")
            else:
                matches = [m for m in model_ids if new_model.lower() in m.lower()]
                if matches:
                    suggestion = "\n".join([f"  • {m}" for m in matches[:5]])
                    tg.send_message(chat_id, f"❌ 模型 '{new_model}' 不存在\n\n相似模型:\n{suggestion}\n\n请使用完整的模型名称")
                else:
                    tg.send_message(chat_id, f"❌ 模型 '{new_model}' 不存在\n\n使用 /models all 查看全部可用模型")
        except Exception as e:
            MODEL_STATE.set_openai_model(new_model)
            tg.send_message(chat_id, f"⚠️ 无法验证模型，已强制设置为: {new_model}\n\n使用 /testai 测试是否可用")
    
    threading.Thread(target=validate_and_set, daemon=True).start()
