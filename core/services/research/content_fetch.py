"""
Fetcher Adapter for Iterative Research
Uses core.services.fetcher for full-text retrieval
"""
import base64
import logging
import threading
from typing import List, Dict, Callable, Optional, Any
from .core_types import IterativeResearchState
from core.browser.edge_launcher import connect_to_real_browser, is_real_browser_running, launch_real_edge_with_cdp
from core.services.fetcher.parsers import html_to_markdown
from core.services.fetcher.batch_fetch import get_domain_from_doi
from core.browser.cf_handler import is_cloudflare_challenge
from config.settings import settings

logger = logging.getLogger('deep_research')

CDP_PORT = 9222


def _ensure_browser_running(interaction_callback: Optional[Callable] = None) -> tuple[bool, str]:
    """
    确保浏览器正在运行，如未运行则自动启动。
    如果启动失败，通过 interaction_callback 询问用户操作。
    
    Returns:
        (success, action): 
        - success=True: 浏览器已就绪
        - success=False, action="continue": 用户选择跳过全文
        - success=False, action="cancel": 用户选择取消任务
    """
    MAX_RETRIES = 2
    
    for attempt in range(MAX_RETRIES):
        # 检查是否已运行
        if is_real_browser_running(CDP_PORT):
            logger.info("✅ Edge 浏览器已检测到")
            return True, "running"
        
        # 尝试自动启动
        logger.info(f"🚀 尝试自动启动 Edge 浏览器 (尝试 {attempt + 1}/{MAX_RETRIES})...")
        success, msg = launch_real_edge_with_cdp(CDP_PORT)
        
        if success:
            logger.info(f"✅ {msg}")
            return True, "launched"
        
        # [P73] Handle Profile Lock specific logic
        if msg == "PROFILE_LOCKED":
             if interaction_callback:
                prompt = f"⚠️ **浏览器 Profile 被占用**\n检测到 Edge 进程正在运行但无法连接 (端口 9222 未开放)。\n这通常是因为有残留的 Edge 进程锁定了用户目录。\n\n请选择操作："
                options = ["🔪 杀掉进程并重试", "🔄 手动解决后重试", "➡️ 继续 (跳过全文)", "❌ 取消任务"]
                
                choice = interaction_callback(prompt, options)
                
                if choice == "🔪 杀掉进程并重试":
                    from core.browser.edge_launcher import kill_edge_process
                    logger.info("用户选择: 杀掉进程并重试")
                    kill_edge_process()
                    continue
                elif choice == "🔄 手动解决后重试" or choice == "🔄 重试":
                    logger.info("用户选择: 重试")
                    continue
                elif choice == "➡️ 继续 (跳过全文)":
                    return False, "continue"
                else: 
                    return False, "cancel"
        
        logger.warning(f"⚠️ 浏览器启动失败: {msg}")
        
        # 如果有交互回调，询问用户 (Generic Failure)
        if interaction_callback:
            prompt = f"⚠️ **浏览器启动失败**\n{msg}\n\n请选择操作："
            options = ["🔄 重试", "➡️ 继续 (跳过全文)", "❌ 取消任务"]
            
            choice = interaction_callback(prompt, options)
            
            if choice == "🔄 重试":
                logger.info("用户选择: 重试")
                continue
            elif choice == "➡️ 继续 (跳过全文)":
                logger.info("用户选择: 继续 (跳过全文)")
                return False, "continue"
            else:
                logger.info("用户选择: 取消任务")
                return False, "cancel"
        else:
            # 无交互回调，默认跳过全文继续
            logger.warning("无交互回调，跳过全文获取")
            return False, "continue"
    
    # 达到最大重试次数
    if interaction_callback:
        prompt = f"⚠️ **浏览器启动失败** (已重试 {MAX_RETRIES} 次)\n\n请选择操作："
        options = ["➡️ 继续 (跳过全文)", "❌ 取消任务"]
        
        choice = interaction_callback(prompt, options)
        
        if choice == "➡️ 继续 (跳过全文)":
            return False, "continue"
        else:
            return False, "cancel"
    
    return False, "continue"


def _sanitize_doi(doi: str) -> str:
    """
    P17/P19: 清洗 DOI，移除常见的 URL 路径前缀和 SI 后缀
    前缀：suppl/10.1021/xxx -> 10.1021/xxx
    后缀：10.1021/xxx.s0 -> 10.1021/xxx (ACS SI DOI)
    """
    import re
    
    if not doi:
        return doi
    
    doi = doi.strip()
    
    # 1. 移除前缀 (ACS, Wiley, RSC 等)
    prefixes_to_remove = [
        "suppl/", "abs/", "full/", "pdf/", "pdfplus/", 
        "epdf/", "doi/", "article/", "10.1021/suppl/"
    ]
    
    for prefix in prefixes_to_remove:
        if doi.lower().startswith(prefix):
            doi = doi[len(prefix):]
    
    # 2. 移除 SI 后缀 (ACS: .s0, .s001, .suppl; RSC: _ESI 等)
    # 常见模式: .s0, .s1, .s001, .suppl, .suppl001
    si_suffix_patterns = [
        r'\.s\d+$',           # .s0, .s001
        r'\.suppl\d*$',       # .suppl, .suppl001  
        r'_ESI$',             # RSC ESI
        r'\.SI$',             # Generic SI
    ]
    
    for pattern in si_suffix_patterns:
        cleaned = re.sub(pattern, '', doi, flags=re.IGNORECASE)
        if cleaned != doi:
            logger.debug(f"DOI SI 后缀清洗: {doi} -> {cleaned}")
            doi = cleaned
            break
    
    # 3. 确保 DOI 格式正确 (应该以 10.xxxx 开头)
    if not doi.startswith("10."):
        match = re.search(r'(10\.\d{4,}/[^\s]+)', doi)
        if match:
            doi = match.group(1)
    
    return doi


