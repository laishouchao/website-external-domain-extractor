#!/usr/bin/env python3
"""
SQLite to PostgreSQL 14 Streaming Data Migration Tool
Website External Domain Extraction System

Features:
- Memory-safe streaming batch migration (constant memory footprint even for 50GB+ databases)
- Foreign key dependency ordered migration
- Live progress, throughput (rows/sec), and ETA
- Automatically updates PostgreSQL sequences (setval) to prevent primary key collision
- Verification mode for comparing SQLite vs PostgreSQL row counts
"""

import os
import sys
import time
import sqlite3
import argparse
from pathlib import Path

# Add project root to sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from app.config import (
    DATA_DIR, PG_HOST, PG_PORT, PG_USER, PG_PASSWORD, PG_DATABASE
)
from app.db.database import init_db_postgresql

TABLES_IN_ORDER = [
    "tasks",
    "sitemap_pages",
    "external_domains",
    "discovered_subdomains",
    "domain_risk_profiles",
    "domain_occurrences",
    "task_logs",
]


def get_sqlite_conn(sqlite_file: Path) -> sqlite3.Connection:
    if not sqlite_file.exists():
        raise FileNotFoundError(f"SQLite database file not found: {sqlite_file}")
    conn = sqlite3.connect(str(sqlite_file))
    conn.row_factory = None
    return conn


def get_pg_conn():
    import pg8000.dbapi
    return pg8000.dbapi.connect(
        user=PG_USER,
        host=PG_HOST,
        port=PG_PORT,
        database=PG_DATABASE,
        password=PG_PASSWORD
    )


def verify_counts(sqlite_conn, pg_conn):
    print("\n" + "=" * 65)
    print(f"{'Table Name':<25} | {'SQLite Count':<14} | {'PostgreSQL Count':<14} | Status")
    print("-" * 65)

    all_matched = True
    s_cur = sqlite_conn.cursor()
    p_cur = pg_conn.cursor()

    for table in TABLES_IN_ORDER:
        try:
            s_cur.execute(f"SELECT COUNT(*) FROM {table}")
            s_count = s_cur.fetchone()[0]
        except Exception:
            s_count = 0

        try:
            p_cur.execute(f"SELECT COUNT(*) FROM {table}")
            p_count = p_cur.fetchone()[0]
        except Exception:
            p_count = 0

        matched = (s_count == p_count)
        if not matched:
            all_matched = False
        status = "OK" if matched else "MISMATCH"
        print(f"{table:<25} | {s_count:<14} | {p_count:<14} | {status}")

    print("=" * 65)
    return all_matched


def sync_sequences(pg_conn):
    """Update PostgreSQL auto-increment sequences to the max id in each table."""
    print("\nUpdating PostgreSQL sequences...")
    p_cur = pg_conn.cursor()
    for table in TABLES_IN_ORDER:
        try:
            sql = f"""
                SELECT setval(
                    pg_get_serial_sequence('{table}', 'id'),
                    COALESCE((SELECT MAX(id) FROM {table}), 1)
                );
            """
            p_cur.execute(sql)
            pg_conn.commit()
            print(f"  [OK] Sequence for {table} synchronized.")
        except Exception as e:
            # Table might not have serial sequence or is empty
            pg_conn.rollback()


