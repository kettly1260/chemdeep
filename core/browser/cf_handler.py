"""
Cloudflare 验证处理器

职责:
- 检测 CF 验证页面
- 处理 CF 验证
- 清理无效 Cookie
"""
import logging
from urllib.parse import urlparse
from core.cf_manager import CF_MANAGER

logger = logging.getLogger('fetcher')


def is_cloudflare_challenge(url: str, html: str) -> bool:
    """
    检测是否为 Cloudflare 验证页面
    
    [P88] 使用更严格的检测条件避免误报
    """
    h = html.lower()
    
    h = html.lower()
    
    # [P91] 放宽长度限制 (CF 页面有时包含大量隐藏表单/脚本)
    if len(h) > 50000:
        return False
    
    # [P91] 使用正则匹配 Title (忽略属性)
    import re
    # 匹配 <title...>text</title>
    title_match = re.search(r'<title[^>]*>(.*?)</title>', h, re.DOTALL)
    if title_match:
        title_text = title_match.group(1).strip()
        cf_titles = [
            "just a moment",
            "please wait",
            "security check",
            "attention required",
            "checking your browser",
            "one more step",
            "verify you are human",
            "web server is down",
            "access denied",
            "cloudflare"
        ]
        if any(t in title_text for t in cf_titles):
            logger.debug(f"检测到 CF Title: {title_text}")
            return True
    
    # [P88] 检测 CF 特有的 JavaScript/Form 元素 (高置信度)
    cf_specific_elements = [
        "cf-browser-verification",
        "cf_chl_opt",
        "_cf_chl_tk",
        "challenge-platform",
        'id="challenge-form"',
        'id="cf-challenge"',
        'class="cf-browser-verification"',
        'cf-turnstile',
        'ray id:', # P91: Re-add but combine with short length or other checks? No, stick to specific elements.
        'window._cf_chl_opt' 
    ]
    for elem in cf_specific_elements:
        if elem in h:
            logger.debug(f"检测到 CF 元素: {elem}")
            return True
    
    # [P88] hCaptcha 检测 (需要 iframe 和 hcaptcha 同时存在)
    if "iframe" in h and "hcaptcha" in h and len(h) < 20000:
        logger.debug("检测到 hCaptcha iframe")
        return True
    
    # [P88] 移除了过于宽泛的指标如 "please wait", "ray id:" 等
    # 这些在正常页面中也可能出现
    
    return False


def clear_invalid_cookies_for_domain(url: str) -> None:
    """
    清理指定 URL 域名的无效 CF cookies
    
    在检测到 CF 验证时调用，仅清理该域名的 cookie
    其他域名的有效 cookie 保持不变
    """
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    
    # 获取主域名 (例如 www.sciencedirect.com -> .sciencedirect.com)
    parts = host.split(".")
    if len(parts) >= 2:
        domain = "." + ".".join(parts[-2:])
    else:
        domain = "." + host
    
    # 清理该域名的 cookies
    if CF_MANAGER.clear_domain(domain):
        logger.info(f"已清理域名 {domain} 的无效 CF cookies")
    
    # 也尝试清理完整主机名
    full_domain = "." + host
    if full_domain != domain:
        CF_MANAGER.clear_domain(full_domain)


def handle_cloudflare(page, notifier, headless: bool, timeout: int = 300) -> bool:
    """
    处理 Cloudflare 验证
    
    Args:
        page: Playwright 页面对象
        notifier: 通知回调
        headless: 是否为无头模式
        timeout: 超时时间（秒）
    
    Returns:
        bool: 是否通过验证
    """
    import time
    
    current_url = page.url
    
    # headless 模式下无法手动通过验证
    if headless:
        notifier.notify("⚠️ 检测到 Cloudflare 验证，headless 模式无法自动通过")
        # 清理该域名的无效 cookie
        clear_invalid_cookies_for_domain(current_url)
        return False
    
    notifier.notify("⚠️ 检测到 Cloudflare 验证，请在浏览器中完成验证...")
    
    start_time = time.time()
    
    while time.time() - start_time < timeout:
        try:
            html = page.content()
            if not is_cloudflare_challenge(current_url, html):
                notifier.notify("✅ Cloudflare 验证通过")
                
                # 保存通过验证后的 cookies
                cookies = page.context.cookies()
                imported = CF_MANAGER.import_from_browser(cookies)
                if imported > 0:
                    logger.info(f"已保存 {imported} 个 CF cookies")
                
                return True
            
            time.sleep(2)
        except Exception as e:
            logger.error(f"检查 CF 状态失败: {e}")
            time.sleep(2)
    
    notifier.notify("❌ Cloudflare 验证超时")
    # 清理无效 cookie
    clear_invalid_cookies_for_domain(current_url)
    return False
