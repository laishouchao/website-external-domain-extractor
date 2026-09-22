#!/usr/bin/env python3
"""
PostgreSQL to ClickHouse High-Speed Streaming Migration Tool
Website External Domain Extraction System (PostgreSQL + ClickHouse Dual Engine)

Migrates append-only big data from PostgreSQL to ClickHouse MergeTree tables:
1. sitemap_pages
2. domain_occurrences
3. task_logs

Features:
- Keyset-based streaming batch migration (constant memory footprint)
- Zero risk to running system (read-only queries on PostgreSQL)
- High throughput batch ingestion via native clickhouse-connect
- Live throughput (rows/sec), progress percentage, and ETA
- Verification mode to compare PostgreSQL and ClickHouse row counts
"""

import sys
import time
import argparse
from pathlib import Path
from datetime import datetime

# Add project root to sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from app.config import (
    PG_HOST, PG_PORT, PG_USER, PG_PASSWORD, PG_DATABASE,
    CH_HOST, CH_PORT, CH_USER, CH_PASSWORD, CH_DATABASE
)
from app.db.database import db_session
from app.db.clickhouse import get_ch_manager, init_clickhouse


def format_num(n: int) -> str:
    return f"{n:,}"


def migrate_sitemap_pages(ch_mgr, chunk_size: int = 50000, task_id: int = None):
    print("\n" + "=" * 60)
    print("  [1/3] Migrating: sitemap_pages -> ClickHouse")
    print("=" * 60)

    with db_session() as conn:
        cursor = conn.cursor()
        task_filter = "WHERE task_id = %s" if task_id else ""
        params = (task_id,) if task_id else ()
        cursor.execute(f"SELECT COUNT(*) FROM sitemap_pages {task_filter}", params)
        total_rows = cursor.fetchone()[0]

    print(f"  PostgreSQL total records: {format_num(total_rows)}")
    if total_rows == 0:
        print("  No records to migrate. Skipping.")
        return

    last_id = 0
    migrated = 0
    start_time = time.time()

    while True:
        with db_session() as conn:
            cursor = conn.cursor()
            if task_id:
                cursor.execute("""
                    SELECT id, task_id, url, path, depth, status_code, content_type,
                           title, response_time_ms, external_domains_count, error, crawled_at
                    FROM sitemap_pages
                    WHERE task_id = %s AND id > %s
                    ORDER BY id ASC
                    LIMIT %s
                """, (task_id, last_id, chunk_size))
            else:
                cursor.execute("""
                    SELECT id, task_id, url, path, depth, status_code, content_type,
                           title, response_time_ms, external_domains_count, error, crawled_at
                    FROM sitemap_pages
                    WHERE id > %s
                    ORDER BY id ASC
                    LIMIT %s
                """, (last_id, chunk_size))

            rows = cursor.fetchall()

        if not rows:
            break

        last_id = rows[-1]['id']

        # Prepare for ClickHouse insert:
        # id, task_id, url, path, depth, status_code, content_type, title, response_time_ms, external_domains_count, error, crawled_at
        ch_data = []
        for r in rows:
            rid = r['id']
            tid = r['task_id']
            url = r['url']
            path = r['path']
            depth = r['depth']
            status_code = r['status_code']
            c_type = r['content_type']
            title = r['title']
            resp_ms = r['response_time_ms']
            ext_cnt = r['external_domains_count']
            err = r['error']
            crawled_at = r['crawled_at']

            crawled_dt = datetime.now()
            if crawled_at:
                try:
                    crawled_dt = datetime.strptime(str(crawled_at)[:19], "%Y-%m-%d %H:%M:%S")
                except Exception:
                    pass

            ch_data.append([
                int(rid),
                int(tid),
                str(url or ''),
                str(path or '/'),
                int(depth or 0),
                int(status_code or 0),
                str(c_type or ''),
                str(title or ''),
                int(resp_ms or 0),
                int(ext_cnt or 0),
                str(err or '') if err else '',
                crawled_dt
            ])

        client = ch_mgr.get_client()
        client.insert(
            f"{ch_mgr.database}.sitemap_pages",
            ch_data,
            column_names=[
                "id", "task_id", "url", "path", "depth", "status_code",
                "content_type", "title", "response_time_ms", "external_domains_count",
                "error", "crawled_at"
            ]
        )

        migrated += len(rows)
        elapsed = time.time() - start_time
        rate = migrated / elapsed if elapsed > 0 else 0
        pct = (migrated / total_rows) * 100 if total_rows > 0 else 100
        eta_sec = (total_rows - migrated) / rate if rate > 0 else 0
        print(f"\r  Progress: {format_num(migrated)} / {format_num(total_rows)} ({pct:.1f}%) | "
              f"{rate:,.0f} rows/s | ETA: {eta_sec:.0f}s", end="", flush=True)

    print(f"\n  Done! Migrated {format_num(migrated)} sitemap pages in {time.time() - start_time:.2f}s.")