def migrate_table(sqlite_conn, pg_conn, table: str, batch_size: int = 5000):
    s_cur = sqlite_conn.cursor()
    p_cur = pg_conn.cursor()

    # Check source count
    try:
        s_cur.execute(f"SELECT COUNT(*) FROM {table}")
        total_rows = s_cur.fetchone()[0]
    except Exception as e:
        print(f"Skipping {table}: not present in SQLite database ({e})")
        return

    if total_rows == 0:
        print(f"Table '{table}' is empty (0 rows), skipped.")
        return

    # Fetch column names
    s_cur.execute(f"PRAGMA table_info({table})")
    cols_info = s_cur.fetchall()
    cols = [col[1] for col in cols_info]
    cols_str = ", ".join(cols)
    placeholders = ", ".join(["%s"] * len(cols))
    insert_sql = f"INSERT INTO {table} ({cols_str}) VALUES ({placeholders}) ON CONFLICT DO NOTHING"

    print(f"\nMigrating table '{table}': {total_rows} rows...")
    s_cur.execute(f"SELECT {cols_str} FROM {table}")

    migrated = 0
    t0 = time.time()

    row_placeholder = f"({placeholders})"

    while True:
        rows = s_cur.fetchmany(batch_size)
        if not rows:
            break

        # PostgreSQL supports up to 65535 parameters; chunk to ~10000 params max per statement
        chunk_size = max(1, 10000 // len(cols))
        for i in range(0, len(rows), chunk_size):
            chunk = rows[i:i + chunk_size]
            values_clause = ", ".join([row_placeholder] * len(chunk))
            batch_sql = f"INSERT INTO {table} ({cols_str}) VALUES {values_clause} ON CONFLICT DO NOTHING"
            flat_params = [val for r in chunk for val in r]
            p_cur.execute(batch_sql, flat_params)

        pg_conn.commit()
        migrated += len(rows)

        elapsed = time.time() - t0
        speed = int(migrated / elapsed) if elapsed > 0 else 0
        pct = (migrated / total_rows) * 100
        print(f"\r  Progress: {migrated}/{total_rows} ({pct:.1f}%) | {speed} rows/s", end="", flush=True)

    print(f"\r  [OK] {table}: {migrated}/{total_rows} rows migrated successfully in {time.time()-t0:.2f}s.")


def main():
    parser = argparse.ArgumentParser(description="Migrate Website External Domain System database from SQLite to PostgreSQL 14")
    parser.add_argument("--sqlite-path", type=str, default=str(DATA_DIR / "crawler.db"), help="Path to source SQLite .db file")
    parser.add_argument("--batch-size", type=int, default=5000, help="Batch size for streaming inserts (default: 5000)")
    parser.add_argument("--verify-only", action="store_true", help="Only verify row counts without migrating")
    parser.add_argument("--table", type=str, default=None, help="Migrate a specific table only")
    args = parser.parse_args()

    sqlite_file = Path(args.sqlite_path)
    print("=" * 65)
    print(" Website External Domain System - Database Migration Tool")
    print(f" Source SQLite    : {sqlite_file}")
    print(f" Target PostgreSQL: {PG_USER}@{PG_HOST}:{PG_PORT}/{PG_DATABASE}")
    print("=" * 65)

    if not sqlite_file.exists():
        print(f"Source SQLite file does not exist: {sqlite_file}")
        sys.exit(1)

    # Initialize PostgreSQL schema & extensions
    print("\nEnsuring PostgreSQL schema and extensions are initialized...")
    init_db_postgresql()
    print("PostgreSQL schema ready.")

    s_conn = get_sqlite_conn(sqlite_file)
    p_conn = get_pg_conn()

    if args.verify_only:
        verify_counts(s_conn, p_conn)
        s_conn.close()
        p_conn.close()
        return

    # Migration
    tables_to_migrate = [args.table] if args.table else TABLES_IN_ORDER
    t_start = time.time()

    for table in tables_to_migrate:
        migrate_table(s_conn, p_conn, table, batch_size=args.batch_size)

    # Sequence alignment
    sync_sequences(p_conn)

    # Final verification
    print("\nExecuting post-migration integrity verification...")
    all_matched = verify_counts(s_conn, p_conn)

    s_conn.close()
    p_conn.close()

    total_time = time.time() - t_start
    print(f"\nMigration completed in {total_time:.2f} seconds!")
    if all_matched:
        print("[SUCCESS] ALL TABLES VERIFIED AND 100% IN SYNC!")
    else:
        print("[WARN] Migration finished with count discrepancies. Please check the report above.")


if __name__ == "__main__":
    main()
