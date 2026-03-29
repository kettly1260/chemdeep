"""
Citation Providers Module (P6/P7)
插件式架构：OpenAlex (主) + Crossref (兜底)
包含缓存、限流、断点续跑支持
"""
import json
import logging
import time
import hashlib
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Optional, Tuple, Any
from urllib.parse import quote

import requests

logger = logging.getLogger('deep_research')

# ============================================================
# 常量配置
# ============================================================
CACHE_DIR = Path("cache/citations")
CACHE_TTL_DAYS = 7
MAX_RETRIES = 3
RETRY_BASE_DELAY = 1.0  # 秒
RATE_LIMIT_DELAY = 0.1  # 请求间隔

OPENALEX_BASE_URL = "https://api.openalex.org"
CROSSREF_BASE_URL = "https://api.crossref.org"

# 邮箱用于 polite pool (提高限额)
CONTACT_EMAIL = "research@example.com"


# ============================================================
# 统一输出数据结构
# ============================================================
@dataclass
class PaperCandidate:
    """统一的论文候选结构"""
    # 标识
    doi: str = ""
    openalex_id: str = ""
    
    # 元数据
    title: str = ""
    abstract: str = ""
    year: Optional[int] = None
    authors: List[str] = field(default_factory=list)
    first_author: str = ""
    
    # 来源与关系
    url: str = ""
    source: str = ""           # "openalex" | "crossref"
    relation: str = ""         # "cited_by" | "references"
    seed_paper_key: str = ""   # 种子论文 key
    
    # 统计
    cited_by_count: int = 0
    
    def to_dict(self) -> dict:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: dict) -> "PaperCandidate":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


# ============================================================
# 缓存管理
# ============================================================
class CitationCache:
    """本地缓存管理 (TTL = 7 天)"""
    
    def __init__(self, cache_dir: Path = CACHE_DIR, ttl_days: int = CACHE_TTL_DAYS):
        self.cache_dir = cache_dir
        self.ttl = timedelta(days=ttl_days)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
    
    def _get_cache_path(self, paper_key: str) -> Path:
        """生成缓存文件路径"""
        safe_key = hashlib.md5(paper_key.encode()).hexdigest()
        return self.cache_dir / f"{safe_key}.json"
    
    def get(self, paper_key: str) -> Optional[List[PaperCandidate]]:
        """获取缓存 (检查 TTL)"""
        path = self._get_cache_path(paper_key)
        if not path.exists():
            return None
        
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            cached_at = datetime.fromisoformat(data.get("cached_at", ""))
            
            if datetime.now() - cached_at > self.ttl:
                logger.debug(f"缓存过期: {paper_key}")
                path.unlink()
                return None
            
            candidates = [PaperCandidate.from_dict(c) for c in data.get("candidates", [])]
            logger.debug(f"缓存命中: {paper_key} ({len(candidates)} items)")
            return candidates
            
        except Exception as e:
            logger.warning(f"缓存读取失败: {e}")
            return None
    
    def set(self, paper_key: str, candidates: List[PaperCandidate]) -> None:
        """写入缓存"""
        path = self._get_cache_path(paper_key)
        data = {
            "cached_at": datetime.now().isoformat(),
            "paper_key": paper_key,
            "candidates": [c.to_dict() for c in candidates]
        }
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.debug(f"缓存写入: {paper_key} ({len(candidates)} items)")


# ============================================================
# HTTP 客户端 (限流 + 重试)
# ============================================================
class RateLimitedClient:
    """带限流和重试的 HTTP 客户端"""
    
    def __init__(self, delay: float = RATE_LIMIT_DELAY, max_retries: int = MAX_RETRIES):
        self.delay = delay
        self.max_retries = max_retries
        self.last_request_time = 0.0
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": f"DeepResearch/1.0 (mailto:{CONTACT_EMAIL})"
        })
    
    def get(self, url: str, params: dict = None) -> Optional[dict]:
        """发起 GET 请求 (带限流和重试)"""
        # 限流
        elapsed = time.time() - self.last_request_time
        if elapsed < self.delay:
            time.sleep(self.delay - elapsed)
        
        for attempt in range(self.max_retries):
            try:
                self.last_request_time = time.time()
                resp = self.session.get(url, params=params, timeout=30)
                
                if resp.status_code == 200:
                    return resp.json()
                
                if resp.status_code == 429 or resp.status_code >= 500:
                    # 指数退避
                    wait = RETRY_BASE_DELAY * (2 ** attempt)
                    logger.warning(f"HTTP {resp.status_code}, 重试 {attempt+1}/{self.max_retries} (等待 {wait}s)")
                    time.sleep(wait)
                    continue
                
                logger.warning(f"HTTP {resp.status_code}: {url}")
                return None
                
            except requests.RequestException as e:
                wait = RETRY_BASE_DELAY * (2 ** attempt)
                logger.warning(f"请求失败: {e}, 重试 {attempt+1}/{self.max_retries}")
                time.sleep(wait)
        
        return None


