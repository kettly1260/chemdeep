import re
import time
import logging
from pathlib import Path
from typing import Any, Callable
from config.settings import settings

logger = logging.getLogger("scholar_search")


class ScholarSearcher:
    """
    Google Scholar 搜索
    使用 Edge 浏览器复用已登录的 session，避免验证问题
    """

    def __init__(self, notify_callback: Callable[[str], None] | None = None):
        self.notify = notify_callback or (lambda x: print(x))
        self.profile_dir = settings.PROFILE_DIR
        self.library_dir = settings.LIBRARY_DIR
        self.results_dir = self.library_dir / "scholar_results"
        self.results_dir.mkdir(parents=True, exist_ok=True)

    def search(
        self, query: str, max_results: int = 50, headless: bool = False
    ) -> dict[str, Any]:
        """
        执行 Google Scholar 搜索

        返回:
            {
                "success": bool,
                "papers": [{"title": str, "doi": str, "authors": str, "year": str, "url": str}],
                "count": int,
                "error": str | None
            }
        """
        try:
            from playwright.sync_api import (
                sync_playwright,
                TimeoutError as PlaywrightTimeout,
            )
        except ImportError:
            return {
                "success": False,
                "error": "Playwright 未安装",
                "papers": [],
                "count": 0,
            }

        logger.info(f"开始 Google Scholar 搜索: {query[:100]}...")
        self.notify("🔍 正在启动浏览器访问 Google Scholar...")

        result = {"success": False, "papers": [], "count": 0, "error": None}

        with sync_playwright() as p:
            try:
                # 优先尝试连接真实 Edge 浏览器
                context = None
                use_real_browser = False

                if settings.USE_REAL_BROWSER:
                    try:
                        from core.browser.edge_launcher import (
                            is_real_browser_running,
                            connect_to_real_browser,
                        )

                        if is_real_browser_running():
                            context = connect_to_real_browser(p)
                            if context:
                                use_real_browser = True
                                self.notify("✅ 使用真实 Edge 浏览器")
                                logger.info("Scholar: 已连接到真实 Edge 浏览器")
                    except Exception as e:
                        logger.warning(f"连接真实浏览器失败: {e}")

                # 回退到 Playwright 模式
                if not context:
                    context = p.chromium.launch_persistent_context(
                        user_data_dir=str(self.profile_dir),
                        headless=headless,
                        accept_downloads=True,
                        channel=settings.BROWSER_CHANNEL,
                        args=[
                            "--disable-blink-features=AutomationControlled",
                            "--disable-automation",
                        ],
                    )

                page = context.new_page()
                page.set_viewport_size({"width": 1920, "height": 1080})

                # 访问 Google Scholar
                self.notify("📡 正在访问 Google Scholar...")

                # 使用编码后的查询
                from urllib.parse import quote

                search_url = (
                    f"https://scholar.google.com/scholar?q={quote(query)}&hl=en"
                )
                page.goto(search_url, wait_until="domcontentloaded", timeout=60000)

                time.sleep(3)

                # 检查是否遇到验证码
                if self._is_captcha(page):
                    self.notify("⚠️ 检测到 Google 验证码，请在浏览器中手动完成...")
                    if headless:
                        result["error"] = "验证码需要 headless=0"
                        return result

                    if not self._wait_for_captcha(page, timeout=300):
                        result["error"] = "验证码超时"
                        return result
                    self.notify("✅ 验证码通过")

                # 解析搜索结果
                papers = []
                pages_fetched = 0
                max_pages = (max_results // 10) + 1

                while len(papers) < max_results and pages_fetched < max_pages:
                    self.notify(f"📄 正在解析第 {pages_fetched + 1} 页...")

                    page_papers = self._parse_results(page)
                    papers.extend(page_papers)

                    pages_fetched += 1

                    if len(papers) >= max_results:
                        break

                    # 尝试翻页
                    if not self._go_next_page(page):
                        break

                    # 限速
                    time.sleep(settings.GOOGLE_SCHOLAR_DELAY)

                papers = papers[:max_results]
                result["success"] = True
                result["papers"] = papers
                result["count"] = len(papers)

                self.notify(f"✅ 找到 {len(papers)} 篇论文")

                # 保存结果
                self._save_results(query, papers)

                # 关闭（真实浏览器时只关闭页面，不关闭 context）
                try:
                    page.close()
                except Exception:
                    pass

                if not use_real_browser:
                    try:
                        context.close()
                    except Exception:
                        pass

            except PlaywrightTimeout as e:
                logger.error(f"Scholar 搜索超时: {e}")
                result["error"] = f"操作超时: {e}"
            except Exception as e:
                logger.error(f"Scholar 搜索失败: {e}", exc_info=True)
                result["error"] = str(e)

        return result

    def _is_captcha(self, page) -> bool:
        """检测是否遇到验证码"""
        try:
            html = page.content().lower()
            url = page.url.lower()

            if "sorry" in url or "captcha" in url:
                return True

            # 扩充验证码关键词
            captcha_indicators = [
                "unusual traffic",
                "captcha",
                "robot",
                "verify you're a human",
                "prove you are human",
                "recaptcha",
                "sending automated queries",
                "we're sorry",
                "computer or network may be sending",
            ]

            if any(x in html for x in captcha_indicators):
                return True

            # 检查 Title
            try:
                title = page.title().lower()
                if "sorry" in title or "captcha" in title:
                    return True
            except:
                pass

            # 检测 iframe
            if page.locator('iframe[src*="recaptcha"]').count() > 0:
                return True

            return False
        except Exception:
            return False

    def _wait_for_captcha(self, page, timeout: int = 300) -> bool:
        """等待验证码完成"""
        logger.info("检测到验证码，等待用户手动处理...")

        # 尝试将窗口前置
        try:
            # 获取 browser 对象
            browser = page.context.browser
            if browser:
                # 这种方法在 Playwright 中不一定有效，但值得一试
                pass

            # 注入提示按钮
            self._inject_verification_button(page)

        except Exception as e:
            logger.warning(f"注入验证按钮失败: {e}")

        deadline = time.time() + timeout

        while time.time() < deadline:
            time.sleep(2)

            # 检查是否点击了"验证完成"按钮
            try:
                is_clicked = page.evaluate("window.verificationButtonClicked === true")
                if is_clicked:
                    self.notify("✅ 用户点击验证完成")
                    return True
            except Exception:
                pass

            # 检查页面是否正常
            if not self._is_captcha(page) and "scholar.google" in page.url:
                try:
                    # 再次检查是否有结果
                    if page.locator(".gs_r").count() > 0:
                        return True
                except:
                    pass

        return False

    def _inject_verification_button(self, page):
        """在页面注入验证完成按钮"""
        script = """
        (function() {
            if (document.getElementById('verify-complete-btn')) return;
            
            const btn = document.createElement('button');
            btn.id = 'verify-complete-btn';
            btn.innerHTML = '✅ 已完成验证，继续搜索';
            btn.style.cssText = `
                position: fixed;
                bottom: 20px;
                right: 20px;
                z-index: 99999;
                padding: 15px 30px;
                background: #4A90E2;
                color: white;
                border: none;
                border-radius: 8px;
                font-size: 16px;
                font-weight: bold;
                cursor: pointer;
                box-shadow: 0 4px 12px rgba(0,0,0,0.3);
            `;
            
            btn.onclick = function() {
                this.innerHTML = '⏳ 处理中...';
                this.style.background = '#666';
                window.verificationButtonClicked = true;
            };
            
            document.body.appendChild(btn);
        })();
        """
        page.evaluate(script)

    def _parse_results(self, page) -> list[dict[str, Any]]:
        """解析当前页面的搜索结果"""
        papers = []

        try:
            # Google Scholar 结果容器
            results = page.locator(".gs_r.gs_or.gs_scl").all()

            for result in results:
                try:
                    paper = {}

                    # 标题和链接
                    title_elem = result.locator(".gs_rt a").first
                    if title_elem.count() > 0:
                        paper["title"] = title_elem.inner_text().strip()
                        paper["url"] = title_elem.get_attribute("href") or ""
                    else:
                        # 无链接的标题
                        title_elem = result.locator(".gs_rt").first
                        paper["title"] = (
                            title_elem.inner_text().strip()
                            if title_elem.count() > 0
                            else ""
                        )
                        paper["url"] = ""

                    if not paper.get("title"):
                        continue

                    # 作者和来源信息
                    meta_elem = result.locator(".gs_a").first
                    if meta_elem.count() > 0:
                        meta_text = meta_elem.inner_text()
                        paper["authors"], paper["year"], paper["source"] = (
                            self._parse_meta(meta_text)
                        )
                    else:
                        paper["authors"] = ""
                        paper["year"] = ""
                        paper["source"] = ""

                    # 摘要
                    abstract_elem = result.locator(".gs_rs").first
                    if abstract_elem.count() > 0:
                        paper["abstract"] = abstract_elem.inner_text().strip()
                    else:
                        paper["abstract"] = ""

                    # 尝试提取 DOI
                    paper["doi"] = self._extract_doi(result)

                    papers.append(paper)

                except Exception as e:
                    logger.debug(f"解析单条结果失败: {e}")
                    continue

        except Exception as e:
            logger.error(f"解析结果页面失败: {e}")

        return papers

    def _parse_meta(self, meta_text: str) -> tuple[str, str, str]:
        """解析作者、年份、来源"""
        authors = ""
        year = ""
        source = ""

        try:
            # 格式通常是: "作者 - 来源, 年份 - 出版商"
            parts = meta_text.split(" - ")

            if len(parts) >= 1:
                authors = parts[0].strip()

            if len(parts) >= 2:
                # 提取年份
                year_match = re.search(r"\b(19|20)\d{2}\b", parts[1])
                if year_match:
                    year = year_match.group()

                # 来源
                source = parts[1].strip()
        except Exception:
            pass

        return authors, year, source

    def _extract_doi(self, result) -> str:
        """尝试从结果中提取 DOI"""
        try:
            # 检查链接中是否包含 DOI
            links = result.locator("a").all()
            for link in links:
                href = link.get_attribute("href") or ""

                # 直接 DOI 链接
                doi_match = re.search(r"doi\.org/(10\.\d+/[^\s&?]+)", href)
                if doi_match:
                    return doi_match.group(1)

                # DOI 在 URL 参数中
                doi_match = re.search(r"doi=(10\.\d+[^&\s]+)", href)
                if doi_match:
                    return doi_match.group(1)

            # 检查文本中是否包含 DOI
            text = result.inner_text()
            doi_match = re.search(r"\b(10\.\d+/[^\s]+)\b", text)
            if doi_match:
                return doi_match.group(1)

        except Exception:
            pass

        return ""

    def _go_next_page(self, page) -> bool:
        """翻到下一页"""
        try:
            next_btn = (
                page.locator('a:has-text("Next")')
                .or_(page.locator(".gs_ico_nav_next"))
                .first
            )

            if next_btn.count() > 0 and next_btn.is_visible():
                next_btn.click()
                time.sleep(3)
                return True
        except Exception as e:
            logger.debug(f"翻页失败: {e}")

        return False

    def _save_results(self, query: str, papers: list[dict]) -> Path:
        """保存搜索结果为文件"""
        import json

        timestamp = int(time.time())
        safe_query = re.sub(r"[^\w\-]", "_", query)[:50]

        # 保存 JSON
        json_path = self.results_dir / f"scholar_{safe_query}_{timestamp}.json"
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(
                {"query": query, "count": len(papers), "papers": papers},
                f,
                ensure_ascii=False,
                indent=2,
            )

        # 保存为简单的 TSV（兼容 WoS 格式）
        tsv_path = self.results_dir / f"scholar_{safe_query}_{timestamp}.txt"
        with open(tsv_path, "w", encoding="utf-8") as f:
            f.write("TI\tDO\tAU\tPY\tSO\n")
            for p in papers:
                f.write(
                    f"{p.get('title', '')}\t{p.get('doi', '')}\t{p.get('authors', '')}\t{p.get('year', '')}\t{p.get('source', '')}\n"
                )

        logger.info(f"结果已保存: {json_path}")
        return tsv_path


class CrossRefSearcher:
    """
    CrossRef API 搜索（无需浏览器，纯 API）
    """

    def __init__(self, notify_callback: Callable[[str], None] | None = None):
        self.notify = notify_callback or (lambda x: print(x))
        self.base_url = "https://api.crossref.org/works"

    def search(self, query: str, max_results: int = 50) -> dict[str, Any]:
        """
        使用 CrossRef API 搜索
        """
        import httpx

        logger.info(f"开始 CrossRef 搜索: {query[:100]}...")
        self.notify("🔍 正在搜索 CrossRef...")

        result = {"success": False, "papers": [], "count": 0, "error": None}

        try:
            papers = []
            rows = 50  # 每页数量
            offset = 0

            while len(papers) < max_results:
                params = {
                    "query": query,
                    "rows": min(rows, max_results - len(papers)),
                    "offset": offset,
                }

                with httpx.Client(timeout=30) as client:
                    resp = client.get(self.base_url, params=params)
                    resp.raise_for_status()
                    data = resp.json()

                items = data.get("message", {}).get("items", [])

                if not items:
                    break

                for item in items:
                    paper = {
                        "title": " ".join(item.get("title", [""])),
                        "doi": item.get("DOI", ""),
                        "authors": ", ".join(
                            [
                                f"{a.get('given', '')} {a.get('family', '')}".strip()
                                for a in item.get("author", [])
                            ]
                        ),
                        "year": str(
                            item.get("published", {}).get("date-parts", [[""]])[0][0]
                            or ""
                        ),
                        "source": " ".join(item.get("container-title", [""])),
                        "url": item.get("URL", ""),
                    }
                    papers.append(paper)

                offset += rows

                if len(items) < rows:
                    break

            result["success"] = True
            result["papers"] = papers[:max_results]
            result["count"] = len(result["papers"])

            self.notify(f"✅ CrossRef 找到 {result['count']} 篇论文")

        except Exception as e:
            logger.error(f"CrossRef 搜索失败: {e}")
            result["error"] = str(e)

        return result


class OpenAlexSearcher:
    """
    OpenAlex API 搜索（免费开放的学术数据库）
    """

    def __init__(self, notify_callback: Callable[[str], None] | None = None):
        self.notify = notify_callback or (lambda x: print(x))
        self.base_url = "https://api.openalex.org/works"

    def search(self, query: str, max_results: int = 50) -> dict[str, Any]:
        """
        使用 OpenAlex API 搜索
        """
        import httpx

        logger.info(f"开始 OpenAlex 搜索: {query[:100]}...")
        self.notify("🔍 正在搜索 OpenAlex...")

        result = {"success": False, "papers": [], "count": 0, "error": None}

        try:
            papers = []
            per_page = 50
            page = 1

            while len(papers) < max_results:
                params = {
                    "search": query,
                    "per_page": min(per_page, max_results - len(papers)),
                    "page": page,
                }

                with httpx.Client(timeout=30) as client:
                    resp = client.get(self.base_url, params=params)
                    resp.raise_for_status()
                    data = resp.json()

                items = data.get("results", [])

                if not items:
                    break

                for item in items:
                    # 提取 DOI
                    doi = ""
                    if item.get("doi"):
                        doi = item["doi"].replace("https://doi.org/", "")

                    paper = {
                        "title": item.get("title", ""),
                        "doi": doi,
                        "authors": ", ".join(
                            [
                                a.get("author", {}).get("display_name", "")
                                for a in item.get("authorships", [])[:5]
                            ]
                        ),
                        "year": str(item.get("publication_year", "")),
                        "source": item.get("primary_location", {})
                        .get("source", {})
                        .get("display_name", ""),
                        "url": item.get("id", ""),
                        "cited_by_count": item.get("cited_by_count", 0),
                    }
                    papers.append(paper)

                page += 1

                if len(items) < per_page:
                    break

            result["success"] = True
            result["papers"] = papers[:max_results]
            result["count"] = len(result["papers"])

            self.notify(f"✅ OpenAlex 找到 {result['count']} 篇论文")

        except Exception as e:
            logger.error(f"OpenAlex 搜索失败: {e}")
            result["error"] = str(e)

        return result


class LanfanshuSearcher:
    """
    烂番薯学术搜索
    使用浏览器自动化访问烂番薯学术
    """

    def __init__(self, notify_callback: Callable[[str], None] | None = None):
        self.notify = notify_callback or (lambda x: print(x))
        self.profile_dir = settings.PROFILE_DIR
        self.library_dir = settings.LIBRARY_DIR
        self.results_dir = self.library_dir / "lanfanshu_results"
        self.results_dir.mkdir(parents=True, exist_ok=True)

    def search(
        self, query: str, max_results: int = 50, headless: bool = False
    ) -> dict[str, Any]:
        """
        执行烂番薯学术搜索

        返回:
            {
                "success": bool,
                "papers": [{"title": str, "doi": str, "authors": str, "year": str, "url": str}],
                "count": int,
                "error": str | None
            }
        """
        try:
            from playwright.sync_api import (
                sync_playwright,
                TimeoutError as PlaywrightTimeout,
            )
        except ImportError:
            return {
                "success": False,
                "error": "Playwright 未安装",
                "papers": [],
                "count": 0,
            }

        logger.info(f"开始烂番薯学术搜索: {query[:100]}...")
        self.notify("🔍 正在启动浏览器访问烂番薯学术...")

        result = {"success": False, "papers": [], "count": 0, "error": None}

        with sync_playwright() as p:
            try:
                # 优先尝试连接真实 Edge 浏览器
                context = None
                use_real_browser = False

                if settings.USE_REAL_BROWSER:
                    try:
                        from core.browser.edge_launcher import (
                            is_real_browser_running,
                            connect_to_real_browser,
                        )

                        if is_real_browser_running():
                            context = connect_to_real_browser(p)
                            if context:
                                use_real_browser = True
                                self.notify("✅ 使用真实 Edge 浏览器")
                                logger.info("Lanfanshu: 已连接到真实 Edge 浏览器")
                    except Exception as e:
                        logger.warning(f"连接真实浏览器失败: {e}")

                # 回退到 Playwright 模式
                if not context:
                    context = p.chromium.launch_persistent_context(
                        user_data_dir=str(self.profile_dir),
                        headless=headless,
                        accept_downloads=True,
                        channel=settings.BROWSER_CHANNEL,
                        args=[
                            "--disable-blink-features=AutomationControlled",
                            "--disable-automation",
                        ],
                    )

                page = context.new_page()
                page.set_viewport_size({"width": 1920, "height": 1080})

                # 访问烂番薯学术
                self.notify("📡 正在访问烂番薯学术...")

                # 使用编码后的查询
                from urllib.parse import quote

                search_url = f"https://xueshu.lanfanshu.cn/scholar?hl=zh-CN&as_sdt=0%2C5&q={quote(query)}&btnG="
                page.goto(search_url, wait_until="domcontentloaded", timeout=60000)

                time.sleep(3)

                # 检查是否遇到验证码
                if self._is_captcha(page):
                    self.notify("⚠️ 检测到验证码，请在浏览器中手动完成...")
                    if headless:
                        result["error"] = "验证码需要 headless=0"
                        return result

                    if not self._wait_for_captcha(page, timeout=300):
                        result["error"] = "验证码超时"
                        return result
                    self.notify("✅ 验证码通过")

                # 解析搜索结果
                papers = []
                pages_fetched = 0
                max_pages = (max_results // 10) + 1

                while len(papers) < max_results and pages_fetched < max_pages:
                    self.notify(f"📄 正在解析第 {pages_fetched + 1} 页...")

                    page_papers = self._parse_results(page)
                    papers.extend(page_papers)

                    pages_fetched += 1

                    if len(papers) >= max_results:
                        break

                    # 尝试翻页
                    if not self._go_next_page(page):
                        break

                    # 限速
                    time.sleep(settings.GOOGLE_SCHOLAR_DELAY)

                papers = papers[:max_results]
                result["success"] = True
                result["papers"] = papers
                result["count"] = len(papers)

                self.notify(f"✅ 找到 {len(papers)} 篇论文")

                # 保存结果
                self._save_results(query, papers)

                # 关闭（真实浏览器时只关闭页面，不关闭 context）
                try:
                    page.close()
                except Exception:
                    pass

                if not use_real_browser:
                    try:
                        context.close()
                    except Exception:
                        pass

            except PlaywrightTimeout as e:
                logger.error(f"烂番薯学术搜索超时: {e}")
                result["error"] = f"操作超时: {e}"
            except Exception as e:
                logger.error(f"烂番薯学术搜索失败: {e}", exc_info=True)
                result["error"] = str(e)

        return result

    def _is_captcha(self, page) -> bool:
        """检测是否遇到验证码"""
        try:
            html = page.content().lower()
            url = page.url.lower()

            if "sorry" in url or "captcha" in url:
                return True

            # 扩充验证码关键词
            captcha_indicators = [
                "unusual traffic",
                "captcha",
                "robot",
                "verify you're a human",
                "prove you are human",
                "recaptcha",
                "sending automated queries",
                "we're sorry",
                "computer or network may be sending",
                "请完成验证",
                "验证码",
            ]

            if any(x in html for x in captcha_indicators):
                return True

            # 检查 Title
            try:
                title = page.title().lower()
                if "sorry" in title or "captcha" in title:
                    return True
            except:
                pass

            # 检测 iframe
            if page.locator('iframe[src*="recaptcha"]').count() > 0:
                return True

            return False
        except Exception:
            return False

    def _wait_for_captcha(self, page, timeout: int = 300) -> bool:
        """等待验证码完成"""
        logger.info("检测到验证码，等待用户手动处理...")

        # 尝试将窗口前置
        try:
            # 注入提示按钮
            self._inject_verification_button(page)

        except Exception as e:
            logger.warning(f"注入验证按钮失败: {e}")

        deadline = time.time() + timeout

        while time.time() < deadline:
            time.sleep(2)

            # 检查是否点击了"验证完成"按钮
            try:
                is_clicked = page.evaluate("window.verificationButtonClicked === true")
                if is_clicked:
                    self.notify("✅ 用户点击验证完成")
                    return True
            except Exception:
                pass

            # 检查页面是否正常
            if not self._is_captcha(page) and "lanfanshu" in page.url:
                try:
                    # 再次检查是否有结果
                    if page.locator(".gs_r").count() > 0:
                        return True
                except:
                    pass

        return False

    def _inject_verification_button(self, page):
        """在页面注入验证完成按钮"""
        script = """
        (function() {
            if (document.getElementById('verify-complete-btn')) return;
            
            const btn = document.createElement('button');
            btn.id = 'verify-complete-btn';
            btn.innerHTML = '✅ 已完成验证，继续搜索';
            btn.style.cssText = `
                position: fixed;
                bottom: 20px;
                right: 20px;
                z-index: 99999;
                padding: 15px 30px;
                background: #4A90E2;
                color: white;
                border: none;
                border-radius: 8px;
                font-size: 16px;
                font-weight: bold;
                cursor: pointer;
                box-shadow: 0 4px 12px rgba(0,0,0,0.3);
            `;
            
            btn.onclick = function() {
                this.innerHTML = '⏳ 处理中...';
                this.style.background = '#666';
                window.verificationButtonClicked = true;
            };
            
            document.body.appendChild(btn);
        })();
        """
        page.evaluate(script)

    def _parse_results(self, page) -> list[dict[str, Any]]:
        """解析当前页面的搜索结果"""
        papers = []

        try:
            # 烂番薯学术使用与Google Scholar类似的HTML结构
            results = page.locator(".gs_r.gs_or.gs_scl").all()

            for result in results:
                try:
                    paper = {}

                    # 标题和链接
                    title_elem = result.locator(".gs_rt a").first
                    if title_elem.count() > 0:
                        paper["title"] = title_elem.inner_text().strip()
                        paper["url"] = title_elem.get_attribute("href") or ""
                    else:
                        # 无链接的标题
                        title_elem = result.locator(".gs_rt").first
                        paper["title"] = (
                            title_elem.inner_text().strip()
                            if title_elem.count() > 0
                            else ""
                        )
                        paper["url"] = ""

                    if not paper.get("title"):
                        continue

                    # 作者和来源信息
                    meta_elem = result.locator(".gs_a").first
                    if meta_elem.count() > 0:
                        meta_text = meta_elem.inner_text()
                        paper["authors"], paper["year"], paper["source"] = (
                            self._parse_meta(meta_text)
                        )
                    else:
                        paper["authors"] = ""
                        paper["year"] = ""
                        paper["source"] = ""

                    # 摘要
                    abstract_elem = result.locator(".gs_rs").first
                    if abstract_elem.count() > 0:
                        paper["abstract"] = abstract_elem.inner_text().strip()
                    else:
                        paper["abstract"] = ""

                    # 尝试提取 DOI
                    paper["doi"] = self._extract_doi(result)

                    # 被引次数
                    cited_elem = result.locator(
                        '.gs_fl a:has-text("被引用"), .gs_fl a:has-text("Cited by")'
                    ).first
                    if cited_elem.count() > 0:
                        cited_text = cited_elem.inner_text()
                        cited_match = re.search(r"(\d+)", cited_text)
                        if cited_match:
                            paper["cited"] = int(cited_match.group(1))

                    papers.append(paper)

                except Exception as e:
                    logger.debug(f"解析单条结果失败: {e}")
                    continue

        except Exception as e:
            logger.error(f"解析结果页面失败: {e}")

        return papers

    def _parse_meta(self, meta_text: str) -> tuple[str, str, str]:
        """解析作者、年份、来源"""
        authors = ""
        year = ""
        source = ""

        try:
            # 格式通常是: "作者 - 来源, 年份 - 出版商"
            parts = meta_text.split(" - ")

            if len(parts) >= 1:
                authors = parts[0].strip()

            if len(parts) >= 2:
                # 提取年份
                year_match = re.search(r"\b(19|20)\d{2}\b", parts[1])
                if year_match:
                    year = year_match.group()

                # 来源
                source = parts[1].strip()
        except Exception:
            pass

        return authors, year, source

    def _extract_doi(self, result) -> str:
        """尝试从结果中提取 DOI"""
        try:
            # 检查链接中是否包含 DOI
            links = result.locator("a").all()
            for link in links:
                href = link.get_attribute("href") or ""

                # 直接 DOI 链接
                doi_match = re.search(r"doi\.org/(10\.\d+/[^\s&?]+)", href)
                if doi_match:
                    return doi_match.group(1)

                # DOI 在 URL 参数中
                doi_match = re.search(r"doi=(10\.\d+[^&\s]+)", href)
                if doi_match:
                    return doi_match.group(1)

            # 检查文本中是否包含 DOI
            text = result.inner_text()
            doi_match = re.search(r"\b(10\.\d+/[^\s]+)\b", text)
            if doi_match:
                return doi_match.group(1)

        except Exception:
            pass

        return ""

    def _go_next_page(self, page) -> bool:
        """翻到下一页"""
        try:
            next_btn = (
                page.locator('a:has-text("下一页")')
                .or_(page.locator('a:has-text("Next")'))
                .or_(page.locator(".gs_ico_nav_next"))
                .first
            )

            if next_btn.count() > 0 and next_btn.is_visible():
                next_btn.click()
                time.sleep(3)
                return True
        except Exception as e:
            logger.debug(f"翻页失败: {e}")

        return False

    def _save_results(self, query: str, papers: list[dict]) -> Path:
        """保存搜索结果为文件"""
        import json

        timestamp = int(time.time())
        safe_query = re.sub(r"[^\w\-]", "_", query)[:50]

        # 保存 JSON
        json_path = self.results_dir / f"lanfanshu_{safe_query}_{timestamp}.json"
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(
                {"query": query, "count": len(papers), "papers": papers},
                f,
                ensure_ascii=False,
                indent=2,
            )

        # 保存为简单的 TSV（兼容 WoS 格式）
        tsv_path = self.results_dir / f"lanfanshu_{safe_query}_{timestamp}.txt"
        with open(tsv_path, "w", encoding="utf-8") as f:
            f.write("TI\tDO\tAU\tPY\tSO\n")
            for p in papers:
                f.write(
                    f"{p.get('title', '')}\t{p.get('doi', '')}\t{p.get('authors', '')}\t{p.get('year', '')}\t{p.get('source', '')}\n"
                )

        logger.info(f"结果已保存: {json_path}")
        return tsv_path


class UnifiedSearcher:
    """
    统一搜索接口，支持多个数据源
    """

    def __init__(self, notify_callback: Callable[[str], None] | None = None):
        self.notify = notify_callback or (lambda x: print(x))
        self.wos = None  # 延迟初始化
        self.scholar = None
        self.lanfanshu = None
        self.crossref = CrossRefSearcher(notify_callback)
        self.openalex = OpenAlexSearcher(notify_callback)

    def search(
        self,
        query: str,
        sources: list[str] | None = None,
        max_results: int = 50,
        headless: bool = False,
        parallel: bool = True,
    ) -> dict[str, Any]:
        """
        统一搜索接口，支持多源搜索并汇总

        sources: ["wos", "scholar", "crossref", "openalex", "lanfanshu"]
        parallel: 是否并行搜索（API源并行，浏览器源串行）
        """
        if sources is None:
            sources = ["openalex", "crossref", "lanfanshu"]  # 默认包含烂番薯

        results = {
            "success": False,
            "papers": [],
            "count": 0,
            "sources_used": [],
            "sources_stats": {},  # 每个源的结果数量
            "errors": {},
        }

        all_papers = []
        seen_dois = set()
        seen_titles = set()  # 用标题去重（部分文献无DOI）

        # 分类搜索源：API源可并行，浏览器源需串行
        api_sources = [s for s in sources if s in ("crossref", "openalex")]
        browser_sources = [s for s in sources if s in ("wos", "scholar", "lanfanshu")]

        # 存储各源结果
        source_results = {}

        # 并行搜索 API 源
        if parallel and api_sources:
            import concurrent.futures

            self.notify(f"📚 并行搜索: {', '.join(api_sources)}")

            def search_api_source(source):
                try:
                    if source == "crossref":
                        return source, self.crossref.search(query, max_results)
                    elif source == "openalex":
                        return source, self.openalex.search(query, max_results)
                except Exception as e:
                    return source, {"success": False, "error": str(e), "papers": []}

            with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
                futures = {
                    executor.submit(search_api_source, s): s for s in api_sources
                }
                for future in concurrent.futures.as_completed(futures):
                    source, result = future.result()
                    source_results[source] = result
        else:
            # 串行搜索 API 源
            for source in api_sources:
                if source == "crossref":
                    source_results[source] = self.crossref.search(query, max_results)
                elif source == "openalex":
                    source_results[source] = self.openalex.search(query, max_results)

        # 串行搜索浏览器源（需要真实浏览器）
        for source in browser_sources:
            self.notify(f"📚 正在搜索 {source.upper()}...")

            try:
                if source == "wos":
                    if self.wos is None:
                        from core.wos_search import WoSSearcher

                        self.wos = WoSSearcher(self.notify)
                    source_results[source] = self.wos.search_and_export(
                        query, max_results, headless=headless
                    )

                elif source == "scholar":
                    if self.scholar is None:
                        self.scholar = ScholarSearcher(self.notify)
                    source_results[source] = self.scholar.search(
                        query, max_results, headless=headless
                    )

                elif source == "lanfanshu":
                    if self.lanfanshu is None:
                        self.lanfanshu = LanfanshuSearcher(self.notify)
                    source_results[source] = self.lanfanshu.search(
                        query, max_results, headless=headless
                    )

            except Exception as e:
                logger.error(f"{source} 搜索失败: {e}")
                source_results[source] = {
                    "success": False,
                    "error": str(e),
                    "papers": [],
                }

        # 汇总所有结果
        for source, result in source_results.items():
            if result.get("success"):
                papers = result.get("papers", [])
                results["sources_used"].append(source)
                results["sources_stats"][source] = len(papers)

                for p in papers:
                    # 双重去重：DOI + 标题
                    doi = (p.get("doi") or "").lower().strip()
                    title = (p.get("title") or "").lower().strip()

                    if doi and doi in seen_dois:
                        continue
                    if title and title in seen_titles:
                        continue

                    if doi:
                        seen_dois.add(doi)
                    if title:
                        seen_titles.add(title)

                    # 标记来源
                    p["_source"] = source
                    all_papers.append(p)

            elif result.get("error"):
                results["errors"][source] = result["error"]

        # 按被引次数排序（如果有）
        all_papers.sort(key=lambda p: p.get("cited", 0) or 0, reverse=True)

        # 去重并限制数量
        results["papers"] = all_papers[:max_results]
        results["count"] = len(results["papers"])
        results["success"] = len(results["papers"]) > 0 or "wos_file" in results

        # 生成汇总报告
        summary = self._generate_summary(results)
        self.notify(summary)

        return results

    def _generate_summary(self, results: dict) -> str:
        """生成搜索汇总报告"""
        lines = [
            "📊 搜索汇总报告",
            "=" * 40,
            f"📄 共找到 {results['count']} 篇论文",
            "",
            "📈 各源统计:",
        ]

        for source, count in results.get("sources_stats", {}).items():
            lines.append(f"  • {source}: {count} 篇")

        if results.get("errors"):
            lines.append("")
            lines.append("⚠️ 错误信息:")
            for source, error in results["errors"].items():
                lines.append(f"  • {source}: {error}")

        lines.append("")
        lines.append(f"✅ 成功来源: {', '.join(results.get('sources_used', []))}")

        return "\n".join(lines)

    def search_all(
        self,
        query: str,
        max_results: int = 50,
        headless: bool = False,
    ) -> dict[str, Any]:
        """
        搜索所有可用数据源并汇总结果

        自动搜索: openalex, crossref, lanfanshu
        """
        return self.search(
            query,
            sources=["openalex", "crossref", "lanfanshu"],
            max_results=max_results,
            headless=headless,
            parallel=True,
        )

    def save_results(
        self, results: dict, output_dir: Path, filename: str = None
    ) -> dict[str, Path]:
        """
        保存搜索结果到文件

        返回保存的文件路径
        """
        import json
        from datetime import datetime

        output_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_query = re.sub(r"[^\w\-]", "_", results.get("query", "search"))[:30]

        if filename is None:
            filename = f"{safe_query}_{timestamp}"

        saved_files = {}

        # 保存 JSON 格式
        json_path = output_dir / f"{filename}.json"
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        saved_files["json"] = json_path

        # 保存 TSV 格式 (兼容 WoS)
        tsv_path = output_dir / f"{filename}.txt"
        with open(tsv_path, "w", encoding="utf-8") as f:
            f.write("TI\tDO\tAU\tPY\tSO\tSRC\n")
            for p in results.get("papers", []):
                title = (p.get("title") or "").replace("\t", " ").replace("\n", " ")
                doi = p.get("doi") or ""
                authors = (p.get("authors") or "").replace("\t", " ")
                year = p.get("year") or ""
                source = (p.get("source") or "").replace("\t", " ")
                src = p.get("_source", "")
                f.write(f"{title}\t{doi}\t{authors}\t{year}\t{source}\t{src}\n")
        saved_files["tsv"] = tsv_path

        logger.info(f"结果已保存到: {output_dir}")
        return saved_files

    def save_as_wos_format(self, papers: list[dict], output_path: Path) -> Path:
        """将搜索结果保存为 WoS 兼容格式"""
        with open(output_path, "w", encoding="utf-8") as f:
            # WoS Tab-delimited 格式头
            f.write("TI\tDO\tAU\tPY\tSO\n")
            for p in papers:
                title = (p.get("title") or "").replace("\t", " ").replace("\n", " ")
                doi = p.get("doi") or ""
                authors = (p.get("authors") or "").replace("\t", " ")
                year = p.get("year") or ""
                source = (p.get("source") or "").replace("\t", " ")
                f.write(f"{title}\t{doi}\t{authors}\t{year}\t{source}\n")

        return output_path
