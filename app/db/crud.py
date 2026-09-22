import json
import time
import threading
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any, Tuple
from app.db.database import db_session
from app.crawler.risk_engine import evaluate_domain_risk
from app.db.clickhouse import get_ch_manager

logger = logging.getLogger("uvicorn.error")

def now_iso() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

# ==================== Task CRUD ====================

def create_task(name: str, target_url: str, config: dict) -> int:
    with db_session() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO tasks (name, target_url, status, config, created_at)
            VALUES (?, ?, 'pending', ?, ?)
        """, (name, target_url, json.dumps(config, ensure_ascii=False), now_iso()))
        return cursor.lastrowid

def create_tasks_batch(tasks_data: List[dict]) -> List[dict]:
    """
    Atomically insert multiple tasks in a single database transaction.
    tasks_data item: {'name': str, 'target_url': str, 'config': dict}
    """
    if not tasks_data:
        return []
    created_tasks = []
    with db_session() as conn:
        cursor = conn.cursor()
        now = now_iso()
        for item in tasks_data:
            cursor.execute("""
                INSERT INTO tasks (name, target_url, status, config, created_at)
                VALUES (?, ?, 'pending', ?, ?)
            """, (item['name'], item['target_url'], json.dumps(item['config'], ensure_ascii=False), now))
            task_id = cursor.lastrowid
            created_tasks.append({
                "id": task_id,
                "name": item['name'],
                "target_url": item['target_url'],
                "status": "pending",
                "config": item['config'],
                "created_at": now
            })
    return created_tasks

def get_task(task_id: int, include_deleting: bool = False) -> Optional[dict]:
    with db_session() as conn:
        cursor = conn.cursor()
        if include_deleting:
            cursor.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
        else:
            cursor.execute("SELECT * FROM tasks WHERE id = ? AND status != 'deleting'", (task_id,))
        row = cursor.fetchone()
        if not row:
            return None
        d = dict(row)
        d["config"] = json.loads(d["config"]) if d["config"] else {}
        return d

def list_tasks(limit: int = 50, offset: int = 0) -> Tuple[List[dict], int]:
    with db_session() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM tasks WHERE status != 'deleting'")
        total = cursor.fetchone()[0]
        
        cursor.execute("""
            SELECT * FROM tasks WHERE status != 'deleting' ORDER BY id DESC LIMIT ? OFFSET ?
        """, (limit, offset))
        rows = cursor.fetchall()
        tasks = []
        for r in rows:
            d = dict(r)
            d["config"] = json.loads(d["config"]) if d["config"] else {}
            tasks.append(d)
        return tasks, total

def update_task_status(task_id: int, status: str, error_message: Optional[str] = None):
    with db_session() as conn:
        cursor = conn.cursor()
        now = now_iso()
        if status == 'running':
            cursor.execute("""
                UPDATE tasks 
                SET status = ?, started_at = COALESCE(started_at, ?), error_message = NULL
                WHERE id = ?
            """, (status, now, task_id))
        elif status in ('completed', 'failed', 'stopped'):
            cursor.execute("""
                UPDATE tasks 
                SET status = ?, finished_at = ?, error_message = COALESCE(?, error_message)
                WHERE id = ?
            """, (status, now, error_message, task_id))
        else:
            cursor.execute("UPDATE tasks SET status = ? WHERE id = ?", (status, task_id))

def update_task_progress(task_id: int, pages_crawled: int, pages_total: int,
                         external_domains_count: int, subdomains_count: int = 0, current_url: str = ""):
    with db_session() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE tasks
            SET pages_crawled = ?, pages_total = ?, external_domains_count = ?, subdomains_count = ?, current_url = ?
            WHERE id = ?
        """, (pages_crawled, pages_total, external_domains_count, subdomains_count, current_url, task_id))

def reset_task(task_id: int):
    """Clear all crawled pages, external domains, subdomains, and logs to allow re-running."""
    ch = get_ch_manager()
    if ch.is_available():
        ch.purge_task_data(task_id)
    with db_session() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM sitemap_pages WHERE task_id = ?", (task_id,))
        cursor.execute("DELETE FROM external_domains WHERE task_id = ?", (task_id,))
        cursor.execute("DELETE FROM discovered_subdomains WHERE task_id = ?", (task_id,))
        cursor.execute("DELETE FROM domain_occurrences WHERE task_id = ?", (task_id,))
        cursor.execute("DELETE FROM task_logs WHERE task_id = ?", (task_id,))
        cursor.execute("""
            UPDATE tasks 
            SET status = 'pending', pages_crawled = 0, pages_total = 0,
                external_domains_count = 0, subdomains_count = 0,
                current_url = '', started_at = NULL, finished_at = NULL, error_message = NULL
            WHERE id = ?
        """, (task_id,))

def mark_task_deleting(task_id: int) -> bool:
    """Instantly mark task status as 'deleting' (< 1ms), hiding it immediately from the UI."""
    with db_session() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE tasks SET status = 'deleting' WHERE id = ?", (task_id,))
        return cursor.rowcount > 0

def mark_tasks_deleting(task_ids: List[int]) -> int:
    """Instantly mark multiple tasks status as 'deleting' (< 5ms)."""
    if not task_ids:
        return 0
    with db_session() as conn:
        cursor = conn.cursor()
        placeholders = ",".join("?" for _ in task_ids)
        cursor.execute(f"UPDATE tasks SET status = 'deleting' WHERE id IN ({placeholders})", task_ids)
        return cursor.rowcount

