"""
抓取命令处理器

处理: /run, /autorun
"""
import threading
import logging
from pathlib import Path

logger = logging.getLogger('main')


def handle_run(chat_id: int, text: str, tg, db) -> None:
    """处理 /run 命令"""
    parts = text.split()
    if len(parts) < 2:
        tg.send_message(chat_id, "用法: /run <文件路径> [goal=synthesis|performance] [max=50]")
        return
    
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
        return
    
    job_id = db.create_job(goal=goal, args={
        "wos_file": str(wos_file),
        "max_papers": max_papers,
        "goal": goal
    })
    
    tg.send_message(chat_id, f"📚 任务已创建: {job_id}\n正在启动抓取...")
    
    _start_fetch_task(chat_id, job_id, wos_file, goal, max_papers, tg)


def handle_run_callback(chat_id: int, papers_file: Path, tg, db) -> None:
    """处理按钮点击的 run 回调"""
    if not papers_file.exists():
        tg.send_message(chat_id, f"❌ 文件不存在: {papers_file}")
        return
    
    goal = "synthesis"
    max_papers = 50
    
    job_id = db.create_job(goal=goal, args={
        "wos_file": str(papers_file),
        "max_papers": max_papers,
        "goal": goal
    })
    
    tg.send_message(chat_id, f"📚 任务已创建: {job_id}\n正在启动抓取...")
    
    _start_fetch_task(chat_id, job_id, papers_file, goal, max_papers, tg)


def _start_fetch_task(chat_id: int, job_id: str, wos_file: Path, 
                      goal: str, max_papers: int, tg) -> None:
    """启动抓取任务线程"""
    def run_fetch_task():
        try:
            from core.services.fetcher import run_fetch_job
            from utils.db import DB as WorkerDB
            from utils.notifier import Notifier as WorkerNotifier
            from apps.telegram_bot.client import TelegramClient as WorkerTG
            
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


def handle_autorun(chat_id: int, tg, db) -> None:
    """处理 /autorun 命令"""
    # 获取最近上传的文件
    last_upload = db.kv_get(f"last_upload_{chat_id}")
    if not last_upload:
        tg.send_message(chat_id, 
            "❌ 没有找到最近上传的文件\n\n"
            "请先上传一个 .txt, .csv 或 .ris 文件"
        )
        return
    
    wos_file = Path(last_upload)
    if not wos_file.exists():
        tg.send_message(chat_id, f"❌ 文件不存在: {wos_file}")
        return
    
    goal = "synthesis"
    max_papers = 50
    
    job_id = db.create_job(goal=goal, args={
        "wos_file": str(wos_file),
        "max_papers": max_papers,
        "goal": goal
    })
    
    tg.send_message(chat_id, 
        f"📚 自动任务已创建: {job_id}\n"
        f"📁 文件: {wos_file.name}\n"
        f"🎯 目标: {goal}\n"
        f"📊 最大数量: {max_papers}\n\n"
        f"正在启动..."
    )
    
    _start_fetch_task(chat_id, job_id, wos_file, goal, max_papers, tg)
