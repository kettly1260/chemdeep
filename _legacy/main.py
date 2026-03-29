import typer
import threading
import time
import logging
import json
from pathlib import Path


# 配置日志
log_dir = Path("logs")
log_dir.mkdir(exist_ok=True)

# 清理旧日志文件（保留最近的）
def cleanup_old_logs():
    for log_file in log_dir.glob("*.log"):
        try:
            # 清空日志文件内容（每次启动时）
            log_file.write_text("", encoding="utf-8")
        except Exception:
            pass

cleanup_old_logs()

# 创建格式化器
log_format = logging.Formatter('%(asctime)s [%(levelname)s] %(name)s: %(message)s')

# 根日志器
root_logger = logging.getLogger()
root_logger.setLevel(logging.DEBUG)

# 1. 控制台日志 (INFO+)
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(log_format)
root_logger.addHandler(console_handler)

# 2. 全量调试日志
debug_handler = logging.FileHandler(log_dir / 'debug.log', encoding='utf-8')
debug_handler.setLevel(logging.DEBUG)
debug_handler.setFormatter(log_format)
root_logger.addHandler(debug_handler)

# 3. 错误和警告日志 (WARNING+) - 便于快速定位问题
error_handler = logging.FileHandler(log_dir / 'errors.log', encoding='utf-8')
error_handler.setLevel(logging.WARNING)
error_handler.setFormatter(log_format)
root_logger.addHandler(error_handler)

# 4. 按模块分离日志
def setup_module_logger(name: str, filename: str, level=logging.DEBUG):
    """为特定模块创建独立日志文件"""
    handler = logging.FileHandler(log_dir / filename, encoding='utf-8')
    handler.setLevel(level)
    handler.setFormatter(log_format)
    module_logger = logging.getLogger(name)
    module_logger.addHandler(handler)

# 抓取模块日志
setup_module_logger('fetcher', 'fetcher.log')
# Bot 模块日志
setup_module_logger('main', 'bot.log')
# AI 模块日志
setup_module_logger('ai', 'ai.log')
# HTTP 日志级别调高，减少噪音
logging.getLogger('httpcore').setLevel(logging.WARNING)
logging.getLogger('httpx').setLevel(logging.WARNING)

logger = logging.getLogger('main')

app = typer.Typer(no_args_is_help=True)


