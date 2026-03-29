"""
CSV and WoS file utilities
"""
import csv
from pathlib import Path
from typing import Any, Iterable
from .parsers import normalize_doi

def _sniff_delimiter(path: Path) -> str:
    head = path.read_bytes()[:8192]
    sample = head.decode("utf-8", errors="ignore")
    if sample.count("\t") >= 2 and sample.count("\t") >= sample.count(","):
        return "\t"
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=[",", "\t", ";", "|"])
        return dialect.delimiter
    except Exception:
        return "\t" if "\t" in sample else ","


def parse_wos_file(path: Path) -> list[dict[str, Any]]:
    delimiter = _sniff_delimiter(path)
    
    with path.open("r", encoding="utf-8-sig", errors="ignore", newline="") as f:
        reader = csv.DictReader(f, delimiter=delimiter)
        if not reader.fieldnames:
            return []
        
        headers = {h: h.lower().strip() for h in reader.fieldnames}
        
        def pick_col(candidates: Iterable[str]) -> str | None:
            candidates_l = [c.lower() for c in candidates]
            for h, hl in headers.items():
                for c in candidates_l:
                    if hl == c or c in hl:
                        return h
            return None
        
        col_doi = pick_col(["di", "doi", "do"])  # "do" 是搜索结果格式的列名
        col_title = pick_col(["ti", "title", "article title"])
        col_year = pick_col(["py", "year", "publication year"])
        col_source = pick_col(["so", "source title", "journal"])
        col_ut = pick_col(["ut", "unique wos id", "wos id"])
        
        papers: list[dict[str, Any]] = []
        for row in reader:
            doi = normalize_doi(row.get(col_doi, "")) if col_doi else None
            title = (row.get(col_title, "") or "").strip() if col_title else ""
            year = (row.get(col_year, "") or "").strip() if col_year else ""
            source = (row.get(col_source, "") or "").strip() if col_source else ""
            ut = (row.get(col_ut, "") or "").strip() if col_ut else ""
            
            if not doi and not title:
                continue
            
            papers.append({
                "doi": doi,
                "title": title or None,
                "year": year or None,
                "source": source or None,
                "ut": ut or None,
            })
        
        return papers
