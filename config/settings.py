from pathlib import Path
from dotenv import load_dotenv
import os

# 加载 .env 文件
load_dotenv(Path(__file__).parent / ".env")


class Settings:
    # ========== Telegram 配置 ==========
    TELEGRAM_TOKEN = os.getenv("CHEMDEEP_TELEGRAM_TOKEN")
    TELEGRAM_PROXY = os.getenv("CHEMDEEP_TELEGRAM_PROXY")
    TELEGRAM_CHAT_ID = int(os.getenv("CHEMDEEP_TELEGRAM_CHAT_ID", 0) or 0)
    TELEGRAM_ALLOWED_CHAT_IDS = {
        int(x.strip())
        for x in os.getenv("CHEMDEEP_TELEGRAM_ALLOWED_CHAT_IDS", "").split(",")
        if x.strip().lstrip("-").isdigit()
    }

    # ========== AI Provider 配置 ==========
    # 可选值: "openai" | "gemini" | "auto"
    AI_PROVIDER = os.getenv("CHEMDEEP_AI_PROVIDER", "openai").lower()

    # OpenAI 兼容 API（支持自定义地址）
    OPENAI_API_KEY = os.getenv("CHEMDEEP_OPENAI_API_KEY")
    OPENAI_API_BASE = os.getenv("CHEMDEEP_OPENAI_API_BASE", "https://api.openai.com/v1")
    OPENAI_MODEL = os.getenv("CHEMDEEP_OPENAI_MODEL", "gpt-4-turbo-preview")

    # Google Gemini
    GEMINI_API_KEY = os.getenv("CHEMDEEP_GEMINI_API_KEY")
    GEMINI_MODEL = os.getenv("CHEMDEEP_GEMINI_MODEL", "gemini-1.5-pro")

    # AI 请求行为
    AI_TIMEOUT = int(os.getenv("CHEMDEEP_AI_TIMEOUT", "60"))
    AI_MAX_RETRIES = int(os.getenv("CHEMDEEP_AI_MAX_RETRIES", "3"))

    # AI 独立代理配置
    OPENAI_PROXY = os.getenv("CHEMDEEP_OPENAI_PROXY")  # 例如 socks5://127.0.0.1:7890
    GEMINI_PROXY = os.getenv("CHEMDEEP_GEMINI_PROXY")  # 例如 socks5://127.0.0.1:7890

    # OpenAlex 配置
    OPENALEX_API_KEY = os.getenv("CHEMDEEP_OPENALEX_API_KEY")
    OPENALEX_MAILTO = os.getenv(
        "CHEMDEEP_OPENALEX_MAILTO"
    )  # 建议填写邮箱以获得更高限额

    # P44: Web Search Proxy
    CHEMDEEP_WEBSEARCH_PROXY = os.getenv("CHEMDEEP_WEBSEARCH_PROXY", "")

    # ========== 路径配置 ==========
    BASE_DIR = Path(__file__).parent.parent
    PROFILE_DIR = Path(os.getenv("CHEMDEEP_PROFILE_DIR", "profiles/msedge"))
    LIBRARY_DIR = Path(os.getenv("CHEMDEEP_LIBRARY_DIR", "data/library"))
    REPORTS_DIR = Path(os.getenv("CHEMDEEP_REPORTS_DIR", "data/reports"))
    # [P59] Unified Output Directory
    PROJECTS_DIR = Path(os.getenv("CHEMDEEP_PROJECTS_DIR", "data/projects"))

    # ========== 浏览器配置 ==========
    RATE_SECONDS = int(os.getenv("CHEMDEEP_RATE_SECONDS", "1"))
    HEADLESS = os.getenv("CHEMDEEP_HEADLESS", "0").lower() in ("1", "true", "yes")
    BROWSER_CHANNEL = os.getenv("CHEMDEEP_BROWSER_CHANNEL", "msedge")
    USE_REAL_BROWSER = os.getenv("CHEMDEEP_USE_REAL_BROWSER", "1").lower() in (
        "1",
        "true",
        "yes",
    )

    # [P63] Concurrency Settings
    SEARCH_CONCURRENCY = int(os.getenv("CHEMDEEP_SEARCH_CONCURRENCY", "6"))
    FETCH_CONCURRENCY = int(os.getenv("CHEMDEEP_FETCH_CONCURRENCY", "3"))

    # [P67] Batch & Robustness
    JSON_REPAIR_RETRIES = int(os.getenv("CHEMDEEP_JSON_REPAIR_RETRIES", "1"))
    EVIDENCE_BATCH_SIZE = int(os.getenv("CHEMDEEP_EVIDENCE_BATCH_SIZE", "4"))
    EVIDENCE_BATCH_MAX_CHARS = int(
        os.getenv("CHEMDEEP_EVIDENCE_BATCH_MAX_CHARS", "3000")
    )
    PARALLEL_FETCHERS = int(os.getenv("CHEMDEEP_PARALLEL_FETCHERS", "8"))

    # ========== 存储分区配置 ==========
    # 1. 文章库 (Articles): 存放全文、原始HTML、PDF等大文件
    LIBRARY_ARTICLE_DIR = Path(
        os.getenv("CHEMDEEP_LIBRARY_ARTICLE_DIR", "data/library/articles")
    )

    # 2. 索引库 (Index): 存放元数据、Embedding索引等
    LIBRARY_INDEX_DIR = Path(
        os.getenv("CHEMDEEP_LIBRARY_INDEX_DIR", "data/library/index")
    )

    # 3. 项目空间 (Projects): 存放具体项目的研究状态、报告
    PROJECTS_DIR = Path(os.getenv("CHEMDEEP_PROJECTS_DIR", "data/projects"))

    # 兼容旧配置 (作为总入口，暂保留)
    LIBRARY_DIR = Path(os.getenv("CHEMDEEP_LIBRARY_DIR", "data/library"))

    # ========== 本地模型配置 (Ollama/LM Studio) ==========
    LOCAL_LLM_API_BASE = os.getenv(
        "CHEMDEEP_LOCAL_LLM_API_BASE", "http://localhost:11434/v1"
    )
    LOCAL_LLM_MODEL = os.getenv("CHEMDEEP_LOCAL_LLM_MODEL", "qwen2.5:7b")
    LOCAL_LLM_API_KEY = os.getenv(
        "CHEMDEEP_LOCAL_LLM_API_KEY", "ollama"
    )  # Ollama 不需要真实 key

    # ========== 搜索配置 ==========
    ENABLE_GOOGLE_SCHOLAR = os.getenv("CHEMDEEP_ENABLE_GOOGLE_SCHOLAR", "0") == "1"
    GOOGLE_SCHOLAR_DELAY = int(os.getenv("CHEMDEEP_GOOGLE_SCHOLAR_DELAY", "5"))

    # 烂番薯学术配置
    ENABLE_LANFANSHU = os.getenv("CHEMDEEP_ENABLE_LANFANSHU", "0") == "1"
    LANFANSHU_DELAY = int(os.getenv("CHEMDEEP_LANFANSHU_DELAY", "5"))

    # 推理功能配置
    ENABLE_REASONING = os.getenv("CHEMDEEP_ENABLE_REASONING", "1") == "1"

    # MCP 配置
    MCP_SERVER_DIR = Path(
        os.getenv("CHEMDEEP_MCP_SERVER_DIR", "paper-search-mcp-nodejs")
    )
    MCP_SERVER_COMMAND = "node"
    MCP_SERVER_COMMAND = "node"
    MCP_SERVER_ARGS = ["dist/server.js"]

    # MCP Web Search Config (Python)
    MCP_WEBSEARCH_COMMAND = "python"
    MCP_WEBSEARCH_ARGS = ["mcp-websearch/search_mcp.py"]

    MCP_WOS_API_KEY = os.getenv("WOS_API_KEY")  # 优先从环境变量读取
    MCP_WOS_API_VERSION = os.getenv("WOS_API_VERSION", "v1")
    MCP_OPENALEX_API_KEY = os.getenv("OPENALEX_API_KEY")  # OpenAlex API Key

    @classmethod
    def validate(cls) -> list[str]:
        """验证配置，返回错误列表"""
        errors = []

        if not cls.TELEGRAM_TOKEN:
            errors.append("CHEMDEEP_TELEGRAM_TOKEN 未配置")

        if not cls.TELEGRAM_ALLOWED_CHAT_IDS:
            errors.append("CHEMDEEP_TELEGRAM_ALLOWED_CHAT_IDS 未配置")

        if not cls.OPENAI_API_KEY and not cls.GEMINI_API_KEY:
            errors.append("至少需要配置一个 AI API (OPENAI 或 GEMINI)")

        return errors

    @classmethod
    def summary(cls) -> str:
        """返回配置摘要"""
        lines = [
            "⚙️ 当前配置:",
            "",
            "【Telegram】",
            f"  Token: {'✅ 已配置' if cls.TELEGRAM_TOKEN else '❌ 未配置'}",
            f"  Proxy: {cls.TELEGRAM_PROXY or '无'}",
            f"  Chat ID: {cls.TELEGRAM_CHAT_ID}",
            f"  Allowed IDs: {cls.TELEGRAM_ALLOWED_CHAT_IDS}",
            "",
            "【AI】",
            f"  Provider: {cls.AI_PROVIDER}",
            f"  OpenAI Key: {'✅ 已配置' if cls.OPENAI_API_KEY else '❌ 未配置'}",
            f"  OpenAI Base: {cls.OPENAI_API_BASE}",
            f"  OpenAI Model: {cls.OPENAI_MODEL}",
            f"  Gemini Key: {'✅ 已配置' if cls.GEMINI_API_KEY else '❌ 未配置'}",
            f"  Gemini Model: {cls.GEMINI_MODEL}",
            f"  Timeout: {cls.AI_TIMEOUT}s",
            f"  Max Retries: {cls.AI_MAX_RETRIES}",
            "",
            "【浏览器】",
            f"  Profile: {cls.PROFILE_DIR}",
            f"  Library: {cls.LIBRARY_DIR}",
            f"  Rate: {cls.RATE_SECONDS}s",
            f"  Headless: {cls.HEADLESS}",
            f"  Channel: {cls.BROWSER_CHANNEL}",
        ]
        return "\n".join(lines)


settings = Settings()