@app.command("bot")
def run_bot():
    """启动 Telegram Bot（主流程）"""
    from core.bot import TelegramClient
    from core.search import SearchOrchestrator
    from core.ai import AIClient, MODEL_STATE
    from core.scholar_search import UnifiedSearcher
    from utils.db import DB
    from utils.notifier import Notifier
    from config.settings import settings
    
    # 验证配置
    errors = settings.validate()
    if errors:
        for e in errors:
            typer.echo(f"❌ {e}")
        raise typer.Exit(1)
    
    tg = TelegramClient()
    db = DB()
    notifier = Notifier(tg, settings.TELEGRAM_CHAT_ID)
    search_orchestrator = SearchOrchestrator(db)
    
    # 全局 AI 客户端
    global_ai = AIClient(notify_callback=lambda x: logger.info(x))
    
    # 文件下载目录
    download_dir = settings.LIBRARY_DIR / "uploads"
    download_dir.mkdir(parents=True, exist_ok=True)
    
    offset = db.kv_get_int("telegram_offset")
    
    typer.echo("=" * 50)
    typer.echo("Deep Research Bot running... (Ctrl+C to stop)")
    typer.echo("=" * 50)
    typer.echo(settings.summary())
    typer.echo("=" * 50)
    logger.info("Bot 启动")
    
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
            
            # ========== 处理 callback_query (按钮点击) ==========
            callback_query = u.get("callback_query")
            if callback_query:
                cb_id = callback_query.get("id")
                cb_data = callback_query.get("data", "")
                cb_chat = callback_query.get("message", {}).get("chat", {})
                cb_chat_id = cb_chat.get("id")
                
                if cb_chat_id and cb_chat_id in settings.TELEGRAM_ALLOWED_CHAT_IDS:
                    logger.info(f"收到按钮点击 [{cb_chat_id}]: {cb_data}")
                    
                    # 回应 callback (消除加载状态)
                    tg.answer_callback_query(cb_id)
                    
                    # 处理不同的 callback data
                    if cb_data.startswith("run:"):
                        # 格式: run:papers_file_path
                        papers_file = Path(cb_data[4:])
                        
                        if not papers_file.exists():
                            tg.send_message(cb_chat_id, f"❌ 文件不存在: {papers_file}")
                        else:
                            # 执行 /run 逻辑
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
                        
                    elif cb_data.startswith("report:"):
                        # 格式: report:research_id
                        research_id = cb_data[7:]
                        tg.send_message(cb_chat_id, f"📊 正在生成报告: {research_id}\n请使用 /report {research_id} 命令")
                        
                    elif cb_data.startswith("list:"):
                        # 格式: list:papers_file_path
                        papers_file = Path(cb_data[5:])
                        if papers_file.exists():
                            try:
                                content = papers_file.read_text(encoding="utf-8")
                                lines = content.strip().split("\n")[:20]  # 最多显示20条
                                preview = "\n".join(lines)
                                if len(content.strip().split("\n")) > 20:
                                    preview += f"\n\n... 还有 {len(content.strip().split(chr(10))) - 20} 条"
                                tg.send_message(cb_chat_id, f"📋 论文列表预览:\n\n{preview}")
                            except Exception as e:
                                tg.send_message(cb_chat_id, f"❌ 读取失败: {e}")
                        else:
                            tg.send_message(cb_chat_id, f"❌ 文件不存在: {papers_file}")
                        
                    elif cb_data.startswith("setmodel:"):
                        # 格式: setmodel:model_name
                        new_model = cb_data[9:]
                        old_model = MODEL_STATE.openai_model
                        MODEL_STATE.set_openai_model(new_model)
                        tg.send_message(cb_chat_id, f"✅ 模型已切换\n\n旧模型: {old_model}\n新模型: {new_model}")
                        
                continue
            
            msg = u.get("message") or u.get("edited_message")
            if not msg:
                continue
            
            chat = msg.get("chat", {})
            chat_id = chat.get("id")
            text = (msg.get("text") or "").strip()
            
            if not chat_id:
                continue
            
            if chat_id not in settings.TELEGRAM_ALLOWED_CHAT_IDS:
                continue
            
            # ========== 处理文件上传 ==========
            if msg.get("document"):
                doc = msg["document"]
                file_name = doc.get("file_name", "uploaded_file")
                file_id = doc.get("file_id")
                
                # 检查文件类型
                if not file_name.lower().endswith(('.txt', '.csv', '.ris')):
                    tg.send_message(chat_id, "⚠️ 请上传 .txt, .csv 或 .ris 格式的文献导出文件")
                    continue
                
                logger.info(f"收到文件上传: {file_name}")
                tg.send_message(chat_id, f"📥 正在下载文件: {file_name}")
                
                def handle_file_upload():
                    try:
                        # 下载文件
                        file_path = tg.download_file(file_id, download_dir / file_name)
                        
                        if file_path and file_path.exists():
                            tg.send_message(chat_id, f"✅ 文件已保存: {file_path.name}\n\n使用以下命令开始分析:\n/run {file_path} goal=synthesis max=50")
                            
                            # 询问是否自动开始
                            tg.send_message(chat_id, "💡 发送 /autorun 自动开始分析此文件")
                            
                            # 保存最近上传的文件路径
                            db.kv_set(f"last_upload_{chat_id}", str(file_path))
                        else:
                            tg.send_message(chat_id, "❌ 文件下载失败")
                    except Exception as e:
                        logger.error(f"文件处理失败: {e}")
                        tg.send_message(chat_id, f"❌ 文件处理失败: {e}")
                
                threading.Thread(target=handle_file_upload, daemon=True).start()
                continue
            
            if not text:
                continue
            
            logger.info(f"收到消息 [{chat_id}]: {text[:100]}...")
            
            # ========== /help 命令 ==========
            if text.startswith("/help"):
                from core.ai import MODEL_STATE
                
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
                continue
            
            # ========== /deepresearch 或 /dr 命令 ==========
            if text.startswith("/deepresearch") or text.startswith("/dr "):
                from core.deep_research import DeepResearcher
                
                # 解析问题
                if text.startswith("/deepresearch"):
                    parts = text.split(maxsplit=1)
                else:
                    parts = text.split(maxsplit=1)
                
                if len(parts) < 2 or not parts[1].strip():
                    tg.send_message(chat_id, 
                        "❌ 请输入研究问题\n\n"
                        "用法: /deepresearch <问题>\n"
                        "或: /dr <问题>\n\n"
                        "示例:\n"
                        "/dr 如何合成噻吩与碳硼烷的偶联化合物？"
                    )
                    continue
                
                question = parts[1].strip()
                
                # 保存问题到会话状态
                research_state = {
                    "question": question,
                    "stage": "planning",
                    "chat_id": chat_id
                }
                db.kv_set(f"research_{chat_id}", json.dumps(research_state))
                
                tg.send_message(chat_id, f"🔬 收到研究问题:\n{question}\n\n正在生成研究计划...")
                
                def run_deep_research():
                    try:
                        researcher = DeepResearcher(notify_callback=lambda x: tg.send_message(chat_id, x))
                        
                        # 生成计划
                        plan = researcher.generate_plan(question)
                        
                        # 更新状态
                        research_state["stage"] = "confirm"
                        research_state["plan"] = plan.to_dict()
                        db.kv_set(f"research_{chat_id}", json.dumps(research_state))
                        
                        # 发送计划
                        plan_text = researcher.format_plan(plan)
                        tg.send_message(chat_id, plan_text)
                        
                    except Exception as e:
                        logger.error(f"深度研究失败: {e}", exc_info=True)
                        tg.send_message(chat_id, f"❌ 生成计划失败: {e}")
                
                threading.Thread(target=run_deep_research, daemon=True).start()
                continue
            
            # ========== /confirm 命令（确认研究计划）==========
            if text.startswith("/confirm"):
                from core.deep_research import DeepResearcher, ResearchPlan
                
                # 获取保存的研究状态
                state_json = db.kv_get(f"research_{chat_id}")
                if not state_json:
                    tg.send_message(chat_id, "❌ 没有待确认的研究计划\n\n请先使用 /deepresearch <问题> 开始研究")
                    continue
                
                try:
                    research_state = json.loads(state_json)
                except:
                    tg.send_message(chat_id, "❌ 研究状态无效")
                    continue
                
                if research_state.get("stage") != "confirm":
                    tg.send_message(chat_id, "❌ 当前没有待确认的计划")
                    continue
                
                question = research_state.get("question", "")
                plan_data = research_state.get("plan", {})
                plan = ResearchPlan.from_dict(plan_data)
                plan.question = question
                
                tg.send_message(chat_id, "✅ 计划已确认，开始执行搜索...")
                
                def execute_research():
                    try:
                        researcher = DeepResearcher(notify_callback=lambda x: tg.send_message(chat_id, x))
                        
                        # 执行搜索
                        search_result = researcher.execute_search(plan)
                        
                        if search_result["count"] == 0:
                            tg.send_message(chat_id, "❌ 未找到相关论文")
                            return
                        
                        # 保存结果
                        research_id = f"dr_{int(time.time())}"
                        papers_file = researcher.save_search_results(research_id, search_result["papers"])
                        
                        # 创建 inline keyboard
                        inline_keyboard = {
                            "inline_keyboard": [
                                [
                                    {"text": "📥 抓取论文", "callback_data": f"run:{papers_file}"},
                                    {"text": "📊 生成报告", "callback_data": f"report:{research_id}"}
                                ],
                                [
                                    {"text": "📋 查看论文列表", "callback_data": f"list:{papers_file}"}
                                ]
                            ]
                        }
                        
                        tg.send_message(chat_id, 
                            f"✅ 搜索完成!\n\n"
                            f"📊 找到 {search_result['count']} 篇论文\n"
                            f"📁 来源: {', '.join(search_result['sources_used'])}\n"
                            f"💾 已保存: {papers_file}\n\n"
                            f"点击下方按钮继续操作:",
                            reply_markup=inline_keyboard
                        )
                        
                        # 更新状态
                        research_state["stage"] = "done"
                        research_state["papers_file"] = str(papers_file)
                        research_state["research_id"] = research_id
                        db.kv_set(f"research_{chat_id}", json.dumps(research_state))
                        
                    except Exception as e:
                        logger.error(f"执行研究失败: {e}", exc_info=True)
                        tg.send_message(chat_id, f"❌ 执行失败: {e}")
                
                threading.Thread(target=execute_research, daemon=True).start()
                continue
            
            # ========== /scholar 命令 ==========
            if text.startswith("/scholar"):
                from core.scholar_search import ScholarSearcher
                
                parts = text.split(maxsplit=1)
                if len(parts) < 2:
                    tg.send_message(chat_id, "用法: /scholar <关键词>")
                    continue
                
                query = parts[1].strip()
                tg.send_message(chat_id, f"🔍 正在搜索 Google Scholar: {query}")
                
                def run_scholar():
                    try:
                        searcher = ScholarSearcher(notify_callback=lambda x: tg.send_message(chat_id, x))
                        result = searcher.search(query, max_results=30, headless=False)
                        
                        if result["success"]:
                            tg.send_message(chat_id, f"✅ 找到 {result['count']} 篇论文")
                        else:
                            tg.send_message(chat_id, f"❌ 搜索失败: {result.get('error', '未知错误')}")
                    except Exception as e:
                        tg.send_message(chat_id, f"❌ 搜索错误: {e}")
                
                threading.Thread(target=run_scholar, daemon=True).start()
                continue
            
            # ========== /models 命令 ==========
            if text.startswith("/models"):
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
                        
                        # 生成文本列表
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
                        
                        # 创建 inline keyboard (显示常用模型按钮)
                        # 限制按钮数量，每行2个，最多10个按钮
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
                continue
            
            # ========== /setmodel 命令 ==========
            if text.startswith("/setmodel"):
                parts = text.split(maxsplit=1)
                if len(parts) < 2:
                    # 显示帮助
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
                    continue
                
                new_model = parts[1].strip()
                old_model = MODEL_STATE.openai_model
                
                # 验证模型是否存在
                def validate_and_set():
                    try:
                        ai = AIClient(notify_callback=lambda x: tg.send_message(chat_id, x))
                        models = ai.fetch_openai_models()
                        model_ids = [m["id"] for m in models]
                        
                        if new_model in model_ids:
                            MODEL_STATE.set_openai_model(new_model)
                            tg.send_message(chat_id, f"✅ 模型已切换\n\n旧模型: {old_model}\n新模型: {new_model}\n\n使用 /testai 测试新模型")
                        else:
                            # 模糊匹配
                            matches = [m for m in model_ids if new_model.lower() in m.lower()]
                            if matches:
                                suggestion = "\n".join([f"  • {m}" for m in matches[:5]])
                                tg.send_message(chat_id, f"❌ 模型 '{new_model}' 不存在\n\n相似模型:\n{suggestion}\n\n请使用完整的模型名称")
                            else:
                                tg.send_message(chat_id, f"❌ 模型 '{new_model}' 不存在\n\n使用 /models all 查看全部可用模型")
                    except Exception as e:
                        # 即使验证失败也允许设置（可能是自定义模型）
                        MODEL_STATE.set_openai_model(new_model)
                        tg.send_message(chat_id, f"⚠️ 无法验证模型，已强制设置为: {new_model}\n\n使用 /testai 测试是否可用")
                
                threading.Thread(target=validate_and_set, daemon=True).start()
                continue
            
            # ========== /currentmodel 命令 ==========
            if text.startswith("/currentmodel") or text.startswith("/current"):
                from core.analyzer import PREPROCESS_LLM_STATE
                current_models = (
                    f"🤖 当前 AI 配置\n\n"
                    f"【云端模型 (报告生成)】\n"
                    f"  模型: {MODEL_STATE.openai_model}\n"
                    f"  API: {MODEL_STATE.openai_api_base}\n\n"
                    f"【预处理模型 (论文分析)】\n"
                    f"  模型: {PREPROCESS_LLM_STATE.model}\n"
                    f"  API: {PREPROCESS_LLM_STATE.api_base}\n\n"
                    f"【Gemini】\n"
                    f"  模型: {MODEL_STATE.gemini_model}\n\n"
                    f"💡 命令:\n"
                    f"  /setmodel <model> - 切换云端模型\n"
                    f"  /apibase <url> - 设置云端 API 地址\n"
                    f"  /premodel <model> - 切换预处理模型\n"
                    f"  /preapi <url> - 设置预处理 API"
                )
                tg.send_message(chat_id, current_models)
                continue
            
            # ========== /setgemini 命令 ==========
            if text.startswith("/setgemini"):
                parts = text.split(maxsplit=1)
                if len(parts) < 2:
                    tg.send_message(chat_id, f"用法: /setgemini <model_id>\n\n当前 Gemini 模型: {MODEL_STATE.gemini_model}")
                    continue
                
                new_model = parts[1].strip()
                old_model = MODEL_STATE.gemini_model
                MODEL_STATE.set_gemini_model(new_model)
                tg.send_message(chat_id, f"✅ Gemini 模型已切换\n\n旧模型: {old_model}\n新模型: {new_model}")
                continue
            
            # ========== /apibase 命令 ==========
            if text.startswith("/apibase"):
                parts = text.split(maxsplit=1)
                if len(parts) < 2:
                    tg.send_message(chat_id, 
                        f"用法: /apibase <url>\n\n"
                        f"当前 API: {MODEL_STATE.openai_api_base}\n\n"
                        f"示例:\n"
                        f"  /apibase https://api.openai.com/v1\n"
                        f"  /apibase https://generativelanguage.googleapis.com/v1beta/openai\n"
                        f"  /apibase https://api.deepseek.com"
                    )
                    continue
                
                new_api = parts[1].strip()
                old_api = MODEL_STATE.openai_api_base
                MODEL_STATE.set_openai_api_base(new_api)
                tg.send_message(chat_id, f"✅ 云端 API 已切换\n\n旧地址: {old_api}\n新地址: {new_api}\n\n⚠️ 新的 AIClient 会使用新地址")
                continue
            
            # ========== /apikey 命令 ==========
            if text.startswith("/apikey"):
                parts = text.split(maxsplit=1)
                if len(parts) < 2:
                    tg.send_message(chat_id, 
                        f"用法: /apikey <key>\n\n"
                        f"设置云端 API Key（当前状态: {'已设置' if MODEL_STATE.openai_api_key else '未设置'}）"
                    )
                    continue
                
                new_key = parts[1].strip()
                MODEL_STATE.set_openai_api_key(new_key)
                tg.send_message(chat_id, "✅ 云端 API Key 已更新")
                continue
            
            # ========== /premodel 命令（预处理模型）==========
            if text.startswith("/localmodel") or text.startswith("/premodel"):
                from core.analyzer import PREPROCESS_LLM_STATE, PreprocessLLMClient
                
                parts = text.split(maxsplit=1)
                if len(parts) < 2:
                    # 显示当前配置和可用模型
                    tg.send_message(chat_id, "🔍 正在获取预处理模型信息...")
                    
                    def show_preprocess_models():
                        try:
                            client = PreprocessLLMClient(
                                api_base=PREPROCESS_LLM_STATE.api_base,
                                model=PREPROCESS_LLM_STATE.model,
                                api_key=PREPROCESS_LLM_STATE.api_key
                            )
                            models = client.list_models()
                            
                            msg = (
                                f"🔧 预处理模型配置\n\n"
                                f"【当前设置】\n"
                                f"  API: {PREPROCESS_LLM_STATE.api_base}\n"
                                f"  模型: {PREPROCESS_LLM_STATE.model}\n\n"
                            )
                            
                            if models:
                                msg += f"【可用模型】({len(models)}个)\n"
                                for m in models[:15]:
                                    msg += f"  • {m}\n"
                                if len(models) > 15:
                                    msg += f"  ... 还有 {len(models) - 15} 个\n"
                            else:
                                msg += "【可用模型】\n  ⚠️ 无法获取模型列表\n"
                            
                            msg += (
                                f"\n💡 命令:\n"
                                f"  /premodel <model> - 设置预处理模型\n"
                                f"  /preapi <url> - 设置预处理 API\n"
                                f"  /prekey <key> - 设置预处理 API Key"
                            )
                            tg.send_message(chat_id, msg)
                        except Exception as e:
                            tg.send_message(chat_id, f"❌ 获取预处理模型失败: {e}\n\n确保 Ollama/LM Studio 正在运行，或检查 API 地址")
                    
                    threading.Thread(target=show_preprocess_models, daemon=True).start()
                else:
                    # 设置模型
                    new_model = parts[1].strip()
                    old_model = PREPROCESS_LLM_STATE.model
                    PREPROCESS_LLM_STATE.set_model(new_model)
                    tg.send_message(chat_id, f"✅ 预处理模型已切换\n\n旧模型: {old_model}\n新模型: {new_model}")
                continue
            
            # ========== /preapi 命令（预处理 API）==========
            if text.startswith("/localapi") or text.startswith("/preapi"):
                from core.analyzer import PREPROCESS_LLM_STATE
                
                parts = text.split(maxsplit=1)
                if len(parts) < 2:
                    tg.send_message(chat_id, 
                        f"用法: /preapi <url>\n\n"
                        f"当前 API: {PREPROCESS_LLM_STATE.api_base}\n\n"
                        f"示例:\n"
                        f"  /preapi http://localhost:11434/v1  (Ollama)\n"
                        f"  /preapi http://localhost:1234/v1   (LM Studio)\n"
                        f"  /preapi https://api.deepseek.com   (便宜云端)"
                    )
                    continue
                
                new_api = parts[1].strip()
                old_api = PREPROCESS_LLM_STATE.api_base
                PREPROCESS_LLM_STATE.set_api_base(new_api)
                tg.send_message(chat_id, f"✅ 预处理 API 已切换\n\n旧地址: {old_api}\n新地址: {new_api}")
                continue
            
            # ========== /prekey 命令（预处理 API Key）==========
            if text.startswith("/prekey"):
                from core.analyzer import PREPROCESS_LLM_STATE
                
                parts = text.split(maxsplit=1)
                if len(parts) < 2:
                    tg.send_message(chat_id, 
                        f"用法: /prekey <api_key>\n\n"
                        f"设置预处理模型的 API Key\n"
                        f"（本地 Ollama 通常不需要 Key）"
                    )
                    continue
                
                new_key = parts[1].strip()
                PREPROCESS_LLM_STATE.set_api_key(new_key)
                tg.send_message(chat_id, "✅ 预处理 API Key 已更新")
                continue
            
            # ========== /provider 命令 ==========
            if text.startswith("/provider"):
                parts = text.split(maxsplit=1)
                if len(parts) < 2:
                    provider_help = (
                        f"用法: /provider <openai|gemini|auto>\n\n"
                        f"当前: {settings.AI_PROVIDER}\n\n"
                        f"说明:\n"
                        f"  openai - 使用 OpenAI 兼容 API\n"
                        f"  gemini - 使用 Google Gemini\n"
                        f"  auto - 优先 OpenAI，失败则尝试 Gemini"
                    )
                    tg.send_message(chat_id, provider_help)
                    continue
                
                new_provider = parts[1].strip().lower()
                if new_provider not in ["openai", "gemini", "auto"]:
                    tg.send_message(chat_id, "❌ 无效的 provider，可选: openai, gemini, auto")
                    continue
                
                # 注意：这只是临时修改，重启后会恢复
                import os
                os.environ["CHEMDEEP_AI_PROVIDER"] = new_provider
                settings.AI_PROVIDER = new_provider
                tg.send_message(chat_id, f"✅ AI Provider 已切换为: {new_provider}\n\n⚠️ 此设置重启后会恢复，如需永久修改请编辑 config/.env")
                continue
            
            # ========== /testai 命令 ==========
            if text.startswith("/testai"):
                parts = text.split(maxsplit=1)
                prompt = parts[1].strip() if len(parts) > 1 else "你好，请用一句话介绍自己"
                
                tg.send_message(chat_id, f"🧪 测试 AI...\n模型: {MODEL_STATE.openai_model}\nPrompt: {prompt}")
                
                def test_ai():
                    try:
                        ai = AIClient(notify_callback=lambda x: tg.send_message(chat_id, x))
                        result = ai.call(prompt, json_mode=False)
                        
                        if result.success:
                            response_text = result.data.get("text", str(result.data))
                            tg.send_message(chat_id, f"✅ AI 响应 ({result.model}):\n\n{response_text[:2000]}")
                        else:
                            tg.send_message(chat_id, f"❌ AI 调用失败: {result.error}")
                    except Exception as e:
                        tg.send_message(chat_id, f"❌ 测试失败: {e}")
                
                threading.Thread(target=test_ai, daemon=True).start()
                continue
            
            # ========== /analyze 命令 ==========
            if text.startswith("/analyze"):
                from core.analyzer import PaperAnalyzer, PreprocessLLMClient, PREPROCESS_LLM_STATE
                
                parts = text.split()
                job_id = None
                use_cloud = False
                
                # 解析参数
                for part in parts[1:]:
                    if part.lower() == "cloud":
                        use_cloud = True
                    elif not job_id and not part.startswith("-"):
                        job_id = part.strip()
                
                if not job_id:
                    # 获取最近的任务
                    rows = db.list_jobs(limit=5)
                    for r in rows:
                        r_dict = dict(r)
                        if r_dict.get("status") in ("running", "done"):
                            job_id = r_dict["job_id"]
                            break
                
                if not job_id:
                    tg.send_message(chat_id, 
                        "❌ 没有找到任务\n\n"
                        "用法: /analyze [job_id] [cloud]\n\n"
                        "参数:\n"
                        "  job_id - 任务 ID（可选，默认最近任务）\n"
                        "  cloud - 使用云端模型分析（跳过预处理模型）"
                    )
                    continue
                
                if use_cloud:
                    tg.send_message(chat_id, f"🔬 开始分析任务 {job_id}...\n\n使用云端模型: {MODEL_STATE.openai_model}")
                else:
                    tg.send_message(chat_id, f"🔬 开始分析任务 {job_id}...\n\n使用预处理模型: {PREPROCESS_LLM_STATE.model}")
                
                def run_analysis():
                    try:
                        # 获取任务信息
                        papers = db.list_papers(job_id)
                        fetched_papers = [dict(p) for p in papers if dict(p).get("status") == "fetched"]
                        
                        if not fetched_papers:
                            tg.send_message(chat_id, "❌ 没有已抓取的论文可供分析")
                            return
                        
                        # 获取任务目标
                        jobs = db.list_jobs(limit=20)
                        goal = "synthesis"
                        for j in jobs:
                            j_dict = dict(j)
                            if j_dict.get("job_id") == job_id:
                                args = j_dict.get("args_json") or "{}"
                                if isinstance(args, str):
                                    try:
                                        args = json.loads(args)
                                    except:
                                        args = {}
                                goal = args.get("goal", "synthesis")
                                break
                        
                        mode_str = "云端模型" if use_cloud else "预处理模型"
                        progress_msg = tg.send_message(chat_id, f"📊 共 {len(fetched_papers)} 篇论文待分析\n目标: {goal}\n模式: {mode_str}\n\n📝 进度: 0/{len(fetched_papers)}")
                        progress_msg_id = progress_msg.get("message_id") if progress_msg else None
                        
                        # 创建分析器
                        if use_cloud:
                            # 直接使用云端模型
                            analyzer = PaperAnalyzer(preprocess_llm=None)
                        else:
                            # 使用预处理模型
                            client = PreprocessLLMClient(
                                api_base=PREPROCESS_LLM_STATE.api_base,
                                model=PREPROCESS_LLM_STATE.model,
                                api_key=PREPROCESS_LLM_STATE.api_key
                            )
                            analyzer = PaperAnalyzer(preprocess_llm=client)
                        
                        # 批量分析（使用消息编辑更新进度）
                        last_update = [0]  # 用列表以便在闭包中修改
                        def progress_cb(current, total):
                            # 每5篇或完成时更新
                            if (current % 5 == 0 or current == total) and progress_msg_id:
                                pct = int(100 * current / total)
                                tg.edit_message(chat_id, progress_msg_id, 
                                    f"📊 共 {total} 篇论文待分析\n目标: {goal}\n模式: {mode_str}\n\n📝 进度: {current}/{total} ({pct}%)")
                        
                        results = analyzer.batch_analyze(
                            fetched_papers, 
                            settings.LIBRARY_DIR,
                            goal=goal,
                            use_cloud=use_cloud,
                            progress_callback=progress_cb
                        )
                        
                        # 统计结果
                        success_count = len([r for r in results if r.success])
                        fail_count = len([r for r in results if not r.success])
                        
                        # 保存分析结果
                        results_dir = settings.REPORTS_DIR / job_id
                        results_dir.mkdir(parents=True, exist_ok=True)
                        
                        analysis_data = []
                        for r in results:
                            analysis_data.append({
                                "paper_id": r.paper_id,
                                "doi": r.doi,
                                "success": r.success,
                                "data": r.data,
                                "error": r.error
                            })
                        
                        analysis_file = results_dir / "analysis.json"
                        analysis_file.write_text(
                            json.dumps(analysis_data, ensure_ascii=False, indent=2),
                            encoding="utf-8"
                        )
                        
                        tg.send_message(chat_id, 
                            f"✅ 分析完成!\n\n"
                            f"成功: {success_count}\n"
                            f"失败: {fail_count}\n\n"
                            f"结果已保存到: {analysis_file}\n\n"
                            f"💡 使用 /report {job_id} 生成综合报告"
                        )
                        
                    except Exception as e:
                        logger.error(f"分析失败: {e}", exc_info=True)
                        tg.send_message(chat_id, f"❌ 分析失败: {e}")
                
                threading.Thread(target=run_analysis, daemon=True).start()
                continue
            
            # ========== /report 命令 ==========
            if text.startswith("/report"):
                from core.analyzer import PaperAnalyzer, AnalysisResult
                from core.ai import AIClient
                
                parts = text.split()
                job_id = None
                
                if len(parts) >= 2:
                    job_id = parts[1].strip()
                else:
                    # 查找有分析结果的任务
                    for d in settings.REPORTS_DIR.iterdir() if settings.REPORTS_DIR.exists() else []:
                        if d.is_dir() and (d / "analysis.json").exists():
                            job_id = d.name
                            break
                
                if not job_id:
                    tg.send_message(chat_id, "❌ 没有找到分析结果\n用法: /report [job_id]\n\n请先运行 /analyze 分析论文")
                    continue
                
                analysis_file = settings.REPORTS_DIR / job_id / "analysis.json"
                if not analysis_file.exists():
                    tg.send_message(chat_id, f"❌ 任务 {job_id} 没有分析结果\n\n请先运行 /analyze {job_id}")
                    continue
                
                tg.send_message(chat_id, f"📝 正在生成报告...\n\n使用模型: {MODEL_STATE.openai_model}")
                
                def run_report():
                    try:
                        # 读取分析结果
                        analysis_data = json.loads(analysis_file.read_text(encoding="utf-8"))
                        
                        # 转换为 AnalysisResult
                        results = []
                        for item in analysis_data:
                            results.append(AnalysisResult(
                                success=item.get("success", False),
                                paper_id=item.get("paper_id", 0),
                                doi=item.get("doi", ""),
                                data=item.get("data"),
                                error=item.get("error")
                            ))
                        
                        # 获取任务目标
                        jobs = db.list_jobs(limit=20)
                        goal = "synthesis"
                        for j in jobs:
                            j_dict = dict(j)
                            if j_dict.get("job_id") == job_id:
                                args = j_dict.get("args_json") or "{}"
                                if isinstance(args, str):
                                    try:
                                        args = json.loads(args)
                                    except:
                                        args = {}
                                goal = args.get("goal", "synthesis")
                                break
                        
                        # 生成报告
                        analyzer = PaperAnalyzer()
                        cloud_ai = AIClient(notify_callback=lambda x: logger.info(x))
                        report = analyzer.generate_report(results, goal, cloud_ai)
                        
                        # 保存报告
                        report_file = settings.REPORTS_DIR / job_id / "report.md"
                        report_file.write_text(report, encoding="utf-8")
                        
                        # 发送报告摘要和上传文件
                        if len(report) > 2000:
                            # 发送摘要
                            summary = report[:2000] + "\n\n... [查看完整报告请下载文件]"
                            tg.send_message(chat_id, summary)
                        else:
                            tg.send_message(chat_id, report)
                        
                        # 上传报告文件
                        if tg.send_document(chat_id, report_file, caption=f"📊 分析报告 - {job_id}"):
                            tg.send_message(chat_id, "✅ 报告文件已上传，点击上方下载")
                        else:
                            tg.send_message(chat_id, f"⚠️ 文件上传失败，报告已保存到: {report_file}")
                        
                    except Exception as e:
                        logger.error(f"生成报告失败: {e}", exc_info=True)
                        tg.send_message(chat_id, f"❌ 生成报告失败: {e}")
                
                threading.Thread(target=run_report, daemon=True).start()
                continue
            
            # ========== /search 命令（多源搜索）==========
            if text.startswith("/search"):
                parts = text.split(maxsplit=1)
                if len(parts) < 2:
                    tg.send_message(chat_id, "用法: /search <关键词> [sources=openalex,crossref] [max=50]\n\n可用数据源: openalex, crossref, scholar, wos")
                    continue
                
                # 解析参数
                args_text = parts[1]
                query = ""
                sources = ["openalex", "crossref"]
                max_results = 50
                
                # 提取参数
                import re
                sources_match = re.search(r'sources?=([^\s]+)', args_text)
                if sources_match:
                    sources = sources_match.group(1).split(",")
                    args_text = args_text.replace(sources_match.group(0), "")
                
                max_match = re.search(r'max=(\d+)', args_text)
                if max_match:
                    max_results = int(max_match.group(1))
                    args_text = args_text.replace(max_match.group(0), "")
                
                query = args_text.strip()
                
                if not query:
                    tg.send_message(chat_id, "请提供搜索关键词")
                    continue
                
                tg.send_message(chat_id, f"🔍 开始搜索...\n关键词: {query}\n数据源: {', '.join(sources)}\n最大结果: {max_results}")
                
                def do_search():
                    try:
                        searcher = UnifiedSearcher(notify_callback=lambda x: tg.send_message(chat_id, x))
                        result = searcher.search(query, sources=sources, max_results=max_results)
                        
                        if result["success"]:
                            # 保存结果
                            timestamp = int(time.time())
                            output_path = settings.LIBRARY_DIR / f"search_{timestamp}.txt"
                            searcher.save_as_wos_format(result["papers"], output_path)
                            
                            tg.send_message(chat_id, f"✅ 搜索完成!\n\n📊 找到 {result['count']} 篇论文\n📁 来源: {', '.join(result['sources_used'])}\n💾 已保存: {output_path.name}\n\n使用以下命令开始分析:\n/run {output_path} goal=synthesis")
                            
                            # 保存路径供 autorun 使用
                            db.kv_set(f"last_upload_{chat_id}", str(output_path))
                            
                            # 显示前5篇
                            if result["papers"]:
                                preview = "📄 前5篇论文:\n"
                                for i, p in enumerate(result["papers"][:5], 1):
                                    title = (p.get("title") or "无标题")[:60]
                                    doi = p.get("doi") or "无DOI"
                                    preview += f"{i}. {title}...\n   DOI: {doi}\n"
                                tg.send_message(chat_id, preview)
                        else:
                            errors_str = "\n".join([f"  {k}: {v}" for k, v in result.get("errors", {}).items()])
                            tg.send_message(chat_id, f"❌ 搜索失败\n{errors_str}")
                    except Exception as e:
                        logger.error(f"搜索失败: {e}", exc_info=True)
                        tg.send_message(chat_id, f"❌ 搜索失败: {e}")
                
                threading.Thread(target=do_search, daemon=True).start()
                continue
            
            # ========== /wos 命令 ==========
            if text.startswith("/wos"):
                parts = text.split(maxsplit=1)
                if len(parts) < 2:
                    tg.send_message(chat_id, "用法: /wos <检索式>\n例: /wos TS=(MOF) AND TS=(CO2 capture)")
                    continue
                
                boolean_query = parts[1].strip()
                tg.send_message(chat_id, f"🔍 正在访问 Web of Science...\n检索式: {boolean_query}")
                
                def do_wos_search():
                    try:
                        searcher = UnifiedSearcher(notify_callback=lambda x: tg.send_message(chat_id, x))
                        result = searcher.search(boolean_query, sources=["wos"], max_results=50)
                        
                        if result["success"] and "wos_file" in result:
                            wos_file = result["wos_file"]
                            tg.send_message(chat_id, f"✅ WoS 导出成功: {wos_file.name}\n\n使用以下命令开始分析:\n/run {wos_file} goal=synthesis")
                            db.kv_set(f"last_upload_{chat_id}", str(wos_file))
                        else:
                            tg.send_message(chat_id, f"❌ WoS 搜索失败: {result.get('errors')}")
                    except Exception as e:
                        logger.error(f"WoS Search failed: {e}")
                        tg.send_message(chat_id, f"❌ 错误: {e}")
                
                threading.Thread(target=do_wos_search, daemon=True).start()
                continue



            
            # ========== /scholar 命令 ==========
            if text.startswith("/scholar"):
                parts = text.split(maxsplit=1)
                if len(parts) < 2:
                    tg.send_message(chat_id, "用法: /scholar <搜索词>\n例: /scholar MOF CO2 capture synthesis")
                    continue
                
                query = parts[1].strip()
                tg.send_message(chat_id, f"🔍 正在搜索 Google Scholar...\n关键词: {query}")
                
                def do_scholar_search():
                    try:
                        from core.mcp_search import MCPSearcher
                        mcp = MCPSearcher()
                        result = mcp.search_google_scholar(query, max_results=30)
                        
                        if result["success"]:
                            # 保存结果前的数据处理
                            papers = result.get("papers", [])
                            for p in papers:
                                # 处理作者列表
                                authors = p.get("authors", [])
                                if isinstance(authors, list):
                                    p["authors"] = ", ".join(authors)
                                    
                                # 确保有 year
                                if "year" not in p and "publishedDate" in p:
                                    try:
                                        p["year"] = int(p["publishedDate"][:4])
                                    except:
                                        pass
                            
                            # 保存结果
                            timestamp = int(time.time())
                            output_path = settings.LIBRARY_DIR / f"scholar_{timestamp}.txt"
                            
                            from core.scholar_search import UnifiedSearcher
                            us = UnifiedSearcher()
                            us.save_as_wos_format(papers, output_path)
                            
                            tg.send_message(chat_id, f"✅ Scholar 搜索成功 (MCP)!\n\n📊 找到 {len(papers)} 篇论文\n💾 已保存: {output_path.name}\n\n使用以下命令开始分析:\n/run {output_path} goal=synthesis")
                            db.kv_set(f"last_upload_{chat_id}", str(output_path))
                        else:
                            tg.send_message(chat_id, f"❌ Scholar 搜索失败 (MCP): {result.get('error')}")
                    except Exception as e:
                        logger.error(f"Scholar 搜索失败: {e}", exc_info=True)
                        tg.send_message(chat_id, f"❌ Scholar 搜索失败: {e}")
                
                threading.Thread(target=do_scholar_search, daemon=True).start()
                continue
            
            # ========== /cfcookie 命令 ==========
            if text.startswith("/cfcookie") or text.startswith("/setcookie"):
                parts = text.split(maxsplit=2)
                
                if len(parts) < 2:
                    from core.cf_manager import CF_MANAGER
                    domains = CF_MANAGER.list_domains()
                    
                    help_text = (
                        "📎 CF Cookie 管理\n\n"
                        "用法:\n"
                        "/cfcookie <域名> <cf_clearance值>\n"
                        "/cfcookie list - 查看已保存的域名\n"
                        "/cfcookie clear <域名> - 清除指定域名\n"
                        "/cfcookie clearall - 清除所有\n\n"
                        "示例:\n"
                        "/cfcookie sciencedirect.com abc123...\n"
                        "/cfcookie wiley.com xyz789...\n\n"
                        "常见域名:\n"
                        "• sciencedirect.com (Elsevier)\n"
                        "• onlinelibrary.wiley.com (Wiley)\n"
                        "• pubs.acs.org (ACS)\n"
                        "• pubs.rsc.org (RSC)\n"
                        "• nature.com\n"
                        "• springer.com"
                    )
                    
                    if domains:
                        help_text += "\n\n✅ 已保存的域名:\n" + "\n".join([f"  • {d}" for d in domains])
                    
                    tg.send_message(chat_id, help_text)
                    continue
                
                from core.cf_manager import CF_MANAGER
                
                if parts[1] == "list":
                    domains = CF_MANAGER.list_domains()
                    if domains:
                        msg = "✅ 已保存 CF cookies 的域名:\n" + "\n".join([f"  • {d}" for d in domains])
                    else:
                        msg = "❌ 暂无已保存的 CF cookies"
                    tg.send_message(chat_id, msg)
                    continue
                
                if parts[1] == "clearall":
                    CF_MANAGER.clear_all()
                    tg.send_message(chat_id, "✅ 已清除所有 CF cookies")
                    continue
                
                if parts[1] == "clear" and len(parts) >= 3:
                    domain = parts[2].strip()
                    if CF_MANAGER.clear_domain(domain):
                        tg.send_message(chat_id, f"✅ 已清除 {domain} 的 cookies")
                    else:
                        tg.send_message(chat_id, f"❌ 未找到 {domain} 的 cookies")
                    continue
                
                if len(parts) >= 3:
                    domain = parts[1].strip()
                    cf_value = parts[2].strip()
                    
                    if not domain.startswith("."):
                        domain = "." + domain
                    
                    CF_MANAGER.set_cf_clearance(domain, cf_value)
                    tg.send_message(chat_id, f"✅ 已保存 {domain} 的 cf_clearance\n\n现在可以重新尝试抓取")
                    continue
                
                tg.send_message(chat_id, "❌ 参数错误，使用 /cfcookie 查看帮助")
                continue
            
            # ========== /login 命令 ==========
            if text.startswith("/login"):
                parts = text.split(maxsplit=1)
                url = parts[1].strip() if len(parts) > 1 else "https://www.webofscience.com"
                
                login_msg = (
                    f"🌐 正在打开浏览器...\n\n"
                    f"请完成以下操作:\n"
                    f"1. 完成 Cloudflare 验证（如果出现）\n"
                    f"2. 完成机构登录（如果需要）\n"
                    f"3. 确认可以正常访问后关闭浏览器\n\n"
                    f"目标网址: {url}"
                )
                tg.send_message(chat_id, login_msg)
                
                def do_login():
                    try:
                        from playwright.sync_api import sync_playwright
                        from core.fetcher import create_stealth_browser_context
                        from core.cf_manager import CF_MANAGER
                        
                        with sync_playwright() as p:
                            context = create_stealth_browser_context(
                                p, 
                                settings.PROFILE_DIR, 
                                headless=False
                            )
                            
                            page = context.new_page()
                            page.goto(url, wait_until="domcontentloaded", timeout=60000)
                            
                            tg.send_message(chat_id, "⏳ 等待操作完成...\n完成后请关闭浏览器窗口")
                            
                            try:
                                while True:
                                    time.sleep(5)
                                    try:
                                        _ = page.url
                                    except Exception:
                                        break
                            except Exception:
                                pass
                            
                            try:
                                cookies = context.cookies()
                                count = CF_MANAGER.import_from_browser(cookies)
                                tg.send_message(chat_id, f"✅ 登录会话已保存\n📎 保存了 {count} 个 CF cookies")
                            except Exception as e:
                                tg.send_message(chat_id, f"⚠️ 保存 cookies 时出错: {e}")
                            
                            try:
                                context.close()
                            except Exception:
                                pass
                    except Exception as e:
                        logger.error(f"登录失败: {e}", exc_info=True)
                        tg.send_message(chat_id, f"❌ 登录失败: {e}")
                
                threading.Thread(target=do_login, daemon=True).start()
                continue
            
            # ========== /loginsite 命令（快捷登录常见出版商）==========
            if text.startswith("/loginsite"):
                sites = {
                    "wos": "https://www.webofscience.com",
                    "elsevier": "https://www.sciencedirect.com",
                    "wiley": "https://onlinelibrary.wiley.com",
                    "acs": "https://pubs.acs.org",
                    "rsc": "https://pubs.rsc.org",
                    "nature": "https://www.nature.com",
                    "springer": "https://link.springer.com",
                    "scholar": "https://scholar.google.com",
                }
                
                parts = text.split(maxsplit=1)
                if len(parts) < 2:
                    site_list = "\n".join([f"  • {k}: {v}" for k, v in sites.items()])
                    tg.send_message(chat_id, f"用法: /loginsite <站点名>\n\n可用站点:\n{site_list}")
                    continue
                
                site_name = parts[1].strip().lower()
                if site_name not in sites:
                    tg.send_message(chat_id, f"❌ 未知站点: {site_name}\n使用 /loginsite 查看可用站点")
                    continue
                
                url = sites[site_name]
                tg.send_message(chat_id, f"🌐 正在打开 {site_name}: {url}")
                
                def do_site_login():
                    try:
                        from playwright.sync_api import sync_playwright
                        from core.fetcher import create_stealth_browser_context
                        from core.cf_manager import CF_MANAGER
                        
                        with sync_playwright() as p:
                            context = create_stealth_browser_context(
                                p,
                                settings.PROFILE_DIR,
                                headless=False
                            )
                            
                            page = context.new_page()
                            page.goto(url, wait_until="domcontentloaded", timeout=60000)
                            
                            tg.send_message(chat_id, "⏳ 请在浏览器中完成验证/登录，完成后关闭窗口")
                            
                            try:
                                while True:
                                    time.sleep(5)
                                    try:
                                        _ = page.url
                                    except Exception:
                                        break
                            except Exception:
                                pass
                            
                            try:
                                cookies = context.cookies()
                                count = CF_MANAGER.import_from_browser(cookies)
                                tg.send_message(chat_id, f"✅ {site_name} 登录完成\n📎 保存了 {count} 个 CF cookies")
                            except Exception as e:
                                tg.send_message(chat_id, f"⚠️ 保存 cookies 时出错: {e}")
                            
                            try:
                                context.close()
                            except Exception:
                                pass
                    except Exception as e:
                        tg.send_message(chat_id, f"❌ 登录失败: {e}")
                
                threading.Thread(target=do_site_login, daemon=True).start()
                continue
            
            # ========== /startedge 命令（启动真实 Edge 浏览器）==========
            if text.startswith("/startedge"):
                from core.fetcher import launch_real_edge_with_cdp
                
                tg.send_message(chat_id, "🚀 正在检查 Edge 浏览器状态...")
                
                success, message = launch_real_edge_with_cdp()
                tg.send_message(chat_id, message)
                
                if success:
                    tg.send_message(chat_id, (
                        "现在可以:\n"
                        "1. 在 Edge 中手动访问需要的网站\n"
                        "2. 完成 Cloudflare 验证和登录\n"
                        "3. 之后 bot 会自动使用这个浏览器会话\n\n"
                        "💡 浏览器保持打开状态时，后续抓取会自动继承登录状态"
                    ))
                continue
            
            # ========== /openurl 命令（在真实 Edge 中打开 URL）==========
            if text.startswith("/openurl"):
                parts = text.split(maxsplit=1)
                if len(parts) < 2:
                    tg.send_message(chat_id, "用法: /openurl <url>\n\n在真实 Edge 浏览器中打开 URL（无自动化标识）")
                    continue
                
                url = parts[1].strip()
                from core.fetcher import open_in_real_edge
                
                if open_in_real_edge(url):
                    tg.send_message(chat_id, f"✅ 已在 Edge 中打开: {url}")
                else:
                    tg.send_message(chat_id, "❌ 打开失败，请检查是否安装了 Edge 浏览器")
                continue
            
            # ========== /config 命令 ==========
            if text.startswith("/config"):
                tg.send_message(chat_id, settings.summary())
                continue
            
            # ========== /research 命令 ==========
            if text.startswith("/research"):
                user_query = text[len("/research"):].strip()
                if not user_query:
                    tg.send_message(chat_id, "请提供研究需求\n例: /research MOF材料CO2捕获合成方法")
                    continue
                
                request_id = db.create_research_request(chat_id, user_query)
                tg.send_message(chat_id, f"✅ 研究请求已接收: {request_id}\n当前模型: {MODEL_STATE.openai_model}")
                
                def process_research():
                    try:
                        from core.search import SearchOrchestrator
                        from utils.db import DB as WorkerDB
                        
                        worker_db = WorkerDB()
                        orchestrator = SearchOrchestrator(worker_db)
                        orchestrator.process_request(request_id)
                    except Exception as e:
                        logger.error(f"研究请求处理失败: {e}", exc_info=True)
                        tg.send_message(chat_id, f"❌ 处理失败: {e}")
                
                threading.Thread(target=process_research, daemon=True).start()
                continue
            
            # ========== /autorun 命令 ==========
            if text.startswith("/autorun"):
                from core.fetcher import is_real_browser_running, launch_real_edge_with_cdp
                
                last_file = db.kv_get(f"last_upload_{chat_id}")
                
                if not last_file:
                    tg.send_message(chat_id, "❌ 没有最近上传/搜索的文件\n请先上传文件或使用 /search 搜索")
                    continue
                
                file_path = Path(last_file)
                if not file_path.exists():
                    tg.send_message(chat_id, f"❌ 文件不存在: {file_path}")
                    continue
                
                # 检查 Edge 状态
                if settings.USE_REAL_BROWSER and not is_real_browser_running():
                    # 保存待执行的任务参数
                    db.kv_set(f"pending_autorun_{chat_id}", text)
                    
                    tg.send_message(chat_id, (
                        "⚠️ 真实 Edge 浏览器未启动\n\n"
                        "为避免 Cloudflare 拦截，建议使用真实浏览器模式：\n\n"
                        "【步骤】\n"
                        "1. 关闭所有 Edge 窗口\n"
                        "2. 在 PowerShell 中运行：\n"
                        "   taskkill /F /IM msedge.exe\n"
                        "3. 发送 /confirmedge 自动启动带调试端口的 Edge\n"
                        "4. 在 Edge 中访问出版商网站完成登录\n"
                        "5. 发送 /confirmrun 继续任务\n\n"
                        "【或者】\n"
                        "发送 /skipedge 跳过此检查，使用 Playwright 模式（可能被 CF 拦截）"
                    ))
                    continue
                
                # 解析参数
                goal = "synthesis"
                max_papers = 50
                force_new = False  # 是否强制创建新任务
                
                parts = text.split()
                for part in parts[1:]:
                    if "=" in part:
                        k, v = part.split("=", 1)
                        if k == "goal":
                            goal = v
                        elif k == "max":
                            try:
                                max_papers = int(v)
                            except ValueError:
                                pass
                    elif part == "new":
                        force_new = True
                
                # 检查是否已有同一文件的未完成任务
                existing_job_id = None
                if not force_new:
                    recent_jobs = db.list_jobs(limit=20)
                    for job in recent_jobs:
                        job_dict = dict(job)  # 转换 sqlite3.Row 为字典
                        if job_dict.get("status") in ("running", "pending", "done"):
                            job_args = job_dict.get("args") or {}
                            if isinstance(job_args, str):
                                try:
                                    job_args = json.loads(job_args)
                                except:
                                    job_args = {}
                            job_file = job_args.get("wos_file", "")
                            if job_file == str(file_path):
                                # 检查是否还有未完成的论文
                                papers = db.list_papers(job_dict["job_id"])
                                pending = [p for p in papers if dict(p).get("status") not in ("fetched",)]
                                if pending:
                                    existing_job_id = job_dict["job_id"]
                                    break
                
                if existing_job_id:
                    job_id = existing_job_id
                    papers = db.list_papers(job_id)
                    done_count = len([p for p in papers if dict(p).get("status") == "fetched"])
                    pending_count = len([p for p in papers if dict(p).get("status") not in ("fetched",)])
                    tg.send_message(chat_id, 
                        f"📎 恢复上次任务: {job_id}\n"
                        f"✅ 已完成: {done_count}\n"
                        f"⏳ 待抓取: {pending_count}\n\n"
                        f"💡 发送 /autorun new 可强制创建新任务"
                    )
                else:
                    job_id = db.create_job(goal=goal, args={
                        "wos_file": str(file_path),
                        "max_papers": max_papers,
                        "goal": goal
                    })
                    tg.send_message(chat_id, f"📚 新任务已创建: {job_id}\n文件: {file_path.name}\n目标: {goal}\n最大数量: {max_papers}")
                
                def run_auto_task():
                    try:
                        from core.fetcher import run_fetch_job
                        from utils.db import DB as WorkerDB
                        from utils.notifier import Notifier as WorkerNotifier
                        from core.bot import TelegramClient as WorkerTG
                        
                        worker_db = WorkerDB()
                        worker_tg = WorkerTG()
                        worker_notifier = WorkerNotifier(worker_tg, chat_id)
                        
                        run_fetch_job(
                            db=worker_db,
                            notifier=worker_notifier,
                            job_id=job_id,
                            wos_file=file_path,
                            goal=goal,
                            max_papers=max_papers
                        )
                    except Exception as e:
                        logger.error(f"自动任务失败: {e}", exc_info=True)
                        tg.send_message(chat_id, f"❌ 任务失败: {e}")
                
                threading.Thread(target=run_auto_task, daemon=True).start()
                continue
            
            # ========== /confirmedge 命令（确认关闭 Edge 后启动）==========
            if text.startswith("/confirmedge"):
                from core.fetcher import launch_real_edge_with_cdp
                
                tg.send_message(chat_id, "🚀 正在启动带调试端口的 Edge...")
                
                success, message = launch_real_edge_with_cdp()
                tg.send_message(chat_id, message)
                
                if success:
                    tg.send_message(chat_id, (
                        "✅ Edge 已启动\n\n"
                        "现在请在 Edge 中:\n"
                        "1. 访问 sciencedirect.com / wiley.com 等网站\n"
                        "2. 完成 Cloudflare 验证和登录\n\n"
                        "完成后发送 /confirmrun 继续任务"
                    ))
                continue
            
            # ========== /confirmrun 命令（确认 Edge 准备好后继续任务）==========
            if text.startswith("/confirmrun"):
                from core.fetcher import is_real_browser_running
                
                if not is_real_browser_running():
                    tg.send_message(chat_id, "❌ Edge 浏览器未运行\n请先发送 /confirmedge 启动浏览器")
                    continue
                
                # 获取保存的待执行任务
                pending = db.kv_get(f"pending_autorun_{chat_id}")
                if not pending:
                    tg.send_message(chat_id, "❌ 没有待执行的任务\n请重新发送 /autorun")
                    continue
                
                # 清除待执行任务
                db.kv_set(f"pending_autorun_{chat_id}", None)
                
                # 重新发送 autorun 命令处理
                tg.send_message(chat_id, "✅ Edge 准备就绪，正在启动任务...")
                
                # 模拟重新处理 autorun
                last_file = db.kv_get(f"last_upload_{chat_id}")
                file_path = Path(last_file)
                
                goal = "synthesis"
                max_papers = 50
                
                parts = pending.split()
                for part in parts[1:]:
                    if "=" in part:
                        k, v = part.split("=", 1)
                        if k == "goal":
                            goal = v
                        elif k == "max":
                            try:
                                max_papers = int(v)
                            except ValueError:
                                pass
                
                job_id = db.create_job(goal=goal, args={
                    "wos_file": str(file_path),
                    "max_papers": max_papers,
                    "goal": goal
                })
                
                tg.send_message(chat_id, f"📚 任务已创建: {job_id}\n文件: {file_path.name}")
                
                def run_confirmed_task():
                    try:
                        from core.fetcher import run_fetch_job
                        from utils.db import DB as WorkerDB
                        from utils.notifier import Notifier as WorkerNotifier
                        from core.bot import TelegramClient as WorkerTG
                        
                        worker_db = WorkerDB()
                        worker_tg = WorkerTG()
                        worker_notifier = WorkerNotifier(worker_tg, chat_id)
                        
                        run_fetch_job(
                            db=worker_db,
                            notifier=worker_notifier,
                            job_id=job_id,
                            wos_file=file_path,
                            goal=goal,
                            max_papers=max_papers
                        )
                    except Exception as e:
                        logger.error(f"任务失败: {e}", exc_info=True)
                        tg.send_message(chat_id, f"❌ 任务失败: {e}")
                
                threading.Thread(target=run_confirmed_task, daemon=True).start()
                continue
            
            # ========== /skipedge 命令（跳过 Edge 检查）==========
            if text.startswith("/skipedge"):
                pending = db.kv_get(f"pending_autorun_{chat_id}")
                if not pending:
                    tg.send_message(chat_id, "❌ 没有待执行的任务")
                    continue
                
                db.kv_set(f"pending_autorun_{chat_id}", None)
                
                tg.send_message(chat_id, "⚠️ 跳过 Edge 检查，使用 Playwright 模式\n可能会被 Cloudflare 拦截")
                
                # 临时禁用真实浏览器
                original_setting = settings.USE_REAL_BROWSER
                settings.USE_REAL_BROWSER = False
                
                last_file = db.kv_get(f"last_upload_{chat_id}")
                file_path = Path(last_file)
                
                goal = "synthesis"
                max_papers = 50
                
                parts = pending.split()
                for part in parts[1:]:
                    if "=" in part:
                        k, v = part.split("=", 1)
                        if k == "goal":
                            goal = v
                        elif k == "max":
                            try:
                                max_papers = int(v)
                            except ValueError:
                                pass
                
                job_id = db.create_job(goal=goal, args={
                    "wos_file": str(file_path),
                    "max_papers": max_papers,
                    "goal": goal
                })
                
                tg.send_message(chat_id, f"📚 任务已创建: {job_id}")
                
                def run_skipped_task():
                    try:
                        from core.fetcher import run_fetch_job
                        from utils.db import DB as WorkerDB
                        from utils.notifier import Notifier as WorkerNotifier
                        from core.bot import TelegramClient as WorkerTG
                        
                        worker_db = WorkerDB()
                        worker_tg = WorkerTG()
                        worker_notifier = WorkerNotifier(worker_tg, chat_id)
                        
                        run_fetch_job(
                            db=worker_db,
                            notifier=worker_notifier,
                            job_id=job_id,
                            wos_file=file_path,
                            goal=goal,
                            max_papers=max_papers
                        )
                    except Exception as e:
                        logger.error(f"任务失败: {e}", exc_info=True)
                        tg.send_message(chat_id, f"❌ 任务失败: {e}")
                    finally:
                        settings.USE_REAL_BROWSER = original_setting
                
                threading.Thread(target=run_skipped_task, daemon=True).start()
                continue
            
            # ========== /status 命令 ==========
            if text.startswith("/status"):
                rows = db.list_jobs(limit=5)
                if not rows:
                    tg.send_message(chat_id, "📋 暂无任务记录")
                else:
                    lines = ["📋 最近任务:"]
                    for r in rows:
                        status_icon = {"completed": "✅", "running": "🔄", "failed": "❌", "queued": "⏳"}.get(r["status"], "❓")
                        lines.append(f"{status_icon} {r['job_id']} | {r['status']} | {r['goal']}")
                    tg.send_message(chat_id, "\n".join(lines))
                continue
            
            # ========== /progress 命令 ==========
            if text.startswith("/progress"):
                import json as json_mod
                
                parts = text.split()
                job_id = None
                
                # 如果指定了 job_id
                if len(parts) >= 2:
                    job_id = parts[1].strip()
                else:
                    # 获取最近的运行中任务
                    rows = db.list_jobs(limit=5)
                    for r in rows:
                        if r["status"] == "running":
                            job_id = r["job_id"]
                            break
                
                if not job_id:
                    tg.send_message(chat_id, "❌ 没有正在运行的任务\n用法: /progress [job_id]")
                    continue
                
                # 从 kv 获取进度
                progress_json = db.kv_get(f"job_progress_{job_id}")
                if progress_json:
                    try:
                        prog = json_mod.loads(progress_json)
                        total = prog.get("total", 0)
                        completed = prog.get("completed", 0)
                        success = prog.get("success", 0)
                        failed = prog.get("failed", 0)
                        pct = int(100 * completed / total) if total > 0 else 0
                        
                        msg = (
                            f"📊 任务进度: {job_id}\n\n"
                            f"进度: {completed}/{total} ({pct}%)\n"
                            f"✅ 成功: {success}\n"
                            f"❌ 失败: {failed}\n"
                            f"⏳ 剩余: {total - completed}"
                        )
                        tg.send_message(chat_id, msg)
                    except Exception as e:
                        tg.send_message(chat_id, f"❌ 解析进度失败: {e}")
                else:
                    tg.send_message(chat_id, f"❌ 找不到任务 {job_id} 的进度\n可能任务尚未开始或已完成")
                continue
            
            # ========== /cancel 命令 ==========
            if text.startswith("/cancel"):
                parts = text.split()
                if len(parts) < 2:
                    tg.send_message(chat_id, "用法: /cancel <job_id>")
                    continue
                target = parts[1].strip()
                db.request_cancel(target)
                tg.send_message(chat_id, f"✅ 已请求取消: {target}")
                continue
            
            # ========== /stop 命令（终止当前任务）==========
            if text.startswith("/stop"):
                # 查找正在运行的任务
                rows = db.list_jobs(limit=10)
                running_jobs = [r for r in rows if r["status"] == "running"]
                
                if not running_jobs:
                    tg.send_message(chat_id, "❌ 没有正在运行的任务")
                    continue
                
                # 取消所有运行中的任务
                cancelled = []
                for job in running_jobs:
                    db.request_cancel(job["job_id"])
                    cancelled.append(job["job_id"])
                
                tg.send_message(chat_id, f"⏹️ 已请求终止 {len(cancelled)} 个任务:\n" + "\n".join(cancelled))
                continue
            
            # ========== /failed 命令 ==========
            if text.startswith("/failed"):
                parts = text.split()
                job_id = None
                
                # 如果指定了 job_id
                if len(parts) >= 2:
                    job_id = parts[1].strip()
                else:
                    # 获取最近的任务
                    rows = db.list_jobs(limit=5)
                    for r in rows:
                        if r["status"] in ("running", "done"):
                            job_id = r["job_id"]
                            break
                
                if not job_id:
                    tg.send_message(chat_id, "❌ 没有找到任务\n用法: /failed [job_id]")
                    continue
                
                # 查询失败的论文
                try:
                    papers = db.list_papers(job_id)
                    failed_papers = [dict(p) for p in papers if dict(p).get("status") in ("fetch_failed", "cf_blocked", "error")]
                    
                    if not failed_papers:
                        tg.send_message(chat_id, f"✅ 任务 {job_id} 没有失败的论文")
                        continue
                    
                    # 构建失败列表
                    lines = [f"❌ 失败论文列表 ({len(failed_papers)}篇):"]
                    for i, p in enumerate(failed_papers[:20], 1):  # 最多显示20篇
                        doi = p.get("doi") or "未知"
                        error = (p.get("fetch_error") or "未知错误")[:50]
                        status = p.get("status") or ""
                        lines.append(f"{i}. {doi}\n   [{status}] {error}")
                    
                    if len(failed_papers) > 20:
                        lines.append(f"\n... 还有 {len(failed_papers) - 20} 篇")
                    
                    tg.send_message(chat_id, "\n".join(lines))
                except Exception as e:
                    tg.send_message(chat_id, f"❌ 查询失败: {e}")
                continue
            
            # ========== /run 命令 ==========
            if text.startswith("/run"):
                parts = text.split()
                if len(parts) < 2:
                    tg.send_message(chat_id, "用法: /run <文件路径> [goal=synthesis|performance] [max=50]")
                    continue
                
                wos_file = Path(parts[1])
                goal = "synthesis"
                max_papers = 50
                
                for part in parts[2:]:
                    if "=" in part:
                        k, v = part.split("=", 1)
                        if k == "goal":
                            goal = v
                        elif k == "max":
                            try:
                                max_papers = int(v)
                            except ValueError:
                                pass
                
                if not wos_file.exists():
                    tg.send_message(chat_id, f"❌ 文件不存在: {wos_file}")
                    continue
                
                job_id = db.create_job(goal=goal, args={
                    "wos_file": str(wos_file),
                    "max_papers": max_papers,
                    "goal": goal
                })
                
                tg.send_message(chat_id, f"📚 任务已创建: {job_id}\n正在启动抓取...")
                
                def run_fetch_task():
                    try:
                        from core.fetcher import run_fetch_job
                        from utils.db import DB as WorkerDB
                        from utils.notifier import Notifier as WorkerNotifier
                        from core.bot import TelegramClient as WorkerTG
                        
                        worker_db = WorkerDB()
                        worker_tg = WorkerTG()
                        worker_notifier = WorkerNotifier(worker_tg, chat_id)
                        
                        run_fetch_job(
                            db=worker_db,
                            notifier=worker_notifier,
                            job_id=job_id,
                            wos_file=wos_file,
                            goal=goal,
                            max_papers=max_papers
                        )
                    except Exception as e:
                        logger.error(f"任务失败: {e}", exc_info=True)
                        tg.send_message(chat_id, f"❌ 任务失败: {e}")
                
                threading.Thread(target=run_fetch_task, daemon=True).start()
                continue
        
        time.sleep(0.2)