# ============================================================
# P27: Interactive CF/CAPTCHA Handling
# ============================================================
# Global event for external trigger (e.g., Telegram callback)
_cf_resolved_events: Dict[str, threading.Event] = {}

def get_cf_event(domain: str) -> threading.Event:
    """Get or create an event for CF resolution on a domain."""
    if domain not in _cf_resolved_events:
        _cf_resolved_events[domain] = threading.Event()
    return _cf_resolved_events[domain]

def signal_cf_resolved(domain: str):
    """Called by Telegram callback when user clicks 'I Solved It'."""
    if domain in _cf_resolved_events:
        _cf_resolved_events[domain].set()
        logger.info(f"📣 CF resolution signaled for {domain}")

def _wait_for_cf_resolution(
    page, 
    domain: str, 
    interaction_callback: Optional[Callable] = None,
    max_wait: int = 45,
    poll_interval: int = 2
) -> bool:
    """
    P27: Wait for Cloudflare challenge to be resolved.
    
    Detection methods:
    1. Auto-detect: Poll page title every 2s, if it changes from CF patterns -> resolved
    2. Manual: User clicks button in Telegram -> triggers event
    3. Timeout: Max 45 seconds
    
    Args:
        page: Playwright page object
        domain: Domain being accessed
        interaction_callback: Optional callback to notify user
        max_wait: Maximum seconds to wait
        poll_interval: Seconds between title checks
    
    Returns:
        True if resolved, False if timeout/skip
    """
    import time
    
    CF_PATTERNS = ["just a moment", "verify you are human", "checking your browser", 
                   "one moment", "ddos protection", "cloudflare"]
    
    def is_cf_title(title: str) -> bool:
        title_lower = title.lower()
        return any(p in title_lower for p in CF_PATTERNS)
    
    # Get initial title
    try:
        initial_title = page.title()
    except:
        initial_title = ""
    
    # Notify user via Telegram (if callback available)
    if interaction_callback:
        try:
            # This will send a message to user and return when they respond
            # Format: (prompt, options) -> selected_option
            result = interaction_callback(
                f"⚠️ **CAPTCHA 检测到!**\n\n域名: `{domain}`\n请在浏览器窗口中完成验证。\n\n等待中... (最多{max_wait}秒)",
                ["✅ 已解决", "⏭️ 跳过"]
            )
            if result == "⏭️ 跳过" or result == "Skip":
                logger.info(f"用户选择跳过 {domain}")
                return False
            elif result == "✅ 已解决":
                # User claims solved, verify
                time.sleep(1)
                try:
                    new_title = page.title()
                    if not is_cf_title(new_title):
                        return True
                except:
                    pass
        except Exception as e:
            logger.error(f"Interaction callback failed in CF check: {e}", exc_info=True)
            # Proceed to fallback polling
    
    # Fallback: Poll-based detection
    logger.info(f"   ⏳ 等待 CF 验证... (最多 {max_wait}s)")
    
    event = get_cf_event(domain)
    event.clear()  # Reset event
    
    elapsed = 0
    while elapsed < max_wait:
        # Check if manually signaled
        if event.is_set():
            return True
        
        # Check page content for auto-resolution
        try:
            # [P91] Use robust detection instead of just title
            html = page.content()
            current_url = page.url
            if not is_cloudflare_challenge(current_url, html):
                 # Double check title to be sure it's not "Just a moment"
                 # (Sometimes HTML updates before JS renders title?)
                 # But is_cloudflare_challenge now checks title too.
                 
                 # Also ensure we are not on an empty/error page
                 if len(html) > 500: # Arbitrary small limit
                     logger.info(f"   ✅ CF 自动通过 (检测通过)")
                     return True
        except Exception as e:
            logger.debug(f"Check failed: {e}")
        
        time.sleep(poll_interval)
        elapsed += poll_interval
    
    logger.warning(f"   ⏰ CF 等待超时 ({max_wait}s)")
    return False

