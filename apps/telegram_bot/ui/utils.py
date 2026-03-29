"""
UI Utilities
"""

def escape_markdown(text: str) -> str:
    """
    Escape special characters for Telegram Markdown (Legacy).
    Based on official docs, legacy Markdown requires escaping:
    _ * ` [ ]
    
    However, legacy markdown is simpler but stricter on pairing.
    If we can't guarantee pairing, we should escape them.
    
    Telegram only processes _ * ` [
    """
    if not text:
        return ""
    
    # In legacy Markdown, we can't easily escape everything correctly without breaking intended formatting.
    # But if we treat input as "raw text", we should escape reserved chars.
    reserved = ['_', '*', '[', '`']
    for char in reserved:
        text = text.replace(char, f"\\{char}")
    return text

def truncate_text(text: str, limit: int = 100) -> str:
    if len(text) > limit:
        return text[:limit-3] + "..."
    return text
