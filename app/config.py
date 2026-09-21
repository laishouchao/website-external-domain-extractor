import os
from pathlib import Path

# Base directories
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True, parents=True)

# Database engine configuration ('postgresql' or 'sqlite')
DB_TYPE = os.getenv("DB_TYPE", "postgresql").lower()

# SQLite configuration
DB_PATH = DATA_DIR / "crawler.db"

# PostgreSQL configuration
PG_HOST = os.getenv("PG_HOST", "202.194.101.181")
PG_PORT = int(os.getenv("PG_PORT", 5432))
PG_USER = os.getenv("PG_USER", "postgres")
PG_PASSWORD = os.getenv("PG_PASSWORD", "Cernet@2026")
PG_DATABASE = os.getenv("PG_DATABASE", "website_domain_db")
PG_POOL_SIZE = int(os.getenv("PG_POOL_SIZE", 25))

# Server configuration
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", 8000))

# Crawler default options
DEFAULT_CRAWLER_CONFIG = {
    "max_depth": 10,              # 0 means unlimited depth
    "max_pages": 1000,           # 0 means unlimited pages
    "concurrency": 15,           # Number of concurrent worker coroutines
    "request_delay": 0.0,        # Delay between requests in seconds
    "batch_size": 25,            # SQLite write batch size (pages per commit)
    "timeout": 10.0,             # HTTP timeout in seconds
    "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "ignore_ssl": True,          # Ignore SSL certificate verification (helpful for intranet/test sites)
    "detect_sitemap": True,      # Automatically parse /sitemap.xml and /robots.txt
    "scope_mode": "root_domain", # 'root_domain' (all subdomains internal) or 'exact_host' (only same hostname internal)
    "extract_assets": True,      # Extract domains from img/script/css assets as well as hrefs
    "extract_text": True,        # Extract domains from raw text, script bodies and comments
    "scan_asset_content": True,  # Directly fetch and scan standalone JS/CSS file content in-memory (no local saving)
    "max_asset_size_kb": 3072,   # Max asset size to read in-memory in KB (default 3MB)
}

