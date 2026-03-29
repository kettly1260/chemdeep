"""
Text and HTML parsers for fetcher service
"""
import re
from pathlib import Path

def safe_slug(value: str, max_len: int = 80) -> str:
    v = re.sub(r"[^\w\-\.]+", "_", value, flags=re.U).strip("_")
    return v[:max_len] if v else "paper"


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def normalize_doi(value: str | None) -> str | None:
    if not value:
        return None
    value = value.strip()
    value = re.sub(r"^https?://(dx\.)?doi\.org/", "", value, flags=re.I).strip()
    value = value.replace("DOI:", "").strip()
    return value or None


def contains_synthesis_steps(text: str) -> bool:
    t = (text or "").lower()
    if not t:
        return False
    score = 0
    if re.search(r"\b(experimental|methods|materials and methods|synthesis|preparation|fabrication)\b", t):
        score += 1
    if re.search(r"\b(\d{2,4})\s*(°c|celsius|k)\b", t):
        score += 1
    if re.search(r"\b(\d+(\.\d+)?)\s*(h|hr|hrs|hours|min|mins|minutes)\b", t):
        score += 1
    if re.search(r"\b(mg|g|kg|ml|l|mmol|mol|m)\b", t):
        score += 1
    if re.search(r"\b(stirred|heated|reflux|anneal|calcine|washed|dried|filtered|centrifuged)\b", t):
        score += 1
    if re.search(r"\b(autoclave|hydrothermal|solvothermal|cvd|ald|sputter|spin[- ]?coat)\b", t):
        score += 1
    return score >= 2


def html_to_markdown(html: str) -> str:
    try:
        import trafilatura
    except ImportError:
        return ""
    md = trafilatura.extract(html, output_format="markdown", include_tables=False, include_comments=False)
    return (md or "").strip()


def find_si_urls_from_html(html: str) -> list[str]:
    if not html:
        return []
    urls: set[str] = set()
    for m in re.finditer(r'href="([^"]+)"', html, flags=re.I):
        href = m.group(1)
        if not href or href.startswith("#"):
            continue
        h = href.lower()
        if any(k in h for k in ["supplement", "supporting", "esi", "supplementary"]):
            urls.add(href)
        elif h.endswith(".pdf") and any(k in h for k in ["supp", "support", "si", "esi"]):
            urls.add(href)
    return list(urls)[:8]


def absolutize_url(href: str, base_url: str) -> str:
    if href.startswith("http://") or href.startswith("https://"):
        return href
    if href.startswith("//"):
        return "https:" + href
    if href.startswith("/"):
        m = re.match(r"^(https?://[^/]+)", base_url)
        if m:
            return m.group(1) + href
    return base_url.rstrip("/") + "/" + href.lstrip("/")
