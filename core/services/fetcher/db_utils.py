"""
Database utilities for fetcher
"""
from typing import Any
from utils.db import DB
from utils.notifier import Notifier

def prepare_papers_for_fetching(db: DB, job_id: str, notifier: Notifier) -> tuple[list[dict], int, int]:
    """
    检查数据库，去重，返回待抓取论文列表
    
    Returns:
        (pending_papers, skipped_local, skipped_global)
    """
    papers = db.list_papers(job_id)
    
    # 获取全局已成功抓取的 DOI 集合（跨所有任务）
    globally_fetched_dois = db.get_fetched_dois()
    
    pending_papers = []
    skipped_local = 0
    skipped_global = 0
    
    for p in papers:
        p_dict = dict(p)
        doi = (p_dict.get("doi") or "").strip().lower()
        status = p_dict.get("status", "")
        
        if status == "fetched":
            # 当前任务中已标记为完成
            skipped_local += 1
        elif doi and doi in globally_fetched_dois:
            # 其他任务中已成功抓取，复制路径信息并更新状态
            _copy_global_paper_status(db, p_dict, doi)
            skipped_global += 1
        else:
            pending_papers.append(p)
            
    return pending_papers, skipped_local, skipped_global


def _copy_global_paper_status(db: DB, p_dict: dict, doi: str) -> None:
    """从已抓取的全局记录复制状态"""
    original_paper = db.get_paper_by_doi(doi)
    if original_paper:
        orig_dict = dict(original_paper)
        db.update_paper_fetch(
            p_dict["id"], 
            status="fetched",
            landing_url=orig_dict.get("landing_url"),
            raw_html_path=orig_dict.get("raw_html_path"),
            clean_md_path=orig_dict.get("clean_md_path"),
            si_json=orig_dict.get("si_json"),
            fetch_error="已在其他任务中抓取"
        )
    else:
        db.update_paper_fetch(p_dict["id"], status="fetched", fetch_error="已在其他任务中抓取")