def fetch(state: IterativeResearchState, interaction_callback: Optional[Callable] = None, cancel_callback: Optional[Callable] = None) -> IterativeResearchState:
    """
    使用现有的 fetcher 服务获取论文全文
    按出版商分组，并发抓取
    
    Args:
        state: 研究状态
        interaction_callback: 用户交互回调 (prompt, options) -> choice
        cancel_callback: 取消检查回调 () -> bool
    """
    from playwright.sync_api import sync_playwright
    
    papers = state.paper_pool
    if not papers:
        logger.warning("No papers to fetch.")
        return state
    
    # 过滤需要获取的论文
    to_fetch = [p for p in papers if p.get("doi") and not p.get("full_content")]
    max_fetch = 15
    to_fetch = to_fetch[:max_fetch]
    
    if not to_fetch:
        logger.info("所有论文已有内容，无需获取")
        return state
    
    logger.info(f"📥 正在并发获取 {len(to_fetch)} 篇论文全文...")
    
    # 按出版商分组
    papers_by_domain: Dict[str, List[Dict]] = {}
    for p in to_fetch:
        doi = p.get("doi", "")
        domain = get_domain_from_doi(doi)
        if domain not in papers_by_domain:
            papers_by_domain[domain] = []
        papers_by_domain[domain].append(p)
    
    domains = list(papers_by_domain.keys())
    logger.info(f"   📚 {len(domains)} 个出版商: {', '.join(domains)}")
    
    cf_lock = threading.Lock()
    cf_domains_warned = set()
    
    try:
        # 确保浏览器运行 (自动启动 + 用户交互)
        browser_ok, action = _ensure_browser_running(interaction_callback)
        
        if not browser_ok:
            if action == "cancel":
                # 用户取消任务
                logger.warning("❌ 用户取消任务")
                state.cancelled = True
                return state
            else:
                # 用户选择继续 (跳过全文)
                logger.warning("⚠️ 跳过全文获取，仅使用摘要")
                return state
        
        with sync_playwright() as pw:
            context = connect_to_real_browser(pw, CDP_PORT)
            if not context:
                logger.warning("⚠️ 无法连接到浏览器")
                return state
            
            logger.info("🌐 已连接到 Edge 浏览器")
            
            # 为每个出版商创建页面
            domain_pages: Dict[str, Any] = {}
            domain_indices: Dict[str, int] = {d: 0 for d in domains}
            
            # [P63] Use configured concurrency
            max_concurrent = min(settings.FETCH_CONCURRENCY, len(domains))
            
            try:
                # 初始化页面池
                for domain in domains[:max_concurrent]:
                    try:
                        domain_pages[domain] = context.new_page()
                        logger.info(f"   创建页面: {domain}")
                    except Exception as e:
                        logger.error(f"创建页面失败 {domain}: {e}")
                
                active_domains = list(domain_pages.keys())
                progress = {"completed": 0, "success": 0}
                
                # 轮询处理
                while active_domains:
                    # [P81] Cancellation Check
                    if cancel_callback and cancel_callback():
                        logger.warning("⚠️ 用户取消任务，停止全文获取")
                        state.cancelled = True
                        return state
                        
                    for domain in list(active_domains):
                        papers_list = papers_by_domain[domain]
                        idx = domain_indices[domain]
                        
                        if idx >= len(papers_list):
                            # 该出版商处理完毕
                            if domain in domain_pages:
                                try:
                                    domain_pages[domain].close()
                                except:
                                    pass
                                del domain_pages[domain]
                            active_domains.remove(domain)
                            
                            # 补充新的出版商
                            remaining = [d for d in domains if d not in domain_pages 
                                        and domain_indices[d] < len(papers_by_domain[d])]
                            if remaining:
                                new_domain = remaining[0]
                                try:
                                    domain_pages[new_domain] = context.new_page()
                                    active_domains.append(new_domain)
                                except:
                                    pass
                            continue
                        
                        paper = papers_list[idx]
                        domain_indices[domain] = idx + 1
                        
                        doi = paper.get("doi", "")
                        page = domain_pages.get(domain)
                        if not page:
                            continue
                        
                        _fetch_single_paper_content(
                            paper, page, doi, domain, 
                            progress, len(to_fetch),
                            cf_lock, cf_domains_warned,
                            interaction_callback=interaction_callback
                        )
                        
                        # 如果页面出错需要重建
                        if paper.get("_page_error"):
                            try:
                                page.close()
                                domain_pages[domain] = context.new_page()
                            except:
                                pass
                
                logger.info(f"✅ 全文获取完成: 成功 {progress['success']}/{len(to_fetch)}")
                
            finally:
                # 关闭所有页面
                for page in domain_pages.values():
                    try:
                        page.close()
                    except:
                        pass
    except Exception as e:
        logger.error(f"全文获取失败: {e}")
    
    return state



def download_pdf_for_paper(
    doi: str,
    title: str = "",
    interaction_callback: Optional[Callable] = None,
) -> Dict[str, Any]:
    """使用当前浏览器会话按 DOI 下载 PDF，优先复用实时登录态。"""
    from playwright.sync_api import sync_playwright
    from urllib.parse import urlparse
    import re
    import time

    sanitized_doi = _sanitize_doi(doi)
    if not sanitized_doi:
        return {
            "success": False,
            "doi": doi,
            "title": title,
            "error": "缺少有效 DOI，无法执行 PDF 下载。",
        }

    domain = get_domain_from_doi(sanitized_doi)
    if domain == "pubs.acs.org" or sanitized_doi.startswith("10.1021"):
        article_url = f"https://pubs.acs.org/doi/{sanitized_doi}"
    else:
        article_url = f"https://doi.org/{sanitized_doi}"

    pid = re.sub(r'[\\/*?:"<>|]', '_', sanitized_doi.lower())
    article_dir = settings.LIBRARY_ARTICLE_DIR / pid
    article_dir.mkdir(parents=True, exist_ok=True)

    browser_ok, action = _ensure_browser_running(interaction_callback)
    if not browser_ok:
        error_message = "浏览器未就绪，已跳过 PDF 下载。"
        if action == "cancel":
            error_message = "用户取消了 PDF 下载任务。"
        return {
            "success": False,
            "doi": sanitized_doi,
            "title": title,
            "article_url": article_url,
            "error": error_message,
            "action": action,
        }

    try:
        with sync_playwright() as pw:
            context = connect_to_real_browser(pw, CDP_PORT)
            if not context:
                return {
                    "success": False,
                    "doi": sanitized_doi,
                    "title": title,
                    "article_url": article_url,
                    "error": "无法连接到浏览器实时会话。",
                }

            page = context.new_page()
            try:
                page.goto(article_url, wait_until="domcontentloaded", timeout=30000)
                try:
                    page.wait_for_load_state("networkidle", timeout=10000)
                except Exception:
                    pass
                time.sleep(3)

                landing_url = page.url
                landing_domain = urlparse(landing_url).netloc.lower()
                html = page.content()

                if "sciengine" in landing_domain:
                    captcha_handled = _handle_sciengine_captcha(page, landing_url, html)
                    if captcha_handled:
                        html = page.content()

                if is_cloudflare_challenge(landing_url, html):
                    resolved = _wait_for_cf_resolution(page, landing_domain, interaction_callback)
                    if not resolved:
                        return {
                            "success": False,
                            "doi": sanitized_doi,
                            "title": title,
                            "article_url": article_url,
                            "landing_url": landing_url,
                            "error": "Cloudflare/验证页未完成，未执行下载。",
                            "requires_manual_resolution": True,
                        }
                    html = page.content()

                pdf_result = _try_download_pdf(page, article_dir, sanitized_doi)
                if not pdf_result and _try_click_full_text_button(page):
                    pdf_result = _try_download_pdf(page, article_dir, sanitized_doi)

                if not pdf_result:
                    return {
                        "success": False,
                        "doi": sanitized_doi,
                        "title": title,
                        "article_url": article_url,
                        "landing_url": landing_url,
                        "error": "未能在当前浏览器会话中定位并下载 PDF。",
                    }

                return {
                    "success": True,
                    "doi": sanitized_doi,
                    "title": title,
                    "article_url": article_url,
                    "landing_url": landing_url,
                    "pdf_path": pdf_result,
                    "content_source": "pdf",
                    "content_level": "pdf",
                    "live_session_used": True,
                }
            finally:
                try:
                    page.close()
                except Exception:
                    pass
    except Exception as e:
        logger.error(f"PDF 下载失败 {sanitized_doi}: {e}")
        return {
            "success": False,
            "doi": sanitized_doi,
            "title": title,
            "article_url": article_url,
            "error": str(e),
        }



