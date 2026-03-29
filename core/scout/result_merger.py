import logging
from typing import List, Dict, Any, Optional
from dataclasses import asdict

from core.scout.web_scout import WebResult

logger = logging.getLogger("result_merger")

class ResultMerger:
    """
    Merges results from Academic DB (Node) and Web Scout (Python).
    Strategy:
    1. Base is Academic DB (more reliable metadata).
    2. Web results with matching DOI -> Augment Academic result.
    3. Web results with unique DOI -> Add as new result (mark source as Web).
    4. Web results without DOI -> Add as "Gray Literature" if highly relevant.
    """

    @staticmethod
    def merge(node_results: List[Dict], web_results: List[WebResult]) -> List[Dict]:
        """
        Input:
            node_results: List of dicts from paper-search-mcp
            web_results: List of WebResult objects from WebScout
        Output:
            Unified list of dicts suitable for LLM context.
        """
        merged_map = {} # DOI -> Result Dict
        final_list = []
        
        # 1. Process Node Results (Base)
        for res in node_results:
            doi = res.get("doi")
            if doi:
                # Normalize DOI
                doi = doi.lower().strip()
                res["source"] = "AcademicDB"
                # Ensure tags exist
                if "tags" not in res: res["tags"] = []
                res["tags"].append("academic_db")
                merged_map[doi] = res
            else:
                # No DOI in Node result? Rare but possible. Add directly.
                res["source"] = "AcademicDB"
                final_list.append(res)
        
        # 2. Process Web Results
        for web in web_results:
            if web.doi:
                doi = web.doi.lower().strip()
                if doi in merged_map:
                    # Match found! Augment existing record.
                    existing = merged_map[doi]
                    existing["web_url"] = web.url
                    existing["web_snippet"] = web.snippet
                    existing["tags"].append("web_verified")
                    # If academic DB missed the title (unlikely), use web title
                    if not existing.get("title") and web.title:
                        existing["title"] = web.title
                else:
                    # New unique DOI found by Web Scout
                    new_entry = {
                        "doi": web.doi,
                        "title": web.title,
                        "abstract": web.snippet, # Use snippet as abstract placeholder
                        "source": "WebScout",
                        "url": web.url,
                        "tags": ["web_scout", "needs_verification"],
                        "year": None, # Unknown
                        "authors": [], # Unknown
                        "journal": "Web Result"
                    }
                    merged_map[doi] = new_entry
            else:
                # No DOI. 
                # If it's from an academic domain, keep it as "Supplemental"
                if web.is_academic_source:
                    gray_entry = {
                        "doi": None,
                        "title": web.title,
                        "abstract": web.snippet,
                        "source": "WebScout(Gray)",
                        "url": web.url,
                        "tags": ["web_scout", "gray_literature"],
                        "journal": "Web Source"
                    }
                    final_list.append(gray_entry)
        
        # Convert map back to list
        combined = list(merged_map.values()) + final_list
        
        logger.info(f"Merged Results: {len(node_results)} Node + {len(web_results)} Web -> {len(combined)} Total")
        return combined
