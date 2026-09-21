import os
import queue
import sqlite3
import threading
from contextlib import contextmanager
from typing import Optional, Any, List, Dict
from app.config import (
    DB_TYPE, DB_PATH, PG_HOST, PG_PORT, PG_USER, PG_PASSWORD, PG_DATABASE, PG_POOL_SIZE
)

_local = threading.local()
_pg_pool: Optional["PGConnectionPool"] = None
_pg_pool_lock = threading.Lock()


class RowDict(dict):
    """
    A row wrapper supporting:
    - Dict key access: row['domain'], row.get('domain')
    - Dict conversion: dict(row)
    - Numeric index access: row[0], row[1]
    - Direct key inspection: 'domain' in row
    This matches sqlite3.Row functionality seamlessly across both SQLite and PostgreSQL.
    """
    def __init__(self, cols: List[str], values: Any):
        super().__init__(zip(cols, values))
        self._values = tuple(values)
        self._cols = cols

    def __getitem__(self, key: Any) -> Any:
        if isinstance(key, int):
            return self._values[key]
        return super().__getitem__(key)

    def get(self, key: Any, default: Any = None) -> Any:
        if isinstance(key, int):
            if 0 <= key < len(self._values):
                return self._values[key]
            return default
        return super().get(key, default)


class PGCursorWrapper:
    """Cursor wrapper for PostgreSQL connection, providing DB-API compatibility with SQLite."""
    def __init__(self, raw_cursor):
        self.cur = raw_cursor
        self._lastrowid = None

    def execute(self, sql: str, params: Any = None):
        self._lastrowid = None
        sql_stripped = sql.strip()
        upper_sql = sql_stripped.upper()

        # Handle autoincrement ID retrieval for INSERT statements automatically
        needs_returning = upper_sql.startswith("INSERT INTO") and "RETURNING" not in upper_sql
        if needs_returning:
            sql_exec = sql_stripped.rstrip(";") + " RETURNING id;"
        else:
            sql_exec = sql_stripped

        # Adapt parameter placeholders from '?' (SQLite) to '%s' (PostgreSQL)
        if "?" in sql_exec:
            sql_exec = sql_exec.replace("?", "%s")

        if params is None:
            res = self.cur.execute(sql_exec)
        else:
            res = self.cur.execute(sql_exec, params)

        if needs_returning:
            try:
                row = self.cur.fetchone()
                if row:
                    self._lastrowid = row[0]
            except Exception:
                pass

        return res

    def executemany(self, sql: str, seq_of_params: Any):
        if "?" in sql:
            sql = sql.replace("?", "%s")
        return self.cur.executemany(sql, seq_of_params)

    def fetchone(self) -> Optional[RowDict]:
        row = self.cur.fetchone()
        if row is None:
            return None
        cols = [d[0] for d in self.cur.description]
        return RowDict(cols, row)

    def fetchall(self) -> List[RowDict]:
        rows = self.cur.fetchall()
        if not rows:
            return []
        cols = [d[0] for d in self.cur.description]
        return [RowDict(cols, r) for r in rows]

    @property
    def lastrowid(self):
        return self._lastrowid

    @property
    def rowcount(self):
        return self.cur.rowcount

    def close(self):
        return self.cur.close()

    def __getattr__(self, name: str) -> Any:
        return getattr(self.cur, name)


class PGConnectionWrapper:
    """Connection wrapper providing context management and execution helper."""
    def __init__(self, raw_conn):
        self.conn = raw_conn

    def cursor(self) -> PGCursorWrapper:
        return PGCursorWrapper(self.conn.cursor())

    def commit(self):
        return self.conn.commit()

    def rollback(self):
        return self.conn.rollback()

    def close(self):
        return self.conn.close()

    def execute(self, sql: str, params: Any = None):
        cur = self.cursor()
        cur.execute(sql, params)
        return cur

    def __getattr__(self, name: str) -> Any:
        return getattr(self.conn, name)


