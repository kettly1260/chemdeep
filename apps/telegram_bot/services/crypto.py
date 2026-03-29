"""
Crypto Service
用于加密存储 API Keys
"""
import base64
import os
from typing import Optional
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from config.settings import settings

def _get_fernet_key() -> bytes:
    """
    从 settings.TELEGRAM_TOKEN (或专用secret) 派生加密密钥
    确保在没有专门 SECRET_KEY 的情况下也能工作，但保持确定性
    """
    # 优先使用专门的 SECRET_KEY，否则回退到 TG TOKEN (作为种子)
    # 实际生产建议在 .env 配置 PROJ_SECRET_KEY
    secret = os.getenv("PROJ_SECRET_KEY", settings.TELEGRAM_TOKEN)
    if not secret:
        raise ValueError("Encryption requires TELEGRAM_TOKEN or PROJ_SECRET_KEY")
        
    salt = b'chemdeep_static_salt' # 简单固定盐，确保重启后能解密
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=100000,
    )
    return base64.urlsafe_b64encode(kdf.derive(secret.encode()))

_fernet: Optional[Fernet] = None

def get_fernet() -> Fernet:
    global _fernet
    if _fernet is None:
        key = _get_fernet_key()
        _fernet = Fernet(key)
    return _fernet

def encrypt_key(api_key: str) -> str:
    """加密 API Key"""
    if not api_key:
        return ""
    f = get_fernet()
    return f.encrypt(api_key.encode()).decode()

def decrypt_key(enc_key: str) -> str:
    """解密 API Key"""
    if not enc_key:
        return ""
    try:
        f = get_fernet()
        return f.decrypt(enc_key.encode()).decode()
    except Exception:
        return ""

def mask_key(api_key: str) -> str:
    """脱敏显示 (sha256 前8位 或 mix)"""
    if not api_key:
        return "Not Set"
    if api_key.startswith("sk-"):
        # OpenAI style
        return f"sk-...{api_key[-4:]}"
    # Generic
    return f"{api_key[:4]}...{api_key[-4:]}"
