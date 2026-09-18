import json
import sqlite3
from datetime import datetime
from typing import Optional, List, Dict, Any, Tuple
from app.db.database import db_session

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

def get_task(task_id: int) -> Optional[dict]:
    with db_session() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
        row = cursor.fetchone()
        if not row:
            return None
        d = dict(row)
        d["config"] = json.loads(d["config"]) if d["config"] else {}
        return d

def list_tasks(limit: int = 50, offset: int = 0) -> Tuple[List[dict], int]:
    with db_session() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM tasks")
        total = cursor.fetchone()[0]
        
        cursor.execute("""
            SELECT * FROM tasks ORDER BY id DESC LIMIT ? OFFSET ?
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

def delete_task(task_id: int):
    """Explicitly delete task child records using indexed task_id lookups for maximum speed."""
    with db_session() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM domain_occurrences WHERE task_id = ?", (task_id,))
        cursor.execute("DELETE FROM sitemap_pages WHERE task_id = ?", (task_id,))
        cursor.execute("DELETE FROM external_domains WHERE task_id = ?", (task_id,))
        cursor.execute("DELETE FROM discovered_subdomains WHERE task_id = ?", (task_id,))
        cursor.execute("DELETE FROM task_logs WHERE task_id = ?", (task_id,))
        cursor.execute("DELETE FROM tasks WHERE id = ?", (task_id,))

def batch_delete_tasks(task_ids: List[int]) -> int:
    """Delete multiple tasks and their associated child tables in a single atomic transaction."""
    if not task_ids:
        return 0
    with db_session() as conn:
        cursor = conn.cursor()
        placeholders = ",".join("?" for _ in task_ids)
        cursor.execute(f"DELETE FROM domain_occurrences WHERE task_id IN ({placeholders})", task_ids)
        cursor.execute(f"DELETE FROM sitemap_pages WHERE task_id IN ({placeholders})", task_ids)
        cursor.execute(f"DELETE FROM external_domains WHERE task_id IN ({placeholders})", task_ids)
        cursor.execute(f"DELETE FROM discovered_subdomains WHERE task_id IN ({placeholders})", task_ids)
        cursor.execute(f"DELETE FROM task_logs WHERE task_id IN ({placeholders})", task_ids)
        cursor.execute(f"DELETE FROM tasks WHERE id IN ({placeholders})", task_ids)
        return cursor.rowcount

# ==================== Sitemap Pages ====================

def insert_page(task_id: int, url: str, path: str, depth: int, status_code: int,
                content_type: str, title: str, response_time_ms: int,
                external_domains_count: int, error: Optional[str] = None) -> int:
    with db_session() as conn:
        cursor = conn.cursor()
        now = now_iso()
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
    Greatly reduces disk I/O and SQLite lock contention in concurrent crawling.
    """
    with db_session() as conn:
        cursor = conn.cursor()
        now = now_iso()

        # 1. Insert sitemap page
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
            page_data['url'],
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
            for d in external_domains:
                cursor.execute("""
                    INSERT INTO external_domains (
                        task_id, domain, root_domain, occurrence_count,
                        has_link, has_text, sample_page_url, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(task_id, domain) DO UPDATE SET
                        occurrence_count = occurrence_count + excluded.occurrence_count,
                        has_link = CASE WHEN excluded.has_link = 1 THEN 1 ELSE has_link END,
                        has_text = CASE WHEN excluded.has_text = 1 THEN 1 ELSE has_text END,
                        sample_page_url = CASE WHEN sample_page_url = '' THEN excluded.sample_page_url ELSE sample_page_url END
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

        # 3. Upsert discovered subdomains
        if subdomains:
            for s in subdomains:
                cursor.execute("""
                    INSERT INTO discovered_subdomains (
                        task_id, subdomain, root_domain, occurrence_count,
                        has_link, has_text, sample_page_url, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(task_id, subdomain) DO UPDATE SET
                        occurrence_count = occurrence_count + excluded.occurrence_count,
                        has_link = CASE WHEN excluded.has_link = 1 THEN 1 ELSE has_link END,
                        has_text = CASE WHEN excluded.has_text = 1 THEN 1 ELSE has_text END,
                        sample_page_url = CASE WHEN sample_page_url = '' THEN excluded.sample_page_url ELSE sample_page_url END
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
                        occurrence_count = occurrence_count + excluded.occurrence_count,
                        has_link = CASE WHEN excluded.has_link = 1 THEN 1 ELSE has_link END,
                        has_text = CASE WHEN excluded.has_text = 1 THEN 1 ELSE has_text END,
                        sample_page_url = CASE WHEN sample_page_url = '' THEN excluded.sample_page_url ELSE sample_page_url END
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
                        occurrence_count = occurrence_count + excluded.occurrence_count,
                        has_link = CASE WHEN excluded.has_link = 1 THEN 1 ELSE has_link END,
                        has_text = CASE WHEN excluded.has_text = 1 THEN 1 ELSE has_text END,
                        sample_page_url = CASE WHEN sample_page_url = '' THEN excluded.sample_page_url ELSE sample_page_url END
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
    and occurrences in a single atomic SQLite transaction.
    Also updates task progress within the same transaction to avoid lock contention.
    """
    if not batch_items:
        return

    with db_session() as conn:
        cursor = conn.cursor()
        now = now_iso()

        # 1. Insert sitemap pages
        pages_to_insert = [
            (
                task_id,
                item['page_data']['url'],
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

        for d in aggregated_ext.values():
            cursor.execute("""
                INSERT INTO external_domains (
                    task_id, domain, root_domain, occurrence_count,
                    has_link, has_text, sample_page_url, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(task_id, domain) DO UPDATE SET
                    occurrence_count = occurrence_count + excluded.occurrence_count,
                    has_link = CASE WHEN excluded.has_link = 1 THEN 1 ELSE has_link END,
                    has_text = CASE WHEN excluded.has_text = 1 THEN 1 ELSE has_text END,
                    sample_page_url = CASE WHEN sample_page_url = '' THEN excluded.sample_page_url ELSE sample_page_url END
            """, (
                task_id,
                d['domain'],
                d['root_domain'],
                d['count'],
                d['has_link'],
                d['has_text'],
                d['sample_page_url'],
                now
            ))

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

        for s in aggregated_sub.values():
            cursor.execute("""
                INSERT INTO discovered_subdomains (
                    task_id, subdomain, root_domain, occurrence_count,
                    has_link, has_text, sample_page_url, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(task_id, subdomain) DO UPDATE SET
                    occurrence_count = occurrence_count + excluded.occurrence_count,
                    has_link = CASE WHEN excluded.has_link = 1 THEN 1 ELSE has_link END,
                    has_text = CASE WHEN excluded.has_text = 1 THEN 1 ELSE has_text END,
                    sample_page_url = CASE WHEN sample_page_url = '' THEN excluded.sample_page_url ELSE sample_page_url END
            """, (
                task_id,
                s['subdomain'],
                s['root_domain'],
                s['count'],
                s['has_link'],
                s['has_text'],
                s['sample_page_url'],
                now
            ))

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
    with db_session() as conn:
        cursor = conn.cursor()
        now = now_iso()
        cursor.executemany("""
            INSERT INTO task_logs (task_id, level, message, created_at)
            VALUES (?, ?, ?, ?)
        """, [(task_id, l['level'], l['message'], l.get('timestamp') or now) for l in logs_list])



def list_pages(task_id: int, depth: Optional[int] = None, status_code: Optional[int] = None,
               search: Optional[str] = None, limit: int = 50, offset: int = 0) -> Tuple[List[dict], int]:
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
                    occurrence_count = occurrence_count + excluded.occurrence_count,
                    has_link = CASE WHEN excluded.has_link = 1 THEN 1 ELSE has_link END,
                    has_text = CASE WHEN excluded.has_text = 1 THEN 1 ELSE has_text END,
                    sample_page_url = CASE WHEN sample_page_url = '' THEN excluded.sample_page_url ELSE sample_page_url END
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
        valid_cols = {'occurrence_count': 'occurrence_count', 'domain': 'domain', 'root_domain': 'root_domain', 'id': 'id'}
        col = valid_cols.get(sort_by, 'occurrence_count')
        sort_order = 'ASC' if order.upper() == 'ASC' else 'DESC'

        query += f" ORDER BY {col} {sort_order}, id DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        cursor.execute(query, params)
        rows = [dict(r) for r in cursor.fetchall()]
        return rows, total

def get_domain_occurrences(task_id: int, domain: str, limit: int = 50) -> List[dict]:
    with db_session() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM domain_occurrences
            WHERE task_id = ? AND domain = ?
            ORDER BY id ASC
            LIMIT ?
        """, (task_id, domain, limit))
        return [dict(r) for r in cursor.fetchall()]

def get_external_domains_for_export(task_id: int) -> List[dict]:
    with db_session() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT domain, root_domain, occurrence_count, has_link, has_text, sample_page_url, created_at
            FROM external_domains
            WHERE task_id = ?
            ORDER BY occurrence_count DESC, domain ASC
        """, (task_id,))
        return [dict(r) for r in cursor.fetchall()]

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
            SELECT domain, root_domain, occurrence_count, has_link, has_text
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
        cursor.execute("SELECT id FROM tasks")
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
    with db_session() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO task_logs (task_id, level, message, created_at)
            VALUES (?, ?, ?, ?)
        """, (task_id, level.upper(), message, now_iso()))

def batch_add_logs(logs: List[dict]):
    if not logs:
        return
    with db_session() as conn:
        cursor = conn.cursor()
        cursor.executemany("""
            INSERT INTO task_logs (task_id, level, message, created_at)
            VALUES (?, ?, ?, ?)
        """, [(l["task_id"], l["level"].upper(), l["message"], l.get("created_at") or now_iso()) for l in logs])

def get_recent_logs(task_id: int, limit: int = 100) -> List[dict]:
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

        where_clauses = ["1=1"]
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
            )
        """
        cursor.execute(count_sql, params + having_params)
        total = cursor.fetchone()[0]

        # Sorting
        valid_cols = {
            'total_occurrences': 'total_occurrences',
            'task_count': 'task_count',
            'domain': 'ed.domain',
            'root_domain': 'ed.root_domain',
            'first_seen_at': 'first_seen_at',
            'last_seen_at': 'last_seen_at'
        }
        col = valid_cols.get(sort_by, 'total_occurrences')
        direction = 'ASC' if order.upper() == 'ASC' else 'DESC'

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
                GROUP_CONCAT(t.id || ':::' || t.name || ':::' || ed.occurrence_count, ';;;') as tasks_summary_raw
            FROM external_domains ed
            JOIN tasks t ON ed.task_id = t.id
            WHERE {where_sql}
            GROUP BY ed.domain
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

            results.append({
                "domain": r["domain"],
                "root_domain": r["root_domain"],
                "total_occurrences": r["total_occurrences"],
                "task_count": r["task_count"],
                "has_link": bool(r["has_link"]),
                "has_text": bool(r["has_text"]),
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

        cursor.execute("SELECT COUNT(*) FROM tasks")
        total_tasks = cursor.fetchone()[0]

        cursor.execute("SELECT COALESCE(SUM(occurrence_count), 0) FROM external_domains")
        total_occurrences = cursor.fetchone()[0]

        cursor.execute("""
            SELECT COUNT(*) FROM (
                SELECT domain FROM external_domains GROUP BY domain HAVING COUNT(DISTINCT task_id) >= 2
            )
        """)
        shared_domains_count = cursor.fetchone()[0]

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
                root_domain,
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
                ed.created_at
            FROM external_domains ed
            JOIN tasks t ON ed.task_id = t.id
            WHERE ed.domain = ?
            ORDER BY ed.occurrence_count DESC, t.id DESC
        """, (domain,))
        tasks_list = [dict(r) for r in cursor.fetchall()]

        for t in tasks_list:
            if max_occurrences_per_task is not None:
                cursor.execute("""
                    SELECT page_url, source_type, raw_match, context_snippet, created_at
                    FROM domain_occurrences
                    WHERE task_id = ? AND domain = ?
                    ORDER BY id ASC
                    LIMIT ?
                """, (t["task_id"], domain, max_occurrences_per_task))
            else:
                cursor.execute("""
                    SELECT page_url, source_type, raw_match, context_snippet, created_at
                    FROM domain_occurrences
                    WHERE task_id = ? AND domain = ?
                    ORDER BY id ASC
                """, (t["task_id"], domain))
            t["occurrences"] = [dict(r) for r in cursor.fetchall()]

        return tasks_list


def get_global_domains_for_export(
    search: Optional[str] = None,
    root_domain: Optional[str] = None,
    min_tasks: Optional[int] = None
) -> List[dict]:
    """Export all aggregated external domains with full metadata."""
    domains, _ = list_global_external_domains(
        search=search,
        root_domain=root_domain,
        min_tasks=min_tasks,
        limit=100000,
        offset=0
    )
    return domains

