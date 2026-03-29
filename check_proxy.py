
import sys
import os
from pathlib import Path
from dotenv import load_dotenv
import httpx
import logging

# Setup basic logging to console
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("check_proxy")

# Load env
load_dotenv(Path(__file__).parent / "config" / ".env")

proxy = os.getenv("CHEMDEEP_TELEGRAM_PROXY")
token = os.getenv("CHEMDEEP_TELEGRAM_TOKEN")
api_base = os.getenv("CHEMDEEP_OPENAI_API_BASE")

logger.info(f"Proxy Configured: {proxy}")
logger.info(f"Token Configured: {bool(token)}")

def check_url(url, p):
    logger.info(f"Checking {url}...")
    try:
        if p:
            client = httpx.Client(proxy=p, timeout=10.0)
        else:
            client = httpx.Client(timeout=10.0)
        
        # Determine if we should use proxies arg or proxy arg (httpx versions differ)
        # But simple test:
        resp = client.get(url)
        logger.info(f"Status: {resp.status_code}")
        return True
    except Exception as e:
        logger.error(f"Failed: {e}")
        return False

# 1. Check Google (if proxy)
if proxy:
    check_url("https://www.google.com", proxy)

# 2. Check Telegram
check_url(f"https://api.telegram.org/bot{token}/getMe", proxy)