def purge_task_data(task_id: int, chunk_size: int = 20000):
    """
    Smoothly purge all child records and task entry for a marked task in small batches.
    Avoids long transactions, eliminates WAL spikes, yields CPU/IO between chunks,
    and prevents any database or FastAPI loop locking.
    """
    import time
    import logging
    logger = logging.getLogger(__name__)

    # 0. Purge from ClickHouse if available
    ch = get_ch_manager()
    if ch.is_available():
        ch.purge_task_data(task_id)

    # Ensure status is marked deleting
    mark_task_deleting(task_id)

    # 1. Chunked delete on domain_occurrences (largest table)
    total_occ_deleted = 0
    while True:
        try:
            with db_session() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    DELETE FROM domain_occurrences
                    WHERE id IN (
                        SELECT id FROM domain_occurrences
                        WHERE task_id = ?
                        LIMIT ?
                    )
                """, (task_id, chunk_size))
                deleted = cursor.rowcount
                total_occ_deleted += deleted
            if deleted == 0:
                break
            time.sleep(0.01)  # Brief yield to let other transactions breathe
        except Exception as e:
            logger.error(f"Error during chunked delete domain_occurrences for task {task_id}: {e}")
            break

    # 2. Chunked delete on sitemap_pages (second largest table)
    total_pages_deleted = 0
    while True:
        try:
            with db_session() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    DELETE FROM sitemap_pages
                    WHERE id IN (
                        SELECT id FROM sitemap_pages
                        WHERE task_id = ?
                        LIMIT ?
                    )
                """, (task_id, chunk_size))
                deleted = cursor.rowcount
                total_pages_deleted += deleted
            if deleted == 0:
                break
            time.sleep(0.01)
        except Exception as e:
            logger.error(f"Error during chunked delete sitemap_pages for task {task_id}: {e}")
            break

    # 3. Chunked delete on task_logs (prevents locking when millions of logs exist)
    while True:
        try:
            with db_session() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    DELETE FROM task_logs
                    WHERE id IN (
                        SELECT id FROM task_logs
                        WHERE task_id = ?
                        LIMIT ?
                    )
                """, (task_id, chunk_size))
                deleted = cursor.rowcount
            if deleted == 0:
                break
            time.sleep(0.01)
        except Exception as e:
            logger.error(f"Error during chunked delete task_logs for task {task_id}: {e}")
            break

    # 4. Clean remaining smaller child tables and tasks record
    try:
        with db_session() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM risk_page_remediations WHERE task_id = ?", (task_id,))
            cursor.execute("DELETE FROM external_domains WHERE task_id = ?", (task_id,))
            cursor.execute("DELETE FROM discovered_subdomains WHERE task_id = ?", (task_id,))
            cursor.execute("DELETE FROM task_logs WHERE task_id = ?", (task_id,))
            cursor.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        logger.info(f"Task {task_id} purge complete: {total_occ_deleted} occurrences and {total_pages_deleted} pages removed.")
    except Exception as e:
        logger.error(f"Error during final cleanup for task {task_id}: {e}")

def purge_tasks_batch(task_ids: List[int], chunk_size: int = 20000):
    """Purge a sequence of tasks smoothly in background."""
    for tid in task_ids:
        purge_task_data(tid, chunk_size=chunk_size)

def purge_dangling_deleting_tasks(chunk_size: int = 20000):
    """Scan and purge any dangling tasks marked 'deleting' (e.g. from previous server restart)."""
    try:
        with db_session() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM tasks WHERE status = 'deleting'")
            task_ids = [r[0] for r in cursor.fetchall()]
        if task_ids:
            purge_tasks_batch(task_ids, chunk_size=chunk_size)
    except Exception:
        pass

def delete_task(task_id: int):
    """Legacy synchronous delete wrapper (calls purge_task_data)."""
    purge_task_data(task_id)

def batch_delete_tasks(task_ids: List[int]) -> int:
    """Legacy batch delete wrapper."""
    mark_tasks_deleting(task_ids)
    purge_tasks_batch(task_ids)
    return len(task_ids)

# ==================== Sitemap Pages ====================

def insert_page(task_id: int, url: str, path: str, depth: int, status_code: int,
                content_type: str, title: str, response_time_ms: int,
                external_domains_count: int, error: Optional[str] = None) -> int:
    with db_session() as conn:
        cursor = conn.cursor()
        now = now_iso()
        if url and len(url) > 800:
            b = url.encode("utf-8", errors="ignore")
            if len(b) > 2000:
                url = b[:2000].decode("utf-8", errors="ignore")
        cursor.execute("""
            INSERT INTO sitemap_pages (
                task_id, url, path, depth, status_code, content_type,
                title, response_time_ms, external_domains_count, crawled_at, error
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(task_id, url) DO UPDATE SET
                status_code = excluded.status_code,
                content_type = excluded.content_type,
                title = excluded.title,
                response_time_ms = excluded.response_time_ms,
                external_domains_count = excluded.external_domains_count,
                crawled_at = excluded.crawled_at,
                error = excluded.error
        """, (task_id, url, path, depth, status_code, content_type, title, response_time_ms, external_domains_count, now, error))
        return cursor.lastrowid

def save_crawl_result(task_id: int, page_data: dict, external_domains: List[dict],
                      occurrences: List[dict], subdomains: Optional[List[dict]] = None) -> int:
    """
    Save page, upsert external domains, upsert subdomains, and insert domain occurrences in a SINGLE atomic database transaction.
    Greatly reduces database round trips and latency in concurrent crawling.
    """
    with db_session() as conn:
        cursor = conn.cursor()
        now = now_iso()

        # 1. Insert sitemap page
        p_url = page_data.get('url', '')
        if p_url and len(p_url) > 800:
            b = p_url.encode("utf-8", errors="ignore")
            if len(b) > 2000:
                p_url = b[:2000].decode("utf-8", errors="ignore")
        cursor.execute("""
            INSERT INTO sitemap_pages (
                task_id, url, path, depth, status_code, content_type,
                title, response_time_ms, external_domains_count, crawled_at, error
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(task_id, url) DO UPDATE SET
                status_code = excluded.status_code,
                content_type = excluded.content_type,
                title = excluded.title,
                response_time_ms = excluded.response_time_ms,
                external_domains_count = excluded.external_domains_count,
                crawled_at = excluded.crawled_at,
                error = excluded.error
        """, (
            task_id,
            p_url,
            page_data['path'],
            page_data['depth'],
            page_data['status_code'],
            page_data['content_type'],
            page_data['title'],
            page_data['response_time_ms'],
            page_data['external_domains_count'],
            now,
            page_data.get('error')
        ))
        page_id = cursor.lastrowid

        # 2. Upsert external domains
        if external_domains:
            cursor.execute("SELECT * FROM domain_risk_profiles")
            profiles = [dict(r) for r in cursor.fetchall()]
            for d in external_domains:
                risk_info = evaluate_domain_risk(d['domain'], d['root_domain'], profiles)
                cursor.execute("""
                    INSERT INTO external_domains (
                        task_id, domain, root_domain, occurrence_count,
                        has_link, has_text, sample_page_url,
                        risk_level, risk_tags, risk_remark, risk_source, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(task_id, domain) DO UPDATE SET
                        occurrence_count = external_domains.occurrence_count + excluded.occurrence_count,
                        has_link = CASE WHEN excluded.has_link = 1 THEN 1 ELSE external_domains.has_link END,
                        has_text = CASE WHEN excluded.has_text = 1 THEN 1 ELSE external_domains.has_text END,
                        sample_page_url = CASE WHEN external_domains.sample_page_url = '' THEN excluded.sample_page_url ELSE external_domains.sample_page_url END
                """, (
                    task_id,
                    d['domain'],
                    d['root_domain'],
                    d.get('count', 1),
                    1 if d.get('has_link') else 0,
                    1 if d.get('has_text') else 0,
                    d.get('sample_page_url', ''),
                    risk_info['risk_level'],
                    json.dumps(risk_info['risk_tags'], ensure_ascii=False),
                    risk_info['risk_remark'],
                    risk_info['risk_source'],
                    now
                ))

        # 3. Upsert discovered subdomains
        if subdomains:
            for s in subdomains:
                cursor.execute("""
                    INSERT INTO discovered_subdomains (
                        task_id, subdomain, root_domain, occurrence_count,
                        has_link, has_text, sample_page_url, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(task_id, subdomain) DO UPDATE SET
                        occurrence_count = discovered_subdomains.occurrence_count + excluded.occurrence_count,
                        has_link = CASE WHEN excluded.has_link = 1 THEN 1 ELSE discovered_subdomains.has_link END,
                        has_text = CASE WHEN excluded.has_text = 1 THEN 1 ELSE discovered_subdomains.has_text END,
                        sample_page_url = CASE WHEN discovered_subdomains.sample_page_url = '' THEN excluded.sample_page_url ELSE discovered_subdomains.sample_page_url END
                """, (
                    task_id,
                    s['subdomain'],
                    s['root_domain'],
                    s.get('count', 1),
                    1 if s.get('has_link') else 0,
                    1 if s.get('has_text') else 0,
                    s.get('sample_page_url', ''),
                    now
                ))

        # 4. Insert domain occurrences
        if occurrences:
            cursor.executemany("""
                INSERT INTO domain_occurrences (
                    task_id, page_id, domain, page_url, source_type, raw_match, context_snippet, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, [
                (
                    task_id,
                    page_id,
                    o['domain'],
                    o['page_url'],
                    o['source_type'],
                    o['raw_match'][:500],
                    o['context_snippet'][:1000],
                    now
                ) for o in occurrences
            ])

        return page_id

def save_asset_scan_result(task_id: int, asset_url: str, external_domains: List[dict],
                           occurrences: List[dict], subdomains: Optional[List[dict]] = None):
    """
    Save external domains, subdomains, and occurrences discovered inside a standalone JS or CSS asset file.
    Executed in a single atomic transaction.
    """
    if not external_domains and not occurrences and not subdomains:
        return

    with db_session() as conn:
        cursor = conn.cursor()
        now = now_iso()

        # 1. Upsert external domains
        if external_domains:
            for d in external_domains:
                cursor.execute("""
                    INSERT INTO external_domains (
                        task_id, domain, root_domain, occurrence_count,
                        has_link, has_text, sample_page_url, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(task_id, domain) DO UPDATE SET
                        occurrence_count = external_domains.occurrence_count + excluded.occurrence_count,
                        has_link = CASE WHEN excluded.has_link = 1 THEN 1 ELSE external_domains.has_link END,
                        has_text = CASE WHEN excluded.has_text = 1 THEN 1 ELSE external_domains.has_text END,
                        sample_page_url = CASE WHEN external_domains.sample_page_url = '' THEN excluded.sample_page_url ELSE external_domains.sample_page_url END
                """, (
                    task_id,
                    d['domain'],
                    d['root_domain'],
                    d.get('count', 1),
                    1 if d.get('has_link') else 0,
                    1 if d.get('has_text') else 0,
                    d.get('sample_page_url', asset_url),
                    now
                ))

        # 2. Upsert discovered subdomains
        if subdomains:
            for s in subdomains:
                cursor.execute("""
                    INSERT INTO discovered_subdomains (
                        task_id, subdomain, root_domain, occurrence_count,
                        has_link, has_text, sample_page_url, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(task_id, subdomain) DO UPDATE SET
                        occurrence_count = discovered_subdomains.occurrence_count + excluded.occurrence_count,
                        has_link = CASE WHEN excluded.has_link = 1 THEN 1 ELSE discovered_subdomains.has_link END,
                        has_text = CASE WHEN excluded.has_text = 1 THEN 1 ELSE discovered_subdomains.has_text END,
                        sample_page_url = CASE WHEN discovered_subdomains.sample_page_url = '' THEN excluded.sample_page_url ELSE discovered_subdomains.sample_page_url END
                """, (
                    task_id,
                    s['subdomain'],
                    s['root_domain'],
                    s.get('count', 1),
                    1 if s.get('has_link') else 0,
                    1 if s.get('has_text') else 0,
                    s.get('sample_page_url', asset_url),
                    now
                ))

        # 3. Insert domain occurrences
        if occurrences:
            cursor.executemany("""
                INSERT INTO domain_occurrences (
                    task_id, page_id, domain, page_url, source_type, raw_match, context_snippet, created_at
                ) VALUES (?, NULL, ?, ?, ?, ?, ?, ?)
            """, [
                (
                    task_id,
                    o['domain'],
                    o.get('page_url', asset_url),
                    o['source_type'],
                    o['raw_match'][:500],
                    o['context_snippet'][:1000],
                    now
                ) for o in occurrences
            ])


# ==================== In-Memory Risk Profiles Cache ====================
_risk_profiles_cache: Optional[List[dict]] = None
_risk_profiles_cache_time: float = 0.0
_risk_profiles_cache_ttl: float = 60.0  # 60s TTL
_risk_profiles_lock = threading.Lock()

def get_cached_risk_profiles(force_refresh: bool = False) -> List[dict]:
    """Return in-memory cached threat intelligence profiles, avoiding high-frequency database roundtrips."""
    global _risk_profiles_cache, _risk_profiles_cache_time
    now = time.time()
    if not force_refresh and _risk_profiles_cache is not None and (now - _risk_profiles_cache_time < _risk_profiles_cache_ttl):
        return _risk_profiles_cache

    with _risk_profiles_lock:
        if not force_refresh and _risk_profiles_cache is not None and (now - _risk_profiles_cache_time < _risk_profiles_cache_ttl):
            return _risk_profiles_cache
        with db_session() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM domain_risk_profiles ORDER BY id ASC")
            rows = []
            for r in cursor.fetchall():
                item = dict(r)
                try:
                    item["tags"] = json.loads(item.get("tags") or "[]")
                except Exception:
                    item["tags"] = []
                rows.append(item)
            _risk_profiles_cache = rows
            _risk_profiles_cache_time = time.time()
            return _risk_profiles_cache

def invalidate_risk_profiles_cache():
    """Invalidate in-memory risk profiles cache when rules are mutated."""
    global _risk_profiles_cache, _risk_profiles_cache_time
    with _risk_profiles_lock:
        _risk_profiles_cache = None
        _risk_profiles_cache_time = 0.0


def save_crawl_results_batch(
    task_id: int,
    batch_items: List[dict],
    pages_crawled: Optional[int] = None,
    pages_total: Optional[int] = None,
    external_domains_count: Optional[int] = None,
    subdomains_count: Optional[int] = None,
    current_url: Optional[str] = None
):
    """
    Persist a batch of crawled pages, consolidated external domains, subdomains,
    and occurrences in a single atomic PostgreSQL transaction.
    Also updates task progress within the same transaction to avoid lock contention.
    """
    if not batch_items:
        return

    with db_session() as conn:
        cursor = conn.cursor()
        now = now_iso()

        # 1. Insert sitemap pages
        def _safe_url(u: str) -> str:
            if u and len(u) > 800:
                b = u.encode("utf-8", errors="ignore")
                if len(b) > 2000:
                    return b[:2000].decode("utf-8", errors="ignore")
            return u

        pages_to_insert = [
            (
                task_id,
                _safe_url(item['page_data']['url']),
                item['page_data']['path'],
                item['page_data']['depth'],
                item['page_data']['status_code'],
                item['page_data']['content_type'],
                item['page_data']['title'],
                item['page_data']['response_time_ms'],
                item['page_data']['external_domains_count'],
                now,
                item['page_data'].get('error')
            ) for item in batch_items
        ]

        ch = get_ch_manager()
        ch_pages_saved = False
        if ch.is_available():
            try:
                ch_pages_saved = ch.insert_sitemap_pages_batch(task_id, pages_to_insert)
            except Exception as e:
                logger.warning(f"[Dual-Engine] ClickHouse sitemap_pages insert failed: {e}. Falling back to PostgreSQL.")
                ch_pages_saved = False

        if not ch_pages_saved:
            cursor.executemany("""
                INSERT INTO sitemap_pages (
                    task_id, url, path, depth, status_code, content_type,
                    title, response_time_ms, external_domains_count, crawled_at, error
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(task_id, url) DO UPDATE SET
                    status_code = excluded.status_code,
                    content_type = excluded.content_type,
                    title = excluded.title,
                    response_time_ms = excluded.response_time_ms,
                    external_domains_count = excluded.external_domains_count,
                    crawled_at = excluded.crawled_at,
                    error = excluded.error
            """, pages_to_insert)

        # 2. Consolidate and upsert external domains in-memory before database insert
        aggregated_ext: Dict[str, dict] = {}
        for item in batch_items:
            for d in item.get('external_domains', []):
                dom = d['domain']
                if dom not in aggregated_ext:
                    aggregated_ext[dom] = {
                        "domain": dom,
                        "root_domain": d['root_domain'],
                        "count": 0,
                        "has_link": 0,
                        "has_text": 0,
                        "sample_page_url": d.get('sample_page_url', '')
                    }
                aggregated_ext[dom]["count"] += d.get('count', 1)
                if d.get('has_link'):
                    aggregated_ext[dom]["has_link"] = 1
                if d.get('has_text'):
                    aggregated_ext[dom]["has_text"] = 1

        # Use in-memory cached risk profiles (eliminates high-frequency SELECT * FROM domain_risk_profiles)
        profiles = get_cached_risk_profiles()

        ext_to_insert = []
        for d in aggregated_ext.values():
            risk_info = evaluate_domain_risk(d['domain'], d['root_domain'], profiles)
            ext_to_insert.append((
                task_id,
                d['domain'],
                d['root_domain'],
                d['count'],
                d['has_link'],
                d['has_text'],
                d['sample_page_url'],
                risk_info['risk_level'],
                json.dumps(risk_info['risk_tags'], ensure_ascii=False),
                risk_info['risk_remark'],
                risk_info['risk_source'],
                now
            ))

        if ext_to_insert:
            cursor.executemany("""
                INSERT INTO external_domains (
                    task_id, domain, root_domain, occurrence_count,
                    has_link, has_text, sample_page_url,
                    risk_level, risk_tags, risk_remark, risk_source, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(task_id, domain) DO UPDATE SET
                    occurrence_count = external_domains.occurrence_count + excluded.occurrence_count,
                    has_link = CASE WHEN excluded.has_link = 1 THEN 1 ELSE external_domains.has_link END,
                    has_text = CASE WHEN excluded.has_text = 1 THEN 1 ELSE external_domains.has_text END,
                    sample_page_url = CASE WHEN external_domains.sample_page_url = '' THEN excluded.sample_page_url ELSE external_domains.sample_page_url END
            """, ext_to_insert)

        # 3. Consolidate and upsert subdomains in-memory
        aggregated_sub: Dict[str, dict] = {}
        for item in batch_items:
            for s in item.get('subdomains', []):
                sub = s['subdomain']
                if sub not in aggregated_sub:
                    aggregated_sub[sub] = {
                        "subdomain": sub,
                        "root_domain": s['root_domain'],
                        "count": 0,
                        "has_link": 0,
                        "has_text": 0,
                        "sample_page_url": s.get('sample_page_url', '')
                    }
                aggregated_sub[sub]["count"] += s.get('count', 1)
                if s.get('has_link'):
                    aggregated_sub[sub]["has_link"] = 1
                if s.get('has_text'):
                    aggregated_sub[sub]["has_text"] = 1

        sub_to_insert = [
            (
                task_id,
                s['subdomain'],
                s['root_domain'],
                s['count'],
                s['has_link'],
                s['has_text'],
                s['sample_page_url'],
                now
            ) for s in aggregated_sub.values()
        ]

        if sub_to_insert:
            cursor.executemany("""
                INSERT INTO discovered_subdomains (
                    task_id, subdomain, root_domain, occurrence_count,
                    has_link, has_text, sample_page_url, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(task_id, subdomain) DO UPDATE SET
                    occurrence_count = discovered_subdomains.occurrence_count + excluded.occurrence_count,
                    has_link = CASE WHEN excluded.has_link = 1 THEN 1 ELSE discovered_subdomains.has_link END,
                    has_text = CASE WHEN excluded.has_text = 1 THEN 1 ELSE discovered_subdomains.has_text END,
                    sample_page_url = CASE WHEN discovered_subdomains.sample_page_url = '' THEN excluded.sample_page_url ELSE discovered_subdomains.sample_page_url END
            """, sub_to_insert)

        # 4. Insert domain occurrences
        all_occurrences = []
        for item in batch_items:
            for o in item.get('occurrences', []):
                all_occurrences.append((
                    task_id,
                    None,
                    o['domain'],
                    o['page_url'],
                    o['source_type'],
                    o['raw_match'][:500],
                    o['context_snippet'][:1000],
                    now
                ))
        if all_occurrences:
            ch_occ_saved = False
            if ch.is_available():
                try:
                    ch_occ_saved = ch.insert_domain_occurrences_batch(all_occurrences)
                except Exception as e:
                    logger.warning(f"[Dual-Engine] ClickHouse domain_occurrences insert failed: {e}. Falling back to PostgreSQL.")
                    ch_occ_saved = False

            if not ch_occ_saved:
                cursor.executemany("""
                    INSERT INTO domain_occurrences (
                        task_id, page_id, domain, page_url, source_type, raw_match, context_snippet, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, all_occurrences)

        # 5. Update task progress directly in the same transaction
        if pages_crawled is not None and pages_total is not None:
            cursor.execute("""
                UPDATE tasks
                SET pages_crawled = ?, pages_total = ?,
                    external_domains_count = COALESCE(?, external_domains_count),
                    subdomains_count = COALESCE(?, subdomains_count),
                    current_url = COALESCE(?, current_url)
                WHERE id = ?
            """, (pages_crawled, pages_total, external_domains_count, subdomains_count, current_url, task_id))


def add_logs_batch(task_id: int, logs_list: List[dict]):
    """Insert multiple logs in a single transaction."""
    if not logs_list:
        return
    now = now_iso()
    ch = get_ch_manager()
    if ch.is_available():
        try:
            ch_logs = [{"task_id": task_id, "level": l['level'], "message": l['message'], "created_at": l.get('timestamp') or now} for l in logs_list]
            if ch.insert_task_logs_batch(ch_logs):
                return
        except Exception as e:
            logger.warning(f"[Dual-Engine] ClickHouse add_logs_batch error: {e}. Falling back to PostgreSQL.")

    with db_session() as conn:
        cursor = conn.cursor()
        cursor.executemany("""
            INSERT INTO task_logs (task_id, level, message, created_at)
            VALUES (?, ?, ?, ?)
        """, [(task_id, l['level'], l['message'], l.get('timestamp') or now) for l in logs_list])


def list_pages(task_id: int, depth: Optional[int] = None, status_code: Optional[int] = None,
               search: Optional[str] = None, limit: int = 50, offset: int = 0) -> Tuple[List[dict], int]:
    ch = get_ch_manager()
    if ch.is_available():
        try:
            ch_res = ch.list_sitemap_pages(
                task_id=task_id,
                depth=depth,
                status_code=status_code,
                search=search,
                limit=limit,
                offset=offset
            )
            if ch_res is not None:
                pages, total = ch_res
                if total > 0 or (search or depth is not None or status_code is not None):
                    return pages, total
        except Exception as e:
            logger.warning(f"[Dual-Engine] ClickHouse list_sitemap_pages failed: {e}. Falling back to PostgreSQL.")

    with db_session() as conn:
        cursor = conn.cursor()
        query = "SELECT * FROM sitemap_pages WHERE task_id = ?"
        count_query = "SELECT COUNT(*) FROM sitemap_pages WHERE task_id = ?"
        params: List[Any] = [task_id]
        count_params: List[Any] = [task_id]

        if depth is not None:
            query += " AND depth = ?"
            count_query += " AND depth = ?"
            params.append(depth)
            count_params.append(depth)

        if status_code is not None:
            query += " AND status_code = ?"
            count_query += " AND status_code = ?"
            params.append(status_code)
            count_params.append(status_code)

        if search:
            query += " AND (url LIKE ? OR title LIKE ?)"
            count_query += " AND (url LIKE ? OR title LIKE ?)"
            pattern = f"%{search}%"
            params.extend([pattern, pattern])
            count_params.extend([pattern, pattern])

        cursor.execute(count_query, count_params)
        total = cursor.fetchone()[0]

        query += " ORDER BY depth ASC, id ASC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        cursor.execute(query, params)
        rows = [dict(r) for r in cursor.fetchall()]
        return rows, total

def get_all_pages_urls(task_id: int) -> List[dict]:
    ch = get_ch_manager()
    if ch.is_available():
        try:
            pages = ch.get_all_pages_urls(task_id)
            if pages is not None and len(pages) > 0:
                return pages
        except Exception as e:
            logger.warning(f"[Dual-Engine] ClickHouse get_all_pages_urls failed: {e}. Falling back to PostgreSQL.")

    with db_session() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, url, path, depth, status_code, content_type, title, crawled_at
            FROM sitemap_pages
            WHERE task_id = ?
            ORDER BY depth ASC, id ASC
        """, (task_id,))
        return [dict(r) for r in cursor.fetchall()]

# ==================== External Domains ====================

def upsert_external_domains(task_id: int, domains_data: List[dict]):
    """
    domains_data items:
    {
        'domain': str,
        'root_domain': str,
        'count': int,
        'has_link': bool,
        'has_text': bool,
        'sample_page_url': str
    }
    """
    if not domains_data:
        return

    with db_session() as conn:
        cursor = conn.cursor()
        now = now_iso()
        for d in domains_data:
            cursor.execute("""
                INSERT INTO external_domains (
                    task_id, domain, root_domain, occurrence_count,
                    has_link, has_text, sample_page_url, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(task_id, domain) DO UPDATE SET
                    occurrence_count = external_domains.occurrence_count + excluded.occurrence_count,
                    has_link = CASE WHEN excluded.has_link = 1 THEN 1 ELSE external_domains.has_link END,
                    has_text = CASE WHEN excluded.has_text = 1 THEN 1 ELSE external_domains.has_text END,
                    sample_page_url = CASE WHEN external_domains.sample_page_url = '' THEN excluded.sample_page_url ELSE external_domains.sample_page_url END
            """, (
                task_id,
                d['domain'],
                d['root_domain'],
                d.get('count', 1),
                1 if d.get('has_link') else 0,
                1 if d.get('has_text') else 0,
                d.get('sample_page_url', ''),
                now
            ))

def insert_domain_occurrences(task_id: int, occurrences: List[dict]):
    """
    occurrences items:
    {
        'page_id': int,
        'domain': str,
        'page_url': str,
        'source_type': str,
        'raw_match': str,
        'context_snippet': str
    }
    """
    if not occurrences:
        return

    ch = get_ch_manager()
    ch_saved = False
    if ch.is_available():
        try:
            ch_saved = ch.insert_domain_occurrences_batch(occurrences)
        except Exception as e:
            logger.warning(f"[Dual-Engine] ClickHouse insert_domain_occurrences failed: {e}. Falling back to PostgreSQL.")
            ch_saved = False

    if not ch_saved:
        with db_session() as conn:
            cursor = conn.cursor()
            now = now_iso()
            cursor.executemany("""
                INSERT INTO domain_occurrences (
                    task_id, page_id, domain, page_url, source_type, raw_match, context_snippet, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, [
                (
                    task_id,
                    o.get('page_id'),
                    o['domain'],
                    o['page_url'],
                    o['source_type'],
                    o['raw_match'][:500],
                    o['context_snippet'][:1000],
                    now
                ) for o in occurrences
            ])

def list_external_domains(task_id: int, has_link: Optional[int] = None,
                          has_text: Optional[int] = None, source_type: Optional[str] = None,
                          root_domain: Optional[str] = None, search: Optional[str] = None,
                          risk_level: Optional[str] = None, verify_status: Optional[str] = None,
                          sort_by: str = 'occurrence_count', order: str = 'DESC',
                          limit: int = 50, offset: int = 0) -> Tuple[List[dict], int]:
    with db_session() as conn:
        cursor = conn.cursor()
        query = "SELECT * FROM external_domains WHERE task_id = ?"
        count_query = "SELECT COUNT(*) FROM external_domains WHERE task_id = ?"
        params: List[Any] = [task_id]
        count_params: List[Any] = [task_id]

        if has_link is not None:
            query += " AND has_link = ?"
            count_query += " AND has_link = ?"
            params.append(has_link)
            count_params.append(has_link)

        if has_text is not None:
            query += " AND has_text = ?"
            count_query += " AND has_text = ?"
            params.append(has_text)
            count_params.append(has_text)

        if risk_level:
            if risk_level == 'risk_only':
                query += " AND risk_level IN ('critical', 'high', 'medium')"
                count_query += " AND risk_level IN ('critical', 'high', 'medium')"
            else:
                query += " AND risk_level = ?"
                count_query += " AND risk_level = ?"
                params.append(risk_level)
                count_params.append(risk_level)

        if verify_status:
            query += " AND verify_status = ?"
            count_query += " AND verify_status = ?"
            params.append(verify_status)
            count_params.append(verify_status)

        if source_type == 'asset':
            asset_clause = """ AND (
                sample_page_url LIKE '%.js' OR sample_page_url LIKE '%.js?%' OR
                sample_page_url LIKE '%.css' OR sample_page_url LIKE '%.css?%' OR
                domain IN (
                    SELECT domain FROM domain_occurrences
                    WHERE task_id = ? AND (
                        source_type LIKE '%_file_%' OR
                        page_url LIKE '%.js%' OR
                        page_url LIKE '%.css%'
                    )
                )
            )"""
            query += asset_clause
            count_query += asset_clause
            params.append(task_id)
            count_params.append(task_id)

        if root_domain:
            query += " AND root_domain = ?"
            count_query += " AND root_domain = ?"
            params.append(root_domain)
            count_params.append(root_domain)

        if search:
            query += " AND (domain LIKE ? OR root_domain LIKE ?)"
            count_query += " AND (domain LIKE ? OR root_domain LIKE ?)"
            pattern = f"%{search}%"
            params.extend([pattern, pattern])
            count_params.extend([pattern, pattern])

        cursor.execute(count_query, count_params)
        total = cursor.fetchone()[0]

        # Validate sorting column
        valid_cols = {
            'occurrence_count': 'occurrence_count',
            'domain': 'domain',
            'root_domain': 'root_domain',
            'risk_level': 'risk_level',
            'verify_status': 'verify_status',
            'id': 'id'
        }
        col = valid_cols.get(sort_by, 'occurrence_count')
        sort_order = 'ASC' if order.upper() == 'ASC' else 'DESC'

        query += f" ORDER BY {col} {sort_order}, id DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        cursor.execute(query, params)
        rows = []
        for r in cursor.fetchall():
            item = dict(r)
            raw_tags = item.get("risk_tags") or "[]"
            if isinstance(raw_tags, str):
                try:
                    item["risk_tags"] = json.loads(raw_tags)
                except Exception:
                    item["risk_tags"] = [raw_tags] if raw_tags else []
            rows.append(item)
        return rows, total

def get_domain_occurrences(task_id: int, domain: str, limit: int = 50) -> List[dict]:
    ch = get_ch_manager()
    if ch.is_available():
        try:
            res = ch.list_domain_occurrences(task_id, domain=domain, limit=limit, offset=0)
            if res is not None:
                occs, total = res
                if total > 0:
                    return occs
        except Exception as e:
            logger.warning(f"[Dual-Engine] ClickHouse get_domain_occurrences failed: {e}. Falling back to PostgreSQL.")

    with db_session() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM domain_occurrences
            WHERE task_id = ? AND domain = ?
            LIMIT ?
        """, (task_id, domain, limit))
        return [dict(r) for r in cursor.fetchall()]

def get_external_domains_for_export(task_id: int) -> List[dict]:
    with db_session() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT domain, root_domain, occurrence_count, has_link, has_text, sample_page_url,
                   risk_level, risk_tags, risk_remark, risk_source, verify_status, verify_time, created_at
            FROM external_domains
            WHERE task_id = ?
            ORDER BY occurrence_count DESC, domain ASC
        """, (task_id,))
        rows = []
        for r in cursor.fetchall():
            item = dict(r)
            raw_tags = item.get("risk_tags") or "[]"
            if isinstance(raw_tags, str):
                try:
                    item["risk_tags"] = json.loads(raw_tags)
                except Exception:
                    item["risk_tags"] = [raw_tags] if raw_tags else []
            rows.append(item)
        return rows

def get_external_domains_stats(task_id: int) -> dict:
    with db_session() as conn:
        cursor = conn.cursor()
        # Total unique domains
        cursor.execute("SELECT COUNT(*) FROM external_domains WHERE task_id = ?", (task_id,))
        total_unique = cursor.fetchone()[0]

        # Total unique root domains
        cursor.execute("SELECT COUNT(DISTINCT root_domain) FROM external_domains WHERE task_id = ?", (task_id,))
        unique_roots = cursor.fetchone()[0]

        # Link count vs text count
        cursor.execute("SELECT COUNT(*) FROM external_domains WHERE task_id = ? AND has_link = 1", (task_id,))
        link_domains = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM external_domains WHERE task_id = ? AND has_text = 1", (task_id,))
        text_domains = cursor.fetchone()[0]

        # Risk breakdown stats
        cursor.execute("""
            SELECT risk_level, COUNT(*) as cnt
            FROM external_domains
            WHERE task_id = ?
            GROUP BY risk_level
        """, (task_id,))
        risk_map = {r['risk_level']: r['cnt'] for r in cursor.fetchall()}
        risk_stats = {
            "critical": risk_map.get("critical", 0),
            "high": risk_map.get("high", 0),
            "medium": risk_map.get("medium", 0),
            "low": risk_map.get("low", 0),
            "safe": risk_map.get("safe", 0),
            "pending": risk_map.get("pending", 0),
            "total_risk": risk_map.get("critical", 0) + risk_map.get("high", 0) + risk_map.get("medium", 0)
        }

        # Verification stats
        cursor.execute("""
            SELECT verify_status, COUNT(*) as cnt
            FROM external_domains
            WHERE task_id = ?
            GROUP BY verify_status
        """, (task_id,))
        verify_map = {r['verify_status']: r['cnt'] for r in cursor.fetchall()}
        verify_stats = {
            "unverified": verify_map.get("unverified", 0),
            "verified_clean": verify_map.get("verified_clean", 0),
            "verified_failed": verify_map.get("verified_failed", 0),
            "error": verify_map.get("error", 0)
        }

        # Top 10 root domains
        cursor.execute("""
            SELECT root_domain, COUNT(*) as domain_count, SUM(occurrence_count) as total_occurrences
            FROM external_domains
            WHERE task_id = ?
            GROUP BY root_domain
            ORDER BY total_occurrences DESC
            LIMIT 10
        """, (task_id,))
        top_roots = [dict(r) for r in cursor.fetchall()]

        # Top 10 domains
        cursor.execute("""
            SELECT domain, root_domain, occurrence_count, has_link, has_text, risk_level
            FROM external_domains
            WHERE task_id = ?
            ORDER BY occurrence_count DESC
            LIMIT 10
        """, (task_id,))
        top_domains = [dict(r) for r in cursor.fetchall()]

        return {
            "total_unique_domains": total_unique,
            "unique_root_domains": unique_roots,
            "link_domains": link_domains,
            "text_domains": text_domains,
            "risk_stats": risk_stats,
            "verify_stats": verify_stats,
            "top_root_domains": top_roots,
            "top_domains": top_domains
        }

def clean_invalid_domains_for_task(task_id: int) -> dict:
    """
    Remove all invalid/pseudo-domains and their occurrences from a task.
    Updates the task's external_domains_count.
    Returns summary of cleaned records.
    """
    from app.crawler.tld_manager import validate_extracted_domain

    with db_session() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, domain FROM external_domains WHERE task_id = ?", (task_id,))
        rows = cursor.fetchall()

        invalid_ids = []
        invalid_domains = []
        for r in rows:
            d_id = r[0]
            d_name = r[1]
            if not validate_extracted_domain(d_name, is_from_url=False):
                invalid_ids.append(d_id)
                invalid_domains.append(d_name)

        if not invalid_domains:
            cursor.execute("SELECT COUNT(*) FROM external_domains WHERE task_id = ?", (task_id,))
            rem = cursor.fetchone()[0]
            return {
                "task_id": task_id,
                "deleted_domains_count": 0,
                "deleted_occurrences_count": 0,
                "remaining_domains_count": rem,
                "deleted_domains": []
            }

        # Delete occurrences
        del_occ_count = 0
        for chunk in [invalid_domains[i:i+200] for i in range(0, len(invalid_domains), 200)]:
            placeholders = ','.join('?' * len(chunk))
            cursor.execute(f"DELETE FROM domain_occurrences WHERE task_id = ? AND domain IN ({placeholders})", [task_id] + chunk)
            del_occ_count += cursor.rowcount

        # Delete external_domains
        for chunk in [invalid_ids[i:i+200] for i in range(0, len(invalid_ids), 200)]:
            placeholders = ','.join('?' * len(chunk))
            cursor.execute(f"DELETE FROM external_domains WHERE id IN ({placeholders})", chunk)

        # Update task external_domains_count
        cursor.execute("SELECT COUNT(*) FROM external_domains WHERE task_id = ?", (task_id,))
        remaining = cursor.fetchone()[0]
        cursor.execute("UPDATE tasks SET external_domains_count = ? WHERE id = ?", (remaining, task_id))

        return {
            "task_id": task_id,
            "deleted_domains_count": len(invalid_domains),
            "deleted_occurrences_count": del_occ_count,
            "remaining_domains_count": remaining,
            "deleted_domains": invalid_domains
        }

def clean_all_tasks_invalid_domains() -> dict:
    """Clean invalid domains across all tasks."""
    with db_session() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM tasks WHERE status != 'deleting'")
        task_ids = [r[0] for r in cursor.fetchall()]

    total_deleted = 0
    total_occ_deleted = 0
    cleaned_tasks = {}
    for tid in task_ids:
        res = clean_invalid_domains_for_task(tid)
        if res["deleted_domains_count"] > 0:
            total_deleted += res["deleted_domains_count"]
            total_occ_deleted += res["deleted_occurrences_count"]
            cleaned_tasks[tid] = res

    return {
        "total_deleted_domains": total_deleted,
        "total_deleted_occurrences": total_occ_deleted,
        "tasks": cleaned_tasks
    }

# ==================== Discovered Subdomains ====================

def list_subdomains(task_id: int, has_link: Optional[int] = None,
                    has_text: Optional[int] = None, search: Optional[str] = None,
                    sort_by: str = 'occurrence_count', order: str = 'DESC',
                    limit: int = 50, offset: int = 0) -> Tuple[List[dict], int]:
    with db_session() as conn:
        cursor = conn.cursor()
        query = "SELECT * FROM discovered_subdomains WHERE task_id = ?"
        count_query = "SELECT COUNT(*) FROM discovered_subdomains WHERE task_id = ?"
        params: List[Any] = [task_id]
        count_params: List[Any] = [task_id]

        if has_link is not None:
            query += " AND has_link = ?"
            count_query += " AND has_link = ?"
            params.append(has_link)
            count_params.append(has_link)

        if has_text is not None:
            query += " AND has_text = ?"
            count_query += " AND has_text = ?"
            params.append(has_text)
            count_params.append(has_text)

        if search:
            query += " AND subdomain LIKE ?"
            count_query += " AND subdomain LIKE ?"
            pattern = f"%{search}%"
            params.append(pattern)
            count_params.append(pattern)

        cursor.execute(count_query, count_params)
        total = cursor.fetchone()[0]

        valid_cols = {'occurrence_count': 'occurrence_count', 'subdomain': 'subdomain', 'id': 'id'}
        col = valid_cols.get(sort_by, 'occurrence_count')
        sort_order = 'ASC' if order.upper() == 'ASC' else 'DESC'

        query += f" ORDER BY {col} {sort_order}, id DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        cursor.execute(query, params)
        rows = [dict(r) for r in cursor.fetchall()]
        return rows, total

def get_subdomains_for_export(task_id: int) -> List[dict]:
    with db_session() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT subdomain, root_domain, occurrence_count, has_link, has_text, sample_page_url, created_at
            FROM discovered_subdomains
            WHERE task_id = ?
            ORDER BY occurrence_count DESC, subdomain ASC
        """, (task_id,))
        return [dict(r) for r in cursor.fetchall()]

def get_subdomains_stats(task_id: int) -> dict:
    with db_session() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM discovered_subdomains WHERE task_id = ?", (task_id,))
        total = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM discovered_subdomains WHERE task_id = ? AND has_link = 1", (task_id,))
        link_count = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM discovered_subdomains WHERE task_id = ? AND has_text = 1", (task_id,))
        text_count = cursor.fetchone()[0]

        return {
            "total_subdomains": total,
            "total_unique_subdomains": total,
            "link_count": link_count,
            "link_subdomains": link_count,
            "text_count": text_count,
            "text_subdomains": text_count
        }

# ==================== Task Logs ====================

def add_log(task_id: int, level: str, message: str):
    now = now_iso()
    ch = get_ch_manager()
    if ch.is_available():
        try:
            if ch.insert_task_logs_batch([{"task_id": task_id, "level": level, "message": message, "created_at": now}]):
                return
        except Exception as e:
            logger.warning(f"[Dual-Engine] ClickHouse add_log error: {e}. Falling back to PostgreSQL.")

    with db_session() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO task_logs (task_id, level, message, created_at)
            VALUES (?, ?, ?, ?)
        """, (task_id, level.upper(), message, now))

def batch_add_logs(logs: List[dict]):
    if not logs:
        return
    ch = get_ch_manager()
    if ch.is_available():
        try:
            if ch.insert_task_logs_batch(logs):
                return
        except Exception as e:
            logger.warning(f"[Dual-Engine] ClickHouse batch_add_logs error: {e}. Falling back to PostgreSQL.")

    with db_session() as conn:
        cursor = conn.cursor()
        cursor.executemany("""
            INSERT INTO task_logs (task_id, level, message, created_at)
            VALUES (?, ?, ?, ?)
        """, [(l["task_id"], l["level"].upper(), l["message"], l.get("created_at") or now_iso()) for l in logs])

def get_recent_logs(task_id: int, limit: int = 100) -> List[dict]:
    ch = get_ch_manager()
    if ch.is_available():
        try:
            ch_logs = ch.get_recent_logs(task_id, limit=limit)
            if ch_logs is not None and len(ch_logs) > 0:
                return ch_logs
        except Exception as e:
            logger.warning(f"[Dual-Engine] ClickHouse get_recent_logs failed: {e}. Falling back to PostgreSQL.")

    with db_session() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM task_logs
            WHERE task_id = ?
            ORDER BY id DESC
            LIMIT ?
        """, (task_id, limit))
        rows = [dict(r) for r in cursor.fetchall()]
        rows.reverse()
        return rows


# ==================== Global External Domains Repository ====================

def list_global_external_domains(
    search: Optional[str] = None,
    root_domain: Optional[str] = None,
    has_link: Optional[int] = None,
    has_text: Optional[int] = None,
    risk_level: Optional[str] = None,
    verify_status: Optional[str] = None,
    min_tasks: Optional[int] = None,
    sort_by: str = 'total_occurrences',
    order: str = 'DESC',
    limit: int = 50,
    offset: int = 0
) -> Tuple[List[dict], int]:
    """
    List aggregated external domains across all tasks in the system.
    Returns: (list of aggregated domains, total count)
    """
    with db_session() as conn:
        cursor = conn.cursor()

        where_clauses = ["1=1", "t.status != 'deleting'"]
        params: List[Any] = []

        if search:
            where_clauses.append("(ed.domain LIKE ? OR ed.root_domain LIKE ?)")
            pat = f"%{search.strip()}%"
            params.extend([pat, pat])

        if root_domain:
            where_clauses.append("ed.root_domain = ?")
            params.append(root_domain.strip())

        if has_link is not None:
            where_clauses.append("ed.has_link = ?")
            params.append(has_link)

        if has_text is not None:
            where_clauses.append("ed.has_text = ?")
            params.append(has_text)

        if risk_level:
            if risk_level == 'risk_only':
                where_clauses.append("ed.risk_level IN ('critical', 'high', 'medium')")
            else:
                where_clauses.append("ed.risk_level = ?")
                params.append(risk_level)

        if verify_status:
            where_clauses.append("ed.verify_status = ?")
            params.append(verify_status)

        where_sql = " AND ".join(where_clauses)

        having_clauses = []
        having_params: List[Any] = []
        if min_tasks and min_tasks > 1:
            having_clauses.append("COUNT(DISTINCT ed.task_id) >= ?")
            having_params.append(min_tasks)

        having_sql = f" HAVING {' AND '.join(having_clauses)}" if having_clauses else ""

        # Count total unique aggregated domains
        count_sql = f"""
            SELECT COUNT(*) FROM (
                SELECT ed.domain
                FROM external_domains ed
                JOIN tasks t ON ed.task_id = t.id
                WHERE {where_sql}
                GROUP BY ed.domain
                {having_sql}
            ) as sub_cnt
        """
        cursor.execute(count_sql, params + having_params)
        total = cursor.fetchone()[0]

        # Sorting
        valid_cols = {
            'total_occurrences': 'total_occurrences',
            'task_count': 'task_count',
            'domain': 'ed.domain',
            'root_domain': 'ed.root_domain',
            'risk_level': 'risk_level',
            'first_seen_at': 'first_seen_at',
            'last_seen_at': 'last_seen_at'
        }
        col = valid_cols.get(sort_by, 'total_occurrences')
        direction = 'ASC' if order.upper() == 'ASC' else 'DESC'

        tasks_agg = "STRING_AGG(CONCAT(t.id, ':::', t.name, ':::', ed.occurrence_count), ';;;')"

        # Main query
        main_sql = f"""
            SELECT 
                ed.domain,
                ed.root_domain,
                SUM(ed.occurrence_count) as total_occurrences,
                COUNT(DISTINCT ed.task_id) as task_count,
                MAX(ed.has_link) as has_link,
                MAX(ed.has_text) as has_text,
                MIN(ed.created_at) as first_seen_at,
                MAX(ed.created_at) as last_seen_at,
                MIN(ed.sample_page_url) as sample_page_url,
                MAX(ed.risk_level) as risk_level,
                MAX(ed.risk_tags) as risk_tags_raw,
                MAX(ed.risk_remark) as risk_remark,
                MAX(ed.verify_status) as verify_status,
                MAX(ed.verify_time) as verify_time,
                {tasks_agg} as tasks_summary_raw
            FROM external_domains ed
            JOIN tasks t ON ed.task_id = t.id
            WHERE {where_sql}
            GROUP BY ed.domain, ed.root_domain
            {having_sql}
            ORDER BY {col} {direction}, ed.domain ASC
            LIMIT ? OFFSET ?
        """
        cursor.execute(main_sql, params + having_params + [limit, offset])
        rows = cursor.fetchall()

        results = []
        for r in rows:
            raw_tasks = r["tasks_summary_raw"] or ""
            tasks_list = []
            for item in raw_tasks.split(';;;'):
                if not item:
                    continue
                parts = item.split(':::')
                if len(parts) >= 3:
                    tasks_list.append({
                        "task_id": int(parts[0]),
                        "task_name": parts[1],
                        "occurrence_count": int(parts[2])
                    })

            raw_tags = r["risk_tags_raw"] or "[]"
            tags_list = []
            if isinstance(raw_tags, str):
                try:
                    tags_list = json.loads(raw_tags)
                except Exception:
                    tags_list = [raw_tags] if raw_tags else []

            results.append({
                "domain": r["domain"],
                "root_domain": r["root_domain"],
                "total_occurrences": r["total_occurrences"],
                "task_count": r["task_count"],
                "has_link": bool(r["has_link"]),
                "has_text": bool(r["has_text"]),
                "risk_level": r["risk_level"] or "pending",
                "risk_tags": tags_list,
                "risk_remark": r["risk_remark"] or "",
                "verify_status": r["verify_status"] or "unverified",
                "verify_time": r["verify_time"] or "",
                "first_seen_at": r["first_seen_at"],
                "last_seen_at": r["last_seen_at"],
                "sample_page_url": r["sample_page_url"] or "",
                "associated_tasks": tasks_list
            })

        return results, total


def get_global_domains_stats() -> dict:
    """Get system-wide summary statistics for all aggregated external domains."""
    with db_session() as conn:
        cursor = conn.cursor()

        cursor.execute("SELECT COUNT(DISTINCT domain) FROM external_domains")
        total_unique_domains = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(DISTINCT root_domain) FROM external_domains")
        unique_root_domains = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM tasks WHERE status != 'deleting'")
        total_tasks = cursor.fetchone()[0]

        cursor.execute("SELECT COALESCE(SUM(occurrence_count), 0) FROM external_domains")
        total_occurrences = cursor.fetchone()[0]

        cursor.execute("""
            SELECT COUNT(*) FROM (
                SELECT domain FROM external_domains GROUP BY domain HAVING COUNT(DISTINCT task_id) >= 2
            ) as sub_shared
        """)
        shared_domains_count = cursor.fetchone()[0]

        # Risk breakdown stats across global domains
        cursor.execute("""
            SELECT risk_level, COUNT(DISTINCT domain) as cnt
            FROM external_domains
            GROUP BY risk_level
        """)
        risk_map = {r['risk_level']: r['cnt'] for r in cursor.fetchall()}
        risk_stats = {
            "critical": risk_map.get("critical", 0),
            "high": risk_map.get("high", 0),
            "medium": risk_map.get("medium", 0),
            "low": risk_map.get("low", 0),
            "safe": risk_map.get("safe", 0),
            "pending": risk_map.get("pending", 0),
            "total_risk": risk_map.get("critical", 0) + risk_map.get("high", 0) + risk_map.get("medium", 0)
        }

        # Verification stats
        cursor.execute("""
            SELECT verify_status, COUNT(DISTINCT domain) as cnt
            FROM external_domains
            GROUP BY verify_status
        """)
        verify_map = {r['verify_status']: r['cnt'] for r in cursor.fetchall()}
        verify_stats = {
            "unverified": verify_map.get("unverified", 0),
            "verified_clean": verify_map.get("verified_clean", 0),
            "verified_failed": verify_map.get("verified_failed", 0),
            "error": verify_map.get("error", 0)
        }

        # Top 10 Root Domains
        cursor.execute("""
            SELECT 
                root_domain,
                COUNT(DISTINCT domain) as domain_count,
                SUM(occurrence_count) as total_occurrences,
                COUNT(DISTINCT task_id) as task_coverage
            FROM external_domains
            GROUP BY root_domain
            ORDER BY total_occurrences DESC
            LIMIT 10
        """)
        top_roots = [dict(r) for r in cursor.fetchall()]

        # Top 10 Domains with highest task coverage
        cursor.execute("""
            SELECT 
                domain,
                MAX(root_domain) as root_domain,
                COUNT(DISTINCT task_id) as task_count,
                SUM(occurrence_count) as total_occurrences
            FROM external_domains
            GROUP BY domain
            ORDER BY task_count DESC, total_occurrences DESC
            LIMIT 10
        """)
        top_shared_domains = [dict(r) for r in cursor.fetchall()]

        return {
            "total_unique_domains": total_unique_domains,
            "unique_root_domains": unique_root_domains,
            "total_tasks": total_tasks,
            "total_occurrences": total_occurrences,
            "shared_domains_count": shared_domains_count,
            "shared_multi_task_domains": shared_domains_count,
            "risk_stats": risk_stats,
            "verify_stats": verify_stats,
            "top_roots": top_roots,
            "top_root_domains": top_roots,
            "top_shared_domains": top_shared_domains
        }


def get_domain_associated_tasks(domain: str, max_occurrences_per_task: Optional[int] = 3) -> List[dict]:
    """Retrieve full task breakdown and sample evidence for a specific domain across all tasks."""
    with db_session() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT 
                t.id as task_id,
                t.name as task_name,
                t.target_url,
                t.status as task_status,
                ed.root_domain,
                ed.occurrence_count,
                ed.has_link,
                ed.has_text,
                ed.sample_page_url,
                ed.risk_level,
                ed.risk_tags,
                ed.risk_remark,
                ed.verify_status,
                ed.verify_time,
                ed.verify_detail,
                ed.created_at
            FROM external_domains ed
            JOIN tasks t ON ed.task_id = t.id
            WHERE ed.domain = ? AND t.status != 'deleting'
            ORDER BY ed.occurrence_count DESC, t.id DESC
        """, (domain,))
        tasks_list = [dict(r) for r in cursor.fetchall()]

        for t in tasks_list:
            raw_tags = t.get("risk_tags") or "[]"
            if isinstance(raw_tags, str):
                try:
                    t["risk_tags"] = json.loads(raw_tags)
                except Exception:
                    t["risk_tags"] = [raw_tags] if raw_tags else []

            # Compute verify progress from verify_detail if available
            t["verify_progress"] = ""
            t["total_pages"] = 0
            t["cleared_count"] = 0
            t["still_present_count"] = 0
            t["verify_summary"] = ""
            if t.get("verify_detail"):
                try:
                    vdetail = json.loads(t["verify_detail"]) if isinstance(t["verify_detail"], str) else t["verify_detail"]
                    total_pages = vdetail.get("total_pages", 0)
                    cleared_pages = vdetail.get("cleared_count", 0)
                    still_present = vdetail.get("still_present_count", 0)
                    t["total_pages"] = total_pages
                    t["cleared_count"] = cleared_pages
                    t["still_present_count"] = still_present
                    t["verify_summary"] = vdetail.get("summary", "")
                    if total_pages > 0:
                        t["verify_progress"] = f"{cleared_pages}/{total_pages}"
                except Exception:
                    pass

            ch = get_ch_manager()
            ch_found = False
            if ch.is_available():
                try:
                    occ_res = ch.list_domain_occurrences(t["task_id"], domain=domain, limit=max_occurrences_per_task or 100)
                    if occ_res is not None and occ_res[1] > 0:
                        t["occurrences"] = occ_res[0]
                        ch_found = True
                except Exception:
                    ch_found = False

            if not ch_found:
                if max_occurrences_per_task is not None:
                    cursor.execute("""
                        SELECT page_url, source_type, raw_match, context_snippet, created_at
                        FROM domain_occurrences
                        WHERE task_id = ? AND domain = ?
                        LIMIT ?
                    """, (t["task_id"], domain, max_occurrences_per_task))
                else:
                    cursor.execute("""
                        SELECT page_url, source_type, raw_match, context_snippet, created_at
                        FROM domain_occurrences
                        WHERE task_id = ? AND domain = ?
                    """, (t["task_id"], domain))
                t["occurrences"] = [dict(r) for r in cursor.fetchall()]

        return tasks_list


def get_global_domains_for_export(
    search: Optional[str] = None,
    root_domain: Optional[str] = None,
    risk_level: Optional[str] = None,
    min_tasks: Optional[int] = None
) -> List[dict]:
    """Export all aggregated external domains with full metadata."""
    domains, _ = list_global_external_domains(
        search=search,
        root_domain=root_domain,
        risk_level=risk_level,
        min_tasks=min_tasks,
        limit=100000,
        offset=0
    )
    return domains


# ==================== Domain Risk & Verification CRUD ====================

def get_domain_occurrence_urls(task_id: int, domain: str, limit: Optional[int] = None) -> List[str]:
    """Get unique occurrence page URLs for targeted remediation re-testing."""
    ch = get_ch_manager()
    if ch.is_available():
        try:
            urls = ch.get_domain_occurrence_urls(task_id, domain=domain, limit=limit)
            if urls:
                return urls
        except Exception:
            pass

    with db_session() as conn:
        cursor = conn.cursor()
        if limit:
            cursor.execute("""
                SELECT DISTINCT page_url FROM domain_occurrences
                WHERE task_id = ? AND domain = ?
                LIMIT ?
            """, (task_id, domain, limit))
        else:
            cursor.execute("""
                SELECT DISTINCT page_url FROM domain_occurrences
                WHERE task_id = ? AND domain = ?
            """, (task_id, domain))
        urls = [r[0] for r in cursor.fetchall() if r[0]]
        if not urls:
            cursor.execute("SELECT sample_page_url FROM external_domains WHERE task_id = ? AND domain = ?", (task_id, domain))
            row = cursor.fetchone()
            if row and row[0]:
                urls = [row[0]]
        return urls


def get_external_domain(task_id: int, domain: str) -> Optional[dict]:
    with db_session() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM external_domains WHERE task_id = ? AND domain = ?", (task_id, domain))
        row = cursor.fetchone()
        if not row:
            return None
        item = dict(row)
        raw_tags = item.get("risk_tags") or "[]"
        if isinstance(raw_tags, str):
            try:
                item["risk_tags"] = json.loads(raw_tags)
            except Exception:
                item["risk_tags"] = [raw_tags] if raw_tags else []
        return item


def update_external_domain_risk(
    task_id: int,
    domain: str,
    risk_level: str,
    tags: Optional[List[str]] = None,
    remark: str = '',
    sync_to_global: bool = False,
    match_type: str = 'root'
) -> bool:
    """Update risk classification for an external domain within a task, optionally syncing to global intel."""
    with db_session() as conn:
        cursor = conn.cursor()
        now = now_iso()
        tags_json = json.dumps(tags or [], ensure_ascii=False)
        cursor.execute("""
            UPDATE external_domains
            SET risk_level = ?, risk_tags = ?, risk_remark = ?, risk_source = 'manual'
            WHERE task_id = ? AND domain = ?
        """, (risk_level, tags_json, remark, task_id, domain))

        if sync_to_global:
            cursor.execute("SELECT root_domain FROM external_domains WHERE task_id = ? AND domain = ?", (task_id, domain))
            row = cursor.fetchone()
            root_dom = row[0] if row else domain
            target_profile_domain = root_dom if match_type == 'root' else domain

            cursor.execute("""
                INSERT INTO domain_risk_profiles (
                    domain, match_type, risk_level, category, tags, source, remark, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 'manual', ?, ?, ?)
                ON CONFLICT(domain) DO UPDATE SET
                    match_type = excluded.match_type,
                    risk_level = excluded.risk_level,
                    tags = excluded.tags,
                    remark = excluded.remark,
                    updated_at = excluded.updated_at
            """, (target_profile_domain, match_type, risk_level, tags[0] if tags else '', tags_json, remark, now, now))

            # Propagate to other tasks
            if match_type == 'root':
                cursor.execute("""
                    UPDATE external_domains
                    SET risk_level = ?, risk_tags = ?, risk_remark = ?, risk_source = 'intel_rule'
                    WHERE (root_domain = ? OR domain = ? OR domain LIKE ?) AND (risk_source != 'manual' OR risk_source IS NULL OR risk_source = '')
                """, (risk_level, tags_json, f"继承自全局情报规则: {target_profile_domain}", target_profile_domain, target_profile_domain, f"%.{target_profile_domain}"))
            else:
                cursor.execute("""
                    UPDATE external_domains
                    SET risk_level = ?, risk_tags = ?, risk_remark = ?, risk_source = 'intel_rule'
                    WHERE domain = ? AND (risk_source != 'manual' OR risk_source IS NULL OR risk_source = '')
                """, (risk_level, tags_json, f"继承自全局情报规则: {target_profile_domain}", target_profile_domain))

        return True


def batch_update_external_domains_risk(
    task_id: int,
    domains: List[str],
    risk_level: str,
    tags: Optional[List[str]] = None,
    remark: str = ''
) -> int:
    """Batch update risk level and tags for multiple domains in a task."""
    if not domains:
        return 0
    with db_session() as conn:
        cursor = conn.cursor()
        tags_json = json.dumps(tags or [], ensure_ascii=False)
        placeholders = ",".join("?" for _ in domains)
        cursor.execute(f"""
            UPDATE external_domains
            SET risk_level = ?, risk_tags = ?, risk_remark = ?, risk_source = 'manual'
            WHERE task_id = ? AND domain IN ({placeholders})
        """, [risk_level, tags_json, remark, task_id] + domains)
        return cursor.rowcount


def update_external_domain_verify_result(
    task_id: int,
    domain: str,
    verify_status: Any = None,
    verify_time: Optional[str] = None,
    verify_detail: Optional[str] = None,
    **kwargs
) -> bool:
    """Save verification / re-testing verdict and evidence details."""
    if isinstance(verify_status, dict):
        status = verify_status.get("verify_status", "verified_clean")
        vtime = verify_status.get("verify_time") or now_iso()
        detail = json.dumps(verify_status, ensure_ascii=False)
        verdict_dict = verify_status
    else:
        status = str(verify_status or "unverified")
        vtime = verify_time or now_iso()
        detail = verify_detail if isinstance(verify_detail, str) else json.dumps(verify_detail or {}, ensure_ascii=False)
        try:
            verdict_dict = json.loads(detail) if isinstance(detail, str) else {}
        except Exception:
            verdict_dict = {}

    with db_session() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE external_domains
            SET verify_status = ?, verify_time = ?, verify_detail = ?
            WHERE task_id = ? AND domain = ?
        """, (status, vtime, detail, task_id, domain))

        # Synchronize to risk_page_remediations using its exact schema:
        # columns: verify_status, last_verified_at, last_verify_detail, manual_status, manual_remark, updated_at
        now = now_iso()
        if status == "verified_clean":
            cursor.execute("""
                UPDATE risk_page_remediations
                SET verify_status = 'verified_clean', last_verified_at = ?, last_verify_detail = ?,
                    manual_status = CASE WHEN manual_status != 'ignored' THEN 'resolved' ELSE manual_status END,
                    manual_remark = CASE 
                        WHEN manual_status != 'ignored' AND (manual_remark IS NULL OR manual_remark = '' OR POSITION('工单重新打开' IN COALESCE(manual_remark, '')) > 0)
                        THEN '系统复测已清除，工单自动完结' 
                        ELSE manual_remark 
                    END,
                    updated_at = ?
                WHERE task_id = ? AND domain = ?
            """, (vtime, detail, now, task_id, domain))
        elif isinstance(verdict_dict, dict) and "details" in verdict_dict and verdict_dict["details"]:
            for item in verdict_dict["details"]:
                p_url = item.get("url")
                p_found = item.get("found")
                if p_url:
                    p_status = "verified_clean" if p_found is False else ("verified_failed" if p_found is True else "error")
                    p_detail = json.dumps(item, ensure_ascii=False)
                    if p_status == "verified_clean":
                        cursor.execute("""
                            UPDATE risk_page_remediations
                            SET verify_status = ?, last_verified_at = ?, last_verify_detail = ?,
                                manual_status = CASE WHEN manual_status != 'ignored' THEN 'resolved' ELSE manual_status END,
                                manual_remark = CASE 
                                    WHEN manual_status != 'ignored' AND (manual_remark IS NULL OR manual_remark = '' OR POSITION('工单重新打开' IN COALESCE(manual_remark, '')) > 0)
                                    THEN '系统复测已清除，工单自动完结' 
                                    ELSE manual_remark 
                                END,
                                updated_at = ?
                            WHERE task_id = ? AND domain = ? AND page_url = ?
                        """, (p_status, vtime, p_detail, now, task_id, domain, p_url))
                    elif p_status == "verified_failed":
                        cursor.execute("""
                            UPDATE risk_page_remediations
                            SET verify_status = ?, last_verified_at = ?, last_verify_detail = ?,
                                manual_status = CASE WHEN manual_status = 'resolved' THEN 'pending' ELSE manual_status END,
                                manual_remark = CASE 
                                    WHEN manual_status = 'resolved' 
                                    THEN '【复测告警】检测到违规外链再次出现，工单重新打开待处置' 
                                    ELSE manual_remark 
                                END,
                                updated_at = ?
                            WHERE task_id = ? AND domain = ? AND page_url = ?
                        """, (p_status, vtime, p_detail, now, task_id, domain, p_url))
                    else:
                        cursor.execute("""
                            UPDATE risk_page_remediations
                            SET verify_status = ?, last_verified_at = ?, last_verify_detail = ?, updated_at = ?
                            WHERE task_id = ? AND domain = ? AND page_url = ?
                        """, (p_status, vtime, p_detail, now, task_id, domain, p_url))
        else:
            cursor.execute("""
                UPDATE risk_page_remediations
                SET verify_status = ?, last_verified_at = ?, last_verify_detail = ?,
                    manual_status = CASE 
                        WHEN ? IN ('verified_clean', 'page_removed') AND manual_status != 'ignored' THEN 'resolved'
                        WHEN ? = 'verified_failed' AND manual_status = 'resolved' THEN 'pending'
                        ELSE manual_status 
                    END,
                    updated_at = ?
                WHERE task_id = ? AND domain = ?
            """, (status, vtime, detail, status, status, now, task_id, domain))
        return True


def evaluate_task_domains_rules(task_id: int) -> dict:
    """Re-evaluate heuristic rules & threat intel for all un-reviewed domains in a task."""
    with db_session() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM domain_risk_profiles")
        profiles = [dict(r) for r in cursor.fetchall()]

        cursor.execute("SELECT id, domain, root_domain, risk_source FROM external_domains WHERE task_id = ?", (task_id,))
        domains = cursor.fetchall()
        updated_count = 0

        for row in domains:
            if row["risk_source"] == "manual":
                continue
            risk_info = evaluate_domain_risk(row["domain"], row["root_domain"], profiles)
            cursor.execute("""
                UPDATE external_domains
                SET risk_level = ?, risk_tags = ?, risk_remark = ?, risk_source = ?
                WHERE id = ?
            """, (
                risk_info["risk_level"],
                json.dumps(risk_info["risk_tags"], ensure_ascii=False),
                risk_info["risk_remark"],
                risk_info["risk_source"],
                row["id"]
            ))
            updated_count += 1

        return {"total": len(domains), "evaluated_count": updated_count}


# ==================== Threat Intelligence Base (domain_risk_profiles) ====================

def create_risk_profile(
    domain: str,
    match_type: str = "root",
    risk_level: str = "high",
    category: str = "",
    tags: Optional[List[str]] = None,
    remark: str = "",
    source: str = "manual",
    sync_to_history: bool = True
) -> dict:
    """Add a new pre-configured risk domain rule and optionally sync to existing tasks."""
    clean_domain = domain.lower().strip().lstrip("*.")
    with db_session() as conn:
        cursor = conn.cursor()
        now = now_iso()
        tags_json = json.dumps(tags or [], ensure_ascii=False)
        cursor.execute("""
            INSERT INTO domain_risk_profiles (
                domain, match_type, risk_level, category, tags, source, remark, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(domain) DO UPDATE SET
                match_type = excluded.match_type,
                risk_level = excluded.risk_level,
                category = excluded.category,
                tags = excluded.tags,
                remark = excluded.remark,
                updated_at = excluded.updated_at
        """, (clean_domain, match_type, risk_level, category, tags_json, source, remark, now, now))
        profile_id = cursor.lastrowid

    invalidate_risk_profiles_cache()

    if sync_to_history:
        sync_risk_profiles_to_history([clean_domain])

    return get_risk_profile_by_domain(clean_domain) or {"id": profile_id, "domain": clean_domain}


def get_risk_profile(profile_id: int) -> Optional[dict]:
    with db_session() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM domain_risk_profiles WHERE id = ?", (profile_id,))
        row = cursor.fetchone()
        if not row:
            return None
        res = dict(row)
        try:
            res["tags"] = json.loads(res.get("tags") or "[]")
        except Exception:
            res["tags"] = []
        return res


def get_risk_profile_by_domain(domain: str) -> Optional[dict]:
    clean_domain = domain.lower().strip().lstrip("*.")
    with db_session() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM domain_risk_profiles WHERE domain = ?", (clean_domain,))
        row = cursor.fetchone()
        if not row:
            return None
        res = dict(row)
        try:
            res["tags"] = json.loads(res.get("tags") or "[]")
        except Exception:
            res["tags"] = []
        return res


def list_risk_profiles(
    search: Optional[str] = None,
    risk_level: Optional[str] = None,
    limit: int = 50,
    offset: int = 0
) -> Tuple[List[dict], int]:
    with db_session() as conn:
        cursor = conn.cursor()
        where_clauses = ["1=1"]
        params: List[Any] = []

        if search:
            where_clauses.append("(domain LIKE ? OR remark LIKE ? OR category LIKE ?)")
            pat = f"%{search.strip()}%"
            params.extend([pat, pat, pat])

        if risk_level:
            where_clauses.append("risk_level = ?")
            params.append(risk_level)

        where_sql = " AND ".join(where_clauses)
        cursor.execute(f"SELECT COUNT(*) FROM domain_risk_profiles WHERE {where_sql}", params)
        total = cursor.fetchone()[0]

        cursor.execute(f"""
            SELECT * FROM domain_risk_profiles
            WHERE {where_sql}
            ORDER BY id DESC
            LIMIT ? OFFSET ?
        """, params + [limit, offset])

        rows = []
        for r in cursor.fetchall():
            item = dict(r)
            try:
                item["tags"] = json.loads(item.get("tags") or "[]")
            except Exception:
                item["tags"] = []
            rows.append(item)

        return rows, total


def get_all_risk_profiles() -> List[dict]:
    return get_cached_risk_profiles()

list_risk_profiles_for_eval = get_all_risk_profiles


def update_risk_profile(profile_id: int, updates: dict) -> Optional[dict]:
    with db_session() as conn:
        cursor = conn.cursor()
        now = now_iso()
        fields = []
        params = []
        for k in ["domain", "match_type", "risk_level", "category", "remark", "source"]:
            if k in updates:
                fields.append(f"{k} = ?")
                params.append(updates[k])
        if "tags" in updates:
            fields.append("tags = ?")
            params.append(json.dumps(updates["tags"] or [], ensure_ascii=False))

        if not fields:
            return get_risk_profile(profile_id)

        fields.append("updated_at = ?")
        params.append(now)
        params.append(profile_id)

        cursor.execute(f"UPDATE domain_risk_profiles SET {', '.join(fields)} WHERE id = ?", params)

    invalidate_risk_profiles_cache()
    return get_risk_profile(profile_id)


def delete_risk_profile(profile_id: int) -> bool:
    with db_session() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM domain_risk_profiles WHERE id = ?", (profile_id,))
        success = cursor.rowcount > 0

    if success:
        invalidate_risk_profiles_cache()
    return success


def batch_import_risk_profiles(items: List[dict], sync_to_history: bool = True) -> int:
    """Batch import multiple risk domain profiles."""
    if not items:
        return 0
    now = now_iso()
    imported_domains = []
    with db_session() as conn:
        cursor = conn.cursor()
        for it in items:
            raw_dom = it.get("domain", "").lower().strip()
            if not raw_dom:
                continue
            is_wildcard = raw_dom.startswith("*.")
            dom = raw_dom.lstrip("*.")
            if not dom:
                continue
            match_type = it.get("match_type") or ("root" if is_wildcard else "exact")
            risk_level = it.get("risk_level", "high") or "high"
            category = it.get("category", "") or ""
            tags = it.get("tags") or []
            remark = it.get("remark", "") or ""
            source = it.get("source", "import")

            cursor.execute("""
                INSERT INTO domain_risk_profiles (
                    domain, match_type, risk_level, category, tags, source, remark, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(domain) DO UPDATE SET
                    match_type = excluded.match_type,
                    risk_level = excluded.risk_level,
                    category = excluded.category,
                    tags = excluded.tags,
                    remark = excluded.remark,
                    updated_at = excluded.updated_at
            """, (dom, match_type, risk_level, category, json.dumps(tags, ensure_ascii=False), source, remark, now, now))
            imported_domains.append(dom)

    if imported_domains:
        invalidate_risk_profiles_cache()

    if sync_to_history and imported_domains:
        sync_risk_profiles_to_history(imported_domains)

    return len(imported_domains)


def sync_risk_profiles_to_history(domains_filter: Optional[List[str]] = None) -> dict:
    """
    Retrospectively sync threat intelligence profiles to all existing tasks and external domains.
    Runs efficiently via targeted bulk updates.
    """
    with db_session() as conn:
        cursor = conn.cursor()
        if domains_filter:
            placeholders = ",".join("?" for _ in domains_filter)
            cursor.execute(f"SELECT * FROM domain_risk_profiles WHERE domain IN ({placeholders})", domains_filter)
        else:
            cursor.execute("SELECT * FROM domain_risk_profiles")
        profiles = [dict(r) for r in cursor.fetchall()]

    total_matched = 0

    for p in profiles:
        dom = p["domain"].lower().strip().lstrip("*.")
        if not dom:
            continue
        match_type = p.get("match_type", "root")
        level = p.get("risk_level", "high")
        tags = p.get("tags") or "[]"
        remark = p.get("remark") or f"命中预设风险情报: {dom}"

        for attempt in range(3):
            try:
                with db_session() as conn:
                    cursor = conn.cursor()
                    cursor.execute("SET lock_timeout = '5s';")

                    # Consistent lock ordering across system:
                    # 1. Update/delete risk_page_remediations first
                    if match_type == "root":
                        if level in ('safe', 'pending'):
                            cursor.execute("""
                                DELETE FROM risk_page_remediations
                                WHERE (root_domain = ? OR domain = ?)
                            """, (dom, dom))
                        else:
                            cursor.execute("""
                                UPDATE risk_page_remediations
                                SET risk_level = ?, risk_tags = ?, risk_remark = ?
                                WHERE (root_domain = ? OR domain = ?)
                            """, (level, tags, remark, dom, dom))

                        # 2. Update external_domains second
                        where_clause = "(root_domain = ? OR domain = ?)"
                        if not domains_filter:
                            where_clause += " AND (risk_source != 'manual' OR risk_source IS NULL OR risk_source = '')"
                        cursor.execute(f"""
                            UPDATE external_domains
                            SET risk_level = ?, risk_tags = ?, risk_remark = ?, risk_source = 'intel_rule'
                            WHERE {where_clause}
                        """, (level, tags, remark, dom, dom))
                    else:
                        if level in ('safe', 'pending'):
                            cursor.execute("""
                                DELETE FROM risk_page_remediations
                                WHERE domain = ?
                            """, (dom,))
                        else:
                            cursor.execute("""
                                UPDATE risk_page_remediations
                                SET risk_level = ?, risk_tags = ?, risk_remark = ?
                                WHERE domain = ?
                            """, (level, tags, remark, dom))

                        where_clause = "domain = ?"
                        if not domains_filter:
                            where_clause += " AND (risk_source != 'manual' OR risk_source IS NULL OR risk_source = '')"
                        cursor.execute(f"""
                            UPDATE external_domains
                            SET risk_level = ?, risk_tags = ?, risk_remark = ?, risk_source = 'intel_rule'
                            WHERE {where_clause}
                        """, (level, tags, remark, dom))

                    total_matched += cursor.rowcount
                break
            except Exception as e:
                err_str = str(e).lower()
                if ("deadlock" in err_str or "lock timeout" in err_str or "could not obtain lock" in err_str) and attempt < 2:
                    time.sleep(0.05 * (attempt + 1))
                    continue
                logger.warning(f"Error syncing risk profile for domain {dom}: {e}")
                break

    if any(p.get("risk_level") in ('critical', 'high', 'medium', 'low') for p in profiles):
        try:
            target_domains = [p["domain"].lower().strip().lstrip("*.") for p in profiles if p.get("domain")] if domains_filter else None
            sync_risk_pages_from_occurrences(domains=target_domains)
        except Exception as e:
            logger.warning(f"Error syncing risk pages after profile history sync: {e}")

    return {"profile_count": len(profiles), "updated_domains": total_matched}


# ==================== Risk Page Remediation (风险页面待处置专区) ====================

def sync_risk_pages_from_occurrences(
    task_id: Optional[int] = None,
    domains: Optional[List[str]] = None
) -> dict:
    """
    Extract risk occurrences matching critical/high/medium/low risk domains
    and upsert them into the dedicated risk_page_remediations table.
    Optionally filters by specific domains for ultra-fast targeted sync.
    """
    now = now_iso()
    clean_domains = [d.lower().strip().lstrip("*.") for d in domains if d] if domains else []

    ch = get_ch_manager()
    if ch.is_available():
        try:
            with db_session() as conn:
                cursor = conn.cursor()
                task_filter = "AND ed.task_id = ?" if task_id is not None else ""
                domain_filter = ""
                params = [task_id] if task_id is not None else []
                if clean_domains:
                    placeholders = ",".join("?" for _ in clean_domains)
                    domain_filter = f"AND (ed.domain IN ({placeholders}) OR ed.root_domain IN ({placeholders}))"
                    params.extend(clean_domains)
                    params.extend(clean_domains)

                sql = f"""
                    SELECT ed.task_id, ed.domain, ed.root_domain, ed.risk_level, ed.risk_tags,
                           ed.risk_remark, ed.verify_status, ed.verify_time, ed.verify_detail
                    FROM external_domains ed
                    JOIN tasks t ON ed.task_id = t.id
                    WHERE t.status != 'deleting'
                      AND ed.risk_level IN ('critical', 'high', 'medium', 'low')
                      {task_filter}
                      {domain_filter}
                """
                cursor.execute(sql, params)
                risk_domains_rows = cursor.fetchall()

            if not risk_domains_rows:
                return {"synced_count": 0}

            domain_map = {}
            domains_list = []
            for r in risk_domains_rows:
                key = (r['task_id'], r['domain'])
                domain_map[key] = dict(r)
                domains_list.append(r['domain'])

            ch_rows = ch.get_risk_occurrences_for_sync(task_id, list(set(domains_list)))
            if ch_rows:
                with db_session() as conn:
                    cursor = conn.cursor()
                    insert_data = []
                    for occ in ch_rows:
                        tid = occ['task_id']
                        dom = occ['domain']
                        meta = domain_map.get((tid, dom))
                        if not meta:
                            continue
                        raw_tags = meta.get('risk_tags') or '[]'
                        if isinstance(raw_tags, list):
                            raw_tags = json.dumps(raw_tags, ensure_ascii=False)
                        insert_data.append((
                            tid,
                            dom,
                            meta.get('root_domain') or occ.get('root_domain') or '',
                            occ.get('page_url') or '',
                            occ.get('page_title') or '',
                            occ.get('source_type') or 'href',
                            occ.get('raw_match') or '',
                            occ.get('context_snippet') or '',
                            meta.get('risk_level') or 'medium',
                            raw_tags,
                            meta.get('risk_remark') or '',
                            meta.get('verify_status') or 'unverified',
                            meta.get('verify_time'),
                            meta.get('verify_detail') or '',
                            'pending',
                            occ.get('created_at') or now,
                            now
                        ))

                    if insert_data:
                        cursor.executemany("""
                            INSERT INTO risk_page_remediations (
                                task_id, domain, root_domain, page_url, page_title, source_type,
                                raw_match, context_snippet, risk_level, risk_tags, risk_remark,
                                verify_status, last_verified_at, last_verify_detail, manual_status,
                                created_at, updated_at
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            ON CONFLICT(task_id, domain, page_url) DO UPDATE SET
                                risk_level = excluded.risk_level,
                                risk_tags = excluded.risk_tags,
                                risk_remark = excluded.risk_remark,
                                context_snippet = CASE 
                                    WHEN LENGTH(risk_page_remediations.context_snippet) < 10 THEN excluded.context_snippet 
                                    ELSE risk_page_remediations.context_snippet 
                                END,
                                page_title = CASE 
                                    WHEN risk_page_remediations.page_title = '' THEN excluded.page_title 
                                    ELSE risk_page_remediations.page_title 
                                END,
                                updated_at = excluded.updated_at
                        """, insert_data)
                        return {"synced_count": len(insert_data)}
        except Exception as e:
            logger.warning(f"[Dual-Engine] ClickHouse sync_risk_pages_from_occurrences failed: {e}. Falling back to PostgreSQL.")

    # PostgreSQL Fallback
    with db_session() as conn:
        cursor = conn.cursor()
        task_filter = "AND o.task_id = ?" if task_id is not None else ""
        domain_filter = ""
        extra_params = []
        if clean_domains:
            placeholders = ",".join("?" for _ in clean_domains)
            domain_filter = f"AND (o.domain IN ({placeholders}) OR ed.root_domain IN ({placeholders}))"
            extra_params.extend(clean_domains)
            extra_params.extend(clean_domains)

        sql = f"""
            INSERT INTO risk_page_remediations (
                task_id, domain, root_domain, page_url, page_title, source_type,
                raw_match, context_snippet, risk_level, risk_tags, risk_remark,
                verify_status, last_verified_at, last_verify_detail, manual_status,
                created_at, updated_at
            )
            SELECT DISTINCT ON (o.task_id, o.domain, o.page_url)
                o.task_id, o.domain, ed.root_domain, o.page_url, '',
                COALESCE(o.source_type, 'href'),
                COALESCE(o.raw_match, ''),
                COALESCE(o.context_snippet, ''),
                ed.risk_level,
                COALESCE(ed.risk_tags, '[]'),
                COALESCE(ed.risk_remark, ''),
                COALESCE(ed.verify_status, 'unverified'),
                ed.verify_time,
                COALESCE(ed.verify_detail, ''),
                'pending',
                COALESCE(o.created_at, ?),
                ?
            FROM domain_occurrences o
            JOIN external_domains ed ON o.task_id = ed.task_id AND o.domain = ed.domain
            JOIN tasks t ON ed.task_id = t.id
            WHERE t.status != 'deleting'
              AND ed.risk_level IN ('critical', 'high', 'medium', 'low')
              {task_filter}
              {domain_filter}
            ORDER BY o.task_id, o.domain, o.page_url, LENGTH(COALESCE(o.context_snippet, '')) DESC
            ON CONFLICT(task_id, domain, page_url) DO UPDATE SET
                risk_level = excluded.risk_level,
                risk_tags = excluded.risk_tags,
                risk_remark = excluded.risk_remark,
                context_snippet = CASE 
                    WHEN LENGTH(risk_page_remediations.context_snippet) < 10 THEN excluded.context_snippet 
                    ELSE risk_page_remediations.context_snippet 
                END,
                page_title = CASE 
                    WHEN risk_page_remediations.page_title = '' THEN excluded.page_title 
                    ELSE risk_page_remediations.page_title 
                END,
                updated_at = excluded.updated_at
        """
        params = [now, now] + ([task_id] if task_id is not None else []) + extra_params
        cursor.execute(sql, params)
        synced_count = cursor.rowcount
        return {"synced_count": max(0, synced_count)}


def list_risk_remediations(
    task_id: Optional[int] = None,
    risk_level: Optional[str] = None,
    verify_status: Optional[str] = None,
    manual_status: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = 50,
    offset: int = 0
) -> Tuple[List[dict], int]:
    """
    List risk page remediations with multi-dimensional filtering, pagination,
    and associated task metadata.
    """
    with db_session() as conn:
        cursor = conn.cursor()
        where_clauses = ["t.status != 'deleting'"]
        params: List[Any] = []

        if task_id:
            where_clauses.append("r.task_id = ?")
            params.append(task_id)

        if risk_level:
            if risk_level == "all_risk":
                where_clauses.append("r.risk_level IN ('critical', 'high', 'medium', 'low')")
            else:
                where_clauses.append("r.risk_level = ?")
                params.append(risk_level)

        if verify_status:
            if verify_status == "pending_only":
                where_clauses.append("r.verify_status IN ('unverified', 'verified_failed')")
            else:
                where_clauses.append("r.verify_status = ?")
                params.append(verify_status)

        if manual_status:
            where_clauses.append("r.manual_status = ?")
            params.append(manual_status)

        if search:
            pat = f"%{search.strip()}%"
            where_clauses.append("(r.page_url LIKE ? OR r.domain LIKE ? OR r.page_title LIKE ? OR t.name LIKE ?)")
            params.extend([pat, pat, pat, pat])

        where_sql = " AND ".join(where_clauses)

        # Count total
        count_sql = f"""
            SELECT COUNT(*)
            FROM risk_page_remediations r
            JOIN tasks t ON r.task_id = t.id
            WHERE {where_sql}
        """
        cursor.execute(count_sql, params)
        total = cursor.fetchone()[0]

        # Query items
        query_sql = f"""
            SELECT 
                r.id,
                r.task_id,
                t.name as task_name,
                t.target_url as target_site_url,
                r.domain,
                r.root_domain,
                r.page_url,
                r.page_title,
                r.source_type,
                r.raw_match,
                r.context_snippet,
                r.risk_level,
                r.risk_tags,
                r.risk_remark,
                r.verify_status,
                r.last_verified_at,
                r.last_verify_detail,
                r.manual_status,
                r.manual_remark,
                r.created_at,
                r.updated_at
            FROM risk_page_remediations r
            JOIN tasks t ON r.task_id = t.id
            WHERE {where_sql}
            ORDER BY 
                CASE 
                    WHEN r.verify_status = 'verified_failed' THEN 1
                    WHEN r.verify_status = 'unverified' THEN 2
                    ELSE 3
                END ASC,
                r.id DESC
            LIMIT ? OFFSET ?
        """
        cursor.execute(query_sql, params + [limit, offset])
        rows = cursor.fetchall()
        items = []
        for r in rows:
            d = dict(r)
            raw_tags = d.get("risk_tags") or "[]"
            if isinstance(raw_tags, str):
                try:
                    d["risk_tags"] = json.loads(raw_tags)
                except Exception:
                    d["risk_tags"] = [raw_tags] if raw_tags else []
            items.append(d)

        return items, total


def get_risk_remediations_stats() -> dict:
    """Get high-level metrics for the pending risk remediation view."""
    with db_session() as conn:
        cursor = conn.cursor()

        cursor.execute("""
            SELECT 
                COUNT(*) as total_items,
                COUNT(CASE WHEN r.verify_status IN ('unverified', 'verified_failed') AND r.manual_status != 'ignored' THEN 1 END) as pending_count,
                COUNT(CASE WHEN r.verify_status = 'verified_failed' THEN 1 END) as failed_count,
                COUNT(CASE WHEN r.verify_status = 'unverified' THEN 1 END) as unverified_count,
                COUNT(CASE WHEN r.verify_status IN ('verified_clean', 'page_removed') THEN 1 END) as clean_count,
                COUNT(DISTINCT CASE WHEN r.verify_status IN ('unverified', 'verified_failed') AND r.manual_status != 'ignored' THEN r.task_id END) as tasks_affected,
                COUNT(DISTINCT r.domain) as unique_risk_domains,
                COUNT(DISTINCT r.page_url) as unique_pages
            FROM risk_page_remediations r
            JOIN tasks t ON r.task_id = t.id
            WHERE t.status != 'deleting'
        """)
        row = dict(cursor.fetchone())

        cursor.execute("""
            SELECT r.risk_level, COUNT(*) as cnt
            FROM risk_page_remediations r
            JOIN tasks t ON r.task_id = t.id
            WHERE t.status != 'deleting'
              AND r.verify_status IN ('unverified', 'verified_failed')
              AND r.manual_status != 'ignored'
            GROUP BY r.risk_level
        """)
        level_map = {r['risk_level']: r['cnt'] for r in cursor.fetchall()}

        cursor.execute("""
            SELECT r.task_id, t.name as task_name, COUNT(*) as pending_count
            FROM risk_page_remediations r
            JOIN tasks t ON r.task_id = t.id
            WHERE t.status != 'deleting'
              AND r.verify_status IN ('unverified', 'verified_failed')
              AND r.manual_status != 'ignored'
            GROUP BY r.task_id, t.name
            ORDER BY pending_count DESC
            LIMIT 20
        """)
        task_summary = [dict(r) for r in cursor.fetchall()]

        return {
            "total_items": row.get("total_items", 0),
            "pending_count": row.get("pending_count", 0),
            "failed_count": row.get("failed_count", 0),
            "unverified_count": row.get("unverified_count", 0),
            "clean_count": row.get("clean_count", 0),
            "tasks_affected": row.get("tasks_affected", 0),
            "unique_risk_domains": row.get("unique_risk_domains", 0),
            "unique_pages": row.get("unique_pages", 0),
            "level_counts": {
                "critical": level_map.get("critical", 0),
                "high": level_map.get("high", 0),
                "medium": level_map.get("medium", 0),
                "low": level_map.get("low", 0),
            },
            "task_summary": task_summary
        }


def get_risk_remediation_by_id(remediation_id: int) -> Optional[dict]:
    """Fetch a single risk remediation item by ID."""
    with db_session() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT r.*, t.name as task_name, t.target_url as target_site_url
            FROM risk_page_remediations r
            JOIN tasks t ON r.task_id = t.id
            WHERE r.id = ?
        """, (remediation_id,))
        row = cursor.fetchone()
        if not row:
            return None
        d = dict(row)
        raw_tags = d.get("risk_tags") or "[]"
        if isinstance(raw_tags, str):
            try:
                d["risk_tags"] = json.loads(raw_tags)
            except Exception:
                d["risk_tags"] = [raw_tags] if raw_tags else []
        return d


def update_risk_remediation_verify_result(
    remediation_id: int,
    verify_status: str,
    verify_time: str,
    verify_detail: str,
    context_snippet: Optional[str] = None
) -> dict:
    """
    Update single risk page verification verdict:
    - If verified_clean / page_removed: marks ticket manual_status as 'resolved' (unless ignored).
    - If verified_failed: if ticket was 'resolved', reopens ticket manual_status to 'pending'.
    - Synchronizes domain-level verification status in external_domains when all pages are clean or when failed.
    """
    with db_session() as conn:
        cursor = conn.cursor()
        now = now_iso()

        if verify_status in ('verified_clean', 'page_removed'):
            if context_snippet:
                cursor.execute("""
                    UPDATE risk_page_remediations
                    SET verify_status = ?, last_verified_at = ?, last_verify_detail = ?,
                        context_snippet = ?,
                        manual_status = CASE WHEN manual_status != 'ignored' THEN 'resolved' ELSE manual_status END,
                        manual_remark = CASE 
                            WHEN manual_status != 'ignored' AND (manual_remark IS NULL OR manual_remark = '' OR POSITION('工单重新打开' IN COALESCE(manual_remark, '')) > 0)
                            THEN '系统自动复测：违规外链已清除，工单自动完结'
                            ELSE manual_remark 
                        END,
                        updated_at = ?
                    WHERE id = ?
                """, (verify_status, verify_time, verify_detail, context_snippet, now, remediation_id))
            else:
                cursor.execute("""
                    UPDATE risk_page_remediations
                    SET verify_status = ?, last_verified_at = ?, last_verify_detail = ?,
                        manual_status = CASE WHEN manual_status != 'ignored' THEN 'resolved' ELSE manual_status END,
                        manual_remark = CASE 
                            WHEN manual_status != 'ignored' AND (manual_remark IS NULL OR manual_remark = '' OR POSITION('工单重新打开' IN COALESCE(manual_remark, '')) > 0)
                            THEN '系统自动复测：违规外链已清除，工单自动完结'
                            ELSE manual_remark 
                        END,
                        updated_at = ?
                    WHERE id = ?
                """, (verify_status, verify_time, verify_detail, now, remediation_id))
        elif verify_status == 'verified_failed':
            if context_snippet:
                cursor.execute("""
                    UPDATE risk_page_remediations
                    SET verify_status = ?, last_verified_at = ?, last_verify_detail = ?,
                        context_snippet = ?,
                        manual_status = CASE WHEN manual_status = 'resolved' THEN 'pending' ELSE manual_status END,
                        manual_remark = CASE 
                            WHEN manual_status = 'resolved' 
                            THEN '【复测告警】检测到违规外链再次出现，工单重新打开待处置'
                            ELSE manual_remark 
                        END,
                        updated_at = ?
                    WHERE id = ?
                """, (verify_status, verify_time, verify_detail, context_snippet, now, remediation_id))
            else:
                cursor.execute("""
                    UPDATE risk_page_remediations
                    SET verify_status = ?, last_verified_at = ?, last_verify_detail = ?,
                        manual_status = CASE WHEN manual_status = 'resolved' THEN 'pending' ELSE manual_status END,
                        manual_remark = CASE 
                            WHEN manual_status = 'resolved' 
                            THEN '【复测告警】检测到违规外链再次出现，工单重新打开待处置'
                            ELSE manual_remark 
                        END,
                        updated_at = ?
                    WHERE id = ?
                """, (verify_status, verify_time, verify_detail, now, remediation_id))
        else:
            if context_snippet:
                cursor.execute("""
                    UPDATE risk_page_remediations
                    SET verify_status = ?, last_verified_at = ?, last_verify_detail = ?,
                        context_snippet = ?, updated_at = ?
                    WHERE id = ?
                """, (verify_status, verify_time, verify_detail, context_snippet, now, remediation_id))
            else:
                cursor.execute("""
                    UPDATE risk_page_remediations
                    SET verify_status = ?, last_verified_at = ?, last_verify_detail = ?, updated_at = ?
                    WHERE id = ?
                """, (verify_status, verify_time, verify_detail, now, remediation_id))

        cursor.execute("SELECT manual_status, task_id, domain FROM risk_page_remediations WHERE id = ?", (remediation_id,))
        curr = cursor.fetchone()
        current_manual_status = curr["manual_status"] if curr else "pending"

        # Synchronize external_domains status
        if curr:
            t_id, dom = curr["task_id"], curr["domain"]
            if verify_status in ('verified_clean', 'page_removed'):
                cursor.execute("""
                    SELECT COUNT(*) as remaining
                    FROM risk_page_remediations
                    WHERE task_id = ? AND domain = ?
                      AND verify_status NOT IN ('verified_clean', 'page_removed')
                """, (t_id, dom))
                rem = cursor.fetchone()
                if rem and rem["remaining"] == 0:
                    cursor.execute("""
                        UPDATE external_domains
                        SET verify_status = 'verified_clean', verify_time = ?,
                            verify_detail = '【系统复测】所有涉险页面均已完成修复清除，工单闭环。'
                        WHERE task_id = ? AND domain = ?
                    """, (verify_time, t_id, dom))
            elif verify_status == 'verified_failed':
                cursor.execute("""
                    UPDATE external_domains
                    SET verify_status = 'verified_failed', verify_time = ?,
                        verify_detail = ?
                    WHERE task_id = ? AND domain = ?
                """, (verify_time, verify_detail, t_id, dom))

        return {"manual_status": current_manual_status}


def batch_update_risk_remediations_manual_status(
    ids: List[int],
    manual_status: str,
    manual_remark: Optional[str] = None
) -> int:
    """Batch update manual handling status (e.g. resolved, ignored, in_progress)."""
    if not ids:
        return 0
    with db_session() as conn:
        cursor = conn.cursor()
        placeholders = ",".join("?" for _ in ids)
        now = now_iso()
        if manual_remark is not None:
            cursor.execute(f"""
                UPDATE risk_page_remediations
                SET manual_status = ?, manual_remark = ?, updated_at = ?
                WHERE id IN ({placeholders})
            """, [manual_status, manual_remark, now] + ids)
        else:
            cursor.execute(f"""
                UPDATE risk_page_remediations
                SET manual_status = ?, updated_at = ?
                WHERE id IN ({placeholders})
            """, [manual_status, now] + ids)
        return cursor.rowcount


def get_unverified_risk_remediations(limit: Optional[int] = None) -> List[dict]:
    """Retrieve items requiring periodic automatic re-check (None means all records)."""
    with db_session() as conn:
        cursor = conn.cursor()
        sql = """
            SELECT r.id, r.task_id, r.domain, r.page_url, r.source_type, r.last_verified_at, r.raw_match
            FROM risk_page_remediations r
            JOIN tasks t ON r.task_id = t.id
            WHERE t.status != 'deleting'
              AND r.verify_status IN ('unverified', 'verified_failed')
              AND r.manual_status != 'ignored'
            ORDER BY r.last_verified_at ASC NULLS FIRST, r.id ASC
        """
        if limit is not None:
            sql += f" LIMIT {int(limit)}"
        cursor.execute(sql)
        return [dict(r) for r in cursor.fetchall()]


def get_remediated_risk_remediations(limit: Optional[int] = None) -> List[dict]:
    """Retrieve remediated items (verified_clean, page_removed) for rollback re-audit (None means all records)."""
    with db_session() as conn:
        cursor = conn.cursor()
        sql = """
            SELECT r.id, r.task_id, r.domain, r.page_url, r.source_type, r.last_verified_at, r.raw_match
            FROM risk_page_remediations r
            JOIN tasks t ON r.task_id = t.id
            WHERE t.status != 'deleting'
              AND r.verify_status IN ('verified_clean', 'page_removed')
              AND r.manual_status != 'ignored'
            ORDER BY r.last_verified_at ASC NULLS FIRST, r.id ASC
        """
        if limit is not None:
            sql += f" LIMIT {int(limit)}"
        cursor.execute(sql)
        return [dict(r) for r in cursor.fetchall()]


def mark_remediation_rollback_failed(
    remediation_id: int,
    task_id: int,
    domain: str,
    verify_time: str,
    verify_detail: str,
    context_snippet: Optional[str] = None
):
    """Mark a previously remediated item as verified_failed when rollback/regression is detected, reopen ticket to pending, and sync external_domains."""
    with db_session() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE risk_page_remediations
            SET verify_status = 'verified_failed',
                last_verified_at = ?,
                last_verify_detail = ?,
                context_snippet = COALESCE(?, context_snippet),
                manual_status = 'pending',
                manual_remark = '【防回滚告警】已修复记录重新检测到违规外链，工单重新打开待处置',
                updated_at = ?
            WHERE id = ?
        """, (verify_time, verify_detail, context_snippet, now_iso(), remediation_id))
        cursor.execute("""
            UPDATE external_domains
            SET verify_status = 'verified_failed', verify_time = ?, verify_detail = ?
            WHERE task_id = ? AND domain = ?
        """, (verify_time, verify_detail, task_id, domain))