def _fetch_single_paper_content(
    paper: Dict, 
    page, 
    doi: str, 
    domain: str,
    progress: Dict,
    total: int,
    cf_lock: threading.Lock,
    cf_domains_warned: set,
    interaction_callback: Optional[Callable] = None
):
    """获取单篇论文内容到 paper dict"""
    import time
    from urllib.parse import urlparse
    
    # P17: 清洗 DOI (移除 ACS 等的路径前缀)
    doi = _sanitize_doi(doi)
    
    # P17: ACS 期刊直接使用 pubs.acs.org，避免 doi.org 重定向问题
    if domain == "pubs.acs.org" or doi.startswith("10.1021"):
        url = f"https://pubs.acs.org/doi/{doi}"
    else:
        url = f"https://doi.org/{doi}"
    
    # 速率限制配置 (域名 -> 延迟秒数)
    RATE_LIMITS = {
        "sciengine.com": 8,    # sciengine 需要更慢的速率
        "www.sciengine.com": 8,
        "default": 2
    }
    
    import json
    import re
    import hashlib
    
    # 1. 获取/生成 Library ID
    pid = paper.get("library_id")
    if not pid:
        if doi:
            pid = re.sub(r'[\\/*?:"<>|]', '_', doi.lower())
        else:
            title = paper.get("title", "")
            pid = hashlib.md5(title.encode('utf-8')).hexdigest()
        paper["library_id"] = pid

    # 2. 准备目录 (分区存储)
    # Article 分区: 存放内容
    article_dir = settings.LIBRARY_ARTICLE_DIR / pid
    article_dir.mkdir(parents=True, exist_ok=True)
    
    # Index 分区: 存放/更新元数据
    index_dir = settings.LIBRARY_INDEX_DIR
    index_dir.mkdir(parents=True, exist_ok=True)
    metadata_path = index_dir / f"{pid}.json"
    
    try:
        logger.info(f"   [{progress['completed']+1}/{total}] {domain}: {doi[:30]}...")
        
        # [P39] Pipeline: Stage A (Browser) is priority. MCP Direct moved to Stage C.
        pass

        # Fallback to browser if MCP download failed
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        
        try:
            page.wait_for_load_state("networkidle", timeout=10000)
        except:
            pass
        
        landing_url = page.url
        landing_domain = urlparse(landing_url).netloc.lower()
        
        # 根据域名应用不同的速率限制
        wait_time = RATE_LIMITS.get(landing_domain, RATE_LIMITS["default"])
        time.sleep(wait_time)
        
        html = page.content()
        
        # 检查 sciengine 验证码
        if "sciengine" in landing_domain:
            captcha_handled = _handle_sciengine_captcha(page, landing_url, html)
            if captcha_handled:
                html = page.content()  # 重新获取内容
        
        # 检查 Cloudflare (P27: Interactive Handling)
        if is_cloudflare_challenge(landing_url, html):
            cf_domain = landing_domain
            
            with cf_lock:
                if cf_domain not in cf_domains_warned:
                    cf_domains_warned.add(cf_domain)
                    logger.warning(f"⚠️ {cf_domain} 需要 CF 验证")
            
            # P27: Interactive CAPTCHA Handling
            # Use callback from kwargs or global scope if available
            callback = interaction_callback
            if not callback and 'interaction_callback' in globals():
                callback = globals()['interaction_callback']
                
            resolved = _wait_for_cf_resolution(page, cf_domain, callback)
            
            if resolved:
                # [P27] Save cookies IMMEDIATELY so other threads/requests benefit
                try:
                    # [Fix] Correct import path
                    from core.cf_manager import CF_MANAGER
                    cookies = page.context.cookies()
                    CF_MANAGER.import_from_browser(cookies)
                    logger.info(f"      🍪 已保存 {cf_domain} 的 Cookies")
                except Exception as e:
                    logger.error(f"Save cookies failed: {e}")
                
                html = page.content()
            else:
                # CF not resolved - skip this paper
                paper["full_content"] = None
                progress["completed"] += 1
                return
        
        # 3. 保存原始内容 (Article 分区)
        try:
            (article_dir / "raw.html").write_text(html, encoding="utf-8", errors="ignore")
        except Exception:
            pass

        # 转换为 Markdown
        md = html_to_markdown(html)
        is_complete, content_level = _is_content_complete(md)
        
        # [P39 Stage A] Action 2: Try to click "Full Text" button if abstract/empty
        if not is_complete:
            if _try_click_full_text_button(page):
                html = page.content()
                md = html_to_markdown(html)
                is_complete, content_level = _is_content_complete(md)
        
        # 如果内容不完整，尝试重试
        if not is_complete and md and len(md) > 100:
            logger.info(f"      ⚠️ 内容级别: {content_level} ({len(md)} 字符)，尝试重试...")
            
            # 重试一次，等待更长时间
            retry_html = _retry_fetch_with_wait(page, url, wait_seconds=8)
            if retry_html:
                retry_md = html_to_markdown(retry_html)
                retry_complete, retry_level = _is_content_complete(retry_md)
                if retry_complete:
                    md = retry_md
                    html = retry_html
                    is_complete = True
                    content_level = retry_level
                    logger.info(f"      ✅ 重试成功，获取到完整内容 ({len(md)} 字符)")
                elif retry_md and len(retry_md) > len(md):
                    # 即使不完整，如果更多内容也使用
                    md = retry_md
                    html = retry_html
                    is_complete, content_level = _is_content_complete(md)
        
        # 根据内容级别决定存储位置
        if content_level == "abstract_only":
            # P18: 先尝试 PDF 回退，可能获得完整内容
            logger.info(f"      📄 仅获取到摘要，尝试 PDF 回退...")
            pdf_result = _try_download_pdf(page, article_dir, doi)
            
            if pdf_result:
                paper["pdf_path"] = pdf_result
                paper["content_source"] = "pdf"
                paper["content_level"] = "pdf"
                paper["full_content_path"] = pdf_result
                progress["completed"] += 1
                progress["success"] += 1
                logger.info(f"      ✅ PDF 全文已获取: {pdf_result}")
                return  # 成功获取 PDF，不保存到 abstract 目录
            
            # PDF 失败，降级为 abstract_only
            # PDF 失败，尝试 Stage C: MCP Direct (Fallback)
            if _try_mcp_download_direct(paper, doi, article_dir, domain):
                paper["content_source"] = "mcp_pdf"
                paper["content_level"] = "pdf"
                paper["full_content_path"] = str(article_dir / f"{doi.split('/')[-1]}.pdf" if '/' in doi else "paper.pdf")
                progress["completed"] += 1
                progress["success"] += 1
                logger.info(f"      ✅ MCP PDF Direct (Fallback) 成功")
                return

            # [P39 Stage D] MCP Sci-Hub Fallback (Final Resort)
            if _try_mcp_scihub_fallback(paper, doi, article_dir):
                paper["content_source"] = "mcp_scihub"
                paper["content_level"] = "pdf"
                paper["full_content_path"] = str(article_dir / f"{doi.split('/')[-1]}.pdf" if '/' in doi else "paper.pdf")
                progress["completed"] += 1
                progress["success"] += 1
                logger.info(f"      ✅ MCP Sci-Hub 补救成功")
                return

            logger.warning(f"      📝 PDF 获取失败，保存摘要到 abstract 目录")
            
            # Abstract-only 文件放到单独目录
            abstract_dir = settings.LIBRARY_DIR / "abstract" / pid
            abstract_dir.mkdir(parents=True, exist_ok=True)
            
            # 保存到 abstract 目录
            try:
                (abstract_dir / "raw.html").write_text(html, encoding="utf-8", errors="ignore")
                (abstract_dir / "abstract.md").write_text(md, encoding="utf-8")
            except Exception:
                pass
            
            paper["content_level"] = "abstract_only"
            paper["abstract_path"] = str(abstract_dir / "abstract.md")
            paper["full_content"] = None  # 不作为分析依据
            
            progress["completed"] += 1
            return
        
        # 保存 HTML（到 articles 目录）
        try:
            (article_dir / "raw.html").write_text(html, encoding="utf-8", errors="ignore")
        except Exception:
            pass
        
        # 如果内容仍不完整，尝试下载 PDF
        if not is_complete and content_level != "full":
            logger.info(f"      📄 HTML 内容不完整 ({content_level})，尝试 PDF 回退...")
            pdf_result = _try_download_pdf(page, article_dir, doi)
            
            if pdf_result:
                paper["pdf_path"] = pdf_result
                paper["content_source"] = "pdf"
                content_level = "pdf"
                logger.info(f"      ✅ PDF 已获取: {pdf_result}")
            else:
                logger.warning(f"      ❌ PDF 获取失败，使用不完整的 HTML 内容")
        
        # 保存 Markdown
        if md and len(md) > 200:
            paper["full_content"] = md
            paper["content_level"] = content_level
            
            # 4. 保存 Markdown (Article 分区)
            md_path = article_dir / "full.md"
            md_path.write_text(md, encoding="utf-8")
            paper["full_content_path"] = str(md_path)
            paper["content_complete"] = is_complete
            
            # 5. 更新全局元数据 (Index 分区)
            try:
                current_meta = {}
                if metadata_path.exists():
                    with open(metadata_path, 'r', encoding='utf-8') as f:
                        current_meta = json.load(f)
                
                current_meta.update(paper)
                # 移除 full_content 文本以减小 metadata 体积，仅保留 path
                if "full_content" in current_meta:
                    del current_meta["full_content"]
                
                with open(metadata_path, 'w', encoding='utf-8') as f:
                    json.dump(current_meta, f, ensure_ascii=False, indent=2)
            except Exception as e:
                logger.warning(f"    更新全局元数据失败 {pid}: {e}")

            progress["success"] += 1
        else:
            paper["full_content"] = None
        
        progress["completed"] += 1
        
    except Exception as e:
        logger.warning(f"   抓取失败 {doi}: {e}")
        paper["full_content"] = None
        paper["_page_error"] = True
        progress["completed"] += 1