# ============================================================
# Provider 抽象基类
# ============================================================
class CitationProvider(ABC):
    """引文数据源抽象基类"""
    
    def __init__(self, client: RateLimitedClient = None):
        self.client = client or RateLimitedClient()
    
    @abstractmethod
    def fetch_references(self, paper_key: str, max_results: int = 50) -> List[PaperCandidate]:
        """获取该论文引用的文献 (references)"""
        pass
    
    @abstractmethod
    def fetch_cited_by(self, paper_key: str, max_results: int = 50) -> List[PaperCandidate]:
        """获取引用该论文的文献 (cited_by)"""
        pass


# ============================================================
# OpenAlex Provider
# ============================================================
class OpenAlexProvider(CitationProvider):
    """OpenAlex API Provider"""
    
    def _parse_openalex_id(self, paper_key: str) -> Optional[str]:
        """从 paper_key 解析 OpenAlex ID"""
        if paper_key.startswith("id:"):
            return paper_key[3:]
        if paper_key.startswith("https://openalex.org/"):
            return paper_key.split("/")[-1]
        return None
    
    def _parse_doi(self, paper_key: str) -> Optional[str]:
        """从 paper_key 解析 DOI"""
        if paper_key.startswith("doi:"):
            return paper_key[4:]
        if paper_key.startswith("10."):
            return paper_key
        return None
    
    def _work_to_candidate(self, work: dict, relation: str, seed_key: str) -> PaperCandidate:
        """将 OpenAlex work 转换为 PaperCandidate"""
        # 提取作者
        authors = []
        first_author = ""
        for auth in work.get("authorships", [])[:10]:
            name = auth.get("author", {}).get("display_name", "")
            if name:
                authors.append(name)
                if not first_author:
                    first_author = name
        
        # 提取 DOI
        doi = work.get("doi", "") or ""
        if doi.startswith("https://doi.org/"):
            doi = doi[16:]
        
        return PaperCandidate(
            doi=doi,
            openalex_id=work.get("id", "").replace("https://openalex.org/", ""),
            title=work.get("title", "") or "",
            abstract=self._reconstruct_abstract(work.get("abstract_inverted_index")),
            year=work.get("publication_year"),
            authors=authors,
            first_author=first_author,
            url=work.get("primary_location", {}).get("landing_page_url", "") or "",
            source="openalex",
            relation=relation,
            seed_paper_key=seed_key,
            cited_by_count=work.get("cited_by_count", 0)
        )
    
    def _reconstruct_abstract(self, inverted_index: Optional[dict]) -> str:
        """从 inverted index 重建摘要"""
        if not inverted_index:
            return ""
        
        # 重建词序
        words = []
        for word, positions in inverted_index.items():
            for pos in positions:
                while len(words) <= pos:
                    words.append("")
                words[pos] = word
        
        return " ".join(words)
    
    def _get_work_id(self, paper_key: str) -> Optional[str]:
        """获取 OpenAlex work ID"""
        oa_id = self._parse_openalex_id(paper_key)
        if oa_id:
            return oa_id
        
        doi = self._parse_doi(paper_key)
        if doi:
            # 通过 DOI 查询 OpenAlex ID
            url = f"{OPENALEX_BASE_URL}/works/doi:{doi}"
            data = self.client.get(url)
            if data:
                return data.get("id", "").replace("https://openalex.org/", "")
        
        return None
    
    def fetch_references(self, paper_key: str, max_results: int = 50) -> List[PaperCandidate]:
        """获取引用的文献"""
        work_id = self._get_work_id(paper_key)
        if not work_id:
            logger.warning(f"无法解析 OpenAlex ID: {paper_key}")
            return []
        
        # 获取 work 详情
        url = f"{OPENALEX_BASE_URL}/works/{work_id}"
        data = self.client.get(url)
        if not data:
            return []
        
        referenced_works = data.get("referenced_works", [])[:max_results]
        candidates = []
        
        # 批量获取引用文献详情
        if referenced_works:
            ids = "|".join([w.replace("https://openalex.org/", "") for w in referenced_works[:50]])
            batch_url = f"{OPENALEX_BASE_URL}/works"
            batch_data = self.client.get(batch_url, params={"filter": f"ids.openalex:{ids}", "per-page": 50})
            
            if batch_data and "results" in batch_data:
                for work in batch_data["results"]:
                    candidates.append(self._work_to_candidate(work, "references", paper_key))
        
        logger.info(f"📚 OpenAlex references: {paper_key} -> {len(candidates)}")
        return candidates
    
    def fetch_cited_by(self, paper_key: str, max_results: int = 50) -> List[PaperCandidate]:
        """获取被引文献"""
        work_id = self._get_work_id(paper_key)
        if not work_id:
            logger.warning(f"无法解析 OpenAlex ID: {paper_key}")
            return []
        
        url = f"{OPENALEX_BASE_URL}/works"
        params = {
            "filter": f"cites:{work_id}",
            "per-page": min(max_results, 50),
            "sort": "cited_by_count:desc"
        }
        
        data = self.client.get(url, params=params)
        if not data or "results" not in data:
            return []
        
        candidates = [
            self._work_to_candidate(work, "cited_by", paper_key)
            for work in data["results"]
        ]
        
        logger.info(f"📚 OpenAlex cited_by: {paper_key} -> {len(candidates)}")
        return candidates


