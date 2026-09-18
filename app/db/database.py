import sqlite3
import threading
from contextlib import contextmanager
from app.config import DB_PATH

_local = threading.local()

def get_connection() -> sqlite3.Connection:
    """Get a thread-local SQLite connection with WAL mode and row factory."""
    if not hasattr(_local, "conn") or _local.conn is None:
        conn = sqlite3.connect(
            str(DB_PATH),
            timeout=60.0,
            check_same_thread=False
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        conn.execute("PRAGMA busy_timeout=60000;")
        conn.execute("PRAGMA temp_store=MEMORY;")
        conn.execute("PRAGMA cache_size=-64000;")
        _local.conn = conn
    return _local.conn

@contextmanager
def db_session():
    """Context manager for database operations with automatic commit/rollback."""
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise

def init_db():
    """Initialize database tables and indexes."""
    with db_session() as conn:
        cursor = conn.cursor()
        
        # Tasks table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            target_url TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            config TEXT NOT NULL,
            pages_crawled INTEGER DEFAULT 0,
            pages_total INTEGER DEFAULT 0,
            external_domains_count INTEGER DEFAULT 0,
            subdomains_count INTEGER DEFAULT 0,
            current_url TEXT DEFAULT '',
            started_at TEXT DEFAULT NULL,
            finished_at TEXT DEFAULT NULL,
            error_message TEXT DEFAULT NULL,
            created_at TEXT NOT NULL
        );
        """)

        # Migration: ensure subdomains_count exists on tasks table
        cursor.execute("PRAGMA table_info(tasks);")
        task_cols = [r[1] for r in cursor.fetchall()]
        if "subdomains_count" not in task_cols:
            cursor.execute("ALTER TABLE tasks ADD COLUMN subdomains_count INTEGER DEFAULT 0;")

        # Sitemap pages table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS sitemap_pages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER NOT NULL,
            url TEXT NOT NULL,
            path TEXT NOT NULL,
            depth INTEGER NOT NULL DEFAULT 0,
            status_code INTEGER DEFAULT 0,
            content_type TEXT DEFAULT '',
            title TEXT DEFAULT '',
            response_time_ms INTEGER DEFAULT 0,
            external_domains_count INTEGER DEFAULT 0,
            crawled_at TEXT NOT NULL,
            error TEXT DEFAULT NULL,
            FOREIGN KEY(task_id) REFERENCES tasks(id) ON DELETE CASCADE,
            UNIQUE(task_id, url)
        );
        """)

        # External domains summary table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS external_domains (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER NOT NULL,
            domain TEXT NOT NULL,
            root_domain TEXT NOT NULL,
            occurrence_count INTEGER DEFAULT 1,
            has_link INTEGER DEFAULT 0,
            has_text INTEGER DEFAULT 0,
            sample_page_url TEXT DEFAULT '',
            created_at TEXT NOT NULL,
            FOREIGN KEY(task_id) REFERENCES tasks(id) ON DELETE CASCADE,
            UNIQUE(task_id, domain)
        );
        """)

        # Domain occurrences detail table (for provenance & context inspection)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS domain_occurrences (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER NOT NULL,
            page_id INTEGER,
            domain TEXT NOT NULL,
            page_url TEXT NOT NULL,
            source_type TEXT NOT NULL,
            raw_match TEXT NOT NULL,
            context_snippet TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(task_id) REFERENCES tasks(id) ON DELETE CASCADE,
            FOREIGN KEY(page_id) REFERENCES sitemap_pages(id) ON DELETE CASCADE
        );
        """)

        # Task logs table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS task_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER NOT NULL,
            level TEXT NOT NULL DEFAULT 'INFO',
            message TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(task_id) REFERENCES tasks(id) ON DELETE CASCADE
        );
        """)

        # Discovered subdomains summary table (belonging to target site root domain)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS discovered_subdomains (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER NOT NULL,
            subdomain TEXT NOT NULL,
            root_domain TEXT NOT NULL,
            occurrence_count INTEGER DEFAULT 1,
            has_link INTEGER DEFAULT 0,
            has_text INTEGER DEFAULT 0,
            sample_page_url TEXT DEFAULT '',
            created_at TEXT NOT NULL,
            FOREIGN KEY(task_id) REFERENCES tasks(id) ON DELETE CASCADE,
            UNIQUE(task_id, subdomain)
        );
        """)

        # Indexes for fast lookup and join
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_sitemap_task ON sitemap_pages(task_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_sitemap_url ON sitemap_pages(task_id, url);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_extdomains_task ON external_domains(task_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_extdomains_domain ON external_domains(task_id, domain);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_extdomains_root ON external_domains(task_id, root_domain);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_subdomains_task ON discovered_subdomains(task_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_subdomains_sub ON discovered_subdomains(task_id, subdomain);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_occurrences_task ON domain_occurrences(task_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_occurrences_domain ON domain_occurrences(task_id, domain);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_occurrences_page ON domain_occurrences(page_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_task_logs_task ON task_logs(task_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_extdomains_only_domain ON external_domains(domain);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_extdomains_only_root ON external_domains(root_domain);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_subdomains_only_sub ON discovered_subdomains(subdomain);")
