"""
Execution Commands

/run, /runs, /status, /stop
"""

import json
from pathlib import Path
from datetime import datetime
from apps.telegram_bot.command_registry import CommandRegistry
from apps.telegram_bot.services.runtime_config import get_user_config, UserConfig
from apps.telegram_bot.ui.cards import render_run_card
from apps.telegram_bot.ui.keyboards import build_run_actions_keyboard
from core.commands.fetch import handle_run_callback  # Reuse for logic if possible?
from core.execution.history import get_run_history

# Check run_research command logic. Better to invoke core service directly but keep it simple.
import logging

logger = logging.getLogger("execution")


def _save_run_config(run_id: str, cfg: UserConfig):
    """
    Freeze config to runs/<run_id>/config.json
    Ensures each run has a record of which model/endpoint was used.
    """
    run_dir = Path(f"runs/{run_id}")
    run_dir.mkdir(parents=True, exist_ok=True)

    config_data = {
        "model": cfg.model,
        "base_url": cfg.base_url,
        "provider": cfg.provider,
        "api_key_masked": cfg.masked_key(),  # Never store raw key
        "frozen_at": datetime.now().isoformat(),
    }

    config_file = run_dir / "config.json"
    config_file.write_text(
        json.dumps(config_data, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return config_file


def _make_interaction_handler(db, tg, chat_id, job_id, logger):
    """[P100] Factory for creating interaction callbacks"""
    import time
    import json

    def handle_interaction(prompt: str, options: list) -> str:
        # 1. Update Status & Save Options
        db.update_job_status(job_id, "waiting_input")
        db.kv_set(
            f"job_interaction_{job_id}",
            json.dumps({"prompt": prompt, "options": options, "ts": time.time()}),
        )

        # 2. Build Keyboard
        kb_rows = []
        for opt in options:
            kb_rows.append(
                [{"text": opt, "callback_data": f"interact:sel:{job_id}:{opt}"}]
            )

        # 3. Send Message
        from apps.telegram_bot.ui.utils import escape_markdown

        safe_prompt = escape_markdown(prompt)

        tg.send_message(
            chat_id,
            f"🔔 **任务需要介入**\n\n{safe_prompt}",
            reply_markup={"inline_keyboard": kb_rows},
            parse_mode="Markdown",
        )

        # 4. Wait for response (Blocking Loop)
        response_key = f"job_response_{job_id}"
        db.kv_set(response_key, "")  # Clear previous

        logger.info(f"Waiting for user input for job {job_id}...")

        selected = None
        while True:
            if db.cancel_requested(job_id):
                raise Exception("User Cancelled during interaction")

            val = db.kv_get(response_key)
            if val:
                selected = val
                break
            time.sleep(1)

        # 5. Cleanup & Resume
        db.kv_set(f"job_interaction_{job_id}", "")
        db.update_job_status(job_id, "running")
        return selected

    return handle_interaction


# [P108] Research Plan Display Functions
def _format_plan_message(goal: str, plan: dict) -> str:
    """格式化计划消息 (ChatGPT 风格)"""
    lines = [
        f"📋 **已收到研究任务**",
        "",
        f"> {goal[:100]}{'...' if len(goal) > 100 else ''}",
        "",
    ]

    # 显示识别的用户要求
    recognized = plan.get("recognized_requirements", [])
    if recognized:
        lines.append("✅ **已识别您的具体要求:**")
        for req in recognized:
            lines.append(f"  • {req}")
        lines.append("")

    # 显示分析摘要
    analysis = plan.get("analysis", "")
    if analysis:
        lines.append(f"💡 **分析**: {analysis}")
        lines.append("")

    lines.append("🔬 **建议从以下维度展开研究:**")
    lines.append("")

    for dim in plan.get("dimensions", []):
        icon = dim.get("icon", "•")
        dtype = dim.get("type", "general").title()
        focus = dim.get("focus", "")
        lines.append(f"  {icon} **{dtype}**: {focus}")

    lines.append("")

    strategy = plan.get("missing_info_strategy", "")
    if strategy:
        lines.append(f"📌 **备选策略**: {strategy}")
        lines.append("")

    lines.append("---")
    lines.append("是否按此计划执行？")

    return "\n".join(lines)


def _show_research_plan(ctx, goal: str, clarifications: str):
    """[P108] 展示研究计划并等待确认"""
    tg = ctx["tg"]
    chat_id = ctx["chat_id"]
    db = ctx["db"]

    tg.send_message(chat_id, "📊 正在分析研究维度，请稍候...")

    from core.services.research.planner import ResearchPlanner

    planner = ResearchPlanner(lambda x: None)
    plan = planner.generate_investigation_dimensions(goal, clarifications)

    # 存储计划
    import json

    db.kv_set(f"research_plan_{chat_id}", json.dumps(plan, ensure_ascii=False))

    # 格式化展示
    msg = _format_plan_message(goal, plan)

    buttons = [
        [{"text": "✅ 按此计划执行", "callback_data": "cmd:/clarify confirm_plan"}],
        [
            {"text": "⚡ 直接开始", "callback_data": "cmd:/clarify quick"},
            {"text": "❌ 取消", "callback_data": "cmd:/clarify cancel"},
        ],
    ]

    tg.send_message(
        chat_id, msg, reply_markup={"inline_keyboard": buttons}, parse_mode="Markdown"
    )


def register_execution_commands(registry: CommandRegistry):
    @registry.register(
        command="/run",
        description="开始新研究",
        usage="/run <goal> [--last] [--max N]",
        examples=["/run synthesizing paracetamol", "/run --last --max 20"],
        group="Execution",
    )
    @registry.register(
        command="/run",
        description="开始新研究",
        usage="/run <goal> [--last] [--max N] [--quick] [--force]",
        examples=[
            "/run synthesizing paracetamol",
            "/run --quick synthesizing paracetamol",
        ],
        group="Execution",
    )
    def cmd_run(payload, ctx):
        tg = ctx["tg"]
        chat_id = ctx["chat_id"]
        user_id = ctx["user_id"]
        db = ctx["db"]

        args = payload["args"]
        flags = payload["flags"]
        goal = " ".join(args)

        # 1. Input Check
        if flags.get("last"):
            last_file = db.kv_get(f"last_upload_{chat_id}")
            if last_file and Path(last_file).exists():
                # File mode -> Skip clarification
                from core.commands.fetch import _start_fetch_task

                job_id = db.create_job("File Processing", {})
                tg.send_message(chat_id, f"🚀 文件任务已创建: `{job_id}`")
                _start_fetch_task(
                    chat_id,
                    job_id,
                    Path(last_file),
                    goal or "synthesis",
                    int(flags.get("max", 50)),
                    tg,
                )
                return
            else:
                tg.send_message(chat_id, "❌ 未找到上次上传的文件")
                return

        if not goal:
            tg.send_message(chat_id, "❌ 请提供研究目标")
            return

        # 2. [P22] Enhanced Task Reuse Strategy
        import core.execution.history
        import importlib

        importlib.reload(core.execution.history)
        history = core.execution.history.get_run_history()

        force_run = bool(flags.get("force", False))
        quick_mode = bool(flags.get("quick", False))

        if not force_run:
            # Check for any matching runs (not just completed)
            all_matches = history.find_all_matches(goal)

            if all_matches:
                # Get most recent run
                prev_run = all_matches[0]
                prev_status = prev_run.get("status", "").lower()
                prev_id = prev_run.get("run_id", "")

                # Store pending goal for later use
                db.kv_set(f"pending_goal_{chat_id}", goal)

                # Build interactive keyboard
                from apps.telegram_bot.ui.keyboards import build_reuse_options_keyboard

                kb = build_reuse_options_keyboard(prev_run, goal)

                # Status-specific message
                if prev_status in ["running", "pending", "waiting_input"]:
                    msg = f"⚠️ **检测到进行中的相似任务**\n\nID: `{prev_id}`\n状态: {prev_status}\n\n请选择操作："
                elif prev_status == "completed":
                    msg = f"✅ **检测到已完成的相同任务**\n\nID: `{prev_id}`\n\n请选择操作："
                else:
                    msg = f"⚠️ **检测到之前的相似任务**\n\nID: `{prev_id}`\n状态: {prev_status}\n\n请选择操作："

                tg.send_message(chat_id, msg, reply_markup=kb, parse_mode="Markdown")
                return

        # 3. No match or --force: Proceed to clarification or quick start
        if quick_mode:
            # Skip clarification (--quick flag)
            # [P93] 传入原始目标 (即 goal 本身)
            _start_research_job(ctx, goal, flags, original_goal=goal)
        else:
            # Start Clarification Flow (default, including --force)
            _start_clarification(ctx, goal)
            return

    @registry.register(
        command="/status",
        description="查看任务状态",
        usage="/status <run_id|current>",
        examples=["/status current", "/status 123456"],
        group="Execution",
    )
    def cmd_status(payload, ctx):
        tg = ctx["tg"]
        chat_id = ctx["chat_id"]
        db = ctx["db"]

        args = payload["args"]
        run_id = args[0] if args else "current"

        if run_id == "current":
            # Find latest job for this chat?? DB schema doesn't link job to chat explicitly in jobs table?
            # jobs table: job_id, status...
            # research_requests has chat_id.
            # Existing logic usually stored "last_job_{chat_id}" in KV.
            run_id = db.kv_get(f"last_job_{chat_id}")
            if not run_id:
                tg.send_message(chat_id, "❌ 当前无活动任务")
                return

        rows = db.list_jobs(limit=100)  # Simple scan
        job = next((dict(r) for r in rows if r["job_id"] == run_id), None)

        if not job:
            msg = f"❌ 未找到任务: {run_id}"
            if ctx.get("message_id"):
                tg.edit_message(chat_id, ctx.get("message_id"), msg)
            else:
                tg.send_message(chat_id, msg)
            return

        text = render_run_card(job)

        # [P71] Check for interaction options
        interaction_options = None
        if job["status"] == "waiting_input":
            # Try to fetch interaction state
            kv_key = f"job_interaction_{job['job_id']}"
            raw = db.kv_get(kv_key)
            if raw:
                import json

                try:
                    idata = json.loads(raw)
                    prompt = idata.get("prompt", "")
                    interaction_options = idata.get("options", [])
                    if prompt:
                        text += f"\n\n🔔 **等待操作**: {prompt}"
                except Exception as e:
                    logger.warning(f"Failed to parse interaction data: {e}")

        kb = build_run_actions_keyboard(
            job["job_id"], job["status"], interaction_options=interaction_options
        )

        if ctx.get("message_id"):
            tg.edit_message(
                chat_id,
                ctx.get("message_id"),
                text,
                reply_markup=kb,
                parse_mode="Markdown",
            )
        else:
            tg.send_message(chat_id, text, reply_markup=kb, parse_mode="Markdown")

    @registry.register(
        command="/stop",
        description="停止任务",
        usage="/stop <run_id|current>",
        examples=["/stop current"],
        group="Execution",
    )
    def cmd_stop(payload, ctx):
        tg = ctx["tg"]
        chat_id = ctx["chat_id"]
        db = ctx["db"]

        args = payload["args"]
        run_id = args[0] if args else "current"

        if run_id == "current":
            run_id = db.kv_get(f"last_job_{chat_id}")

        if not run_id:
            tg.send_message(chat_id, "❌ 无指定任务")
            return

        db.request_cancel(run_id)
        tg.send_message(chat_id, f"🛑 已请求停止任务: `{run_id}`")

    @registry.register(
        command="/run_refine",
        description="基于旧报告深化研究",
        usage="/run_refine <old_run_id>",
        examples=["/run_refine 123456"],
        group="Execution",
    )
    def cmd_run_refine(payload, ctx):
        """基于旧报告内容深化研究"""
        tg = ctx["tg"]
        chat_id = ctx["chat_id"]
        db = ctx["db"]

        args = payload["args"]
        if not args:
            tg.send_message(chat_id, "❌ 请提供 old_run_id")
            return

        old_run_id = args[0]
        goal = db.kv_get(f"pending_goal_{chat_id}")  # Get pending goal

        if not goal:
            tg.send_message(
                chat_id, "❌ 未找到待处理的 Pending Goal，请重新输入 /run 命令"
            )
            return

        # 1. Load old report content
        from config.settings import settings
        import glob

        search_paths = [
            settings.REPORTS_DIR / old_run_id,
            Path(f"runs/{old_run_id}"),
            settings.BASE_DIR / "runs" / old_run_id,
        ]

        context_content = ""
        for search_dir in search_paths:
            if search_dir.exists() and search_dir.is_dir():
                md_files = list(search_dir.glob("*.md"))
                if md_files:
                    try:
                        context_content = md_files[0].read_text(encoding="utf-8")
                        break
                    except:
                        pass

        if not context_content:
            tg.send_message(
                chat_id, f"⚠️ 未找到旧报告({old_run_id})内容，将作为普通新任务运行"
            )

        # 2. Create NEW job
        job_id = db.create_job(goal, {})
        _save_run_config(job_id, get_user_config(ctx.get("user_id")))
        db.kv_set(f"last_job_{chat_id}", job_id)

        # 3. Start worker with context
        import threading
        from core.services.research.iterative_main import run_iterative_research

        def cancel_check():
            return db.cancel_requested(job_id)

    @registry.register(
        command="/clarify",
        description="管理澄清会话",
        usage="/clarify [start|quick|cancel]",
        examples=["/clarify start", "/clarify cancel"],
        group="Execution",
    )
    def cmd_clarify(payload, ctx):
        """[P60] Clarification Command Handler"""
        tg = ctx["tg"]
        chat_id = ctx["chat_id"]
        db = ctx["db"]
        args = payload["args"]

        session_json = db.kv_get(f"clarify_session_{chat_id}")
        if not session_json:
            tg.send_message(chat_id, "⚠️ 当前没有进行中的澄清会话")
            return

        import json

        session = json.loads(session_json)
        action = args[0] if args else "status"

        if action == "cancel":
            db.kv_set(f"clarify_session_{chat_id}", "")
            tg.send_message(chat_id, "❌ 澄清会话已取消")
            return

        if action == "quick":
            topic = session["topic"]
            tg.send_message(chat_id, f"⚡ 跳过澄清，直接开始研究: {topic}")
            db.kv_set(f"clarify_session_{chat_id}", "")
            # [P93] 传入原始目标
            _start_research_job(ctx, topic, {}, original_goal=topic)
            return

        if action == "start":
            topic = session["topic"]
            answers = session.get("answers", [])

            if not answers:
                clarifications = ""
            else:
                clarifications = "; ".join(answers)

            # [P108] Show research plan instead of starting directly
            _show_research_plan(ctx, topic, clarifications)
            return

        # [P108] Handle plan confirmation
        if action == "confirm_plan":
            plan_json = db.kv_get(f"research_plan_{chat_id}")
            topic = session.get("topic", "")
            answers = session.get("answers", [])

            if not plan_json:
                tg.send_message(chat_id, "⚠️ 未找到研究计划，请重新开始")
                return

            import json as json_mod

            plan = json_mod.loads(plan_json)

            # Build final goal with clarifications
            if answers:
                ans_text = "; ".join(answers)
                final_goal = f"{topic} (补充要求: {ans_text})"
            else:
                final_goal = topic

            tg.send_message(
                chat_id, f"✅ 计划已确认，开始研究!\n目标: {final_goal[:100]}..."
            )

            # [P108 Fix] Skip duplicate check here - user already chose "开启新任务"
            # Clear session and plan before starting
            db.kv_set(f"clarify_session_{chat_id}", "")
            db.kv_set(f"research_plan_{chat_id}", "")

            # [P93] 传入原始目标 topic
            _start_research_job(ctx, final_goal, {}, original_goal=topic)
            return

        # Status
        ans_count = len(session.get("answers", []))
        questions = session.get("questions", [])
        q_text = "\n".join([f"- {q}" for q in questions])

        msg = (
            f"📝 **当前澄清会话**\n"
            f"目标: {session['topic']}\n"
            f"已收集回答: {ans_count} 条\n\n"
            f"**问题**:\n{q_text}\n\n"
            f"请直接回复文本，完成后 /clarify start"
        )
        tg.send_message(chat_id, msg, parse_mode="Markdown")

    @registry.register(
        command="/cancel_setup",
        description="取消任务设置",
        usage="/cancel_setup",
        examples=["/cancel_setup"],
        group="Execution",
    )
    def cmd_cancel_setup(payload, ctx):
        tg = ctx["tg"]
        chat_id = ctx["chat_id"]
        db = ctx["db"]
        message_id = ctx.get("message_id")

        if message_id:
            tg.edit_message(chat_id, message_id, "❌ 任务已取消")
        else:
            tg.send_message(chat_id, "❌ 任务已取消")

        db.kv_set(f"pending_goal_{chat_id}", "")

    # Updated /run_force to handle "current_pending"
    @registry.register(
        command="/run_force",
        description="强制启动新任务 (跳过缓存)",
        usage="/run_force <job_id|current_pending>",
        examples=["/run_force abc123"],
        group="Execution",
    )
    def cmd_run_force(payload, ctx):
        """强制启动新任务，跳过重复检查"""
        tg = ctx["tg"]
        chat_id = ctx["chat_id"]
        db = ctx["db"]
        user_id = ctx["user_id"]

        args = payload["args"]
        if not args:
            tg.send_message(chat_id, "❌ 请提供 job_id")
            return

        arg_id = args[0]

        if arg_id == "current_pending":
            # New flow: get goal from chat storage
            goal = db.kv_get(f"pending_goal_{chat_id}")
            # Create new job ID now
            if not goal:
                tg.send_message(chat_id, "❌ 未找到 Pending Goal")
                return
            job_id = db.create_job(goal, {})
            _save_run_config(job_id, get_user_config(user_id))
            db.kv_set(f"last_job_{chat_id}", job_id)

            # [P86] 立即记录任务到历史 (状态: running)
            from core.execution.history import get_run_history

            history = get_run_history()
            history.add_running_task(goal, job_id)
        else:
            job_id = arg_id
            goal = db.kv_get(f"pending_goal_{job_id}")  # Old flow fallback

        if not goal:
            tg.send_message(chat_id, f"❌ 未找到待处理的任务: {job_id}")
            return

        # Start the actual worker (copy logic from /run)
        import threading
        from core.services.research.iterative_main import run_iterative_research

        def cancel_check():
            return db.cancel_requested(job_id)

        def run_worker():
            try:
                import asyncio

                state = asyncio.run(
                    run_iterative_research(
                        goal=goal,
                        max_iterations=3,
                        cancel_callback=cancel_check,
                        job_id=job_id,
                    )
                )
                # [P32] Send report document logic
                report_path = getattr(state, "final_report_path", None)
                if report_path and Path(report_path).exists():
                    tg.send_document(
                        chat_id, report_path, caption=f"✅ 研究报告 (ID: {job_id})"
                    )
                else:
                    tg.send_message(
                        chat_id, f"⚠️ 报告文件未找到，但研究已完成 (ID: {job_id})"
                    )

                tg.send_message(chat_id, f"✅ 研究完成! (Iter: {state.iteration + 1})")
                db.update_job_status(job_id, "completed")

                # Record history
                try:
                    status = (
                        "completed"
                        if not hasattr(state, "cancelled") or not state.cancelled
                        else "cancelled"
                    )
                    summary = f"论文: {len(state.paper_pool)}, 证据: {len(state.evidence_set)}"
                    history = get_run_history()
                    r_path = (
                        getattr(state, "final_report_path", "")
                        if "state" in locals()
                        else ""
                    )
                    history.add_run(goal, job_id, status, summary, str(r_path))
                except Exception as e:
                    logger.error(f"Failed to record run history: {e}")
                    tg.send_message(chat_id, f"⚠️ 历史记录保存失败: {e}")

            except Exception as e:
                logger.error(f"Error in run_worker: {e}", exc_info=True)
                tg.send_message(chat_id, f"❌ 研究出错: {e}")
                db.update_job_status(job_id, "failed", str(e))

        tg.send_message(chat_id, f"🚀 开始新任务: `{job_id}`")
        threading.Thread(target=run_worker, daemon=True).start()

        # Clean up
        db.kv_set(f"pending_goal_{chat_id}", "")

    @registry.register(
        command="/run_load",
        description="加载已有研究结果",
        usage="/run_load <run_id>",
        examples=["/run_load abc123"],
        group="Execution",
    )
    def cmd_run_load(payload, ctx):
        """加载已有的研究结果"""
        tg = ctx["tg"]
        chat_id = ctx["chat_id"]

        args = payload["args"]
        if not args:
            tg.send_message(chat_id, "❌ 请提供 run_id")
            return

        run_id = args[0]

        # Try to find report in multiple locations
        from config.settings import settings
        import glob

        search_paths = [
            settings.REPORTS_DIR / run_id,  # data/reports/{id}/
            Path(f"runs/{run_id}"),  # runs/{id}/
            settings.BASE_DIR / "runs" / run_id,  # {BASE}/runs/{id}/
        ]

        report_path = None
        for search_dir in search_paths:
            if search_dir.exists() and search_dir.is_dir():
                # Look for any .md file
                md_files = list(search_dir.glob("*.md"))
                if md_files:
                    report_path = md_files[0]  # Take first .md file
                    break

        if report_path and report_path.exists():
            try:
                content = report_path.read_text(encoding="utf-8")
                # Truncate for message preview
                if len(content) > 3500:
                    preview = content[:3500] + "\n\n...[完整版见附件]"
                else:
                    preview = content

                tg.send_message(
                    chat_id, f"📄 **报告加载成功**:\n\n{preview}", parse_mode="Markdown"
                )

                # Also send as document
                tg.send_document(
                    chat_id, str(report_path), caption=f"📎 完整报告 (ID: {run_id})"
                )

            except Exception as e:
                tg.send_message(chat_id, f"❌ 读取报告失败: {e}")
        else:
            tg.send_message(
                chat_id,
                f"❌ 未找到报告 (ID: {run_id})\n\n此任务可能是在 P26 更新之前运行的，报告未保存。请使用 `🆕 开始新任务` 重新运行。",
            )

    @registry.register(
        command="/run_resume",
        description="从检查点恢复中断的任务",
        usage="/run_resume <run_id>",
        examples=["/run_resume abc123"],
        group="Execution",
    )
    def cmd_run_resume(payload, ctx):
        """[P86] 从检查点恢复中断的任务"""
        tg = ctx["tg"]
        chat_id = ctx["chat_id"]
        db = ctx["db"]
        user_id = ctx["user_id"]

        args = payload["args"]
        if not args:
            tg.send_message(chat_id, "❌ 请提供 run_id")
            return

        run_id = args[0]

        # 加载检查点
        from core.services.research.checkpoint_manager import (
            load_checkpoint,
            delete_checkpoint,
        )

        checkpoint = load_checkpoint(run_id)

        if not checkpoint:
            tg.send_message(
                chat_id,
                f"❌ 未找到检查点 (ID: {run_id})\n\n可能任务未保存检查点，请重新开始。",
            )
            return

        phase = checkpoint.get("phase", "unknown")
        timestamp = checkpoint.get("timestamp", "")
        state_data = checkpoint.get("state", {})
        goal = state_data.get("problem_spec", {}).get("goal", "")

        tg.send_message(
            chat_id, f"📥 正在从检查点恢复...\n\n阶段: {phase}\n时间: {timestamp}"
        )

        # 启动恢复任务
        import threading
        from core.services.research.iterative_main import run_iterative_research

        def cancel_check():
            return db.cancel_requested(run_id)

        def resume_worker():
            try:
                import asyncio

                # 重建状态对象
                from core.services.research.core_types import IterativeResearchState

                initial_state = IterativeResearchState.from_dict(state_data)

                # Check for cancelled flag
                if initial_state.cancelled:
                    tg.send_message(
                        chat_id,
                        f"⚠️ 检测到此检查点标记为 '已取消'，尝试重置状态并继续...",
                    )
                    initial_state.cancelled = False

                # [P100] Make interaction handler
                handle_interaction = _make_interaction_handler(
                    db, tg, chat_id, run_id, logger
                )

                state = asyncio.run(
                    run_iterative_research(
                        goal=goal,
                        max_iterations=3,
                        cancel_callback=cancel_check,
                        job_id=run_id,  # Must match
                        initial_state=initial_state,
                        interaction_callback=handle_interaction,  # [P100] Pass callback
                    )
                )

                # 完成后删除检查点
                delete_checkpoint(run_id)

                report_path = getattr(state, "final_report_path", None)
                if report_path and Path(report_path).exists():
                    tg.send_document(
                        chat_id, report_path, caption=f"✅ 研究报告 (ID: {run_id})"
                    )

                tg.send_message(chat_id, f"✅ 恢复任务完成!")
                # [P101] Clear previous error message
                db.update_job_status(run_id, "completed", "")

            except Exception as e:
                logger.error(f"Resume worker error: {e}", exc_info=True)
                tg.send_message(chat_id, f"❌ 恢复任务出错: {e}")
                db.update_job_status(run_id, "failed", str(e))

        tg.send_message(chat_id, f"🚀 恢复任务: `{run_id}`")
        threading.Thread(target=resume_worker, daemon=True).start()


def _start_research_job(ctx, goal: str, flags: dict, original_goal: str = ""):
    """Helper to start the actual research job"""
    tg = ctx["tg"]
    chat_id = ctx["chat_id"]
    db = ctx["db"]
    user_id = ctx["user_id"]

    # 解析年份和评分参数
    min_year = None
    if flags.get("year5"):
        from datetime import datetime

        min_year = datetime.now().year - 5
    elif flags.get("year10"):
        from datetime import datetime

        min_year = datetime.now().year - 10
    elif flags.get("year"):
        try:
            min_year = int(flags.get("year"))
        except (ValueError, TypeError):
            pass

    min_score = float(flags.get("score", 0) or 0)

    # Create Job
    job_args = {
        "max_results": int(flags.get("max", 50)),
        "model_override": get_user_config(user_id, db).model,
        "min_year": min_year,
        "min_score": min_score,
    }
    job_id = db.create_job(goal, job_args)
    _save_run_config(job_id, get_user_config(user_id, db))
    db.kv_set(f"last_job_{chat_id}", job_id)

    # [P89 Fix] 立即记录任务到历史 (状态: running)
    from core.execution.history import get_run_history

    history = get_run_history()
    # [P93] 传入原始目标
    history.add_running_task(goal, job_id, original_goal=original_goal)

    # 构建启动消息
    start_msg = f"🚀 任务启动: `{job_id}`\n目标: {goal}"
    if min_year:
        start_msg += f"\n📅 年份筛选: ≥{min_year}"
    if min_score > 0:
        start_msg += f"\n🏆 最低评分: {min_score}"
    tg.send_message(chat_id, start_msg)

    # Start Worker
    import threading
    from core.services.research.iterative_main import run_iterative_research

    def cancel_check():
        return db.cancel_requested(job_id)

    def run_worker():
        try:
            # [P71] Ensure status is updated immediately
            db.update_job_status(job_id, "running")

            import asyncio
            import time

            # [P71] Interaction Callback Implementation
            # [P100] Use shared factory
            handle_interaction = _make_interaction_handler(
                db, tg, chat_id, job_id, logger
            )

            # 6. Run Research Job
            state = asyncio.run(
                run_iterative_research(
                    goal=goal,
                    max_iterations=3,
                    cancel_callback=cancel_check,
                    job_id=job_id,
                    interaction_callback=handle_interaction,
                    min_year=min_year,
                    min_score=min_score,
                )
            )

            # [P59] Send Report
            report_path = getattr(state, "final_report_path", None)
            if report_path and Path(report_path).exists():
                tg.send_document(
                    chat_id, report_path, caption=f"✅ 研究报告 (ID: {job_id})"
                )
            else:
                tg.send_message(chat_id, "⚠️ 报告未生成")

            db.update_job_status(job_id, "completed", "")

            # History
            try:
                from core.execution.history import get_run_history

                history = get_run_history()
                history.add_run(goal, job_id, "completed", "", str(report_path or ""))
            except:
                pass

        except Exception as e:
            logger.error(f"Worker failed: {e}")
            tg.send_message(chat_id, f"❌ 任务失败: {e}")
            db.update_job_status(job_id, "failed", str(e))

    threading.Thread(target=run_worker, daemon=True).start()


def _start_clarification(ctx, goal: str):
    """[P60] Initialize Clarification Session"""
    tg = ctx["tg"]
    chat_id = ctx["chat_id"]
    db = ctx["db"]

    tg.send_message(chat_id, "🤔 正在分析研究目标，生成澄清问题...")

    from core.services.research.planner import ResearchPlanner

    planner = ResearchPlanner(lambda x: None)
    questions = planner.generate_clarifying_questions(goal)

    session = {
        "topic": goal,
        "questions": questions,
        "answers": [],
        "created_at": datetime.now().isoformat(),
    }
    db.kv_set(f"clarify_session_{chat_id}", json.dumps(session))

    q_text = "\n".join([f"{i + 1}. {q}" for i, q in enumerate(questions)])
    msg = (
        f"🎯 **需明确研究范围**\n\n"
        f"目标: {goal}\n\n"
        f"**请直接回复以下问题 (可分多条)**:\n"
        f"{q_text}\n\n"
        f"回复完成后，请点击 [✅ 开始研究]"
    )

    buttons = [
        [{"text": "✅ 开始研究", "callback_data": "cmd:/clarify start"}],
        [
            {"text": "⚡ 快速开始 (跳过)", "callback_data": "cmd:/clarify quick"},
            {"text": "❌ 取消", "callback_data": "cmd:/clarify cancel"},
        ],
    ]

    tg.send_message(
        chat_id, msg, reply_markup={"inline_keyboard": buttons}, parse_mode="Markdown"
    )