def _handle_sciengine_captcha(page, url: str, html: str) -> bool:
    """
    处理 sciengine.com 的验证码
    尝试自动填写，失败则提示用户
    返回 True 表示已处理
    """
    import time
    
    h = html.lower()
    
    # 检测验证码页面的特征
    captcha_indicators = [
        "验证码",
        "captcha",
        "human verification",
        "安全验证",
        "滑动验证"
    ]
    
    has_captcha = any(ind in h for ind in captcha_indicators)
    
    if not has_captcha:
        return False
    
    logger.warning(f"⚠️ sciengine.com 出现验证码页面")
    
    # 尝试自动处理常见验证码类型
    try:
        # 1. 尝试查找并点击验证按钮
        verify_btn = page.query_selector('button:has-text("验证"), button:has-text("Verify"), .verify-btn, #verify')
        if verify_btn:
            verify_btn.click()
            time.sleep(3)
            return True
        
        # 2. 尝试处理简单的数学验证码
        math_captcha = page.query_selector('input[name*="captcha"], input[placeholder*="验证码"]')
        if math_captcha:
            # 查找验证码提示文本
            captcha_text = page.query_selector('.captcha-text, .verify-question')
            if captcha_text:
                question = captcha_text.inner_text()
                answer = _solve_simple_captcha(question)
                if answer:
                    math_captcha.fill(answer)
                    submit_btn = page.query_selector('button[type="submit"], input[type="submit"]')
                    if submit_btn:
                        submit_btn.click()
                        time.sleep(3)
                        return True
        
        # 3. 自动处理失败，提示用户
        logger.warning("⚠️ 无法自动处理验证码，请在浏览器中手动完成验证")
        logger.warning(f"   验证页面: {url}")
        
        # 等待用户手动处理 (最多60秒)
        for _ in range(12):
            time.sleep(5)
            new_html = page.content().lower()
            if not any(ind in new_html for ind in captcha_indicators):
                logger.info("✅ 验证码已手动解决")
                return True
        
        logger.warning("❌ 验证码处理超时")
        return False
        
    except Exception as e:
        logger.error(f"验证码处理失败: {e}")
        return False


