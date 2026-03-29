"""
模型相关命令处理器

处理: /models, /setmodel, /currentmodel
"""
import threading
import logging
from core.ai import AIClient, MODEL_STATE
from config.settings import settings

logger = logging.getLogger('main')


import time

# 简单的内存缓存
_models_cache = {"data": [], "timestamp": 0}


def get_all_models(notify_callback=None) -> list[str]:
    """获取所有模型 ID (带缓存 5分钟)"""
    now = time.time()
    if _models_cache["data"] and (now - _models_cache["timestamp"] < 300):
        return _models_cache["data"]
    
    try:
        ai = AIClient(notify_callback=notify_callback)
        models = ai.fetch_openai_models()
        if not models:
            return []
        
        # 排序：优先显示 gpt-4, gpt-3.5, gemini, claude 等常用模型
        model_ids = sorted([m["id"] for m in models])
        
        # 简单的优先级排序优化
        priority = []
        others = []
        for m in model_ids:
            if any(k in m for k in ["gpt-4", "claude-3", "gemini-1.5"]):
                priority.append(m)
            else:
                others.append(m)
        
        sorted_ids = priority + others
        
        _models_cache["data"] = sorted_ids
        _models_cache["timestamp"] = now
        return sorted_ids
    except Exception:
        return []


def show_models_page(chat_id: int, page: int, tg, message_id: int = None) -> None:
    """显示指定页的模型列表"""
    
    def _fetch_and_render():
        try:
            # 如果是第一页且是新消息，提示正在获取
            if page == 0 and message_id is None:
                tg.send_message(chat_id, "🔍 正在获取模型列表...")
            
            model_ids = get_all_models(lambda x: None)
            current_model = MODEL_STATE.openai_model
            
            if not model_ids:
                if message_id:
                    tg.edit_message(chat_id, message_id, "❌ 无法获取模型列表")
                else:
                    tg.send_message(chat_id, "❌ 无法获取模型列表")
                return
            
            # 分页参数
            PAGE_SIZE = 10
            total_models = len(model_ids)
            total_pages = (total_models + PAGE_SIZE - 1) // PAGE_SIZE
            
            # 修正 page 范围
            current_page = page
            if current_page < 0: current_page = 0
            if current_page >= total_pages: current_page = total_pages - 1
            
            start_idx = current_page * PAGE_SIZE
            end_idx = start_idx + PAGE_SIZE
            page_models = model_ids[start_idx:end_idx]
            
            # 构建文本内容
            text_lines = [
                f"🤖 可用模型 (共 {total_models} 个)\n",
                f"📍 当前: {current_model}\n",
                f"📄 第 {current_page+1}/{total_pages} 页\n",
                "━" * 20
            ]
            
            for m in page_models:
                marker = "✓ " if m == current_model else "  "
                text_lines.append(f"{marker}{m}")
            
            text_content = "\n".join(text_lines)
            
            # 构建按钮
            keyboard_rows = []
            
            # 模型选择按钮 (每行2个)
            row = []
            for m in page_models:
                label = m
                # 截断过长名称
                if len(label) > 20: 
                    label = label[:9] + ".." + label[-9:]
                
                if m == current_model:
                    label = "✅ " + label
                    
                row.append({"text": label, "callback_data": f"setmodel:{m}"})
                
                if len(row) == 2:
                    keyboard_rows.append(row)
                    row = []
            if row:
                keyboard_rows.append(row)
            
            # 翻页按钮
            nav_row = []
            if current_page > 0:
                nav_row.append({"text": "⬅️ 上一页", "callback_data": f"flipmodel:{current_page-1}"})
            
            # 中间显示页码（不可点）
            nav_row.append({"text": f"{current_page+1}/{total_pages}", "callback_data": "noop"})
            
            if current_page < total_pages - 1:
                nav_row.append({"text": "下一页 ➡️", "callback_data": f"flipmodel:{current_page+1}"})
                
            keyboard_rows.append(nav_row)
            
            inline_keyboard = {"inline_keyboard": keyboard_rows}
            
            if message_id:
                # 编辑现有消息
                tg.edit_message(chat_id, message_id, text_content, reply_markup=inline_keyboard)
            else:
                # 发送新消息
                tg.send_message(chat_id, text_content, reply_markup=inline_keyboard)

        except Exception as e:
            logger.error(f"Render models page failed: {e}")
            if not message_id:
                tg.send_message(chat_id, f"❌ 错误: {e}")

    threading.Thread(target=_fetch_and_render, daemon=True).start()


def handle_models(chat_id: int, text: str, tg) -> None:
    """处理 /models 命令"""
    # 始终显示第一页
    show_models_page(chat_id, 0, tg)



def handle_currentmodel(chat_id: int, tg) -> None:
    """处理 /currentmodel 命令"""
    info = (
        f"🤖 当前模型配置:\n\n"
        f"OpenAI 模型: {MODEL_STATE.openai_model}\n"
        f"Gemini 模型: {MODEL_STATE.gemini_model}\n"
        f"API Base: {settings.OPENAI_API_BASE}\n"
        f"Provider: {settings.AI_PROVIDER}"
    )
    tg.send_message(chat_id, info)


def handle_setmodel(chat_id: int, text: str, tg) -> None:
    """处理 /setmodel 命令"""
    parts = text.split(maxsplit=1)
    if len(parts) < 2:
        _show_setmodel_help(chat_id, tg)
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


def _show_setmodel_help(chat_id: int, tg) -> None:
    """显示 /setmodel 帮助"""
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
