"""
Context Manager for Citation System (P26)
Handles source deduplication, ID assignment, and formatted context for LLM.
"""
import hashlib
import logging
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any

logger = logging.getLogger('deep_research')


@dataclass
class IndexedSource:
    """A source with a unique citation ID."""
    id: int
    title: str
    authors: str = ""
    doi: Optional[str] = None
    url: Optional[str] = None
    abstract: str = ""
    content: str = ""  # Full text if available
    source_type: str = "academic"  # "academic", "web", "gray"
    
    def get_reference_line(self) -> str:
        """Generate reference line for bibliography."""
        parts = [f"[{self.id}]"]
        if self.title:
            parts.append(f"**{self.title}**")
        if self.authors:
            parts.append(f"_{self.authors}_")
        if self.doi:
            parts.append(f"[DOI](https://doi.org/{self.doi})")
        elif self.url:
            parts.append(f"[Link]({self.url})")
        return " ".join(parts)
    
    def to_context_block(self) -> str:
        """Format for LLM context injection."""
        lines = [f"[ID: {self.id}] **{self.title}**"]
        if self.authors:
            lines.append(f"Authors: {self.authors}")
        if self.doi:
            lines.append(f"DOI: {self.doi}")
        
        # Use content if available, otherwise abstract
        text = self.content if self.content else self.abstract
        if text:
            # Truncate to reasonable length
            if len(text) > 1500:
                text = text[:1500] + "..."
            lines.append(f"Content: {text}")
        
        return "\n".join(lines)


class ContextManager:
    """
    Manages sources for citation-aware LLM prompting.
    
    Usage:
        cm = ContextManager()
        cm.add_sources(academic_papers, source_type="academic")
        cm.add_sources(web_results, source_type="web")
        context_str = cm.get_context_string()
        # Send context_str to LLM with citation rules
        # After LLM response, use cm.get_references(cited_ids) to build bibliography
    """
    
    def __init__(self):
        self._sources: List[IndexedSource] = []
        self._seen_fingerprints: set = set()
        self._next_id = 1
    
    def _fingerprint(self, doi: Optional[str], url: Optional[str], title: str) -> str:
        """Create unique fingerprint for deduplication."""
        if doi:
            return f"doi:{doi.lower()}"
        if url:
            return f"url:{url.lower()}"
        # Fallback to title hash
        return f"title:{hashlib.md5(title.lower().encode()).hexdigest()[:12]}"
    
    def add_source(self, 
                   title: str,
                   authors: str = "",
                   doi: Optional[str] = None,
                   url: Optional[str] = None,
                   abstract: str = "",
                   content: str = "",
                   source_type: str = "academic") -> Optional[int]:
        """
        Add a single source. Returns assigned ID or None if duplicate.
        """
        fp = self._fingerprint(doi, url, title)
        
        if fp in self._seen_fingerprints:
            logger.debug(f"Duplicate source skipped: {title[:50]}")
            return None
        
        self._seen_fingerprints.add(fp)
        
        source = IndexedSource(
            id=self._next_id,
            title=title,
            authors=authors,
            doi=doi,
            url=url,
            abstract=abstract,
            content=content,
            source_type=source_type
        )
        
        self._sources.append(source)
        assigned_id = self._next_id
        self._next_id += 1
        
        return assigned_id
    
    def add_sources_from_papers(self, papers: List[Dict[str, Any]], source_type: str = "academic") -> int:
        """
        Add multiple sources from paper dict format.
        Returns count of newly added sources.
        """
        added = 0
        for paper in papers:
            result = self.add_source(
                title=paper.get("title", "Untitled"),
                authors=paper.get("authors", ""),
                doi=paper.get("doi"),
                url=paper.get("url"),
                abstract=paper.get("abstract", ""),
                content=paper.get("full_text", ""),
                source_type=source_type
            )
            if result is not None:
                added += 1
        return added
    
    def get_context_string(self, max_sources: int = 15) -> str:
        """
        Generate formatted context string for LLM.
        Includes citation rules.
        """
        if not self._sources:
            return "No sources available."
        
        lines = [
            "# Supporting Evidence",
            "",
            "**CITATION RULES (MANDATORY):**",
            "- Rule A: Every specific claim (property, yield, method) MUST be followed by [ID].",
            "- Rule B: Place citations next to the relevant sentence, NOT at paragraph end.",
            "- Rule C: Generate a 'References' section at the end listing ONLY cited sources.",
            "",
            "---",
            ""
        ]
        
        # Add top sources
        for source in self._sources[:max_sources]:
            lines.append(source.to_context_block())
            lines.append("")
            lines.append("---")
            lines.append("")
        
        return "\n".join(lines)
    
    def get_references(self, cited_ids: Optional[List[int]] = None) -> str:
        """
        Generate references section.
        If cited_ids is None, include all sources.
        """
        lines = ["## References", ""]
        
        for source in self._sources:
            if cited_ids is None or source.id in cited_ids:
                lines.append(source.get_reference_line())
        
        return "\n".join(lines)
    
    def get_all_sources(self) -> List[IndexedSource]:
        """Return all indexed sources."""
        return self._sources.copy()
    
    def get_source_count(self) -> int:
        """Return total unique source count."""
        return len(self._sources)
