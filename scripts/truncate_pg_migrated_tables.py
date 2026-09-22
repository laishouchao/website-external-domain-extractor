#!/usr/bin/env python3
"""
PostgreSQL Big Tables Truncation Script (Plan A)
Safely empties domain_occurrences, sitemap_pages, and task_logs in PostgreSQL
after full migration to ClickHouse, freeing up physical disk space.
"""
import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db.database import db_session
from app.db.clickhouse import get_ch_manager

def main():
    print("=" * 65)
    print("  PostgreSQL Big Tables Truncation Tool (Plan A)")
    print("=" * 65)

    # 1. Verify ClickHouse status
    ch = get_ch_manager()
    if not ch.is_available():
        print("[WARNING] ClickHouse is currently NOT available or unreachable!")
        print("Please make sure ClickHouse is running before truncating PG tables.")
        sys.exit(1)

    print("[1/3] ClickHouse status verified: ONLINE and ready.")

    # 2. Check PG row counts before truncate
    print("\n[2/3] Checking PostgreSQL row counts before truncation...")
    with db_session() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM domain_occurrences;")
        occ_count = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM sitemap_pages;")
        pages_count = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM task_logs;")
        logs_count = cursor.fetchone()[0]

    print(f"  - domain_occurrences: {occ_count:,} rows")
    print(f"  - sitemap_pages:      {pages_count:,} rows")
    print(f"  - task_logs:          {logs_count:,} rows")

    # 3. Execute TRUNCATE
    print("\n[3/3] Truncating PostgreSQL big tables (CASCADE)...")
    start_t = time.time()
    with db_session() as conn:
        cursor = conn.cursor()
        cursor.execute("TRUNCATE TABLE domain_occurrences, sitemap_pages, task_logs CASCADE;")
    elapsed = time.time() - start_t
    print(f"  Truncate completed in {elapsed:.2f}s!")

    # Verify after truncate
    with db_session() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM domain_occurrences;")
        new_occ = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM sitemap_pages;")
        new_pages = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM task_logs;")
        new_logs = cursor.fetchone()[0]

    print(f"\nVerification after truncation:")
    print(f"  - domain_occurrences: {new_occ} rows")
    print(f"  - sitemap_pages:      {new_pages} rows")
    print(f"  - task_logs:          {new_logs} rows")

    print("\n[SUCCESS] Plan A executed successfully! Tables are now empty shells, freeing storage and WAL load.")

if __name__ == "__main__":
    main()