def migrate_domain_occurrences(ch_mgr, chunk_size: int = 50000, task_id: int = None):
    print("\n" + "=" * 60)
    print("  [2/3] Migrating: domain_occurrences -> ClickHouse")
    print("=" * 60)

    with db_session() as conn:
        cursor = conn.cursor()
        task_filter = "WHERE task_id = %s" if task_id else ""
        params = (task_id,) if task_id else ()
        cursor.execute(f"SELECT COUNT(*) FROM domain_occurrences {task_filter}", params)
        total_rows = cursor.fetchone()[0]

    print(f"  PostgreSQL total records: {format_num(total_rows)}")
    if total_rows == 0:
        print("  No records to migrate. Skipping.")
        return

    last_id = 0
    migrated = 0
    start_time = time.time()

    while True:
        with db_session() as conn:
            cursor = conn.cursor()
            if task_id:
                cursor.execute("""
                    SELECT id, task_id, domain, page_url, source_type, raw_match, context_snippet, created_at
                    FROM domain_occurrences
                    WHERE task_id = %s AND id > %s
                    ORDER BY id ASC
                    LIMIT %s
                """, (task_id, last_id, chunk_size))
            else:
                cursor.execute("""
                    SELECT id, task_id, domain, page_url, source_type, raw_match, context_snippet, created_at
                    FROM domain_occurrences
                    WHERE id > %s
                    ORDER BY id ASC
                    LIMIT %s
                """, (last_id, chunk_size))

            rows = cursor.fetchall()

        if not rows:
            break

        last_id = rows[-1]['id']

        ch_data = []
        for r in rows:
            rid = r['id']
            tid = r['task_id']
            dom = r['domain']
            p_url = r['page_url']
            src_type = r['source_type']
            raw_m = r['raw_match']
            snippet = r['context_snippet']
            created_at = r['created_at']

            created_dt = datetime.now()
            if created_at:
                try:
                    created_dt = datetime.strptime(str(created_at)[:19], "%Y-%m-%d %H:%M:%S")
                except Exception:
                    pass

            dom_str = str(dom or '')
            parts = dom_str.split('.')
            root_dom = ".".join(parts[-2:]) if len(parts) >= 2 else dom_str
            is_link = 1 if ('link' in str(src_type) or src_type == 'href') else 0

            ch_data.append([
                int(rid),
                int(tid),
                dom_str,
                root_dom,
                str(p_url or ''),
                '',  # page_title
                str(src_type or ''),
                str(raw_m or '')[:500],
                str(snippet or '')[:1000],
                is_link,
                created_dt
            ])

        client = ch_mgr.get_client()
        client.insert(
            f"{ch_mgr.database}.domain_occurrences",
            ch_data,
            column_names=[
                "id", "task_id", "domain", "root_domain", "page_url", "page_title",
                "source_type", "raw_match", "context_snippet", "is_link", "created_at"
            ]
        )

        migrated += len(rows)
        elapsed = time.time() - start_time
        rate = migrated / elapsed if elapsed > 0 else 0
        pct = (migrated / total_rows) * 100 if total_rows > 0 else 100
        eta_sec = (total_rows - migrated) / rate if rate > 0 else 0
        print(f"\r  Progress: {format_num(migrated)} / {format_num(total_rows)} ({pct:.1f}%) | "
              f"{rate:,.0f} rows/s | ETA: {eta_sec:.0f}s", end="", flush=True)

    print(f"\n  Done! Migrated {format_num(migrated)} occurrences in {time.time() - start_time:.2f}s.")


