import os
from pathlib import Path

# Base directories
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True, parents=True)

# Load environment variables from .env file
try:
    from dotenv import load_dotenv
    load_dotenv(BASE_DIR / ".env", override=False)
except ImportError:
    env_file = BASE_DIR / ".env"
    if env_file.exists():
        try:
            with open(env_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        k = k.strip()
                        v = v.strip().strip("'\"")
                        if k and k not in os.environ:
                            os.environ[k] = v
        except Exception:
            pass


def _bool_env(key: str, default: bool) -> bool:
    val = os.getenv(key)
    if val is None:
        return default
    return val.strip().lower() in ("true", "1", "yes", "on")


# ==============================================================================
# PostgreSQL Database Configuration
# ==============================================================================
PG_HOST = os.getenv("PG_HOST", "127.0.0.1")
PG_PORT = int(os.getenv("PG_PORT", 5432))
PG_USER = os.getenv("PG_USER", "postgres")
PG_PASSWORD = os.getenv("PG_PASSWORD", "")
PG_DATABASE = os.getenv("PG_DATABASE", "website_domain_db")
PG_POOL_SIZE = int(os.getenv("PG_POOL_SIZE", 25))

# ==============================================================================
# Server Configuration
# ==============================================================================
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", 8000))

# ==============================================================================
# Crawler Default Options
# ==============================================================================
DEFAULT_CRAWLER_CONFIG = {
    "max_depth": int(os.getenv("CRAWLER_MAX_DEPTH", 10)),
    "max_pages": int(os.getenv("CRAWLER_MAX_PAGES", 1000)),
    "concurrency": int(os.getenv("CRAWLER_CONCURRENCY", 35)),
    "request_delay": float(os.getenv("CRAWLER_REQUEST_DELAY", 0.0)),
    "batch_size": int(os.getenv("CRAWLER_BATCH_SIZE", 50)),
    "timeout": float(os.getenv("CRAWLER_TIMEOUT", 10.0)),
    "user_agent": os.getenv("CRAWLER_USER_AGENT", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"),
    "ignore_ssl": _bool_env("CRAWLER_IGNORE_SSL", True),
    "detect_sitemap": _bool_env("CRAWLER_DETECT_SITEMAP", True),
    "scope_mode": os.getenv("CRAWLER_SCOPE_MODE", "root_domain"),
    "extract_assets": _bool_env("CRAWLER_EXTRACT_ASSETS", True),
    "extract_text": _bool_env("CRAWLER_EXTRACT_TEXT", True),
    "scan_asset_content": _bool_env("CRAWLER_SCAN_ASSET_CONTENT", True),
    "max_asset_size_kb": int(os.getenv("CRAWLER_MAX_ASSET_SIZE_KB", 3072)),
}