def sync_existing_remediation_manual_statuses() -> dict:
    """
    Synchronize manual ticket status for existing remediation records:
    1. Records verified clean or removed -> mark manual_status as 'resolved' (ticket finished).
    2. Records verified failed that were resolved -> reopen manual_status to 'pending'.
    """
    with db_session() as conn:
        cursor = conn.cursor()
        now = now_iso()
        cursor.execute("""
            UPDATE risk_page_remediations
            SET manual_status = 'resolved',
                manual_remark = COALESCE(NULLIF(manual_remark, ''), '系统自动复测：违规外链已清除，工单自动完结'),
                updated_at = ?
            WHERE verify_status IN ('verified_clean', 'page_removed')
              AND manual_status NOT IN ('resolved', 'ignored')
        """, (now,))
        resolved_count = cursor.rowcount

        cursor.execute("""
            UPDATE risk_page_remediations
            SET manual_status = 'pending',
                manual_remark = '【复测告警】检测到违规外链再次出现，工单重新打开待处置',
                updated_at = ?
            WHERE verify_status = 'verified_failed'
              AND manual_status = 'resolved'
        """, (now,))
        reopened_count = cursor.rowcount

        return {"auto_resolved": resolved_count, "reopened": reopened_count}



def get_risk_remediations_for_export(
    task_id: Optional[int] = None,
    verify_status: Optional[str] = None,
    risk_level: Optional[str] = None
) -> List[dict]:
    """Fetch complete remediation rows formatted for task-based Excel/CSV exports."""
    with db_session() as conn:
        cursor = conn.cursor()
        where_clauses = ["t.status != 'deleting'"]
        params: List[Any] = []

        if task_id:
            where_clauses.append("r.task_id = ?")
            params.append(task_id)

        if verify_status:
            if verify_status == "pending_only":
                where_clauses.append("r.verify_status IN ('unverified', 'verified_failed')")
            else:
                where_clauses.append("r.verify_status = ?")
                params.append(verify_status)

        if risk_level:
            if risk_level != "all_risk":
                where_clauses.append("r.risk_level = ?")
                params.append(risk_level)

        where_sql = " AND ".join(where_clauses)
        cursor.execute(f"""
            SELECT 
                r.id,
                r.task_id,
                t.name as task_name,
                t.target_url as target_site_url,
                r.page_url,
                r.page_title,
                r.domain,
                r.root_domain,
                r.risk_level,
                r.risk_tags,
                r.risk_remark,
                r.source_type,
                r.context_snippet,
                r.verify_status,
                r.last_verified_at,
                r.last_verify_detail,
                r.manual_status,
                r.manual_remark,
                r.created_at
            FROM risk_page_remediations r
            JOIN tasks t ON r.task_id = t.id
            WHERE {where_sql}
            ORDER BY r.task_id ASC, r.risk_level ASC, r.id ASC
        """, params)
        return [dict(r) for r in cursor.fetchall()]