def migrate_task_logs(ch_mgr, chunk_size: int = 50000, task_id: int = None):
    print("\n" + "=" * 60)
    print("  [3/3] Migrating: task_logs -> ClickHouse")
    print("=" * 60)

    with db_session() as conn:
        cursor = conn.cursor()
        task_filter = "WHERE task_id = %s" if task_id else ""
        params = (task_id,) if task_id else ()
        cursor.execute(f"SELECT COUNT(*) FROM task_logs {task_filter}", params)
        total_rows = cursor.fetchone()[0]

    print(f"  PostgreSQL total records: {format_num(total_rows)}")
    if total_rows == 0:
        print("  No records to migrate. Skipping.")
        return

    last_id = 0
    migrated = 0
    start_time = time.time()

    while True:
        with db_session() as conn:
            cursor = conn.cursor()
            if task_id:
                cursor.execute("""
                    SELECT id, task_id, level, message, created_at
                    FROM task_logs
                    WHERE task_id = %s AND id > %s
                    ORDER BY id ASC
                    LIMIT %s
                """, (task_id, last_id, chunk_size))
            else:
                cursor.execute("""
                    SELECT id, task_id, level, message, created_at
                    FROM task_logs
                    WHERE id > %s
                    ORDER BY id ASC
                    LIMIT %s
                """, (last_id, chunk_size))

            rows = cursor.fetchall()

        if not rows:
            break

        last_id = rows[-1]['id']

        ch_data = []
        for r in rows:
            rid = r['id']
            tid = r['task_id']
            lvl = r['level']
            msg = r['message']
            created_at = r['created_at']

            created_dt = datetime.now()
            if created_at:
                try:
                    created_dt = datetime.strptime(str(created_at)[:19], "%Y-%m-%d %H:%M:%S")
                except Exception:
                    pass

            ch_data.append([
                int(rid),
                int(tid),
                str(lvl or 'INFO').upper(),
                str(msg or ''),
                created_dt
            ])

        client = ch_mgr.get_client()
        client.insert(
            f"{ch_mgr.database}.task_logs",
            ch_data,
            column_names=["id", "task_id", "level", "message", "created_at"]
        )

        migrated += len(rows)
        elapsed = time.time() - start_time
        rate = migrated / elapsed if elapsed > 0 else 0
        pct = (migrated / total_rows) * 100 if total_rows > 0 else 100
        eta_sec = (total_rows - migrated) / rate if rate > 0 else 0
        print(f"\r  Progress: {format_num(migrated)} / {format_num(total_rows)} ({pct:.1f}%) | "
              f"{rate:,.0f} rows/s | ETA: {eta_sec:.0f}s", end="", flush=True)

    print(f"\n  Done! Migrated {format_num(migrated)} task logs in {time.time() - start_time:.2f}s.")


def verify_counts(ch_mgr):
    print("\n" + "=" * 60)
    print("  [Verification] Row Count Comparison (PG vs ClickHouse)")
    print("=" * 60)

    client = ch_mgr.get_client()
    if not client:
        print("  ClickHouse is unreachable.")
        return

    tables = ["sitemap_pages", "domain_occurrences", "task_logs"]
    print(f"  {'Table':<25} | {'PostgreSQL':<15} | {'ClickHouse':<15} | {'Match'}")
    print("  " + "-" * 65)

    for tbl in tables:
        with db_session() as conn:
            cursor = conn.cursor()
            cursor.execute(f"SELECT COUNT(*) FROM {tbl}")
            pg_cnt = cursor.fetchone()[0]

        try:
            res = client.query(f"SELECT count(*) FROM {ch_mgr.database}.{tbl}")
            ch_cnt = res.result_rows[0][0]
        except Exception as e:
            ch_cnt = f"Error ({e})"

        match_str = "YES" if pg_cnt == ch_cnt else "NO"
        print(f"  {tbl:<25} | {format_num(pg_cnt):<15} | {format_num(ch_cnt) if isinstance(ch_cnt, int) else ch_cnt:<15} | {match_str}")


def main():
    parser = argparse.ArgumentParser(description="PostgreSQL -> ClickHouse Streaming Migration Tool")
    parser.add_argument("--batch-size", type=int, default=50000, help="Batch chunk size (default: 50000)")
    parser.add_argument("--table", choices=["all", "sitemap_pages", "domain_occurrences", "task_logs"], default="all")
    parser.add_argument("--task-id", type=int, default=None, help="Migrate specific task ID only")
    parser.add_argument("--verify-only", action="store_true", help="Only verify row counts without migrating")
    args = parser.parse_args()

    print("===============================================================")
    print("  PostgreSQL + ClickHouse Dual Engine Data Migration Tool")
    print(f"  Source (PG): {PG_HOST}:{PG_PORT}/{PG_DATABASE}")
    print(f"  Target (CH): {CH_HOST}:{CH_PORT}/{CH_DATABASE}")
    print("===============================================================")

    ch_mgr = get_ch_manager()
    if not ch_mgr.is_available():
        print(f"\n[ERROR] Cannot connect to ClickHouse at {CH_HOST}:{CH_PORT}.")
        print("Please check:")
        print("1. ClickHouse server is running on target machine.")
        print("2. <listen_host>0.0.0.0</listen_host> is set in /etc/clickhouse-server/config.xml")
        print("3. Port 8123 is open in firewall/security group.")
        sys.exit(1)

    # Ensure schema exists
    init_clickhouse()

    if args.verify_only:
        verify_counts(ch_mgr)
        return

    t0 = time.time()
    if args.table in ("all", "sitemap_pages"):
        migrate_sitemap_pages(ch_mgr, chunk_size=args.batch_size, task_id=args.task_id)
    if args.table in ("all", "domain_occurrences"):
        migrate_domain_occurrences(ch_mgr, chunk_size=args.batch_size, task_id=args.task_id)
    if args.table in ("all", "task_logs"):
        migrate_task_logs(ch_mgr, chunk_size=args.batch_size, task_id=args.task_id)

    verify_counts(ch_mgr)
    print(f"\nMigration completed successfully in {time.time() - t0:.2f} seconds!")


if __name__ == "__main__":
    main()
