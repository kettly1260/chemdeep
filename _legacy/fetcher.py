import re
import json
import time
import csv
import logging
from pathlib import Path
from typing import Any, Iterable
from config.settings import settings
from utils.notifier import Notifier
from utils.db import DB
from core.cf_manager import CF_MANAGER

logger = logging.getLogger('fetcher')


def safe_slug(value: str, max_len: int = 80) -> str:
    v = re.sub(r"[^\w\-\.]+", "_", value, flags=re.U).strip("_")
    return v[:max_len] if v else "paper"


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def normalize_doi(value: str | None) -> str | None:
    if not value:
        return None
    value = value.strip()
    value = re.sub(r"^https?://(dx\.)?doi\.org/", "", value, flags=re.I).strip()
    value = value.replace("DOI:", "").strip()
    return value or None


def contains_synthesis_steps(text: str) -> bool:
    t = (text or "").lower()
    if not t:
        return False
    score = 0
    if re.search(r"\b(experimental|methods|materials and methods|synthesis|preparation|fabrication)\b", t):
        score += 1
    if re.search(r"\b(\d{2,4})\s*(°c|celsius|k)\b", t):
        score += 1
    if re.search(r"\b(\d+(\.\d+)?)\s*(h|hr|hrs|hours|min|mins|minutes)\b", t):
        score += 1
    if re.search(r"\b(mg|g|kg|ml|l|mmol|mol|m)\b", t):
        score += 1
    if re.search(r"\b(stirred|heated|reflux|anneal|calcine|washed|dried|filtered|centrifuged)\b", t):
        score += 1
    if re.search(r"\b(autoclave|hydrothermal|solvothermal|cvd|ald|sputter|spin[- ]?coat)\b", t):
        score += 1
    return score >= 2


def is_cloudflare_challenge(url: str, html: str) -> bool:
    """检测是否为 Cloudflare 验证页面
    
    使用更严格的检测条件避免误报
    """
    u = (url or "").lower()
    h = (html or "").lower()
    
    # URL 中包含 CF 特征（确定性高）
    if "cdn-cgi/challenge" in u or "challenge-platform" in u:
        return True
    
    # 检查页面标题是否是典型的 CF 验证标题
    cf_titles = [
        "<title>just a moment</title>",
        "<title>please wait</title>",
        "<title>attention required</title>",
        "<title>checking your browser</title>",
    ]
    if any(title in h for title in cf_titles):
        return True
    
    # 检查特定的 CF 验证元素组合（需要多个条件同时满足）
    has_cf_ray = "cf-ray" in h or "ray id" in h
    has_cf_script = "cf-chl" in h or "turnstile" in h or "cf_chl_opt" in h
    has_challenge_form = "challenge-form" in h or "cf-challenge" in h
    
    # 需要至少两个条件同时满足
    cf_score = sum([has_cf_ray, has_cf_script, has_challenge_form])
    if cf_score >= 2:
        return True
    
    # 检查页面内容是否过短（CF 验证页面通常很短）
    # 同时包含 cloudflare 关键词
    if len(h) < 5000 and "cloudflare" in h and ("challenge" in h or "verify" in h):
        return True
    
    return False


def html_to_markdown(html: str) -> str:
    try:
        import trafilatura
    except ImportError:
        return ""
    md = trafilatura.extract(html, output_format="markdown", include_tables=False, include_comments=False)
    return (md or "").strip()


def find_si_urls_from_html(html: str) -> list[str]:
    if not html:
        return []
    urls: set[str] = set()
    for m in re.finditer(r'href="([^"]+)"', html, flags=re.I):
        href = m.group(1)
        if not href or href.startswith("#"):
            continue
        h = href.lower()
        if any(k in h for k in ["supplement", "supporting", "esi", "supplementary"]):
            urls.add(href)
        elif h.endswith(".pdf") and any(k in h for k in ["supp", "support", "si", "esi"]):
            urls.add(href)
    return list(urls)[:8]


def absolutize_url(href: str, base_url: str) -> str:
    if href.startswith("http://") or href.startswith("https://"):
        return href
    if href.startswith("//"):
        return "https:" + href
    if href.startswith("/"):
        m = re.match(r"^(https?://[^/]+)", base_url)
        if m:
            return m.group(1) + href
    return base_url.rstrip("/") + "/" + href.lstrip("/")