@app.command("search")
def cli_search(
    query: str,
    sources: str = typer.Option("openalex,crossref", help="数据源，逗号分隔"),
    max_results: int = typer.Option(50, help="最大结果数")
):
    """命令行搜索"""
    from core.scholar_search import UnifiedSearcher
    
    typer.echo(f"搜索: {query}")
    typer.echo(f"数据源: {sources}")
    
    searcher = UnifiedSearcher(notify_callback=lambda x: typer.echo(x))
    result = searcher.search(query, sources=sources.split(","), max_results=max_results)
    
    if result["success"]:
        typer.echo(f"\n找到 {result['count']} 篇论文")
        for i, p in enumerate(result["papers"][:10], 1):
            typer.echo(f"{i}. {p.get('title', '无标题')[:60]}")
            typer.echo(f"   DOI: {p.get('doi', '无')}")
    else:
        typer.echo(f"搜索失败: {result.get('errors')}")


@app.command("models")
def list_models(show_all: bool = typer.Option(False, "--all", help="显示全部模型")):
    """列出可用的 AI 模型"""
    from core.ai import AIClient
    
    typer.echo("正在获取模型列表...")
    ai = AIClient(notify_callback=lambda x: typer.echo(x))
    result = ai.list_models(show_all=show_all)
    typer.echo(result)


