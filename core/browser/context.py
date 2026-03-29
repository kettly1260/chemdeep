"""
浏览器上下文管理

职责:
- 创建浏览器上下文
- 管理真实 Edge 连接
- 注入 cookies
"""
import logging
from pathlib import Path
from config.settings import settings
from core.cf_manager import CF_MANAGER

logger = logging.getLogger('fetcher')


def create_stealth_browser_context(p, profile_dir: Path, headless: bool, 
                                   download_dir: Path = None, 
                                   use_real_browser: bool = False):
    """
    创建浏览器上下文
    
    Args:
        p: Playwright 实例
        profile_dir: 用户配置目录
        headless: 是否无头模式
        download_dir: 下载目录
        use_real_browser: 是否尝试使用真实浏览器
    
    Returns:
        context: 浏览器上下文
    """
    context = None
    
    # 优先尝试连接真实 Edge 浏览器
    if use_real_browser:
        try:
            from core.browser.edge_launcher import is_real_browser_running, connect_to_real_browser
            if is_real_browser_running():
                context = connect_to_real_browser(p)
                if context:
                    logger.info("已连接到真实 Edge 浏览器")
        except Exception as e:
            logger.warning(f"连接真实浏览器失败: {e}")
    
    # 回退到 Playwright 模式
    if not context:
        context_options = {
            "user_data_dir": str(profile_dir),
            "headless": headless,
            "accept_downloads": True,
            "channel": settings.BROWSER_CHANNEL,
            "args": [
                "--disable-blink-features=AutomationControlled",
                "--disable-automation",
            ]
        }
        
        if download_dir:
            context_options["downloads_path"] = str(download_dir)
        
        context = p.chromium.launch_persistent_context(**context_options)
    
    # 注入保存的 cookies
    inject_cf_cookies(context)
    
    return context


def inject_cf_cookies(context) -> int:
    """
    向浏览器上下文注入保存的 CF cookies
    
    Returns:
        int: 注入的 cookie 数量
    """
    cookies = CF_MANAGER.get_all_cookies()
    if cookies:
        try:
            context.add_cookies(cookies)
            logger.info(f"已注入 {len(cookies)} 个 CF cookies")
            return len(cookies)
        except Exception as e:
            logger.warning(f"注入 cookies 失败: {e}")
    return 0
