"""
Core logic for fetching a single paper
"""
import time
import json
import logging
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

from utils.db import DB
from utils.notifier import Notifier

from .parsers import (
    safe_slug, html_to_markdown, contains_synthesis_steps, 
    find_si_urls_from_html, absolutize_url
)
from core.browser.cf_handler import is_cloudflare_challenge, handle_cloudflare, clear_invalid_cookies_for_domain

# Define domain semaphore getter type for static analysis/hints
# (In runtime we will pass the actual function or object)

logger = logging.getLogger('fetcher')


def fetch_single_paper(
    row: dict, 
    context, 
    library_dir: Path, 
    goal: str, 
    db: DB, 
    notifier: Notifier, 
    headless: bool, 
    cf_lock, 
    cf_domains_warned: set,
    fetch_rate_seconds: int = 2
) -> dict:
    """抓取单篇论文"""
    paper_row_id = int(row["id"])
    doi = (row["doi"] or "").strip()
    title = (row["title"] or "").strip()
    ut = (row["ut"] or "").strip()
    
    result = {"paper_id": paper_row_id, "doi": doi, "status": "unknown", "error": None}
    
    # 1. 验证 DOI
    if not doi:
        _record_skip(db, paper_row_id, "missing DOI")
        result["status"] = "skipped"
        return result
    
    # 2. 准备目录
    paper_dir = library_dir / f"{paper_row_id:06d}_{safe_slug(ut or doi or title or str(paper_row_id))}"
    paper_dir.mkdir(parents=True, exist_ok=True)
    
    url = f"https://doi.org/{doi}"
    
    page = None
    try:
        page = context.new_page()
        
        # 3. 导航到论文页面
        _navigate_to_paper(page, url, fetch_rate_seconds)
        
        # 4. 处理 Cloudflare
        landing_url, html = _handle_potential_cf(
            page, notifier, headless, cf_lock, cf_domains_warned
        )
        if not html:
            _record_failure(db, paper_row_id, "cf_blocked", f"CF Blocked: {landing_url}")
            result["status"] = "cf_blocked"
            result["error"] = "Cloudflare Blocked"
            return result
            
        # 5. 保存并分析内容
        raw_html_path, clean_md_path = _save_content(paper_dir, html)
        clean_md = clean_md_path.read_text(encoding="utf-8")
        
        # 6. 处理 SI (如需要)
        synthesis_missing, si_records = _process_si(
            goal, clean_md, html, landing_url, context, paper_dir
        )
        
        # 7. 更新数据库
        db.update_paper_fetch(
            paper_row_id,
            status="fetched",
            landing_url=landing_url,
            raw_html_path=str(raw_html_path),
            clean_md_path=str(clean_md_path),
            synthesis_missing=synthesis_missing,
            si_json=json.dumps(si_records, ensure_ascii=False) if si_records else None,
            fetch_error=None,
        )
        result["status"] = "success"
        
    except Exception as e:
        error_msg = str(e)[:200]
        _record_failure(db, paper_row_id, "fetch_failed", error_msg)
        result["status"] = "failed"
        result["error"] = error_msg
        logger.error(f"抓取失败 {doi}: {error_msg}")
    finally:
        if page:
            try:
                page.close()
            except Exception:
                pass
            
    return result


def _record_skip(db: DB, pid: int, reason: str):
    db.update_paper_fetch(pid, status="skipped_no_doi", fetch_error=reason)


def _record_failure(db: DB, pid: int, status: str, error: str):
    db.update_paper_fetch(pid, status=status, fetch_error=error)


def _navigate_to_paper(page, url: str, rate_seconds: int):
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        try:
            page.wait_for_load_state("networkidle", timeout=20000)
        except Exception:
            pass
        time.sleep(rate_seconds)
    except Exception as e:
        raise e


def _handle_potential_cf(page, notifier, headless, cf_lock, cf_domains_warned) -> tuple[str, str | None]:
    """检查并处理 CF，返回 (landing_url, html)，失败返回 (url, None)"""
    landing_url = page.url
    html = page.content()
    
    if is_cloudflare_challenge(landing_url, html):
        from urllib.parse import urlparse
        cf_domain = urlparse(landing_url).netloc
        
        with cf_lock:
            if cf_domain not in cf_domains_warned:
                cf_domains_warned.add(cf_domain)
                notifier.send(f"⚠️ {cf_domain} 需要 CF 验证")
        
        if handle_cloudflare(page, notifier, headless, timeout=120):
            return page.url, page.content()
        else:
            return landing_url, None
            
    return landing_url, html


def _save_content(paper_dir: Path, html: str) -> tuple[Path, Path]:
    raw_html_path = paper_dir / "raw.html"
    raw_html_path.write_text(html, encoding="utf-8", errors="ignore")
    
    clean_md = html_to_markdown(html)
    clean_md_path = paper_dir / "clean.md"
    clean_md_path.write_text(clean_md or "", encoding="utf-8")
    
    return raw_html_path, clean_md_path


def _process_si(goal: str, clean_md: str, html: str, landing_url: str, context, paper_dir: Path):
    synthesis_missing = None
    si_records = []
    
    if goal == "synthesis":
        missing = 0 if contains_synthesis_steps(clean_md) else 1
        synthesis_missing = missing
        
        if missing:
            si_hrefs = find_si_urls_from_html(html)[:3]
            for j, href in enumerate(si_hrefs, start=1):
                si_url = absolutize_url(href, landing_url)
                _fetch_si_file(context, si_url, paper_dir, j, si_records)
                
    return synthesis_missing, si_records


def _fetch_si_file(context, url: str, paper_dir: Path, idx: int, records: list):
    page = None
    try:
        page = context.new_page()
        resp = page.goto(url, wait_until="domcontentloaded", timeout=30000)
        if not resp:
            records.append({"url": url, "status": "error"})
            return

        ct = (resp.headers.get("content-type") or "").lower()
        body = resp.body()
        
        if len(body) > 25 * 1024 * 1024:
            records.append({"url": url, "status": "too_large"})
            return

        if "pdf" in ct or url.lower().endswith(".pdf"):
            path = paper_dir / f"si_{idx}.pdf"
            path.write_bytes(body)
            records.append({"url": url, "path": str(path), "type": "pdf", "status": "ok"})
        else:
            text = body.decode("utf-8", errors="ignore")
            path = paper_dir / f"si_{idx}.html"
            path.write_text(text, encoding="utf-8", errors="ignore")
            records.append({"url": url, "path": str(path), "type": "html", "status": "ok"})
            
    except Exception as e:
        records.append({"url": url, "status": "error", "error": str(e)})
    finally:
        if page:
            try:
                page.close()
            except Exception:
                pass