# ============================================================
# Crossref Provider (兜底)
# ============================================================
class CrossrefProvider(CitationProvider):
    """Crossref API Provider"""
    
    def _parse_doi(self, paper_key: str) -> Optional[str]:
        if paper_key.startswith("doi:"):
            return paper_key[4:]
        if paper_key.startswith("10."):
            return paper_key
        return None
    
    def _work_to_candidate(self, item: dict, relation: str, seed_key: str) -> PaperCandidate:
        """将 Crossref item 转换为 PaperCandidate"""
        authors = []
        first_author = ""
        for auth in item.get("author", [])[:10]:
            name = f"{auth.get('given', '')} {auth.get('family', '')}".strip()
            if name:
                authors.append(name)
                if not first_author:
                    first_author = name
        
        # 年份
        year = None
        if "published-print" in item:
            year = item["published-print"].get("date-parts", [[None]])[0][0]
        elif "published-online" in item:
            year = item["published-online"].get("date-parts", [[None]])[0][0]
        
        return PaperCandidate(
            doi=item.get("DOI", ""),
            openalex_id="",
            title=item.get("title", [""])[0] if item.get("title") else "",
            abstract=item.get("abstract", ""),
            year=year,
            authors=authors,
            first_author=first_author,
            url=item.get("URL", ""),
            source="crossref",
            relation=relation,
            seed_paper_key=seed_key,
            cited_by_count=item.get("is-referenced-by-count", 0)
        )
    
    def fetch_references(self, paper_key: str, max_results: int = 50) -> List[PaperCandidate]:
        """获取引用的文献"""
        doi = self._parse_doi(paper_key)
        if not doi:
            return []
        
        url = f"{CROSSREF_BASE_URL}/works/{quote(doi, safe='')}"
        data = self.client.get(url)
        
        if not data or "message" not in data:
            return []
        
        message = data["message"]
        references = message.get("reference", [])[:max_results]
        
        candidates = []
        for ref in references:
            if ref.get("DOI"):
                candidates.append(PaperCandidate(
                    doi=ref.get("DOI", ""),
                    title=ref.get("article-title", "") or ref.get("unstructured", "")[:100],
                    year=ref.get("year"),
                    first_author=ref.get("author", ""),
                    source="crossref",
                    relation="references",
                    seed_paper_key=paper_key
                ))
        
        logger.info(f"📚 Crossref references: {paper_key} -> {len(candidates)}")
        return candidates
    
    def fetch_cited_by(self, paper_key: str, max_results: int = 50) -> List[PaperCandidate]:
        """Crossref 不支持 cited_by 查询，返回空"""
        logger.debug("Crossref 不支持 cited_by 查询")
        return []


# ============================================================
# 统一入口函数
# ============================================================
_cache = CitationCache()
_openalex = OpenAlexProvider()
_crossref = CrossrefProvider()


def fetch_citations(
    paper_key: str,
    relation: str = "both",
    max_results: int = 50,
    use_cache: bool = True
) -> List[PaperCandidate]:
    """
    统一的引文获取入口
    
    Args:
        paper_key: 论文标识 (doi:xxx | id:xxx | url:xxx)
        relation: "references" | "cited_by" | "both"
        max_results: 每类最大数量
        use_cache: 是否使用缓存
    
    Returns:
        PaperCandidate 列表
    """
    cache_key = f"{paper_key}:{relation}"
    
    # 检查缓存
    if use_cache:
        cached = _cache.get(cache_key)
        if cached is not None:
            return cached
    
    candidates = []
    
    # OpenAlex 优先
    try:
        if relation in ("references", "both"):
            candidates.extend(_openalex.fetch_references(paper_key, max_results))
        if relation in ("cited_by", "both"):
            candidates.extend(_openalex.fetch_cited_by(paper_key, max_results))
    except Exception as e:
        logger.warning(f"OpenAlex 失败: {e}")
    
    # Crossref 兜底 (仅 references)
    if not candidates and relation in ("references", "both"):
        try:
            candidates.extend(_crossref.fetch_references(paper_key, max_results))
        except Exception as e:
            logger.warning(f"Crossref 失败: {e}")
    
    # 写入缓存
    if use_cache and candidates:
        _cache.set(cache_key, candidates)
    
    return candidates


def clear_cache() -> int:
    """清空缓存目录"""
    count = 0
    for f in CACHE_DIR.glob("*.json"):
        f.unlink()
        count += 1
    return count
