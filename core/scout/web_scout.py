import logging
import re
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
import time
import os
import threading

from core.mcp_client import MCPClient
from config.settings import settings

logger = logging.getLogger("web_scout")

@dataclass
class WebResult:
    title: str
    url: str
    snippet: str
    doi: Optional[str] = None
    is_academic_source: bool = False
    
class WebScout:
    """
    Open Web Scouting Service using MCP-Websearch (DuckDuckGo).
    Finds papers via general web search and extracts DOIs.
    """
    
    # 学术出版商域名白名单 (High Confidence)
    PUBLISHER_DOMAINS = [
        "pubs.acs.org", "onlinelibrary.wiley.com", "sciencedirect.com", 
        "nature.com", "rsc.org", "springer.com", "link.springer.com",
        "chemrxiv.org", "pubmed.ncbi.nlm.nih.gov", "science.org",
        "tandfonline.com", "thieme-connect.com", "iopscience.iop.org"
    ]
    
    # 忽略的域名黑名单
    BLOCKLIST_DOMAINS = [
        "wikipedia.org", "quora.com", "facebook.com", "linkedin.com", "baidu.com",
        "twitter.com", "x.com", "youtube.com", "instagram.com", "reddit.com"
    ]
    
    # [P76] Singleton Client to prevent process spamming
    _shared_client: Optional[MCPClient] = None
    _client_lock = threading.Lock()

    def __init__(self):
        pass # Client is lazy loaded via _get_client
        
    @classmethod
    def _get_client(cls) -> MCPClient:
        """Get or create regular Python MCP client for Web Search (Shared)"""
        with cls._client_lock:
            if cls._shared_client:
                return cls._shared_client
            
            try:
                # 使用 settings 中配置的 python 命令
                cmd = settings.MCP_WEBSEARCH_COMMAND
                args = settings.MCP_WEBSEARCH_ARGS
                cwd = settings.BASE_DIR
                
                # [P44] Proxy Support
                env = os.environ.copy()
                if settings.CHEMDEEP_WEBSEARCH_PROXY:
                    logger.info(f"Setting WebSearch Proxy: {settings.CHEMDEEP_WEBSEARCH_PROXY}")
                    env["HTTP_PROXY"] = settings.CHEMDEEP_WEBSEARCH_PROXY
                    env["HTTPS_PROXY"] = settings.CHEMDEEP_WEBSEARCH_PROXY
                    env["ALL_PROXY"] = settings.CHEMDEEP_WEBSEARCH_PROXY
                
                logger.info(f"Initializing WebScout MCP (Singleton): {cmd} {args}")
                cls._shared_client = MCPClient(
                    command=cmd,
                    args=args,
                    cwd=str(cwd),
                    env=env
                )
                return cls._shared_client
            except Exception as e:
                logger.error(f"Failed to init WebScout MCP: {e}")
                raise

    def extract_doi(self, text: str) -> Optional[str]:
        """Extract DOI from text using standard regex"""
        # 标准 DOI 正则: 10.xxxx/...
        # Case insensitive, handles common suffixes
        pattern = r'\b(10\.\d{4,9}/[-._;()/:A-Z0-9]+)\b'
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            doi = match.group(1)
            # Basic cleanup (remove trailing punctuation often caught by regex)
            doi = doi.rstrip(".;,)")
            return doi
        return None

    def _is_academic_domain(self, url: str) -> bool:
        return any(d in url.lower() for d in self.PUBLISHER_DOMAINS)

    def _is_blocked(self, url: str) -> bool:
        return any(d in url.lower() for d in self.BLOCKLIST_DOMAINS)

    def search(self, query: str, max_results: int = 10) -> List[WebResult]:
        """Run web search and parse results"""
        try:
            client = self._get_client()
            
            # Call MCP tool "web_search"
            # [P76] Reduced timeout to 60s to prevent hanging
            logger.info(f"🔍 Web Scout: {query}")
            response = client.call_tool("web_search", {
                "query": query,
                "max_results": max_results
            }, timeout=60)

            
            # response format depend on mcp implementation.
            # Our search_mcp.py returns raw text string. We need to parse it?
            # Wait, search_mcp.py returns [TextContent(text=...)].
            # Client.call_tool returns the 'result' part of JSON-RPC response.
            # Let's inspect mcp_client.py call_tool implementation. 
            # It returns the whole result object. content is inside.
            
            content_list = response.get("content", [])
            full_text = ""
            for item in content_list:
                if item.get("type") == "text":
                    full_text += item.get("text", "")
            
            # The search_mcp.py returns a formatted string: 
            # "1. **Title**\n   URL: ...\n   Snippet..."
            # We need to parse this string back into structured data.
            # This is bit inefficient (String -> String -> Parse), but fits the MCP text-based protocol.
            
            results = self._parse_ddg_text(full_text)
            return results
            
        except Exception as e:
            logger.error(f"Web Scout Search Failed: {e}")
            return []

    def _parse_ddg_text(self, text: str) -> List[WebResult]:
        """Parse the formatted text output from search_mcp.py"""
        # Format ref:
        # 1. **Title**
        #    URL: https://...
        #    Body text...
        
        results = []
        entries = re.split(r'\n\n(?=\d+\.)', text)
        
        for entry in entries:
            try:
                web_res = WebResult(title="", url="", snippet="")
                
                lines = entry.strip().split('\n')
                if not lines: continue
                
                # Line 1: 1. **Title**
                # Remove number and bold markers
                title_line = lines[0]
                title_clean = re.sub(r'^\d+\.\s*\*\*(.*)\*\*$', r'\1', title_line)
                web_res.title = title_clean
                
                for line in lines[1:]:
                    line = line.strip()
                    if line.startswith("URL:"):
                        web_res.url = line[4:].strip()
                    else:
                        web_res.snippet += line + " "
                
                # Post-processing
                web_res.snippet = web_res.snippet.strip()
                
                # Domain check
                if self._is_blocked(web_res.url):
                    continue
                    
                web_res.is_academic_source = self._is_academic_domain(web_res.url)
                
                # DOI Extraction
                # Try URL first (high confidence)
                web_res.doi = self.extract_doi(web_res.url)
                if not web_res.doi:
                    # Try snippet
                    web_res.doi = self.extract_doi(web_res.snippet)
                
                results.append(web_res)
                
            except Exception as e:
                logger.debug(f"Error parsing entry: {e}")
                continue
                
        return results

    def scout_for_doi(self, query: str) -> List[WebResult]:
        """
        Main Workflow: Search -> Filter -> Extract unique DOIs
        """
        raw_results = self.search(query)
        valid_results = []
        seen_dois = set()
        
        for res in raw_results:
            if res.doi:
                if res.doi in seen_dois:
                    continue
                seen_dois.add(res.doi)
                valid_results.append(res)
            elif res.is_academic_source:
                # No DOI but academic source -> Keep it (maybe "Gray Literature" or Supplemental)
                valid_results.append(res)
                
        logger.info(f"Web Scout found {len(valid_results)} candidates (DOIs: {len(seen_dois)})")
        return valid_results