@app.command("test-ai")
def test_ai(
    prompt: str = typer.Option("你好，请用一句话介绍自己", help="测试 prompt"),
    model: str = typer.Option(None, help="指定模型")
):
    """测试 AI 连接"""
    from core.ai import AIClient, MODEL_STATE
    
    ai = AIClient(notify_callback=lambda x: typer.echo(x))
    
    if model:
        MODEL_STATE.set_openai_model(model)
        typer.echo(f"使用模型: {model}")
    else:
        typer.echo(f"使用模型: {MODEL_STATE.openai_model}")
    
    typer.echo(f"Prompt: {prompt}")
    typer.echo("正在调用 AI...")
    
    result = ai.call(prompt, json_mode=False)
    
    if result.success:
        typer.echo(f"\n✅ 调用成功!")
        typer.echo(f"Provider: {result.provider}")
        typer.echo(f"Model: {result.model}")
        typer.echo(f"Response:\n{result.data.get('text', result.data)}")
    else:
        typer.echo(f"\n❌ 调用失败: {result.error}")


@app.command("status")
def show_status(limit: int = 5):
    """显示最近任务状态"""
    from utils.db import DB
    
    db = DB()
    rows = db.list_jobs(limit=limit)
    
    if not rows:
        typer.echo("暂无任务记录")
        return
    
    typer.echo("最近任务:")
    for r in rows:
        typer.echo(f"  {r['job_id']}  {r['status']:9s}  goal={r['goal']:<11s}  msg={r['message'] or ''}")


