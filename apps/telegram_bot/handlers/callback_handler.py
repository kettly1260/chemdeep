"""
回调处理器

将按钮点击转换为命令执行
"""
import logging
import shlex
from .message_router import registry # Import shared registry

logger = logging.getLogger('main')

def handle_callback_query(callback_query: dict, tg, db, settings) -> None:
    """处理按钮点击回调"""
    cb_id = callback_query.get("id")
    cb_data = callback_query.get("data", "")
    message = callback_query.get("message", {})
    chat = message.get("chat", {})
    chat_id = chat.get("id")
    from_user = callback_query.get("from", {})
    user_id = from_user.get("id", chat_id)
    
    if not chat_id or chat_id not in settings.TELEGRAM_ALLOWED_CHAT_IDS:
        return
    
    logger.info(f"收到按钮点击 [{chat_id}]: {cb_data}")
    tg.answer_callback_query(cb_id)
    
    # 转换逻辑: Button Data -> Command Text
    # 比如 "run_last" -> "/run --last"
    # 或者 "report:123" -> "/report 123"
    
    if cb_data.startswith("interact:"):
        # [P74] Support Job-based Interaction (interact:sel:job_id:result)
        if cb_data.startswith("interact:sel:"):
            try:
                # interact:sel:job_id:result (result might contain colons? unlikely for options)
                parts = cb_data.split(":", 3)
                if len(parts) == 4:
                    _, _, t_job_id, result = parts
                    
                    # Update DB (signals execution.py loop)
                    db.kv_set(f"job_response_{t_job_id}", result)
                    
                    # We don't send message here because loop will verify and send "Checked/Selected"
                    # But loop waits for poll. User might want immediate feedback?
                    # execution.py logic: tg.send_message(..., "✅ 已选择: {selected}")
                    # So we just acknowledge callback.
                    return
            except Exception as e:
                logger.error(f"Job interaction resolve failed: {e}")
            return

        # Format: interact:chat_id:result (Legacy/InteractionManager)
        try:
            parts = cb_data.split(":", 2)
            if len(parts) == 3:
                _, t_chat_id, result = parts
                if int(t_chat_id) == chat_id:
                    from apps.telegram_bot.services.interaction_manager import InteractionManager
                    im = InteractionManager.get_instance()
                    im.resolve_interaction(chat_id, result)
        except Exception as e:
            logger.error(f"Interaction resolve failed: {e}")
        return
    
    # Routing: Prefix Based
    # 1. cmd: -> Execute Command via Registry
    if cb_data.startswith("cmd:"):
        cmd_str = cb_data[4:].strip()
        logger.info(f"Callback Cmd: {cmd_str}")
        
        ctx = {
            "tg": tg,
            "db": db,
            "chat_id": chat_id,
            "user_id": user_id,
            "message_id": message.get("message_id"), # for editing
            "registry": registry
        }
        registry.dispatch(cmd_str, ctx)
        return

    # 2. help: -> /help <group>
    if cb_data.startswith("help:"):
        group = cb_data[5:].strip()
        cmd_str = f"/help {group}"
        logger.info(f"Callback Help: {group}")
        
        ctx = {
            "tg": tg,
            "db": db,
            "chat_id": chat_id,
            "user_id": user_id,
            "message_id": message.get("message_id"),
            "registry": registry
        }
        registry.dispatch(cmd_str, ctx)
        return

    # 3. run_load: -> /run_load <run_id>
    if cb_data.startswith("run_load:"):
        run_id = cb_data[9:].strip()
        cmd_str = f"/run_load {run_id}"
        logger.info(f"Callback Run Load: {run_id}")
        
        ctx = {
            "tg": tg,
            "db": db,
            "chat_id": chat_id,
            "user_id": user_id,
            "message_id": message.get("message_id"),
            "registry": registry
        }
        registry.dispatch(cmd_str, ctx)
        return

    # 4. run_force: -> /run_force <job_id>
    if cb_data.startswith("run_force:"):
        job_id = cb_data[10:].strip()
        cmd_str = f"/run_force {job_id}"
        logger.info(f"Callback Run Force: {job_id}")
        
        ctx = {
            "tg": tg,
            "db": db,
            "chat_id": chat_id,
            "user_id": user_id,
            "message_id": message.get("message_id"),
            "registry": registry
        }
        registry.dispatch(cmd_str, ctx)
        return

    # [P54] 5. run_refine: -> /run_refine <old_run_id>
    if cb_data.startswith("run_refine:"):
        old_id = cb_data[11:].strip()
        cmd_str = f"/run_refine {old_id}"
        logger.info(f"Callback Run Refine: {old_id}")
        
        ctx = {
            "tg": tg,
            "db": db,
            "chat_id": chat_id,
            "user_id": user_id,
            "message_id": message.get("message_id"), # For editing
            "registry": registry
        }
        registry.dispatch(cmd_str, ctx)
        return

    # [P22] 7. reuse: -> Task Reuse Options
    if cb_data.startswith("reuse:"):
        parts = cb_data.split(":", 2)
        action = parts[1] if len(parts) > 1 else ""
        run_id = parts[2] if len(parts) > 2 else ""
        
        goal = db.kv_get(f"pending_goal_{chat_id}") or ""
        
        ctx = {
            "tg": tg,
            "db": db,
            "chat_id": chat_id,
            "user_id": user_id,
            "message_id": message.get("message_id"),
            "registry": registry
        }
        
        if action == "new":
            # Start new task (force mode)
            if goal:
                tg.send_message(chat_id, f"🆕 开启新任务: {goal}")
                safe_goal = shlex.quote(goal)
                registry.dispatch(f"/run {safe_goal} --force", ctx)
            else:
                tg.send_message(chat_id, "❌ 未找到待处理目标，请重新输入 /run")
        elif action == "report":
            # Extract existing report
            registry.dispatch(f"/run_load {run_id}", ctx)
        elif action == "refine":
            # Use old report as context
            registry.dispatch(f"/run_refine {run_id}", ctx)
        elif action == "retry":
            # Retry failed task
            if goal:
                tg.send_message(chat_id, f"🔄 重试任务: {goal}")
                safe_goal = shlex.quote(goal)
                registry.dispatch(f"/run {safe_goal} --force", ctx)
            else:
                tg.send_message(chat_id, "❌ 未找到待处理目标，请重新输入 /run")
        elif action == "continue":
            # Continue running task (just show status)
            registry.dispatch(f"/status {run_id}", ctx)
        elif action == "resume":
            # [P86] Resume from checkpoint
            registry.dispatch(f"/run_resume {run_id}", ctx)
        elif action == "cancel":
            # Cancel - clear pending goal
            db.kv_set(f"pending_goal_{chat_id}", "")
            tg.send_message(chat_id, "❌ 操作已取消")
        else:
            tg.send_message(chat_id, f"⚠️ 未知操作: {action}")
        return

    # [P54] 6. cancel_setup: -> /cancel_setup
    if cb_data.startswith("cancel_setup"):
        cmd_str = "/cancel_setup"
        logger.info(f"Callback Cancel Setup")
        
        ctx = {
            "tg": tg,
            "db": db,
            "chat_id": chat_id,
            "user_id": user_id,
            "message_id": message.get("message_id"),
            "registry": registry
        }
        registry.dispatch(cmd_str, ctx)
        return

    # 5. cf_solved: -> Signal CF resolution (P27)
    if cb_data.startswith("cf_solved:"):
        domain = cb_data[10:].strip()
        logger.info(f"Callback CF Solved: {domain}")
        try:
            from core.services.research.content_fetch import signal_cf_resolved
            signal_cf_resolved(domain)
            tg.send_message(chat_id, f"✅ CF 验证信号已发送: {domain}")
        except Exception as e:
            logger.error(f"CF signal failed: {e}")
        return

    # 3. interact: -> User Interaction (Answer Blocking Question)
    if cb_data.startswith("interact:"):
        # Format: interact:type OR interact:chat_id:result (P12)
        # Check P12 style first
        try:
            parts = cb_data.split(":", 2)
            if len(parts) == 3 and parts[1].isdigit():
                # interact:chat_id:result (Wait Mechanism)
                _, t_chat_id, result = parts
                if int(t_chat_id) == chat_id:
                    from apps.telegram_bot.services.interaction_manager import InteractionManager
                    im = InteractionManager.get_instance()
                    im.resolve_interaction(chat_id, result)
                    return
        except Exception:
            pass
            
        # Standard P11.1 Interactions (e.g. interact:key -> Ask user input)
        itype = cb_data.split(":", 1)[1]
        if itype == "key":
            tg.send_message(chat_id, "🔑 请回复您的 API Key (以 sk- 开头):")
            # Need to set state to accept next message as key?
            # Current architecture doesn't have FSM for message handler.
            # Workaround: Tell user to use command /key set sk-...
            tg.send_message(chat_id, "提示: 请使用命令 `/key set <your-key>`", parse_mode="Markdown")
        elif itype == "endpoint":
             tg.send_message(chat_id, "🔗 请使用命令 `/endpoint set <url>`", parse_mode="Markdown")
        elif itype == "model_search":
             tg.send_message(chat_id, "🔍 请使用命令 `/models <keyword>` (暂未实现搜索过滤，请直接列表翻页)", parse_mode="Markdown")
        return

    # Legacy Fallback
    command_text = None
    if cb_data.startswith("/"):
        command_text = cb_data
    
    if command_text:
        ctx = {
            "tg": tg,
            "db": db,
            "chat_id": chat_id,
            "user_id": user_id,
            "message_id": message.get("message_id"), 
            "registry": registry
        }
        registry.dispatch(command_text, ctx)