def _solve_simple_captcha(question: str) -> str | None:
    """
    尝试解决简单的数学验证码
    例如: "3 + 5 = ?", "请输入 8 减 2 的结果"
    """
    import re
    
    question = question.strip()
    
    # 尝试匹配 "a + b" 或 "a - b" 格式
    match = re.search(r'(\d+)\s*[\+加]\s*(\d+)', question)
    if match:
        return str(int(match.group(1)) + int(match.group(2)))
    
    match = re.search(r'(\d+)\s*[\-减]\s*(\d+)', question)
    if match:
        return str(int(match.group(1)) - int(match.group(2)))
    
    match = re.search(r'(\d+)\s*[\*乘×]\s*(\d+)', question)
    if match:
        return str(int(match.group(1)) * int(match.group(2)))
    
    return None


def _is_content_complete(md: str) -> tuple[bool, str]:
    """
    检查抓取的内容是否完整
    
    返回: (is_complete, content_level)
    - content_level: "full" | "abstract_only" | "empty"
    
    判断逻辑：
    - 有 Introduction/Methods/Results 等 → full
    - 只有 Abstract → abstract_only
    - 都没有 → empty
    """
    if not md or len(md) < 100:
        return False, "empty"
    
    md_lower = md.lower()
    
    # 检测正文章节的关键词
    full_text_indicators = [
        "introduction",
        "方法",
        "methods",
        "materials and methods",
        "experimental",
        "实验部分",
        "results",
        "结果",
        "discussion",
        "讨论",
        "conclusion",
        "结论",
    ]
    
    # 检测是否有 Abstract
    has_abstract = any(kw in md_lower for kw in ["abstract", "摘要", "summary"])
    
    # 检测是否有正文章节
    has_full_text = any(kw in md_lower for kw in full_text_indicators)
    
    # 额外检查：长度和段落数
    lines = md.strip().split('\n')
    non_empty_lines = [l for l in lines if l.strip()]
    long_paragraphs = sum(1 for l in lines if len(l.strip()) > 300)
    
    if has_full_text and len(md) > 3000 and long_paragraphs >= 3:
        return True, "full"
    elif has_abstract and not has_full_text:
        return False, "abstract_only"
    elif len(md) > 5000 and long_paragraphs >= 5:
        # 即使没有明确章节，内容足够多也算完整
        return True, "full"
    elif has_abstract:
        return False, "abstract_only"
    else:
        return False, "empty"


def _extract_sciencedirect_pdf_url_from_html(page_url: str, html: str) -> str | None:
    """从 ScienceDirect 文章 HTML 中提取实时会话可访问的 PDF URL。"""
    import re

    if "sciencedirect.com" not in (page_url or "").lower():
        return None

    pdf_re = re.compile(
        r'"pdfDownload":\{"isPdfFullText":(?:true|false),"urlMetadata":\{"queryParams":\{"md5":"([^"]+)","pid":"([^"]+)"\},"pii":"([^"]+)","pdfExtension":"([^"]+)","path":"([^"]+)"\}\}'
    )
    match = pdf_re.search(html or "")
    if not match:
        return None

    md5, pid, pii, pdf_ext, path = match.groups()
    normalized_path = path.lstrip("/")
    return f"https://www.sciencedirect.com/{normalized_path}/{pii}{pdf_ext}?md5={md5}&pid={pid}"