@app.command("init")
def init_config():
    """初始化配置文件"""
    env_template = """# Telegram Bot 配置
CHEMDEEP_TELEGRAM_TOKEN=your_bot_token_here
CHEMDEEP_TELEGRAM_PROXY=socks5h://127.0.0.1:7890
CHEMDEEP_TELEGRAM_CHAT_ID=your_chat_id
CHEMDEEP_TELEGRAM_ALLOWED_CHAT_IDS=your_chat_id

# AI Provider 配置 (openai | gemini | auto)
CHEMDEEP_AI_PROVIDER=openai

# OpenAI 兼容 API
CHEMDEEP_OPENAI_API_KEY=sk-xxx
CHEMDEEP_OPENAI_API_BASE=https://api.openai.com/v1
CHEMDEEP_OPENAI_MODEL=gpt-4-turbo-preview

# Google Gemini
CHEMDEEP_GEMINI_API_KEY=
CHEMDEEP_GEMINI_MODEL=gemini-1.5-pro

# AI 请求行为
CHEMDEEP_AI_TIMEOUT=60
CHEMDEEP_AI_MAX_RETRIES=3

# 路径配置
CHEMDEEP_PROFILE_DIR=profiles/msedge
CHEMDEEP_LIBRARY_DIR=data/library
CHEMDEEP_REPORTS_DIR=data/reports

# 浏览器行为配置
CHEMDEEP_RATE_SECONDS=75
CHEMDEEP_HEADLESS=0
CHEMDEEP_BROWSER_CHANNEL=msedge

# Google Scholar
CHEMDEEP_ENABLE_GOOGLE_SCHOLAR=1
CHEMDEEP_GOOGLE_SCHOLAR_DELAY=5
"""
    env_path = Path("config/.env")
    if env_path.exists():
        typer.echo(f"配置文件已存在: {env_path}")
        overwrite = typer.confirm("是否覆盖?")
        if not overwrite:
            return
    env_path.parent.mkdir(parents=True, exist_ok=True)
    env_path.write_text(env_template, encoding="utf-8")
    typer.echo(f"✅ 已创建配置文件: {env_path}")
    typer.echo("请编辑配置文件填入你的 API 密钥和 Telegram 信息")