def _sniff_delimiter(path: Path) -> str:
    head = path.read_bytes()[:8192]
    sample = head.decode("utf-8", errors="ignore")
    if sample.count("\t") >= 2 and sample.count("\t") >= sample.count(","):
        return "\t"
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=[",", "\t", ";", "|"])
        return dialect.delimiter
    except Exception:
        return "\t" if "\t" in sample else ","


def parse_wos_file(path: Path) -> list[dict[str, Any]]:
    delimiter = _sniff_delimiter(path)
    
    with path.open("r", encoding="utf-8-sig", errors="ignore", newline="") as f:
        reader = csv.DictReader(f, delimiter=delimiter)
        if not reader.fieldnames:
            return []
        
        headers = {h: h.lower().strip() for h in reader.fieldnames}
        
        def pick_col(candidates: Iterable[str]) -> str | None:
            candidates_l = [c.lower() for c in candidates]
            for h, hl in headers.items():
                for c in candidates_l:
                    if hl == c or c in hl:
                        return h
            return None
        
        col_doi = pick_col(["di", "doi", "do"])  # "do" 是搜索结果格式的列名
        col_title = pick_col(["ti", "title", "article title"])
        col_year = pick_col(["py", "year", "publication year"])
        col_source = pick_col(["so", "source title", "journal"])
        col_ut = pick_col(["ut", "unique wos id", "wos id"])
        
        papers: list[dict[str, Any]] = []
        for row in reader:
            doi = normalize_doi(row.get(col_doi, "")) if col_doi else None
            title = (row.get(col_title, "") or "").strip() if col_title else ""
            year = (row.get(col_year, "") or "").strip() if col_year else ""
            source = (row.get(col_source, "") or "").strip() if col_source else ""
            ut = (row.get(col_ut, "") or "").strip() if col_ut else ""
            
            if not doi and not title:
                continue
            
            papers.append({
                "doi": doi,
                "title": title or None,
                "year": year or None,
                "source": source or None,
                "ut": ut or None,
            })
        
        return papers


def launch_real_edge_with_cdp(port: int = 9222) -> tuple[bool, str]:
    """启动真实 Edge 浏览器并开启远程调试端口
    
    Returns:
        (success, message)
    """
    import subprocess
    import os
    
    # 先检查端口是否已经可用（已经有调试浏览器在运行）
    if is_real_browser_running(port):
        return True, "Edge 浏览器已在运行（调试端口已开启）"
    
    # 检查是否有 Edge 进程在运行（可能没有调试端口）
    try:
        result = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq msedge.exe"],
            capture_output=True,
            text=True,
            shell=False
        )
        if "msedge.exe" in result.stdout:
            return False, (
                "❌ Edge 浏览器已在运行但未开启调试端口\n\n"
                "请完全关闭 Edge 浏览器后重试:\n"
                "1. 关闭所有 Edge 窗口\n"
                "2. 在任务管理器中结束所有 msedge.exe 进程\n"
                "3. 重新运行 /startedge"
            )
    except Exception:
        pass
    
    # Edge 可执行文件路径
    edge_paths = [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Edge\Application\msedge.exe"),
    ]
    
    edge_exe = None
    for path in edge_paths:
        if os.path.exists(path):
            edge_exe = path
            break
    
    if not edge_exe:
        return False, "❌ 找不到 Edge 浏览器，请确认已安装 Microsoft Edge"
    
    # 使用用户的默认 Profile
    user_data_dir = os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Edge\User Data")
    
    try:
        subprocess.Popen([
            edge_exe,
            f"--remote-debugging-port={port}",
            f"--user-data-dir={user_data_dir}",
            "--no-first-run",
            "--restore-last-session",
        ], shell=False)
        
        # 等待浏览器启动
        for _ in range(10):
            time.sleep(1)
            if is_real_browser_running(port):
                logger.info(f"Edge 浏览器已启动，调试端口: {port}")
                return True, "✅ Edge 浏览器已启动"
        
        return False, "⚠️ Edge 已启动但调试端口未开启，请检查"
    except Exception as e:
        logger.error(f"启动 Edge 失败: {e}")
        return False, f"❌ 启动 Edge 失败: {e}"


def is_real_browser_running(port: int = 9222) -> bool:
    """检查真实浏览器是否已启动"""
    import socket
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1)
        result = sock.connect_ex(('localhost', port))
        sock.close()
        return result == 0
    except Exception:
        return False


