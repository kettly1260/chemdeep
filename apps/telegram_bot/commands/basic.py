"""
Basic Commands

/help, /config, /key
"""
from apps.telegram_bot.command_registry import CommandRegistry
from apps.telegram_bot.services.runtime_config import get_user_config, set_user_config, reset_user_config
from apps.telegram_bot.ui.cards import render_config_card
from apps.telegram_bot.ui.keyboards import build_config_keyboard, build_help_menu

def register_basic_commands(registry: CommandRegistry):

    @registry.register(
        command="/help",
        description="显示帮助信息",
        usage="/help [group|all]",
        examples=["/help", "/help Config", "/help all"],
        group="Basic"
    )
    def cmd_help(payload, ctx):
        tg = ctx["tg"]
        chat_id = ctx["chat_id"]
        msg_id = ctx.get("message_id")
        
        args = payload["args"]
        group = args[0] if args else None
        
        # Mapping for Chinese Interaction
        alias_map = {
            "配置": "Config",
            "基础": "Basic",
            "任务": "Execution",
            "报告": "Reporting",
            "全部": "all"
        }
        
        if group:
            # Resolve alias
            group = alias_map.get(group, group)
        
        if group and group.lower() != "main":
            # Show specific group or All
            if group.lower() == "all":
                # Full list (No menu buttons to avoid spam)
                text = registry.get_help_text()
                tg.send_message(chat_id, text, parse_mode="Markdown")
                return
            else:
                 # Filter by group
                 lines = [f"📚 **Help: {group}**\n"]
                 found = False
                 # Sort commands for stability
                 for cmd, specs in sorted(registry.commands.items()):
                     for spec in specs:
                         if spec.group.lower() == group.lower():
                             # Format: /cmd [args] - desc
                             pat = f" {spec.pattern}" if spec.pattern else ""
                             lines.append(f"`/{spec.command}{pat}`\n{spec.description}")
                             lines.append(f"Idea: `{spec.examples[0]}`\n")
                             found = True
                 
                 if not found:
                     text = f"❌ Group '{group}' not found.\nShowing menu..."
                     # Fallback to menu
                     groups = sorted(list(set(spec.group for specs in registry.commands.values() for spec in specs)))
                     kb = build_help_menu(groups)
                     if msg_id:
                        tg.edit_message(chat_id, msg_id, text, reply_markup=kb, parse_mode="Markdown")
                     else:
                        tg.send_message(chat_id, text, reply_markup=kb, parse_mode="Markdown")
                     return

                 # Add Back Button
                 text = "\n".join(lines)
                 kb = {"inline_keyboard": [[{"text": "🔙 返回菜单", "callback_data": "cmd:/help"}]]}
                 
                 if msg_id:
                     tg.edit_message(chat_id, msg_id, text, reply_markup=kb, parse_mode="Markdown")
                 else:
                     tg.send_message(chat_id, text, reply_markup=kb, parse_mode="Markdown")
        else:
            # Main Menu (Default)
            groups = sorted(list(set(spec.group for specs in registry.commands.values() for spec in specs)))
            kb = build_help_menu(groups)
            text = "📚 **帮助菜单**\n请选择功能分类："
            
            if msg_id:
                tg.edit_message(chat_id, msg_id, text, reply_markup=kb, parse_mode="Markdown")
            else:
                tg.send_message(chat_id, text, reply_markup=kb, parse_mode="Markdown")

    @registry.register(
        command="/config",
        description="查看当前配置 (Token已脱敏)",
        usage="/config [reset]",
        examples=["/config", "/config reset"],
        group="Config"
    )
    def cmd_config(payload, ctx):
        tg = ctx["tg"]
        chat_id = ctx["chat_id"]
        user_id = ctx["user_id"]
        db = ctx["db"]
        
        args = payload["args"]
        if args and args[0] == "reset":
            reset_user_config(user_id, db)
            tg.send_message(chat_id, "✅ 已重置配置，恢复默认 .env 设置")
            return

        cfg = get_user_config(user_id, db)
        msg_id = ctx.get("message_id")
        
        text = render_config_card(cfg)
        kb = build_config_keyboard()
        
        if msg_id:
            tg.edit_message(chat_id, msg_id, text, reply_markup=kb, parse_mode="Markdown")
        else:
            tg.send_message(chat_id, text, reply_markup=kb, parse_mode="Markdown")

    @registry.register(
        command="/key",
        pattern="set",
        description="设置 API Key (加密存储)",
        usage="/key set <sk-...>",
        examples=["/key set sk-xxxx"],
        group="Config"
    )
    def cmd_key_set(payload, ctx):
        tg = ctx["tg"]
        chat_id = ctx["chat_id"]
        user_id = ctx["user_id"]
        db = ctx["db"]
        msg_id = ctx.get("message_id")
        
        args = payload["args"]
        if not args:
            tg.send_message(chat_id, "❌ 请提供 API Key")
            return
            
        key = args[0]
        set_user_config(user_id, "api_key", key, db)
        
        # 尝试删除用户消息以防泄露
        if msg_id:
            try:
                # Note: Bot need delete permission
                # We don't have delete_message yet in client, skip for now or add it later
                # For safety, just reply with masked key
                pass
            except Exception:
                pass
                
        # Masked echo
        from apps.telegram_bot.services.crypto import mask_key
        masked = mask_key(key)
        tg.send_message(chat_id, f"✅ API Key 已更新 (加密存储)\n指纹: `{masked}`", parse_mode="Markdown")

    @registry.register(
        command="/proxy_websearch",
        description="设置 Web Search 代理",
        usage="/proxy_websearch <url> | none",
        examples=["/proxy_websearch socks5://127.0.0.1:7890", "/proxy_websearch none"],
        group="Config"
    )
    def cmd_proxy_websearch(payload, ctx):
        """[P44] 运行时设置 Web Search 代理"""
        tg = ctx["tg"]
        chat_id = ctx["chat_id"]
        args = payload["args"]
        
        if not args:
            tg.send_message(chat_id, "❌ 请提供代理 URL，例如: `socks5://127.0.0.1:7890` 或 `none`", parse_mode="Markdown")
            return
            
        proxy_url = args[0]
        if proxy_url.lower() == "none":
            proxy_url = ""
            msg = "✅ Web Search 代理已清除 (使用直接连接)"
        else:
            msg = f"✅ Web Search 代理已更新: `{proxy_url}`"
            
        from config.settings import settings
        settings.CHEMDEEP_WEBSEARCH_PROXY = proxy_url
        
        tg.send_message(chat_id, msg, parse_mode="Markdown")