@app.command("config")
def show_config():
    """显示当前配置"""
    from config.settings import settings
    typer.echo(settings.summary())


@app.command("login")
def login_browser(url: str = typer.Option("https://www.webofscience.com", help="登录网址")):
    """打开浏览器登录 WoS/Scholar"""
    from core.wos_search import WoSSearcher
    typer.echo(f"正在打开浏览器: {url}")
    typer.echo("请在浏览器中完成登录，完成后关闭窗口")
    searcher = WoSSearcher(notify_callback=lambda x: typer.echo(x))
    searcher.login_interactive()


@app.command("setmodel")
def cli_setmodel(model: str):
    """设置 AI 模型"""
    from core.ai import MODEL_STATE
    old = MODEL_STATE.openai_model
    MODEL_STATE.set_openai_model(model)
    typer.echo(f"模型已切换: {old} -> {model}")


@app.command("currentmodel")
def cli_currentmodel():
    """显示当前模型"""
    from core.ai import MODEL_STATE
    from config.settings import settings
    typer.echo(f"OpenAI 模型: {MODEL_STATE.openai_model}")
    typer.echo(f"Gemini 模型: {MODEL_STATE.gemini_model}")
    typer.echo(f"API Base: {settings.OPENAI_API_BASE}")
    typer.echo(f"Provider: {settings.AI_PROVIDER}")


if __name__ == "__main__":
    app()