class PGConnectionPool:
    """Thread-safe connection pool for PostgreSQL."""
    def __init__(self, host: str, port: int, user: str, password: str, database: str, max_connections: int = 25):
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.database = database
        self.max_connections = max_connections
        self.pool: queue.Queue = queue.Queue(maxsize=max_connections)
        self.lock = threading.Lock()
        self.created_count = 0

    def _connect(self):
        import pg8000.dbapi
        return pg8000.dbapi.connect(
            user=self.user,
            host=self.host,
            port=self.port,
            database=self.database,
            password=self.password
        )

    def get_connection(self):
        while True:
            try:
                conn = self.pool.get_nowait()
                try:
                    cur = conn.cursor()
                    cur.execute("SELECT 1;")
                    cur.close()
                    return conn
                except Exception:
                    try:
                        conn.close()
                    except Exception:
                        pass
                    with self.lock:
                        self.created_count -= 1
            except queue.Empty:
                break

        with self.lock:
            if self.created_count < self.max_connections:
                conn = self._connect()
                self.created_count += 1
                return conn

        return self.pool.get(timeout=30)

    def release_connection(self, conn, error: bool = False):
        if error:
            try:
                conn.rollback()
            except Exception:
                pass
            try:
                conn.close()
            except Exception:
                pass
            with self.lock:
                self.created_count -= 1
            return

        try:
            conn.commit()
        except Exception:
            pass
        try:
            self.pool.put_nowait(conn)
        except queue.Full:
            try:
                conn.close()
            except Exception:
                pass
            with self.lock:
                self.created_count -= 1


def get_pg_pool() -> PGConnectionPool:
    """Get or initialize the global PostgreSQL connection pool."""
    global _pg_pool
    if _pg_pool is None:
        with _pg_pool_lock:
            if _pg_pool is None:
                _pg_pool = PGConnectionPool(
                    host=PG_HOST,
                    port=PG_PORT,
                    user=PG_USER,
                    password=PG_PASSWORD,
                    database=PG_DATABASE,
                    max_connections=PG_POOL_SIZE
                )
    return _pg_pool


def get_sqlite_connection() -> sqlite3.Connection:
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


def get_connection():
    """Get active database connection depending on DB_TYPE."""
    if DB_TYPE == "postgresql":
        raw = get_pg_pool().get_connection()
        return PGConnectionWrapper(raw)
    else:
        return get_sqlite_connection()


@contextmanager
def db_session():
    """Context manager for database operations with automatic commit/rollback and connection pool release."""
    if DB_TYPE == "postgresql":
        pool = get_pg_pool()
        raw_conn = pool.get_connection()
        conn = PGConnectionWrapper(raw_conn)
        is_err = False
        try:
            yield conn
            conn.commit()
        except Exception:
            is_err = True
            conn.rollback()
            raise
        finally:
            pool.release_connection(raw_conn, error=is_err)
    else:
        conn = get_sqlite_connection()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise


def init_db():
    """Initialize database tables and indexes based on DB_TYPE."""
    if DB_TYPE == "postgresql":
        init_db_postgresql()
    else:
        init_db_sqlite()


def init_db_postgresql():
    """Initialize PostgreSQL tables, partitions, and specialized indexes."""
    with db_session() as conn:
        cursor = conn.cursor()

        # Tasks table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id SERIAL PRIMARY KEY,
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

        # Sitemap pages table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS sitemap_pages (
            id SERIAL PRIMARY KEY,
            task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
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
            UNIQUE(task_id, url)
        );
        """)

        # External domains summary table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS external_domains (
            id SERIAL PRIMARY KEY,
            task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
            domain TEXT NOT NULL,
            root_domain TEXT NOT NULL,
            occurrence_count INTEGER DEFAULT 1,
            has_link INTEGER DEFAULT 0,
            has_text INTEGER DEFAULT 0,
            sample_page_url TEXT DEFAULT '',
            risk_level TEXT DEFAULT 'pending',
            risk_tags TEXT DEFAULT '[]',
            risk_remark TEXT DEFAULT '',
            risk_source TEXT DEFAULT '',
            verify_status TEXT DEFAULT 'unverified',
            verify_time TEXT DEFAULT NULL,
            verify_detail TEXT DEFAULT '',
            created_at TEXT NOT NULL,
            UNIQUE(task_id, domain)
        );
        """)

        # Global domain risk intelligence & profile rules table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS domain_risk_profiles (
            id SERIAL PRIMARY KEY,
            domain TEXT NOT NULL UNIQUE,
            match_type TEXT NOT NULL DEFAULT 'root',
            risk_level TEXT NOT NULL,
            category TEXT DEFAULT '',
            tags TEXT DEFAULT '[]',
            source TEXT DEFAULT 'manual',
            remark TEXT DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        """)

        # Domain occurrences detail table (BIGSERIAL for massive scale)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS domain_occurrences (
            id BIGSERIAL PRIMARY KEY,
            task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
            page_id INTEGER REFERENCES sitemap_pages(id) ON DELETE CASCADE,
            domain TEXT NOT NULL,
            page_url TEXT NOT NULL,
            source_type TEXT NOT NULL,
            raw_match TEXT NOT NULL,
            context_snippet TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        """)

        # Task logs table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS task_logs (
            id SERIAL PRIMARY KEY,
            task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
            level TEXT NOT NULL DEFAULT 'INFO',
            message TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        """)

        # Discovered subdomains summary table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS discovered_subdomains (
            id SERIAL PRIMARY KEY,
            task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
            subdomain TEXT NOT NULL,
            root_domain TEXT NOT NULL,
            occurrence_count INTEGER DEFAULT 1,
            has_link INTEGER DEFAULT 0,
            has_text INTEGER DEFAULT 0,
            sample_page_url TEXT DEFAULT '',
            created_at TEXT NOT NULL,
            UNIQUE(task_id, subdomain)
        );
        """)

        # Standard B-Tree Indexes (UNIQUE(task_id, url) already creates an index for sitemap_pages)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_sitemap_task ON sitemap_pages(task_id);")
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
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_extdomains_risk ON external_domains(task_id, risk_level);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_extdomains_verify ON external_domains(task_id, verify_status);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_risk_profile_domain ON domain_risk_profiles(domain);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_risk_profile_level ON domain_risk_profiles(risk_level);")

        # GIN Trigram Indexes for Ultra-Fast Substring/Wildcard Domain Lookups
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_extdomains_trgm_domain ON external_domains USING gin (domain gin_trgm_ops);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_extdomains_trgm_root ON external_domains USING gin (root_domain gin_trgm_ops);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_occurrences_trgm_domain ON domain_occurrences USING gin (domain gin_trgm_ops);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_risk_profile_trgm_domain ON domain_risk_profiles USING gin (domain gin_trgm_ops);")


