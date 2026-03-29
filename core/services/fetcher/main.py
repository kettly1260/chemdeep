"""
Main entry point for fetcher service
"""
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any
from pathlib import Path

from utils.db import DB
from utils.notifier import Notifier
from config.settings import settings
from playwright.sync_api import sync_playwright

from core.browser.edge_launcher import is_real_browser_running
from core.browser.context import create_stealth_browser_context

from .csv_utils import parse_wos_file
from .db_utils import prepare_papers_for_fetching
from .batch_fetch import run_batch_fetch

logger = logging.getLogger('fetcher')


def run_fetch_job(
    db: DB,
    notifier: Notifier,
    job_id: str,
    wos_file: Path,
    goal: str,
    max_papers: int,
) -> None:
    """运行完整的抓取任务"""
    
    # 1. 导入
    if not _import_papers(db, notifier, job_id, wos_file, max_papers):
        return

    # 2. 准备抓取
    pending_papers, already_done, skipped_global = prepare_papers_for_fetching(db, job_id, notifier)
    
    total = len(db.list_papers(job_id))
    pending_count = len(pending_papers)
    
    notifier.send(f"📎 待抓取: {pending_count} 篇 (去重: {skipped_global}, 已完成: {already_done})")
    
    if pending_count == 0:
        _finish_job(db, job_id, notifier, "success", "No papers to fetch")
        return

    # 3. 执行抓取
    progress = {"completed": 0, "success": 0, "failed": 0}
    
    try:
        with sync_playwright() as p:
            profile_dir = settings.PROFILE_DIR
            headless = settings.HEADLESS
            
            context = create_stealth_browser_context(p, profile_dir, headless)
            
            run_batch_fetch(
                context=context,
                pending_papers=pending_papers,
                job_id=job_id,
                db=db,
                notifier=notifier,
                progress=progress,
                total=total,
                already_done=already_done,
                library_dir=settings.LIBRARY_DIR,
                goal=goal,
                headless=headless
            )
            
        _finish_job(db, job_id, notifier, "completed", "Job done")
        
    except Exception as e:
        logger.error(f"Fetch job failed: {e}", exc_info=True)
        _finish_job(db, job_id, notifier, "failed", str(e))


def _import_papers(db: DB, notifier: Notifier, job_id: str, wos_file: Path, max: int) -> bool:
    db.update_job_status(job_id, "running", "importing")
    notifier.send(f"📥 导入: {wos_file.name}")
    
    try:
        papers = parse_wos_file(wos_file)
        if max > 0:
            papers = papers[:max]
            
        if not papers:
            raise ValueError("No papers found in file")
            
        db._conn.executemany(
            """INSERT INTO papers(job_id, ut, doi, title, year, source, status)
               VALUES(?, ?, ?, ?, ?, ?, 'imported')""",
            [(job_id, p.get("ut"), p.get("doi"), p.get("title"), p.get("year"), p.get("source")) for p in papers]
        )
        db._conn.commit()
        return True
    except Exception as e:
        _finish_job(db, job_id, notifier, "failed", str(e))
        return False


def _finish_job(db: DB, job_id: str, notifier: Notifier, status: str, msg: str):
    db.update_job_status(job_id, status, msg)
    conn_msg = "🎉 完成" if status == "completed" else f"❌ 结束: {status}"
    notifier.send(f"{conn_msg}: {job_id}")
