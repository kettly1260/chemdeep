import json
import logging
import time
from pathlib import Path
from typing import Any, Callable
from config.settings import settings

logger = logging.getLogger('cf_manager')


class CFCookieManager:
    """
    Cloudflare Cookie 管理器
    支持多个域名的 CF cookie 管理
    """
    
    # 常见出版商域名
    PUBLISHER_DOMAINS = [
        ".sciencedirect.com",
        ".elsevier.com",
        ".wiley.com",
        ".onlinelibrary.wiley.com",
        ".springer.com",
        ".nature.com",
        ".acs.org",
        ".pubs.acs.org",
        ".rsc.org",
        ".pubs.rsc.org",
        ".tandfonline.com",
        ".webofscience.com",
        ".clarivate.com",
        ".mdpi.com",
        ".frontiersin.org",
        ".cell.com",
        ".science.org",
        ".pnas.org",
    ]
    
    def __init__(self):
        self.cookie_file = Path("config/cf_cookies.json")
        self.cookie_file.parent.mkdir(parents=True, exist_ok=True)
        self._cookies: dict[str, list[dict]] = {}
        self._load()
    
    def _load(self) -> None:
        """加载已保存的 cookies"""
        if self.cookie_file.exists():
            try:
                with open(self.cookie_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                
                # 兼容旧格式（列表）
                if isinstance(data, list):
                    # 旧格式：列表，需要转换为字典
                    self._cookies = {}
                    for cookie in data:
                        domain = cookie.get("domain", "")
                        if domain:
                            if domain not in self._cookies:
                                self._cookies[domain] = []
                            self._cookies[domain].append(cookie)
                    logger.info(f"已迁移旧格式 cookies: {len(data)} 个")
                    self._save()  # 保存为新格式
                elif isinstance(data, dict):
                    self._cookies = data
                else:
                    self._cookies = {}
                
                logger.info(f"已加载 {len(self._cookies)} 个域名的 cookies")
            except Exception as e:
                logger.error(f"加载 cookies 失败: {e}")
                self._cookies = {}
    
    def _save(self) -> None:
        """保存 cookies"""
        try:
            with open(self.cookie_file, "w", encoding="utf-8") as f:
                json.dump(self._cookies, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"保存 cookies 失败: {e}")
    
    def set_cookie(self, domain: str, name: str, value: str, **kwargs) -> None:
        """设置单个 cookie"""
        # 标准化域名
        if not domain.startswith("."):
            domain = "." + domain
        
        cookie = {
            "name": name,
            "value": value,
            "domain": domain,
            "path": kwargs.get("path", "/"),
            "secure": kwargs.get("secure", True),
            "httpOnly": kwargs.get("httpOnly", True),
        }
        
        if domain not in self._cookies:
            self._cookies[domain] = []
        
        # 更新或添加
        updated = False
        for i, c in enumerate(self._cookies[domain]):
            if c["name"] == name:
                self._cookies[domain][i] = cookie
                updated = True
                break
        
        if not updated:
            self._cookies[domain].append(cookie)
        
        self._save()
        logger.info(f"已设置 cookie: {domain} / {name}")
    
    def set_cf_clearance(self, domain: str, value: str) -> None:
        """设置 cf_clearance cookie"""
        self.set_cookie(domain, "cf_clearance", value)
    
    def get_cookies_for_url(self, url: str) -> list[dict]:
        """获取指定 URL 的所有相关 cookies"""
        from urllib.parse import urlparse
        
        parsed = urlparse(url)
        host = parsed.netloc.lower()
        
        result = []
        
        for domain, cookies in self._cookies.items():
            # 检查域名匹配
            if host.endswith(domain.lstrip(".")):
                result.extend(cookies)
        
        return result
    
    def get_all_cookies(self) -> list[dict]:
        """获取所有 cookies（用于注入浏览器）"""
        result = []
        for cookies in self._cookies.values():
            result.extend(cookies)
        return result
    
    def import_from_browser(self, cookies: list[dict]) -> int:
        """从浏览器导入 cookies"""
        count = 0
        cf_names = {"cf_clearance", "__cf_bm", "cf_chl_2", "cf_chl_prog"}
        
        for cookie in cookies:
            name = cookie.get("name", "")
            domain = cookie.get("domain", "")
            
            # 只保存 CF 相关的 cookies
            if name in cf_names or "cf" in name.lower():
                if domain not in self._cookies:
                    self._cookies[domain] = []
                
                # 检查是否已存在
                exists = False
                for i, c in enumerate(self._cookies[domain]):
                    if c["name"] == name:
                        self._cookies[domain][i] = cookie
                        exists = True
                        break
                
                if not exists:
                    self._cookies[domain].append(cookie)
                
                count += 1
        
        self._save()
        logger.info(f"导入了 {count} 个 CF cookies")
        return count
    
    def list_domains(self) -> list[str]:
        """列出所有已保存 cookie 的域名"""
        return list(self._cookies.keys())
    
    def clear_domain(self, domain: str) -> bool:
        """清除指定域名的 cookies"""
        if domain in self._cookies:
            del self._cookies[domain]
            self._save()
            return True
        return False
    
    def clear_all(self) -> None:
        """清除所有 cookies"""
        self._cookies = {}
        self._save()


# 全局实例
CF_MANAGER = CFCookieManager()