def _extract_pdf_bytes_from_pdfjs_viewer(page, timeout_ms: int = 30000) -> bytes | None:
    """从浏览器内 PDF.js viewer 提取 PDF 字节。"""
    try:
        encoded = page.evaluate(
            """
async ({ timeoutMs }) => {
  const deadline = Date.now() + timeoutMs;
  const toBase64 = (data) => {
    const chunk = 0x8000;
    let binary = '';
    for (let i = 0; i < data.length; i += chunk) {
      binary += String.fromCharCode.apply(null, data.subarray(i, i + chunk));
    }
    return btoa(binary);
  };

  return await new Promise((resolve) => {
    const tick = () => {
      try {
        const app = window.PDFViewerApplication;
        if (app && app.pdfDocument) {
          app.pdfDocument.getData()
            .then((data) => resolve(toBase64(data)))
            .catch((err) => resolve('ERR:' + String(err)));
          return;
        }
      } catch (err) {
        resolve('ERR:' + String(err));
        return;
      }

      if (Date.now() >= deadline) {
        resolve(null);
        return;
      }
      setTimeout(tick, 500);
    };
    tick();
  });
}
            """,
            {"timeoutMs": timeout_ms},
        )
        if not encoded or (isinstance(encoded, str) and encoded.startswith("ERR:")):
            return None
        return base64.b64decode(encoded)
    except Exception as e:
        logger.warning(f"      PDF.js 提取失败: {e}")
        return None



def _try_download_pdf(page, article_dir, doi: str) -> str | None:
    """
    尝试从页面下载 PDF 文件
    返回 PDF 路径或 None
    """
    import time
    
    logger.info(f"      📄 尝试下载 PDF...")
    
    # 常见的 PDF 链接选择器
    pdf_selectors = [
        'a.article__btn__secondary--pdf',
        'a[data-id="article_header_OpenPDF"]',
        'a[title="PDF"][href*="/doi/pdf/"]',
        'a.coolBar__ctrl.pdf-download',
        'a[title="ePDF"]',
        'a[href*="/doi/epdf/"]',
        'a.navbar-download',
        'a[href*="/doi/pdfdirect/"]',
        'a[href*="/articlepdf/"]',
        'a[data-test="pdf-link"]',
        'a.c-pdf-download__link',
        'a.link-button-primary[href*="/pdfft"]',
        'a[aria-label*="View PDF"]',
        'a.accessbar-utility-link[href*="pdfft"]',
        'a[href$=".pdf"]',
        'a[href*=".pdf"]',
        'a[href*="/pdf/"]',
        'a[href*="pdf."]',
        'a:has-text("PDF")',
        'a:has-text("Download PDF")',
        'a:has-text("Full Text PDF")',
        'a:has-text("下载PDF")',
        '.pdf-link',
        '#pdf-link',
        '[data-pdf-url]',
        'a[title*="PDF"]',
    ]
    
    pdf_url = None
    
    # 尝试查找 PDF 链接
    for selector in pdf_selectors:
        try:
            elem = page.query_selector(selector)
            if elem:
                href = elem.get_attribute('href')
                if href:
                    from urllib.parse import urljoin
                    pdf_url = urljoin(page.url, href)
                    logger.info(f"      找到 PDF 链接: {pdf_url[:60]}...")
                    break
        except Exception:
            continue
    
    # 也检查 data-pdf-url 属性
    if not pdf_url:
        try:
            elem = page.query_selector('[data-pdf-url]')
            if elem:
                pdf_url = elem.get_attribute('data-pdf-url')
        except Exception:
            pass

    # ScienceDirect 元数据兜底
    if not pdf_url:
        try:
            pdf_url = _extract_sciencedirect_pdf_url_from_html(page.url, page.content())
            if pdf_url:
                logger.info(f"      从 ScienceDirect 元数据恢复 PDF 链接: {pdf_url[:60]}...")
        except Exception as e:
            logger.warning(f"      ScienceDirect 元数据解析失败: {e}")
    
    if not pdf_url:
        logger.warning(f"      未找到 PDF 链接")
        return None
    
    try:
        pdf_path = article_dir / "paper.pdf"

        try:
            response = page.context.request.get(pdf_url, timeout=60000)
            if response.ok:
                content_type = response.headers.get('content-type', '')
                if 'pdf' in content_type.lower() or pdf_url.endswith('.pdf'):
                    pdf_bytes = response.body()
                    if pdf_bytes.startswith(b'%PDF-'):
                        pdf_path.write_bytes(pdf_bytes)
                        logger.info(f"      ✅ PDF 下载成功: {pdf_path.name}")
                        return str(pdf_path)
                else:
                    logger.warning(f"      响应不是 PDF: {content_type}")
        except Exception as e:
            logger.warning(f"      PDF 直连下载失败: {e}")

        try:
            page.goto(pdf_url, wait_until="domcontentloaded", timeout=30000)
            time.sleep(3)
            pdf_bytes = _extract_pdf_bytes_from_pdfjs_viewer(page, timeout_ms=30000)
            if pdf_bytes and pdf_bytes.startswith(b'%PDF-'):
                pdf_path.write_bytes(pdf_bytes)
                logger.info(f"      ✅ PDF.js 会话提取成功: {pdf_path.name}")
                return str(pdf_path)

            current_url = page.url
            logger.warning(f"      PDF viewer 提取失败: {current_url[:80]}...")
        except Exception as e2:
            logger.warning(f"      PDF 导航失败: {e2}")

    except Exception as e:
        logger.error(f"      PDF 处理异常: {e}")
    
    return None


