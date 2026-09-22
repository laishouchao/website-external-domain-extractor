import os
import queue
import threading
import logging
from contextlib import contextmanager
from typing import Optional, Any, List, Dict
from app.config import (
    PG_HOST, PG_PORT, PG_USER, PG_PASSWORD, PG_DATABASE, PG_POOL_SIZE
)

logger = logging.getLogger("uvicorn.error")

_pg_pool: Optional["PGConnectionPool"] = None
_pg_pool_lock = threading.Lock()


class RowDict(dict):
    """
    A row wrapper supporting:
    - Dict key access: row['domain'], row.get('domain')
    - Dict conversion: dict(row)
    - Numeric index access: row[0], row[1]
    - Direct key inspection: 'domain' in row
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
    """Cursor wrapper for PostgreSQL connection, providing DB-API compatibility with ? and lastrowid."""
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

        # Adapt parameter placeholders from '?' to '%s'
        # In psycopg2/pg8000 format paramstyle, any literal '%' in SQL must be escaped to '%%'
        # when query params are provided, otherwise psycopg2 mistakes literal '%' for param formatters.
        if params is not None and "?" in sql_exec:
            sql_exec = sql_exec.replace("%", "%%").replace("?", "%s")
        elif "?" in sql_exec:
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
        if seq_of_params and "?" in sql:
            sql = sql.replace("%", "%%").replace("?", "%s")
        elif "?" in sql:
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
    """Thread-safe connection pool for PostgreSQL with dual-driver auto detection."""
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
        try:
            import psycopg2
            return psycopg2.connect(
                host=self.host,
                port=self.port,
                user=self.user,
                password=self.password,
                dbname=self.database
            )
        except ImportError:
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
                    conn.rollback()  # Reset transaction state so connection is clean
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
            conn.rollback()  # Ensure connection is clean and not 'idle in transaction' in pool
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


def get_connection() -> PGConnectionWrapper:
    """Get an active PostgreSQL connection wrapper from pool."""
    raw = get_pg_pool().get_connection()
    return PGConnectionWrapper(raw)


@contextmanager
def db_session():
    """Context manager for PostgreSQL operations with automatic commit/rollback and connection pool release."""
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


def init_db():
    """Initialize PostgreSQL database tables, extensions, and indexes."""
    init_db_postgresql()


def init_db_postgresql():
    """Initialize PostgreSQL tables, partitions, and specialized indexes."""
    # Ensure extensions are created
    try:
        raw_conn = get_pg_pool().get_connection()
        try:
            cur = raw_conn.cursor()
            cur.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm;")
            cur.execute("CREATE EXTENSION IF NOT EXISTS btree_gin;")
            raw_conn.commit()
            cur.close()
        except Exception:
            try:
                raw_conn.rollback()
            except Exception:
                pass
        finally:
            get_pg_pool().release_connection(raw_conn)
    except Exception:
        pass

    # 1. Inspect existing tables and indexes to avoid unnecessary DDL and lock contention
    existing_tables = set()
    existing_indexes = set()
    try:
        with db_session() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public';")
            existing_tables = {row[0].lower() for row in cursor.fetchall()}
            cursor.execute("SELECT indexname FROM pg_indexes WHERE schemaname = 'public';")
            existing_indexes = {row[0].lower() for row in cursor.fetchall()}
    except Exception as e:
        logger.warning(f"Failed to inspect existing tables and indexes: {e}")

    # Tables to create if missing
    tables = [
        ("tasks", """
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
        """),
        ("sitemap_pages", """
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
        """),
        ("external_domains", """
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
        """),
        ("domain_risk_profiles", """
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
        """),
        ("domain_occurrences", """
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
        """),
        ("task_logs", """
        CREATE TABLE IF NOT EXISTS task_logs (
            id SERIAL PRIMARY KEY,
            task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
            level TEXT NOT NULL DEFAULT 'INFO',
            message TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        """),
        ("discovered_subdomains", """
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
        """),
        ("risk_page_remediations", """
        CREATE TABLE IF NOT EXISTS risk_page_remediations (
            id SERIAL PRIMARY KEY,
            task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
            domain TEXT NOT NULL,
            root_domain TEXT NOT NULL,
            page_url TEXT NOT NULL,
            page_title TEXT DEFAULT '',
            source_type TEXT NOT NULL DEFAULT 'href',
            raw_match TEXT NOT NULL DEFAULT '',
            context_snippet TEXT NOT NULL DEFAULT '',
            risk_level TEXT NOT NULL,
            risk_tags TEXT DEFAULT '[]',
            risk_remark TEXT DEFAULT '',
            verify_status TEXT NOT NULL DEFAULT 'unverified',
            last_verified_at TEXT DEFAULT NULL,
            last_verify_detail TEXT DEFAULT '',
            manual_status TEXT DEFAULT 'pending',
            manual_remark TEXT DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(task_id, domain, page_url)
        );
        """),
    ]

    for tbl_name, ddl in tables:
        if tbl_name.lower() not in existing_tables:
            try:
                with db_session() as conn:
                    cursor = conn.cursor()
                    cursor.execute("SET lock_timeout = '5s';")
                    cursor.execute(ddl)
                existing_tables.add(tbl_name.lower())
                logger.info(f"Initialized table: {tbl_name}")
            except Exception as e:
                logger.error(f"Error initializing table {tbl_name}: {e}")

    # Indexes to create if missing
    indexes = [
        ("idx_sitemap_task", "CREATE INDEX IF NOT EXISTS idx_sitemap_task ON sitemap_pages(task_id);"),
        ("idx_extdomains_task", "CREATE INDEX IF NOT EXISTS idx_extdomains_task ON external_domains(task_id);"),
        ("idx_extdomains_domain", "CREATE INDEX IF NOT EXISTS idx_extdomains_domain ON external_domains(task_id, domain);"),
        ("idx_extdomains_root", "CREATE INDEX IF NOT EXISTS idx_extdomains_root ON external_domains(task_id, root_domain);"),
        ("idx_subdomains_task", "CREATE INDEX IF NOT EXISTS idx_subdomains_task ON discovered_subdomains(task_id);"),
        ("idx_subdomains_sub", "CREATE INDEX IF NOT EXISTS idx_subdomains_sub ON discovered_subdomains(task_id, subdomain);"),
        ("idx_occurrences_task", "CREATE INDEX IF NOT EXISTS idx_occurrences_task ON domain_occurrences(task_id);"),
        ("idx_occurrences_domain", "CREATE INDEX IF NOT EXISTS idx_occurrences_domain ON domain_occurrences(task_id, domain);"),
        ("idx_occurrences_page", "CREATE INDEX IF NOT EXISTS idx_occurrences_page ON domain_occurrences(page_id);"),
        ("idx_task_logs_task", "CREATE INDEX IF NOT EXISTS idx_task_logs_task ON task_logs(task_id);"),
        ("idx_extdomains_only_domain", "CREATE INDEX IF NOT EXISTS idx_extdomains_only_domain ON external_domains(domain);"),
        ("idx_extdomains_only_root", "CREATE INDEX IF NOT EXISTS idx_extdomains_only_root ON external_domains(root_domain);"),
        ("idx_subdomains_only_sub", "CREATE INDEX IF NOT EXISTS idx_subdomains_only_sub ON discovered_subdomains(subdomain);"),
        ("idx_extdomains_risk", "CREATE INDEX IF NOT EXISTS idx_extdomains_risk ON external_domains(task_id, risk_level);"),
        ("idx_extdomains_verify", "CREATE INDEX IF NOT EXISTS idx_extdomains_verify ON external_domains(task_id, verify_status);"),
        ("idx_risk_profile_domain", "CREATE INDEX IF NOT EXISTS idx_risk_profile_domain ON domain_risk_profiles(domain);"),
        ("idx_risk_profile_level", "CREATE INDEX IF NOT EXISTS idx_risk_profile_level ON domain_risk_profiles(risk_level);"),
        ("idx_remediation_task", "CREATE INDEX IF NOT EXISTS idx_remediation_task ON risk_page_remediations(task_id);"),
        ("idx_remediation_status", "CREATE INDEX IF NOT EXISTS idx_remediation_status ON risk_page_remediations(verify_status);"),
        ("idx_remediation_level", "CREATE INDEX IF NOT EXISTS idx_remediation_level ON risk_page_remediations(risk_level);"),
        ("idx_remediation_domain", "CREATE INDEX IF NOT EXISTS idx_remediation_domain ON risk_page_remediations(domain);"),
        ("idx_remediation_root", "CREATE INDEX IF NOT EXISTS idx_remediation_root ON risk_page_remediations(root_domain);"),
        ("idx_remediation_manual", "CREATE INDEX IF NOT EXISTS idx_remediation_manual ON risk_page_remediations(manual_status);"),
        ("idx_extdomains_trgm_domain", "CREATE INDEX IF NOT EXISTS idx_extdomains_trgm_domain ON external_domains USING gin (domain gin_trgm_ops);"),
        ("idx_extdomains_trgm_root", "CREATE INDEX IF NOT EXISTS idx_extdomains_trgm_root ON external_domains USING gin (root_domain gin_trgm_ops);"),
        ("idx_occurrences_trgm_domain", "CREATE INDEX IF NOT EXISTS idx_occurrences_trgm_domain ON domain_occurrences USING gin (domain gin_trgm_ops);"),
        ("idx_risk_profile_trgm_domain", "CREATE INDEX IF NOT EXISTS idx_risk_profile_trgm_domain ON domain_risk_profiles USING gin (domain gin_trgm_ops);"),
        ("idx_remediation_trgm_domain", "CREATE INDEX IF NOT EXISTS idx_remediation_trgm_domain ON risk_page_remediations USING gin (domain gin_trgm_ops);"),
    ]

    for idx_name, ddl in indexes:
        if idx_name.lower() not in existing_indexes:
            try:
                with db_session() as conn:
                    cursor = conn.cursor()
                    cursor.execute("SET lock_timeout = '5s';")
                    cursor.execute(ddl)
                existing_indexes.add(idx_name.lower())
                logger.info(f"Created missing index: {idx_name}")
            except Exception as e:
                logger.warning(f"Could not create index {idx_name} (skipped to prevent block): {e}")