def connect_to_real_browser(p, port: int = 9222):
    """连接到真实的 Edge 浏览器（通过 CDP）"""
    
    # 先检查端口是否可用
    if not is_real_browser_running(port):
        logger.info(f"端口 {port} 未开放，真实浏览器未运行")
        return None
    
    try:
        logger.info(f"正在连接到 localhost:{port}...")
        browser = p.chromium.connect_over_cdp(f"http://localhost:{port}")
        contexts = browser.contexts
        
        if contexts:
            logger.info(f"已连接到真实浏览器，使用现有上下文")
            return contexts[0]
        else:
            logger.info(f"已连接到真实浏览器，创建新上下文")
            return browser.new_context()
    except Exception as e:
        logger.error(f"连接到浏览器失败: {e}")
        return None


def create_stealth_browser_context(p, profile_dir: Path, headless: bool, download_dir: Path = None, use_real_browser: bool = False):
    """创建浏览器上下文
    
    Args:
        use_real_browser: 如果为 True，尝试连接到真实的 Edge 浏览器
    """
    
    # 尝试连接真实浏览器
    if use_real_browser or settings.USE_REAL_BROWSER:
        try:
            logger.info("尝试连接真实 Edge 浏览器...")
            context = connect_to_real_browser(p)
            if context:
                logger.info("已连接到真实 Edge 浏览器")
                return context
        except Exception as e:
            logger.warning(f"连接真实浏览器失败: {e}，回退到 Playwright 模式")
    
    # 回退到 Playwright 模式
    profile_dir.mkdir(parents=True, exist_ok=True)
    
    args = [
        "--disable-blink-features=AutomationControlled",
        "--disable-automation",
        "--disable-infobars",
        "--no-sandbox",
        "--disable-dev-shm-usage",
    ]
    
    kwargs = {
        "user_data_dir": str(profile_dir),
        "headless": headless,
        "accept_downloads": True,
        "channel": settings.BROWSER_CHANNEL,
        "args": args,
        "ignore_default_args": ["--enable-automation"],
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0",
        "viewport": {"width": 1920, "height": 1080},
        "locale": "en-US",
    }
    
    if download_dir:
        kwargs["downloads_path"] = str(download_dir)
    
    context = p.chromium.launch_persistent_context(**kwargs)
    
    # 注入脚本隐藏自动化标识
    context.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
        Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
        Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en', 'zh-CN']});
        window.chrome = {runtime: {}};
        
        // 隐藏 Playwright 特征
        delete window.__playwright;
        delete window.__pw_manual;
    """)
    
    # 注入已保存的 CF cookies
    cf_cookies = CF_MANAGER.get_all_cookies()
    if cf_cookies:
        try:
            context.add_cookies(cf_cookies)
            logger.info(f"已注入 {len(cf_cookies)} 个 CF cookies")
        except Exception as e:
            logger.warning(f"注入 cookies 失败: {e}")
    
    return context


def open_in_real_edge(url: str) -> bool:
    """在真实 Edge 浏览器中打开 URL（完全无自动化标识）"""
    import subprocess
    import os
    
    edge_paths = [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Edge\Application\msedge.exe"),
    ]
    
    edge_exe = None
    for path in edge_paths:
        if os.path.exists(path):
            edge_exe = path
            break
    
    if not edge_exe:
        return False
    
    try:
        subprocess.Popen([edge_exe, url], shell=False)
        return True
    except Exception:
        return False


def handle_cloudflare(page, notifier: Notifier, headless: bool, timeout: int = 300) -> bool:
    """处理 Cloudflare 验证"""
    url = page.url
    
    if headless:
        notifier.send(f"⚠️ 遇到 Cloudflare 验证: {url}\n请使用 headless=0 或设置 CF cookie")
        return False
    
    notifier.send(f"⚠️ 遇到 Cloudflare 验证\n👆 请在浏览器窗口中手动完成验证...")
    
    deadline = time.time() + timeout
    
    while time.time() < deadline:
        time.sleep(2)
        
        try:
            html = page.content()
            current_url = page.url
            
            if not is_cloudflare_challenge(current_url, html):
                notifier.send("✅ Cloudflare 验证通过")
                
                # 保存新的 cookies
                try:
                    context = page.context
                    cookies = context.cookies()
                    count = CF_MANAGER.import_from_browser(cookies)
                    if count > 0:
                        notifier.send(f"📎 已保存 {count} 个 CF cookies")
                except Exception as e:
                    logger.warning(f"保存 cookies 失败: {e}")
                
                return True
        except Exception:
            continue
    
    notifier.send("❌ Cloudflare 验证超时")
    return False


def run_fetch_job(
    db: DB,
    notifier: Notifier,
    job_id: str,
    wos_file: Path,
    goal: str,
    max_papers: int,
) -> None:
    """运行完整的抓取任务"""
    
    db._conn.execute(
        "UPDATE jobs SET status='running', message='importing' WHERE job_id=?",
        (job_id,)
    )
    db._conn.commit()
    
    notifier.send(f"📥 正在导入文件: {wos_file.name}")
    
    try:
        papers = parse_wos_file(wos_file)
        if max_papers > 0:
            papers = papers[:max_papers]
    except Exception as e:
        notifier.send(f"❌ 解析文件失败: {e}")
        db._conn.execute(
            "UPDATE jobs SET status='failed', message=? WHERE job_id=?",
            (str(e), job_id)
        )
        db._conn.commit()
        return
    
    if not papers:
        notifier.send("❌ 未找到有效记录")
        db._conn.execute(
            "UPDATE jobs SET status='failed', message='no papers found' WHERE job_id=?",
            (job_id,)
        )
        db._conn.commit()
        return
    
    db._conn.executemany(
        """INSERT INTO papers(job_id, ut, doi, title, year, source, status)
           VALUES(?, ?, ?, ?, ?, ?, 'imported')""",
        [(job_id, p.get("ut"), p.get("doi"), p.get("title"), p.get("year"), p.get("source")) for p in papers]
    )
    db._conn.commit()
    
    notifier.send(f"✅ 已导入 {len(papers)} 篇论文")
    notifier.send(f"🌐 开始抓取全文 (goal={goal})")
    
    try:
        fetch_publisher_html_and_si(
            db=db,
            notifier=notifier,
            job_id=job_id,
            goal=goal,
            profile_dir=settings.PROFILE_DIR,
            library_dir=settings.LIBRARY_DIR,
            headless=settings.HEADLESS,
            rate_seconds=settings.RATE_SECONDS,
        )
        
        db._conn.execute(
            "UPDATE jobs SET status='completed', message='done' WHERE job_id=?",
            (job_id,)
        )
        db._conn.commit()
        notifier.send(f"🎉 任务完成: {job_id}")
        
    except Exception as e:
        logger.error(f"抓取失败: {e}", exc_info=True)
        db._conn.execute(
            "UPDATE jobs SET status='failed', message=? WHERE job_id=?",
            (str(e), job_id)
        )
        db._conn.commit()
        notifier.send(f"❌ 任务失败: {e}")


def fetch_publisher_html_and_si(
    db: DB,
    notifier: Notifier,
    job_id: str,
    *,
    goal: str,
    profile_dir: Path,
    library_dir: Path,
    headless: bool,
    rate_seconds: int,
) -> None:
    """核心抓取函数 - 并行版本"""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    import threading
    
    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright
    except ImportError as e:
        notifier.send("❌ Playwright 未安装")
        raise RuntimeError("Playwright not installed") from e
    
    ensure_dir(profile_dir)
    ensure_dir(library_dir)
    
    papers = db.list_papers(job_id)
    
    # 获取全局已成功抓取的 DOI 集合（跨所有任务）
    globally_fetched_dois = db.get_fetched_dois()
    logger.info(f"全局已抓取 DOI 数量: {len(globally_fetched_dois)}")
    
    # 过滤掉已成功抓取的论文（支持断点续传 + 跨任务去重）
    pending_papers = []
    skipped_global = 0
    skipped_local = 0
    
    for p in papers:
        p_dict = dict(p)
        doi = (p_dict.get("doi") or "").strip().lower()
        status = p_dict.get("status", "")
        
        if status == "fetched":
            # 当前任务中已标记为完成
            skipped_local += 1
        elif doi and doi in globally_fetched_dois:
            # 其他任务中已成功抓取，复制路径信息并更新状态
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
            skipped_global += 1
        else:
            pending_papers.append(p)
    
    already_done = skipped_local + skipped_global
    total = len(papers)
    pending_count = len(pending_papers)
    
    if pending_count == 0:
        if already_done > 0:
            notifier.send(f"✅ 所有 {total} 篇论文已抓取完成，无需重复抓取")
        else:
            notifier.send("⚠️ 没有论文需要抓取")
        return
    
    skip_msg = ""
    if skipped_global > 0:
        skip_msg = f"\n🔄 跨任务去重: {skipped_global} 篇"
    if skipped_local > 0:
        skip_msg += f"\n✓ 本任务已完成: {skipped_local} 篇"
    
    notifier.send(f"📎 待抓取: {pending_count}/{total} 篇{skip_msg}")
    
    # 进度跟踪（线程安全）
    progress = {"completed": 0, "success": 0, "failed": 0}
    progress_lock = threading.Lock()
    
    # 域名信号量：每个域名同时只处理1篇
    domain_semaphores: dict[str, threading.Semaphore] = {}
    domain_lock = threading.Lock()
    
    # CF 域名警告记录
    cf_domains_warned = set()
    cf_lock = threading.Lock()
    
    def get_domain_semaphore(domain: str) -> threading.Semaphore:
        with domain_lock:
            if domain not in domain_semaphores:
                domain_semaphores[domain] = threading.Semaphore(1)
            return domain_semaphores[domain]
    
    def get_domain_from_doi(doi: str) -> str:
        """从 DOI 推断出版商域名"""
        doi_lower = doi.lower()
        domain_map = {
            "10.1016": "sciencedirect.com",
            "10.1002": "wiley.com",
            "10.1021": "pubs.acs.org",
            "10.1039": "pubs.rsc.org",
            "10.1038": "nature.com",
            "10.1007": "springer.com",
            "10.1080": "tandfonline.com",
            "10.3390": "mdpi.com",
            "10.3389": "frontiersin.org",
        }
        for prefix, domain in domain_map.items():
            if doi_lower.startswith(prefix):
                return domain
        return "unknown"
    
    def fetch_single_paper(row, context, paper_idx: int) -> dict:
        """抓取单篇论文"""
        paper_row_id = int(row["id"])
        doi = (row["doi"] or "").strip()
        title = (row["title"] or "").strip()
        ut = (row["ut"] or "").strip()
        
        result = {"paper_id": paper_row_id, "doi": doi, "status": "unknown", "error": None}
        
        if not doi:
            db.update_paper_fetch(paper_row_id, status="skipped_no_doi", fetch_error="missing DOI")
            result["status"] = "skipped"
            return result
        
        domain = get_domain_from_doi(doi)
        sem = get_domain_semaphore(domain)
        
        paper_dir = library_dir / f"{paper_row_id:06d}_{safe_slug(ut or doi or title or str(paper_row_id))}"
        ensure_dir(paper_dir)
        
        url = f"https://doi.org/{doi}"
        
        # 获取域名信号量
        sem.acquire()
        try:
            page = context.new_page()
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=60000)
                
                try:
                    page.wait_for_load_state("networkidle", timeout=20000)
                except PlaywrightTimeoutError:
                    pass
                
                time.sleep(rate_seconds)
                
                landing_url = page.url
                html = page.content()
                
                # 检查 Cloudflare
                if is_cloudflare_challenge(landing_url, html):
                    from urllib.parse import urlparse
                    cf_domain = urlparse(landing_url).netloc
                    
                    with cf_lock:
                        if cf_domain not in cf_domains_warned:
                            cf_domains_warned.add(cf_domain)
                            notifier.send(f"⚠️ {cf_domain} 需要 CF 验证，请在浏览器中手动完成")
                    
                    # 等待验证
                    if handle_cloudflare(page, notifier, headless, timeout=120):
                        html = page.content()
                        landing_url = page.url
                    else:
                        db.update_paper_fetch(paper_row_id, status="cf_blocked", fetch_error=f"CF: {cf_domain}")
                        result["status"] = "cf_blocked"
                        result["error"] = f"Cloudflare: {cf_domain}"
                        return result
                
                # 保存 HTML
                raw_html_path = paper_dir / "raw.html"
                raw_html_path.write_text(html, encoding="utf-8", errors="ignore")
                
                clean_md = html_to_markdown(html)
                clean_md_path = paper_dir / "clean.md"
                clean_md_path.write_text(clean_md or "", encoding="utf-8")
                
                synthesis_missing = None
                si_records = []
                
                if goal == "synthesis":
                    missing = 0 if contains_synthesis_steps(clean_md) else 1
                    synthesis_missing = missing
                    
                    if missing:
                        si_hrefs = find_si_urls_from_html(html)
                        for j, href in enumerate(si_hrefs[:3], start=1):
                            si_url = absolutize_url(href, landing_url)
                            si_page = None
                            try:
                                si_page = context.new_page()
                                resp = si_page.goto(si_url, wait_until="domcontentloaded", timeout=60000)
                                
                                if resp is None:
                                    si_records.append({"url": si_url, "status": "error"})
                                    continue
                                
                                si_html = si_page.content()
                                if is_cloudflare_challenge(si_page.url, si_html):
                                    si_records.append({"url": si_url, "status": "cf_blocked"})
                                    continue
                                
                                ct = (resp.headers.get("content-type") or "").lower()
                                body = resp.body()
                                
                                if len(body) > 25 * 1024 * 1024:
                                    si_records.append({"url": si_url, "status": "too_large"})
                                    continue
                                
                                if "pdf" in ct or si_url.lower().endswith(".pdf"):
                                    si_path = paper_dir / f"si_{j}.pdf"
                                    si_path.write_bytes(body)
                                    si_records.append({"url": si_url, "path": str(si_path), "type": "pdf", "status": "ok"})
                                else:
                                    text = body.decode("utf-8", errors="ignore")
                                    si_html_path = paper_dir / f"si_{j}.html"
                                    si_html_path.write_text(text, encoding="utf-8", errors="ignore")
                                    si_md = html_to_markdown(text)
                                    si_md_path = paper_dir / f"si_{j}.md"
                                    si_md_path.write_text(si_md or "", encoding="utf-8")
                                    si_records.append({"url": si_url, "path": str(si_html_path), "type": "html", "status": "ok"})
                            except Exception as e:
                                si_records.append({"url": si_url, "status": "error", "error": str(e)})
                            finally:
                                if si_page:
                                    try:
                                        si_page.close()
                                    except Exception:
                                        pass
                
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
                return result
                
            except PlaywrightError as e:
                db.update_paper_fetch(paper_row_id, status="fetch_failed", fetch_error=str(e))
                result["status"] = "failed"
                result["error"] = str(e)
                notifier.send(f"❌ {doi}: {type(e).__name__}")
                return result
            except Exception as e:
                db.update_paper_fetch(paper_row_id, status="fetch_failed", fetch_error=str(e))
                result["status"] = "failed"
                result["error"] = str(e)
                logger.error(f"抓取失败 {doi}: {e}", exc_info=True)
                return result
            finally:
                try:
                    page.close()
                except Exception:
                    pass
        finally:
            sem.release()
    
    # 保存任务进度到数据库供 /progress 命令查询
    db.kv_set(f"job_progress_{job_id}", json.dumps({
        "total": total, 
        "completed": already_done, 
        "success": already_done,
        "failed": 0,
        "pending": pending_count
    }))
    
    # 按出版商分组论文
    def get_domain_from_doi(doi: str) -> str:
        doi_lower = doi.lower()
        domain_map = {
            "10.1016": "elsevier",
            "10.1002": "wiley",
            "10.1021": "acs",
            "10.1039": "rsc",
            "10.1038": "nature",
            "10.1007": "springer",
            "10.1080": "taylor",
            "10.3390": "mdpi",
            "10.3389": "frontiers",
        }
        for prefix, domain in domain_map.items():
            if doi_lower.startswith(prefix):
                return domain
        return "other"
    
    # 将论文按出版商分组
    papers_by_domain: dict[str, list] = {}
    for row in pending_papers:
        doi = (row["doi"] or "").strip()
        if doi:
            domain = get_domain_from_doi(doi)
            if domain not in papers_by_domain:
                papers_by_domain[domain] = []
            papers_by_domain[domain].append(row)
    
    domains = list(papers_by_domain.keys())
    max_concurrent = min(settings.PARALLEL_FETCHERS, len(domains), 8)
    
    # 重置进度消息，开始使用消息编辑
    notifier.reset_progress()
    notifier.progress_update(f"🚀 开始并发抓取 {pending_count} 篇论文\n📚 {len(domains)} 个出版商, {max_concurrent} 并发")
    
    with sync_playwright() as p:
        # 检查是否应该使用真实浏览器
        if settings.USE_REAL_BROWSER:
            if is_real_browser_running():
                logger.info("已连接到真实 Edge 浏览器")
            else:
                logger.info("真实浏览器未运行，使用 Playwright 模式")
        
        context = create_stealth_browser_context(p, profile_dir, headless)
        
        # 为每个活跃的出版商创建一个页面
        domain_pages: dict[str, Any] = {}
        domain_indices: dict[str, int] = {d: 0 for d in domains}  # 每个域名的当前处理索引
        
        try:
            # 初始化页面池
            for domain in domains[:max_concurrent]:
                try:
                    domain_pages[domain] = context.new_page()
                except Exception as e:
                    logger.error(f"创建页面失败 {domain}: {e}")
            
            processed = 0
            active_domains = list(domain_pages.keys())
            
            while active_domains and not db.cancel_requested(job_id):
                # 依次处理每个活跃出版商的一篇论文
                for domain in list(active_domains):
                    if db.cancel_requested(job_id):
                        break
                    
                    papers_list = papers_by_domain[domain]
                    idx = domain_indices[domain]
                    
                    if idx >= len(papers_list):
                        # 该出版商的论文已全部处理完
                        if domain in domain_pages:
                            try:
                                domain_pages[domain].close()
                            except Exception:
                                pass
                            del domain_pages[domain]
                        active_domains.remove(domain)
                        
                        # 如果还有未处理的出版商，为其创建页面
                        remaining_domains = [d for d in domains if d not in domain_pages and domain_indices[d] < len(papers_by_domain[d])]
                        if remaining_domains:
                            new_domain = remaining_domains[0]
                            try:
                                domain_pages[new_domain] = context.new_page()
                                active_domains.append(new_domain)
                            except Exception as e:
                                logger.error(f"创建页面失败 {new_domain}: {e}")
                        continue
                    
                    row = papers_list[idx]
                    domain_indices[domain] = idx + 1
                    
                    paper_row_id = int(row["id"])
                    doi = (row["doi"] or "").strip()
                    title = (row["title"] or "").strip()
                    ut = (row["ut"] or "").strip()
                    
                    if not doi:
                        db.update_paper_fetch(paper_row_id, status="skipped_no_doi", fetch_error="missing DOI")
                        progress["completed"] += 1
                        continue
                    
                    paper_dir = library_dir / f"{paper_row_id:06d}_{safe_slug(ut or doi or title or str(paper_row_id))}"
                    ensure_dir(paper_dir)
                    
                    url = f"https://doi.org/{doi}"
                    processed += 1
                    logger.info(f"[{processed}/{pending_count}] {domain}: {doi}")
                    
                    page = domain_pages.get(domain)
                    if not page:
                        continue
                    
                    try:
                        page.goto(url, wait_until="domcontentloaded", timeout=30000)
                        
                        # 等待页面导航完成（处理重定向）
                        try:
                            page.wait_for_load_state("networkidle", timeout=10000)
                        except Exception:
                            pass  # 超时后继续
                        
                        # 等待页面稳定
                        time.sleep(2)
                        
                        # 重试获取内容（防止页面仍在导航）
                        html = None
                        for attempt in range(3):
                            try:
                                landing_url = page.url
                                html = page.content()
                                break
                            except Exception as e:
                                if attempt < 2:
                                    time.sleep(1)
                                else:
                                    raise e
                        
                        # 检查 Cloudflare
                        if is_cloudflare_challenge(landing_url, html):
                            from urllib.parse import urlparse
                            cf_domain = urlparse(landing_url).netloc
                            
                            if cf_domain not in cf_domains_warned:
                                cf_domains_warned.add(cf_domain)
                                notifier.send(f"⚠️ {cf_domain} 需要 CF 验证")
                            
                            if handle_cloudflare(page, notifier, headless, timeout=60):
                                html = page.content()
                                landing_url = page.url
                            else:
                                db.update_paper_fetch(paper_row_id, status="cf_blocked", fetch_error=f"CF: {cf_domain}")
                                progress["completed"] += 1
                                progress["failed"] += 1
                                continue
                        
                        # 保存 HTML
                        raw_html_path = paper_dir / "raw.html"
                        raw_html_path.write_text(html, encoding="utf-8", errors="ignore")
                        
                        clean_md = html_to_markdown(html)
                        clean_md_path = paper_dir / "clean.md"
                        clean_md_path.write_text(clean_md or "", encoding="utf-8")
                        
                        synthesis_missing = None
                        si_records = []
                        
                        if goal == "synthesis":
                            missing = 0 if contains_synthesis_steps(clean_md) else 1
                            synthesis_missing = missing
                            
                            # 简化 SI 处理，加快速度
                            if missing:
                                si_hrefs = find_si_urls_from_html(html)[:2]  # 最多 2 个 SI
                                for j, href in enumerate(si_hrefs, start=1):
                                    si_url = absolutize_url(href, landing_url)
                                    si_page = None
                                    try:
                                        si_page = context.new_page()
                                        resp = si_page.goto(si_url, wait_until="domcontentloaded", timeout=15000)
                                        
                                        if resp:
                                            ct = (resp.headers.get("content-type") or "").lower()
                                            body = resp.body()
                                            
                                            if len(body) < 10 * 1024 * 1024:  # 10MB 限制
                                                if "pdf" in ct or si_url.lower().endswith(".pdf"):
                                                    si_path = paper_dir / f"si_{j}.pdf"
                                                    si_path.write_bytes(body)
                                                    si_records.append({"url": si_url, "type": "pdf", "status": "ok"})
                                                else:
                                                    text = body.decode("utf-8", errors="ignore")
                                                    si_html_path = paper_dir / f"si_{j}.html"
                                                    si_html_path.write_text(text, encoding="utf-8", errors="ignore")
                                                    si_records.append({"url": si_url, "type": "html", "status": "ok"})
                                    except Exception as e:
                                        si_records.append({"url": si_url, "status": "error"})
                                    finally:
                                        if si_page:
                                            try:
                                                si_page.close()
                                            except Exception:
                                                pass
                        
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
                        
                        progress["completed"] += 1
                        progress["success"] += 1
                        
                    except PlaywrightError as e:
                        error_msg = str(e)[:200]  # 截断错误消息
                        db.update_paper_fetch(paper_row_id, status="fetch_failed", fetch_error=error_msg)
                        progress["completed"] += 1
                        progress["failed"] += 1
                        logger.warning(f"Playwright 错误 {doi}: {error_msg}")
                        # 重新创建页面
                        try:
                            page.close()
                            domain_pages[domain] = context.new_page()
                        except Exception:
                            pass
                    except Exception as e:
                        error_msg = str(e)[:200]
                        db.update_paper_fetch(paper_row_id, status="fetch_failed", fetch_error=error_msg)
                        progress["completed"] += 1
                        progress["failed"] += 1
                        logger.error(f"抓取失败 {doi}: {error_msg}", exc_info=True)
                    
                    # 更新进度
                    db.kv_set(f"job_progress_{job_id}", json.dumps({
                        "total": total,
                        "completed": already_done + progress["completed"],
                        "success": already_done + progress["success"],
                        "failed": progress["failed"],
                        "pending": pending_count - progress["completed"]
                    }))
                    
                    # 每 5 篇更新一次进度消息
                    if progress["completed"] % 5 == 0 or progress["completed"] == pending_count:
                        pct = int(100 * (already_done + progress["completed"]) / total)
                        notifier.progress_update(
                            f"📊 抓取进度: {already_done + progress['completed']}/{total} ({pct}%)\n"
                            f"✅ 成功: {already_done + progress['success']}\n"
                            f"❌ 失败: {progress['failed']}"
                        )
            
            if db.cancel_requested(job_id):
                notifier.send("⏹️ 任务已取消")
            else:
                # 完成汇报
                total_success = already_done + progress["success"]
                notifier.send(
                    f"🎉 抓取完成!\n"
                    f"✅ 成功: {total_success} (本次 {progress['success']})\n"
                    f"❌ 失败: {progress['failed']}\n"
                    f"📊 共计: {already_done + progress['completed']}/{total}"
                )
        finally:
            # 关闭所有页面
            for page in domain_pages.values():
                try:
                    page.close()
                except Exception:
                    pass
            
            # 只有非真实浏览器模式才关闭 context
            # 真实浏览器通过 CDP 连接时，关闭 context 会关闭整个浏览器
            if not settings.USE_REAL_BROWSER or not is_real_browser_running():
                try:
                    context.close()
                except Exception:
                    pass