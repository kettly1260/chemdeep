"""
Models Commands

/models, /model set, /endpoint set
"""
import time
from apps.telegram_bot.command_registry import CommandRegistry
from apps.telegram_bot.services.runtime_config import get_user_config, set_user_config
from apps.telegram_bot.services.model_provider import fetch_models
from apps.telegram_bot.ui.keyboards import build_models_keyboard

def register_models_commands(registry: CommandRegistry):

    @registry.register(
        command="/models",
        description="列出可用模型 (24h缓存)",
        usage="/models [refresh] [page N]",
        examples=["/models", "/models refresh", "/models page 2"],
        group="Config"
    )
    def cmd_models(payload, ctx):
        tg = ctx["tg"]
        chat_id = ctx["chat_id"]
        user_id = ctx["user_id"]
        db = ctx["db"]
        msg_id_to_edit = ctx.get("message_id")
        
        args = payload["args"]
        force = "refresh" in args
        page = 1
        if "page" in args:
            try:
                idx = args.index("page")
                if idx + 1 < len(args):
                    page = int(args[idx+1])
            except ValueError:
                pass
        
        cfg = get_user_config(user_id, db)
        
        # If refreshing or first load, show loader if not editing
        if not msg_id_to_edit:
            sent = tg.send_message(chat_id, "🔄 正在拉取模型列表...")
            if sent: msg_id_to_edit = sent["message_id"]
        
        try:
            models = fetch_models(cfg, force_refresh=force)
            if not models:
                if msg_id_to_edit:
                    tg.edit_message(chat_id, msg_id_to_edit, "❌ 未找到可用模型或 API 错误")
                else:
                    tg.send_message(chat_id, "❌ 未找到可用模型或 API 错误")
                return
                
            # Build Keyboard
            kb = build_models_keyboard(models, cfg.model, page)
            
            text = f"📋 **可用模型列表 ({len(models)})**\n当前: `{cfg.model}`"
                
            if msg_id_to_edit:
                tg.edit_message(chat_id, msg_id_to_edit, text, reply_markup=kb, parse_mode="Markdown")
            else:
                tg.send_message(chat_id, text, reply_markup=kb, parse_mode="Markdown")
                
        except Exception as e:
            if msg_id_to_edit:
                tg.edit_message(chat_id, msg_id_to_edit, f"❌ 拉取失败: {str(e)}")
            else:
                tg.send_message(chat_id, f"❌ 拉取失败: {str(e)}")

    @registry.register(
        command="/model",
        description="查看当前模型",
        usage="/model",
        examples=["/model"],
        group="Config"
    )
    def cmd_model_show(payload, ctx):
        # Handle '/model' without args (view current)
        # But wait, registry dispatches '/model set' separately if pattern matches.
        # This handler will catch '/model' only if no subcommand matches?
        # Registry 'dispatch' logic prioritizes pattern match. 
        # If args provided but no pattern match -> Falls to this if no pattern?
        # My registry implementation: "Fallback to empty pattern".
        # So I leave pattern="" here.
        if payload["args"]:
             return # Let other handlers handle it? 
             # Actually if pattern doesn't match, registry loops.
             # If I register this with pattern="", it acts as fallback.
             pass
             
        tg = ctx["tg"]
        chat_id = ctx["chat_id"]
        user_id = ctx["user_id"]
        db = ctx["db"]
        
        cfg = get_user_config(user_id, db)
        
        btns = [
             [{"text": "🔄 Refresh", "callback_data": "cmd:/models refresh"},
              {"text": "📋 Change Model", "callback_data": "cmd:/models"}]
        ]
        
        text = f"🤖 **Current Model**: `{cfg.model}`"
        tg.send_message(chat_id, text, reply_markup={"inline_keyboard": btns}, parse_mode="Markdown")

    @registry.register(
        command="/model",
        pattern="set",
        description="设置当前模型",
        usage="/model set <model_id>",
        examples=["/model set gpt-4"],
        group="Config"
    )
    def cmd_model_set(payload, ctx):
        tg = ctx["tg"]
        chat_id = ctx["chat_id"]
        user_id = ctx["user_id"]
        db = ctx["db"]
        
        args = payload["args"]
        if not args:
            tg.send_message(chat_id, "❌ 请指定模型 ID")
            return
            
        model_id = args[0]
        
        # Optional: Validate against fetch_models? 
        # Requirement says: "Validate model_id in current list"
        # We try to fetch cache (no force refresh) to validate
        cfg = get_user_config(user_id, db)
        known_models = fetch_models(cfg, force_refresh=False)
        
        if known_models and model_id not in known_models:
            tg.send_message(chat_id, f"⚠️ 模型 `{model_id}` 不在列表中，建议先 `/models refresh`")
            # We allow setting it anyway? Plan said: "reject".
            # Let's reject to be safe.
            tg.send_message(chat_id, "❌ 设置失败：模型不在列表中")
            return
            
        set_user_config(user_id, "model", model_id, db)
        tg.send_message(chat_id, f"✅ 模型已设置为: `{model_id}`", parse_mode="Markdown")

    @registry.register(
        command="/endpoint",
        pattern="set",
        description="设置 API Base URL",
        usage="/endpoint set <url>",
        examples=["/endpoint set https://api.openai.com/v1"],
        group="Config"
    )
    def cmd_endpoint_set(payload, ctx):
        tg = ctx["tg"]
        chat_id = ctx["chat_id"]
        user_id = ctx["user_id"]
        db = ctx["db"]
        
        args = payload["args"]
        if not args:
            tg.send_message(chat_id, "❌ 请指定 URL")
            return
            
        url = args[0]
        set_user_config(user_id, "base_url", url, db)
        tg.send_message(chat_id, f"✅ Base URL 已设置为: `{url}`", parse_mode="Markdown")