def init_db_sqlite():
    """Initialize SQLite tables and indexes."""
    with db_session() as conn:
        cursor = conn.cursor()

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

        cursor.execute("PRAGMA table_info(tasks);")
        task_cols = [r[1] for r in cursor.fetchall()]
        if "subdomains_count" not in task_cols:
            cursor.execute("ALTER TABLE tasks ADD COLUMN subdomains_count INTEGER DEFAULT 0;")

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
            risk_level TEXT DEFAULT 'pending',
            risk_tags TEXT DEFAULT '[]',
            risk_remark TEXT DEFAULT '',
            risk_source TEXT DEFAULT '',
            verify_status TEXT DEFAULT 'unverified',
            verify_time TEXT DEFAULT NULL,
            verify_detail TEXT DEFAULT '',
            created_at TEXT NOT NULL,
            FOREIGN KEY(task_id) REFERENCES tasks(id) ON DELETE CASCADE,
            UNIQUE(task_id, domain)
        );
        """)

        cursor.execute("PRAGMA table_info(external_domains);")
        ext_cols = [r[1] for r in cursor.fetchall()]
        if "risk_level" not in ext_cols:
            cursor.execute("ALTER TABLE external_domains ADD COLUMN risk_level TEXT DEFAULT 'pending';")
        if "risk_tags" not in ext_cols:
            cursor.execute("ALTER TABLE external_domains ADD COLUMN risk_tags TEXT DEFAULT '[]';")
        if "risk_remark" not in ext_cols:
            cursor.execute("ALTER TABLE external_domains ADD COLUMN risk_remark TEXT DEFAULT '';")
        if "risk_source" not in ext_cols:
            cursor.execute("ALTER TABLE external_domains ADD COLUMN risk_source TEXT DEFAULT '';")
        if "verify_status" not in ext_cols:
            cursor.execute("ALTER TABLE external_domains ADD COLUMN verify_status TEXT DEFAULT 'unverified';")
        if "verify_time" not in ext_cols:
            cursor.execute("ALTER TABLE external_domains ADD COLUMN verify_time TEXT DEFAULT NULL;")
        if "verify_detail" not in ext_cols:
            cursor.execute("ALTER TABLE external_domains ADD COLUMN verify_detail TEXT DEFAULT '';")

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS domain_risk_profiles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            domain TEXT NOT NULL UNIQUE,
            match_type TEXT NOT NULL DEFAULT 'root',
            risk_level TEXT NOT NULL,
            category TEXT DEFAULT '',
            tags TEXT DEFAULT '[]',
            source TEXT DEFAULT 'manual',
            remark TEXT DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        """)

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

        # Indexes
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
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_extdomains_risk ON external_domains(task_id, risk_level);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_extdomains_verify ON external_domains(task_id, verify_status);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_risk_profile_domain ON domain_risk_profiles(domain);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_risk_profile_level ON domain_risk_profiles(risk_level);")