def _retry_fetch_with_wait(page, url: str, wait_seconds: int = 5) -> str:
    """
    重试抓取，增加等待时间
    """
    import time
    
    logger.info(f"      🔄 重试抓取，等待 {wait_seconds} 秒...")
    
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=45000)
        
        # 等待更长时间
        try:
            page.wait_for_load_state("networkidle", timeout=20000)
        except:
            pass
        
        time.sleep(wait_seconds)
        
        # 尝试滚动页面触发懒加载
        try:
            page.evaluate("window.scrollTo(0, document.body.scrollHeight / 2)")
            time.sleep(2)
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            time.sleep(2)
        except:
            pass
        
        return page.content()
        
    
    except Exception as e:
        logger.warning(f"      重试抓取失败: {e}")
        return ""


def _try_mcp_download_direct(paper: Dict, doi: str, save_dir: Any, domain: str) -> bool:
    """
    [Stage 1] 优先尝试通过 MCP 直连下载 PDF
    支持: arXiv, bioRxiv, medRxiv, Wiley (TDM)
    注意: 不包含 Sci-Hub (留作 Stage 3)
    [P84] Simplified to direct synchronous call.
    """
    if not doi:
        return False
        
    from core.mcp_search import mcp_searcher
    
    # 确定平台
    platform = None
    if "arxiv" in domain: platform = "arxiv"
    elif "biorxiv" in domain: platform = "biorxiv"
    elif "medrxiv" in domain: platform = "medrxiv"
    elif "wiley" in domain: platform = "wiley"
    
    if not platform:
        return False
    
    logger.info(f"   [MCP] 尝试直连下载 PDF (DOI: {doi}, Platform: {platform})")
    
    try:
        save_path = str(save_dir)
        result = mcp_searcher.download_paper(
            paper_id=doi, 
            platform=platform,
            save_path=save_path
        )
        
        if result.get("success"):
            logger.info(f"      ✅ MCP download_paper success for {doi}")
            return True
    except Exception as e:
        logger.warning(f"      MCP Direct Download error: {e}")
        
    return False


def _try_mcp_scihub_fallback(paper: Dict, doi: str, save_dir: Any) -> bool:
    """
    [Stage 3] Sci-Hub 兜底下载
    [P84] Simplified to direct synchronous call.
    """
    if not doi:
        return False
        
    from core.mcp_search import mcp_searcher
    
    logger.info(f"   [MCP] 尝试 Sci-Hub 兜底下载 (DOI: {doi})")
    
    try:
        save_path = str(save_dir)
        result = mcp_searcher.search_scihub(
            doi_or_url=doi,
            download_pdf=True,
            save_path=save_path
        )

        if result.get("success"):
            logger.info(f"      ✅ MCP Sci-Hub success for {doi}")
            return True
            
    except Exception as e:
        logger.warning(f"      MCP Sci-Hub error: {e}")
        
    return False


def _try_click_full_text_button(page) -> bool:
    """
    [P39 Action 2] Try to click 'Full Text / HTML' buttons
    Returns True if clicked and navigation happened
    """
    import time
    
    logger.info(f"      🖱️ 尝试寻找 'Full Text HTML' 按钮...")
    
    selectors = [
        # ACS (Updated P82 based on user HTML sample)
        'a.article__btn__secondary--pdf',
        'a[data-id="article_header_OpenPDF"]',
        'a[title="PDF"][href*="/doi/pdf/"]',
        'a[title="Full Text HTML"]', 
        'li.articleHeaderHtml a', 
        'a:has-text("Full Text HTML")',
        # Wiley (Updated P83 based on user HTML sample)
        'a.coolBar__ctrl.pdf-download',
        'a[title="ePDF"]',
        'a[href*="/doi/epdf/"]',
        'a.navbar-download',
        'a[href*="/doi/pdfdirect/"]',
        'a[aria-label*="Download PDF"]',
        'a[href*="/full/"]', 
        'a.coolBar__ctrl--full-text', 
        'a[title="HTML"]',
        # RSC
        'a[href*="articlehtml"]', 
        'a.btn--download:has-text("HTML")',
        # [P77] RSC Explicit text
        'a:has-text("Article HTML")',
        # Springer
        'a[data-test="fulltext-link"]', 
        'a.c-pdf-download__link span:has-text("HTML")',
        # ScienceDirect (Updated P87 based on user HTML sample)
        'a.link-button-primary[href*="/pdfft"]',
        'a[aria-label*="View PDF"]',
        'a.accessbar-utility-link[href*="pdfft"]',
        'a.anchor-text:has-text("HTML")',
        # Generic
        'a:has-text("Read Online")', 
        'a:has-text("Full Text")', 
        'a[class*="html"]',
        # [P65] User suggestion: Open PDF buttons
        'a:has-text("Open PDF")', 
        'button:has-text("Open PDF")',
        # [P79] Case insensitive / Partial match
        'a[title*="Open PDF" i]',
        'a:text-matches("Open PDF", "i")',
        'a:has-text("PDF")', # More generic fallback
        'a:has-text("View PDF")',
        'a[title="View PDF"]',
        'a[class*="pdf"]'
    ]
    
    for selector in selectors:
        try:
            elem = page.query_selector(selector)
            if elem and elem.is_visible():
                logger.info(f"      Found Full Text button: {selector}")
                # Check if it opens in new tab? Use click with wait logic
                # Handling navigation
                with page.expect_navigation(timeout=15000):
                    elem.click()
                
                # Wait for load
                page.wait_for_load_state("domcontentloaded", timeout=15000)
                time.sleep(3)
                return True
        except Exception:
            pass
            
    return False

