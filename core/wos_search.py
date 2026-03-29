import re
import time
import json
import logging
from pathlib import Path
from typing import Any, Callable
from config.settings import settings

logger = logging.getLogger('wos_search')


class WoSSearcher:
    """
    Web of Science 自动搜索和导出
    使用真实 Edge profile 避免 CF 检测
    """
    
    def __init__(self, notify_callback: Callable[[str], None] | None = None):
        self.notify = notify_callback or (lambda x: print(x))
        self.profile_dir = settings.PROFILE_DIR
        self.library_dir = settings.LIBRARY_DIR
        self.download_dir = self.library_dir / "downloads"
        self.download_dir.mkdir(parents=True, exist_ok=True)
        
        # CF Cookie 文件路径
        self.cf_cookie_file = Path("config/cf_cookies.json")
    
    def set_cf_cookies(self, cookies: list[dict]) -> None:
        """保存 CF cookies"""
        self.cf_cookie_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.cf_cookie_file, "w", encoding="utf-8") as f:
            json.dump(cookies, f, indent=2)
        logger.info(f"CF cookies 已保存: {len(cookies)} 个")
    
    def load_cf_cookies(self) -> list[dict]:
        """加载 CF cookies"""
        if not self.cf_cookie_file.exists():
            return []
        try:
            with open(self.cf_cookie_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"加载 CF cookies 失败: {e}")
            return []
    
    def search_and_export(
        self,
        boolean_query: str,
        max_results: int = 50,
        headless: bool = False
    ) -> dict[str, Any]:
        """自动执行 WoS 搜索并导出结果"""
        try:
            from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
        except ImportError:
            return {"success": False, "error": "Playwright 未安装", "file_path": None, "count": 0}
        
        logger.info(f"开始 WoS 搜索: {boolean_query[:100]}...")
        self.notify("🔍 正在启动浏览器...")
        
        result = {"success": False, "file_path": None, "count": 0, "error": None}
        
        with sync_playwright() as p:
            try:
                # 使用真实 Edge profile，最大程度模拟真实浏览器
                context = self._create_browser_context(p, headless)
                
                # 注入 CF cookies
                cf_cookies = self.load_cf_cookies()
                if cf_cookies:
                    self.notify(f"📎 注入 {len(cf_cookies)} 个 CF cookies...")
                    try:
                        context.add_cookies(cf_cookies)
                    except Exception as e:
                        logger.warning(f"注入 cookies 失败: {e}")
                
                page = context.new_page()
                
                # 设置更真实的 viewport 和 headers
                page.set_viewport_size({"width": 1920, "height": 1080})
                
                # 访问 WoS
                self.notify("📡 正在访问 Web of Science...")
                
                try:
                    page.goto("https://www.webofscience.com/wos/woscc/basic-search", 
                              wait_until="domcontentloaded", timeout=60000)
                except Exception as e:
                    logger.warning(f"首次访问超时: {e}")
                
                time.sleep(5)
                
                # 检查 CF 挑战
                if self._is_cloudflare_challenge(page):
                    self.notify("⚠️ 检测到 Cloudflare 验证...")
                    
                    if headless:
                        result["error"] = "Cloudflare 验证需要 headless=0，请先运行 /login"
                        context.close()
                        return result
                    
                    self.notify("👆 请在浏览器窗口中手动完成验证...")
                    
                    if self._wait_for_cloudflare(page, timeout=300):
                        self.notify("✅ Cloudflare 验证通过")
                        # 保存新的 cookies
                        self._save_cookies_after_cf(context)
                    else:
                        result["error"] = "Cloudflare 验证超时"
                        context.close()
                        return result
                
                # 检查登录状态
                if self._needs_login(page):
                    self.notify("⚠️ 需要登录 WoS...")
                    
                    if headless:
                        result["error"] = "需要登录，请先运行 /login"
                        context.close()
                        return result
                    
                    self.notify("👆 请在浏览器窗口中完成登录...")
                    
                    if not self._wait_for_login(page, timeout=300):
                        result["error"] = "登录超时"
                        context.close()
                        return result
                    
                    self.notify("✅ 登录成功")
                
                # 执行搜索
                self.notify(f"🔎 正在执行搜索...")
                
                if not self._perform_search(page, boolean_query):
                    result["error"] = "搜索执行失败，请检查检索式格式"
                    context.close()
                    return result
                
                time.sleep(5)
                
                # 获取结果数量
                result_count = self._get_result_count(page)
                self.notify(f"📊 找到 {result_count} 条结果")
                result["count"] = result_count
                
                if result_count == 0:
                    result["error"] = "未找到结果"
                    context.close()
                    return result
                
                # 导出结果
                export_count = min(max_results, result_count)
                self.notify(f"📥 正在导出前 {export_count} 条结果...")
                
                export_path = self._export_results(page, export_count)
                
                if export_path and export_path.exists():
                    result["success"] = True
                    result["file_path"] = str(export_path)
                    self.notify(f"✅ 导出成功: {export_path.name}")
                else:
                    result["error"] = "导出失败"
                
                context.close()
                
            except PlaywrightTimeout as e:
                logger.error(f"WoS 搜索超时: {e}")
                result["error"] = f"操作超时: {e}"
            except Exception as e:
                logger.error(f"WoS 搜索失败: {e}", exc_info=True)
                result["error"] = str(e)
        
        return result
    
    def _create_browser_context(self, p, headless: bool):
        """创建浏览器上下文，优先使用真实 Edge 浏览器"""
        
        # 优先尝试连接真实 Edge 浏览器（通过 CDP）
        if settings.USE_REAL_BROWSER:
            try:
                from core.browser.edge_launcher import is_real_browser_running, connect_to_real_browser
                if is_real_browser_running():
                    context = connect_to_real_browser(p)
                    if context:
                        logger.info("WoS: 已连接到真实 Edge 浏览器")
                        self.notify("✅ 使用真实 Edge 浏览器")
                        return context
                    else:
                        logger.warning("连接真实浏览器失败，回退到 Playwright")
            except Exception as e:
                logger.warning(f"尝试连接真实浏览器失败: {e}")
        
        # 回退到 Playwright 持久化上下文
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        
        args = [
            "--disable-blink-features=AutomationControlled",
            "--disable-automation",
            "--disable-infobars",
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-web-security",
            "--allow-running-insecure-content",
            "--disable-features=IsolateOrigins,site-per-process",
        ]
        
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(self.profile_dir),
            headless=headless,
            accept_downloads=True,
            channel=settings.BROWSER_CHANNEL,
            downloads_path=str(self.download_dir),
            args=args,
            ignore_default_args=["--enable-automation"],
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0",
            viewport={"width": 1920, "height": 1080},
            locale="en-US",
            timezone_id="Asia/Shanghai",
        )
        
        # 注入脚本隐藏自动化标识
        context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
            Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en', 'zh-CN']});
            window.chrome = {runtime: {}};
        """)
        
        return context
    
    def _save_cookies_after_cf(self, context) -> None:
        """CF 验证通过后保存 cookies"""
        try:
            cookies = context.cookies()
            cf_cookies = [c for c in cookies if 'cf' in c.get('name', '').lower() or 
                          'cloudflare' in c.get('domain', '').lower() or
                          c.get('name') == '__cf_bm' or
                          c.get('name') == 'cf_clearance']
            if cf_cookies:
                self.set_cf_cookies(cf_cookies)
                logger.info(f"已保存 {len(cf_cookies)} 个 CF cookies")
        except Exception as e:
            logger.error(f"保存 cookies 失败: {e}")
    
    def _is_cloudflare_challenge(self, page) -> bool:
        """检测是否遇到 Cloudflare 验证"""
        try:
            html = page.content().lower()
            url = page.url.lower()
            
            if "cdn-cgi" in url or "challenge-platform" in url:
                return True
            
            cf_indicators = [
                "cloudflare",
                "cf-chl",
                "turnstile",
                "just a moment",
                "checking your browser",
                "please wait",
                "ray id",
            ]
            
            return any(indicator in html for indicator in cf_indicators)
        except Exception:
            return False
    
    def _wait_for_cloudflare(self, page, timeout: int = 300) -> bool:
        """等待 Cloudflare 验证完成"""
        deadline = time.time() + timeout
        check_interval = 2
        
        while time.time() < deadline:
            time.sleep(check_interval)
            
            try:
                if not self._is_cloudflare_challenge(page):
                    return True
            except Exception:
                continue
        
        return False
    
    def _needs_login(self, page) -> bool:
        """检测是否需要登录"""
        try:
            html = page.content().lower()
            url = page.url.lower()
            
            if any(x in url for x in ["login", "signin", "authenticate", "shibboleth"]):
                return True
            
            if "sign in" in html and "institutional" in html:
                return True
            
            return False
        except Exception:
            return False
    
    def _wait_for_login(self, page, timeout: int = 300) -> bool:
        """等待用户完成登录"""
        deadline = time.time() + timeout
        
        while time.time() < deadline:
            time.sleep(3)
            
            try:
                url = page.url.lower()
                if "wos/woscc" in url and not self._needs_login(page):
                    return True
            except Exception:
                continue
        
        return False
    
    def _perform_search(self, page, boolean_query: str) -> bool:
        """执行搜索"""
        try:
            # 等待页面加载
            time.sleep(3)
            
            # 尝试切换到高级搜索
            try:
                advanced_selectors = [
                    "text=Advanced Search",
                    "text=高级搜索",
                    'a[href*="advanced"]',
                    'button:has-text("Advanced")',
                ]
                for selector in advanced_selectors:
                    try:
                        elem = page.locator(selector).first
                        if elem.is_visible(timeout=2000):
                            elem.click()
                            time.sleep(2)
                            break
                    except Exception:
                        continue
            except Exception:
                pass
            
            # 查找搜索输入框
            search_selectors = [
                'textarea[id*="advancedSearch"]',
                'textarea[name*="value"]',
                'textarea.search-input',
                '#advancedSearchInputArea textarea',
                'textarea[placeholder*="search"]',
                'textarea',
            ]
            
            search_input = None
            for selector in search_selectors:
                try:
                    elem = page.locator(selector).first
                    if elem.is_visible(timeout=2000):
                        search_input = elem
                        logger.info(f"找到搜索框: {selector}")
                        break
                except Exception:
                    continue
            
            if not search_input:
                logger.error("找不到搜索输入框")
                self.notify("❌ 找不到搜索输入框，请尝试手动搜索")
                return False
            
            # 清空并输入检索式
            search_input.click()
            time.sleep(0.5)
            search_input.fill("")
            time.sleep(0.3)
            
            # 分段输入（更像人类）
            for i in range(0, len(boolean_query), 50):
                chunk = boolean_query[i:i+50]
                search_input.type(chunk, delay=10)
                time.sleep(0.1)
            
            time.sleep(1)
            
            # 点击搜索按钮
            search_button_selectors = [
                'button:has-text("Search")',
                'button:has-text("搜索")',
                'button[type="submit"]',
                '.search-button',
                '#searchButton',
                'button[aria-label*="search"]',
            ]
            
            for selector in search_button_selectors:
                try:
                    btn = page.locator(selector).first
                    if btn.is_visible(timeout=2000):
                        btn.click()
                        logger.info(f"点击搜索按钮: {selector}")
                        time.sleep(3)
                        return True
                except Exception:
                    continue
            
            # 尝试按 Enter
            search_input.press("Enter")
            time.sleep(3)
            return True
            
        except Exception as e:
            logger.error(f"执行搜索失败: {e}", exc_info=True)
            return False
    
    def _get_result_count(self, page) -> int:
        """获取搜索结果数量"""
        try:
            time.sleep(3)
            html = page.content()
            
            patterns = [
                r'(\d[\d,]*)\s*(?:条)?结果',
                r'(\d[\d,]*)\s*results?',
                r'of\s*(\d[\d,]*)',
                r'共\s*(\d[\d,]*)',
                r'Results:\s*(\d[\d,]*)',
            ]
            
            for pattern in patterns:
                match = re.search(pattern, html, re.I)
                if match:
                    count_str = match.group(1).replace(",", "")
                    return int(count_str)
            
            return 0
        except Exception as e:
            logger.error(f"获取结果数量失败: {e}")
            return 0
    
    def _export_results(self, page, max_results: int) -> Path | None:
        """导出搜索结果"""
        try:
            time.sleep(2)
            
            # 点击导出按钮
            export_selectors = [
                'button:has-text("Export")',
                'button:has-text("导出")',
                '[data-ta="export-menu-trigger"]',
                'button[aria-label*="export"]',
                '.export-button',
            ]
            
            export_btn = None
            for selector in export_selectors:
                try:
                    btn = page.locator(selector).first
                    if btn.is_visible(timeout=3000):
                        export_btn = btn
                        break
                except Exception:
                    continue
            
            if not export_btn:
                logger.error("找不到导出按钮")
                self.notify("❌ 找不到导出按钮")
                return None
            
            export_btn.click()
            time.sleep(2)
            
            # 选择导出格式
            format_selectors = [
                'text=Tab delimited',
                'text=制表符分隔',
                'label:has-text("Tab")',
                '[value="tabWinUnicode"]',
            ]
            
            for selector in format_selectors:
                try:
                    opt = page.locator(selector).first
                    if opt.is_visible(timeout=2000):
                        opt.click()
                        break
                except Exception:
                    continue
            
            time.sleep(1)
            
            # 设置导出数量
            try:
                range_inputs = [
                    'input[name="markTo"]',
                    'input[placeholder*="to"]',
                    'input[id*="count"]',
                ]
                for selector in range_inputs:
                    try:
                        inp = page.locator(selector).first
                        if inp.is_visible(timeout=2000):
                            inp.fill(str(max_results))
                            break
                    except Exception:
                        continue
            except Exception:
                pass
            
            time.sleep(1)
            
            # 点击确认导出
            confirm_selectors = [
                'button:has-text("Export")',
                'button:has-text("导出")',
                'button:has-text("OK")',
                'button:has-text("确定")',
            ]
            
            # 等待下载
            with page.expect_download(timeout=120000) as download_info:
                for selector in confirm_selectors:
                    try:
                        btn = page.locator(selector).last
                        if btn.is_visible(timeout=2000):
                            btn.click()
                            break
                    except Exception:
                        continue
                
                download = download_info.value
            
            # 保存文件
            timestamp = int(time.time())
            save_path = self.download_dir / f"wos_export_{timestamp}.txt"
            download.save_as(save_path)
            
            logger.info(f"文件已保存: {save_path}")
            return save_path
            
        except Exception as e:
            logger.error(f"导出失败: {e}", exc_info=True)
            self.notify(f"❌ 导出失败: {e}")
            return None
    
    def login_interactive(self) -> bool:
        """交互式登录"""
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            self.notify("❌ Playwright 未安装")
            return False
        
        self.notify("🌐 正在打开浏览器...")
        self.notify("请完成以下操作:")
        self.notify("1. 完成 Cloudflare 验证（如果出现）")
        self.notify("2. 完成机构登录")
        self.notify("3. 确认可以正常访问 WoS 后关闭浏览器")
        
        with sync_playwright() as p:
            context = self._create_browser_context(p, headless=False)
            page = context.new_page()
            
            page.goto("https://www.webofscience.com/wos/woscc/basic-search", 
                      wait_until="domcontentloaded", timeout=60000)
            
            self.notify("⏳ 等待操作完成...")
            
            try:
                # 等待用户操作
                while True:
                    time.sleep(5)
                    try:
                        # 检查浏览器是否还在运行
                        _ = page.url
                    except Exception:
                        break
            except Exception:
                pass
            
            # 保存 cookies
            try:
                self._save_cookies_after_cf(context)
                context.close()
            except Exception:
                pass
        
        self.notify("✅ 登录会话已保存")
        return True