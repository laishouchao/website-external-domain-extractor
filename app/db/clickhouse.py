import logging
import threading
import time
from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime

from app.config import (
    CH_ENABLED, CH_HOST, CH_PORT, CH_USER, CH_PASSWORD, CH_DATABASE
)

logger = logging.getLogger("uvicorn.error")

_ch_manager: Optional["ClickHouseManager"] = None
_ch_lock = threading.Lock()


class ClickHouseManager:
    """Thread-safe ClickHouse client manager with graceful degradation and auto-reconnect."""

    def __init__(self):
        self.enabled = CH_ENABLED
        self.host = CH_HOST
        self.port = CH_PORT
        self.user = CH_USER
        self.password = CH_PASSWORD
        self.database = CH_DATABASE

        self._client = None
        self._lock = threading.Lock()
        self._last_connect_attempt = 0.0
        self._is_alive = False

    def get_client(self):
        """Acquire or lazily establish connection to ClickHouse."""
        if not self.enabled:
            return None

        with self._lock:
            now = time.time()
            if self._client is not None and self._is_alive:
                return self._client

            # Throttle reconnection attempts on failure (min 10 seconds between attempts)
            if now - self._last_connect_attempt < 10.0:
                return None

            self._last_connect_attempt = now
            try:
                import clickhouse_connect
                client = clickhouse_connect.get_client(
                    host=self.host,
                    port=self.port,
                    username=self.user,
                    password=self.password,
                    connect_timeout=3,
                    send_receive_timeout=15,
                    compress=True
                )
                # Verify connectivity
                res = client.command("SELECT 1")
                if res == 1:
                    self._client = client
                    self._is_alive = True
                    logger.info(f"[ClickHouse] Connected to {self.host}:{self.port} (database: {self.database})")
                    return self._client
            except Exception as e:
                self._client = None
                self._is_alive = False
                logger.warning(f"[ClickHouse] Unavailable at {self.host}:{self.port} ({e}). Falling back to PostgreSQL.")
                return None

    def is_available(self) -> bool:
        """Check whether ClickHouse is active and available."""
        if not self.enabled:
            return False
        return self.get_client() is not None

    def init_db(self):
        """Create ClickHouse database and optimized MergeTree tables if not exist."""
        client = self.get_client()
        if not client:
            return False

        try:
            # 1. Create database
            client.command(f"CREATE DATABASE IF NOT EXISTS {self.database}")

            # 2. Table: domain_occurrences
            client.command(f"""
                CREATE TABLE IF NOT EXISTS {self.database}.domain_occurrences (
                    id UInt64,
                    task_id UInt32,
                    domain String,
                    root_domain LowCardinality(String),
                    page_url String,
                    page_title String,
                    source_type LowCardinality(String),
                    raw_match String,
                    context_snippet String,
                    is_link UInt8,
                    created_at DateTime DEFAULT now()
                ) ENGINE = ReplacingMergeTree(id)
                PARTITION BY toYYYYMM(created_at)
                ORDER BY (task_id, domain, root_domain, id)
                SETTINGS index_granularity = 8192;
            """)

            # 3. Table: sitemap_pages
            client.command(f"""
                CREATE TABLE IF NOT EXISTS {self.database}.sitemap_pages (
                    id UInt64,
                    task_id UInt32,
                    url String,
                    path String,
                    depth UInt16,
                    status_code UInt16,
                    content_type LowCardinality(String),
                    title String,
                    response_time_ms UInt32,
                    external_domains_count UInt32,
                    error String,
                    crawled_at DateTime DEFAULT now()
                ) ENGINE = ReplacingMergeTree(id)
                PARTITION BY toYYYYMM(crawled_at)
                ORDER BY (task_id, url, id)
                SETTINGS index_granularity = 8192;
            """)

            # 4. Table: task_logs (With 90 days automatic TTL)
            client.command(f"""
                CREATE TABLE IF NOT EXISTS {self.database}.task_logs (
                    id UInt64,
                    task_id UInt32,
                    level LowCardinality(String),
                    message String,
                    created_at DateTime DEFAULT now()
                ) ENGINE = MergeTree()
                PARTITION BY toYYYYMM(created_at)
                ORDER BY (task_id, id)
                TTL created_at + INTERVAL 90 DAY
                SETTINGS index_granularity = 8192;
            """)

            logger.info("[ClickHouse] Database and MergeTree tables initialized successfully.")
            return True
        except Exception as e:
            logger.error(f"[ClickHouse] Schema initialization failed: {e}")
            return False

    # ==================== Ingestion Helpers ====================

    def insert_sitemap_pages_batch(self, task_id: int, pages_rows: List[tuple]) -> bool:
        """
        Bulk insert crawled pages into ClickHouse.
        pages_rows item tuple: (task_id, url, path, depth, status_code, content_type, title, response_time_ms, external_domains_count, crawled_at, error)
        """
        client = self.get_client()
        if not client or not pages_rows:
            return False

        try:
            # Generate deterministic pseudo 64-bit ID from hash if not provided
            data = []
            now_dt = datetime.now()
            for r in pages_rows:
                # r: (task_id, url, path, depth, status_code, content_type, title, response_time_ms, external_domains_count, crawled_at, error)
                tid = r[0]
                url = str(r[1] or '')
                url_hash = abs(hash((tid, url))) & 0xFFFFFFFFFFFFFFFF
                crawled_dt = now_dt
                if len(r) > 9 and r[9]:
                    try:
                        crawled_dt = datetime.strptime(str(r[9])[:19], "%Y-%m-%d %H:%M:%S")
                    except Exception:
                        pass
                data.append([
                    url_hash,
                    tid,
                    url,
                    str(r[2] or '/'),
                    int(r[3] or 0),
                    int(r[4] or 0),
                    str(r[5] or ''),
                    str(r[6] or ''),
                    int(r[7] or 0),
                    int(r[8] or 0),
                    str(r[10] or '') if len(r) > 10 and r[10] else '',
                    crawled_dt
                ])

            client.insert(
                f"{self.database}.sitemap_pages",
                data,
                column_names=[
                    "id", "task_id", "url", "path", "depth", "status_code",
                    "content_type", "title", "response_time_ms", "external_domains_count",
                    "error", "crawled_at"
                ]
            )
            return True
        except Exception as e:
            logger.error(f"[ClickHouse] Batch insert sitemap_pages failed: {e}")
            return False

    def insert_domain_occurrences_batch(self, occurrences_rows: List[Any]) -> bool:
        """
        Bulk insert occurrences into ClickHouse.
        occurrences_rows item can be:
        - tuple: (task_id, page_id, domain, page_url, source_type, raw_match, context_snippet, created_at, [root_domain])
        - or dict: {'task_id': ..., 'domain': ..., 'page_url': ..., 'source_type': ..., 'raw_match': ..., 'context_snippet': ..., 'root_domain': ...}
        """
        client = self.get_client()
        if not client or not occurrences_rows:
            return False

        try:
            data = []
            now_dt = datetime.now()
            for r in occurrences_rows:
                if isinstance(r, dict):
                    tid = int(r.get("task_id", 0))
                    dom = str(r.get("domain", ""))
                    p_url = str(r.get("page_url", ""))
                    src_type = str(r.get("source_type", ""))
                    raw_m = str(r.get("raw_match", ""))[:500]
                    snippet = str(r.get("context_snippet", ""))[:1000]
                    root_dom = str(r.get("root_domain", ""))
                    created_str = r.get("created_at")
                    p_title = str(r.get("page_title", ""))
                elif isinstance(r, (list, tuple)):
                    tid = int(r[0])
                    # r[1] is page_id
                    dom = str(r[2] or "")
                    p_url = str(r[3] or "")
                    src_type = str(r[4] or "")
                    raw_m = str(r[5] or "")[:500]
                    snippet = str(r[6] or "")[:1000]
                    created_str = r[7] if len(r) > 7 else None
                    root_dom = str(r[8]) if len(r) > 8 and r[8] else ""
                    p_title = ""
                else:
                    continue

                if not root_dom and dom:
                    parts = dom.split(".")
                    root_dom = ".".join(parts[-2:]) if len(parts) >= 2 else dom

                c_dt = now_dt
                if created_str:
                    try:
                        c_dt = datetime.strptime(str(created_str)[:19], "%Y-%m-%d %H:%M:%S")
                    except Exception:
                        pass

                occ_hash = abs(hash((tid, dom, p_url, src_type, raw_m))) & 0xFFFFFFFFFFFFFFFF
                is_link = 1 if ('link' in src_type or src_type == 'href') else 0

                data.append([
                    occ_hash,
                    tid,
                    dom,
                    root_dom,
                    p_url,
                    p_title,
                    src_type,
                    raw_m,
                    snippet,
                    is_link,
                    c_dt
                ])

            if not data:
                return True

            client.insert(
                f"{self.database}.domain_occurrences",
                data,
                column_names=[
                    "id", "task_id", "domain", "root_domain", "page_url", "page_title",
                    "source_type", "raw_match", "context_snippet", "is_link", "created_at"
                ]
            )
            return True
        except Exception as e:
            logger.error(f"[ClickHouse] Batch insert domain_occurrences failed: {e}")
            return False

    def insert_task_logs_batch(self, logs: List[dict]) -> bool:
        """Bulk insert task execution logs into ClickHouse."""
        client = self.get_client()
        if not client or not logs:
            return False

        try:
            data = []
            now_dt = datetime.now()
            for l in logs:
                tid = int(l.get("task_id", 0))
                lvl = str(l.get("level", "INFO")).upper()
                msg = str(l.get("message", ""))
                created_str = l.get("created_at")
                c_dt = now_dt
                if created_str:
                    try:
                        c_dt = datetime.strptime(str(created_str)[:19], "%Y-%m-%d %H:%M:%S")
                    except Exception:
                        pass
                log_id = abs(hash((tid, msg, time.time_ns()))) & 0xFFFFFFFFFFFFFFFF
                data.append([log_id, tid, lvl, msg, c_dt])

            client.insert(
                f"{self.database}.task_logs",
                data,
                column_names=["id", "task_id", "level", "message", "created_at"]
            )
            return True
        except Exception as e:
            logger.error(f"[ClickHouse] Batch insert task_logs failed: {e}")
            return False

    # ==================== Query Helpers ====================

    def get_recent_logs(self, task_id: int, limit: int = 50) -> Optional[List[dict]]:
        """Fetch latest task logs from ClickHouse with millisecond latency."""
        client = self.get_client()
        if not client:
            return None

        try:
            query = f"""
                SELECT id, task_id, level, message, formatDateTime(created_at, '%Y-%m-%d %H:%M:%S') AS created_at
                FROM {self.database}.task_logs
                WHERE task_id = %(task_id)s
                ORDER BY id DESC
                LIMIT %(limit)s
            """
            result = client.query(query, parameters={"task_id": task_id, "limit": limit})
            rows = []
            for r in result.result_rows:
                rows.append({
                    "id": r[0],
                    "task_id": r[1],
                    "level": r[2],
                    "message": r[3],
                    "created_at": r[4]
                })
            rows.reverse()
            return rows
        except Exception as e:
            logger.error(f"[ClickHouse] get_recent_logs failed: {e}")
            return None

    def list_sitemap_pages(
        self,
        task_id: int,
        depth: Optional[int] = None,
        search: Optional[str] = None,
        status_code: Optional[int] = None,
        limit: int = 50,
        offset: int = 0
    ) -> Optional[Tuple[List[dict], int]]:
        """Query sitemap pages from ClickHouse."""
        client = self.get_client()
        if not client:
            return None

        try:
            where_clauses = ["task_id = %(task_id)s"]
            params: Dict[str, Any] = {"task_id": task_id}

            if depth is not None:
                where_clauses.append("depth = %(depth)s")
                params["depth"] = depth
            if search:
                where_clauses.append("(url LIKE %(search)s OR title LIKE %(search)s)")
                params["search"] = f"%{search}%"
            if status_code is not None:
                where_clauses.append("status_code = %(status_code)s")
                params["status_code"] = status_code

            where_sql = " AND ".join(where_clauses)

            # Count
            count_res = client.query(f"SELECT count(*) FROM {self.database}.sitemap_pages WHERE {where_sql}", parameters=params)
            total = int(count_res.result_rows[0][0]) if count_res.result_rows else 0

            # Rows
            params["limit"] = limit
            params["offset"] = offset
            query = f"""
                SELECT id, task_id, url, path, depth, status_code, content_type, title,
                       response_time_ms, external_domains_count, error,
                       formatDateTime(crawled_at, '%Y-%m-%d %H:%M:%S') AS crawled_at
                FROM {self.database}.sitemap_pages
                WHERE {where_sql}
                ORDER BY depth ASC, id ASC
                LIMIT %(limit)s OFFSET %(offset)s
            """
            res = client.query(query, parameters=params)
            pages = []
            for r in res.result_rows:
                pages.append({
                    "id": r[0],
                    "task_id": r[1],
                    "url": r[2],
                    "path": r[3],
                    "depth": r[4],
                    "status_code": r[5],
                    "content_type": r[6],
                    "title": r[7],
                    "response_time_ms": r[8],
                    "external_domains_count": r[9],
                    "error": r[10] or None,
                    "crawled_at": r[11]
                })
            return pages, total
        except Exception as e:
            logger.error(f"[ClickHouse] list_sitemap_pages failed: {e}")
            return None

    def get_all_pages_urls(self, task_id: int) -> Optional[List[dict]]:
        """Fetch all page URLs and basic metadata for a task from ClickHouse."""
        client = self.get_client()
        if not client:
            return None
        try:
            query = f"""
                SELECT id, url, path, depth, status_code, content_type, title,
                       formatDateTime(crawled_at, '%Y-%m-%d %H:%M:%S') AS crawled_at
                FROM {self.database}.sitemap_pages
                WHERE task_id = %(task_id)s
                ORDER BY depth ASC, id ASC
            """
            res = client.query(query, parameters={"task_id": task_id})
            pages = []
            for r in res.result_rows:
                pages.append({
                    "id": r[0],
                    "url": r[1],
                    "path": r[2],
                    "depth": r[3],
                    "status_code": r[4],
                    "content_type": r[5],
                    "title": r[6],
                    "crawled_at": r[7]
                })
            return pages
        except Exception as e:
            logger.error(f"[ClickHouse] get_all_pages_urls failed: {e}")
            return None

    def list_domain_occurrences(
        self,
        task_id: int,
        domain: Optional[str] = None,
        limit: int = 50,
        offset: int = 0
    ) -> Optional[Tuple[List[dict], int]]:
        """Query occurrences from ClickHouse."""
        client = self.get_client()
        if not client:
            return None

        try:
            where_clauses = ["task_id = %(task_id)s"]
            params: Dict[str, Any] = {"task_id": task_id}

            if domain:
                where_clauses.append("domain = %(domain)s")
                params["domain"] = domain

            where_sql = " AND ".join(where_clauses)

            # Count
            count_res = client.query(f"SELECT count(*) FROM {self.database}.domain_occurrences WHERE {where_sql}", parameters=params)
            total = int(count_res.result_rows[0][0]) if count_res.result_rows else 0

            params["limit"] = limit
            params["offset"] = offset
            query = f"""
                SELECT id, task_id, domain, root_domain, page_url, page_title, source_type,
                       raw_match, context_snippet, is_link,
                       formatDateTime(created_at, '%Y-%m-%d %H:%M:%S') AS created_at
                FROM {self.database}.domain_occurrences
                WHERE {where_sql}
                ORDER BY id DESC
                LIMIT %(limit)s OFFSET %(offset)s
            """
            res = client.query(query, parameters=params)
            occurrences = []
            for r in res.result_rows:
                occurrences.append({
                    "id": r[0],
                    "task_id": r[1],
                    "domain": r[2],
                    "root_domain": r[3],
                    "page_url": r[4],
                    "page_title": r[5],
                    "source_type": r[6],
                    "raw_match": r[7],
                    "context_snippet": r[8],
                    "is_link": bool(r[9]),
                    "created_at": r[10]
                })
            return occurrences, total
        except Exception as e:
            logger.error(f"[ClickHouse] list_domain_occurrences failed: {e}")
            return None

    def get_domain_occurrence_urls(self, task_id: int, domain: str, limit: Optional[int] = None) -> Optional[List[str]]:
        """Fetch distinct page URLs where a domain occurs from ClickHouse."""
        client = self.get_client()
        if not client:
            return None
        try:
            limit_clause = f"LIMIT {int(limit)}" if limit else ""
            query = f"""
                SELECT DISTINCT page_url
                FROM {self.database}.domain_occurrences
                WHERE task_id = %(task_id)s AND domain = %(domain)s
                {limit_clause}
            """
            res = client.query(query, parameters={"task_id": task_id, "domain": domain})
            return [r[0] for r in res.result_rows if r[0]]
        except Exception as e:
            logger.error(f"[ClickHouse] get_domain_occurrence_urls failed: {e}")
            return None

    def get_risk_occurrences_for_sync(self, task_id: Optional[int], domains: List[str]) -> Optional[List[dict]]:
        """Fetch distinct occurrences for risk domains for upserting into risk_page_remediations."""
        client = self.get_client()
        if not client or not domains:
            return None
        try:
            where_clauses = ["domain IN %(domains)s"]
            params: Dict[str, Any] = {"domains": tuple(domains)}
            if task_id is not None:
                where_clauses.append("task_id = %(task_id)s")
                params["task_id"] = task_id
            where_sql = " AND ".join(where_clauses)

            query = f"""
                SELECT task_id, domain, root_domain, page_url, page_title, source_type,
                       raw_match, context_snippet, formatDateTime(created_at, '%Y-%m-%d %H:%M:%S') AS created_at
                FROM {self.database}.domain_occurrences
                WHERE {where_sql}
                LIMIT 50000
            """
            res = client.query(query, parameters=params)
            rows = []
            for r in res.result_rows:
                rows.append({
                    "task_id": r[0],
                    "domain": r[1],
                    "root_domain": r[2],
                    "page_url": r[3],
                    "page_title": r[4],
                    "source_type": r[5],
                    "raw_match": r[6],
                    "context_snippet": r[7],
                    "created_at": r[8]
                })
            return rows
        except Exception as e:
            logger.error(f"[ClickHouse] get_risk_occurrences_for_sync failed: {e}")
            return None

    def purge_task_data(self, task_id: int) -> bool:
        """Fast asynchronous drop/delete of big data partitions in ClickHouse."""
        client = self.get_client()
        if not client:
            return False

        try:
            # Lightweight mutation in ClickHouse
            client.command(f"ALTER TABLE {self.database}.sitemap_pages DELETE WHERE task_id = {task_id}")
            client.command(f"ALTER TABLE {self.database}.domain_occurrences DELETE WHERE task_id = {task_id}")
            client.command(f"ALTER TABLE {self.database}.task_logs DELETE WHERE task_id = {task_id}")
            logger.info(f"[ClickHouse] Purged data for task {task_id}")
            return True
        except Exception as e:
            logger.error(f"[ClickHouse] Purge task data failed for {task_id}: {e}")
            return False


def get_ch_manager() -> ClickHouseManager:
    """Get or initialize the global ClickHouse manager singleton."""
    global _ch_manager
    if _ch_manager is None:
        with _ch_lock:
            if _ch_manager is None:
                _ch_manager = ClickHouseManager()
    return _ch_manager


def init_clickhouse() -> bool:
    """Convenience initialization hook called at app startup."""
    return get_ch_manager().init_db()
