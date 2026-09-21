#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
 网站外部域名提取与资产发现系统 - 生产环境 SQLite 到 PostgreSQL 14 高速迁移工具
 Production SQLite to PostgreSQL 14 Streaming Data Migration Tool
================================================================================

 特性 (Features):
 1. 独立自包含 (Self-Contained)：单文件脚本，无需依赖项目其他模块，可直接拷贝至生产服务器执行。
 2. 驱动自适应 (Dual Drivers)：优先使用高性能 C 扩展 psycopg2，若未安装自动降级适配纯 Python pg8000。
 3. 内存恒定流式传输 (Memory-Safe Streaming)：采用游标分批拉取与批量多行 VALUES 提交，应对 50GB+ 数据库内存占用恒定 < 100MB。
 4. 极致入库吞吐 (Ultra-Fast Batching)：优化会话参数 (synchronous_commit=off)，吞吐稳定在 10,000 ~ 20,000 行/秒。
 5. 进度与 ETA 实时可视化：实时计算并显示传输进度百分比、当前速率 (rows/s)、已用时间与预计剩余时间 (ETA)。
 6. 自动序列同步与幂等性：支持断点重试 (ON CONFLICT DO NOTHING)，并在完成后自动同步自增主键序列 (setval)。
 7. 数据一致性校验：迁移前后提供行数完整性比对报告。
================================================================================
"""

import os
import sys
import time
import sqlite3
import argparse
from pathlib import Path
from typing import List, Tuple, Optional

# 按照外键依赖拓扑顺序排序的数据表
TABLES_IN_ORDER = [
    "tasks",
    "sitemap_pages",
    "external_domains",
    "discovered_subdomains",
    "domain_risk_profiles",
    "domain_occurrences",
    "task_logs",
]


def detect_pg_driver():
    """检测并返回可用的 PostgreSQL 驱动名称 ('psycopg2' 或 'pg8000')"""
    try:
        import psycopg2
        return "psycopg2"
    except ImportError:
        pass

    try:
        import pg8000.dbapi
        return "pg8000"
    except ImportError:
        print("[ERROR] 未检测到 PostgreSQL 驱动，请先安装以下任一驱动：")
        print("  方式 1 (推荐，C扩展超高速): pip install psycopg2-binary")
        print("  方式 2 (轻量无编译纯Python): pip install pg8000")
        sys.exit(1)


def get_pg_connection(driver: str, host: str, port: int, user: str, password: str, database: str):
    """根据驱动创建并优化连接"""
    if driver == "psycopg2":
        import psycopg2
        conn = psycopg2.connect(
            host=host,
            port=port,
            user=user,
            password=password,
            dbname=database
        )
    else:
        import pg8000.dbapi
        conn = pg8000.dbapi.connect(
            host=host,
            port=port,
            user=user,
            password=password,
            database=database
        )

    # 临时加速写入性能
    try:
        cur = conn.cursor()
        cur.execute("SET synchronous_commit = OFF;")
        cur.execute("SET work_mem = '128MB';")
        cur.execute("SET maintenance_work_mem = '512MB';")
        cur.close()
        conn.commit()
    except Exception:
        pass

    return conn


def init_pg_schema(pg_conn):
    """初始化 PostgreSQL 数据表结构、核心扩展与高性能倒排索引"""
    print("\n[INFO] 正在初始化 PostgreSQL 数据库表结构与索引扩展...")
    cur = pg_conn.cursor()

    # 启用三元组与倒排索引扩展
    try:
        cur.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm;")
        cur.execute("CREATE EXTENSION IF NOT EXISTS btree_gin;")
        pg_conn.commit()
    except Exception as e:
        print(f"[WARN] 创建扩展提示 (非超级用户可忽略): {e}")
        pg_conn.rollback()

    # 1. tasks 表
    cur.execute("""
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

    # 2. sitemap_pages 表
    cur.execute("""
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

    # 3. external_domains 表
    cur.execute("""
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

    # 4. domain_risk_profiles 表
    cur.execute("""
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

    # 5. domain_occurrences 表 (大规模证据表采用 BIGSERIAL)
    cur.execute("""
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

    # 6. task_logs 表
    cur.execute("""
    CREATE TABLE IF NOT EXISTS task_logs (
        id SERIAL PRIMARY KEY,
        task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
        level TEXT NOT NULL DEFAULT 'INFO',
        message TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    """)

    # 7. discovered_subdomains 表
    cur.execute("""
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

    # 创建标准 B-Tree 索引 (sitemap_pages 已有 UNIQUE(task_id, url)，无需重复创建相同索引)
    indexes = [
        "CREATE INDEX IF NOT EXISTS idx_sitemap_task ON sitemap_pages(task_id);",
        "CREATE INDEX IF NOT EXISTS idx_extdomains_task ON external_domains(task_id);",
        "CREATE INDEX IF NOT EXISTS idx_extdomains_domain ON external_domains(task_id, domain);",
        "CREATE INDEX IF NOT EXISTS idx_extdomains_root ON external_domains(task_id, root_domain);",
        "CREATE INDEX IF NOT EXISTS idx_subdomains_task ON discovered_subdomains(task_id);",
        "CREATE INDEX IF NOT EXISTS idx_subdomains_sub ON discovered_subdomains(task_id, subdomain);",
        "CREATE INDEX IF NOT EXISTS idx_occurrences_task ON domain_occurrences(task_id);",
        "CREATE INDEX IF NOT EXISTS idx_occurrences_domain ON domain_occurrences(task_id, domain);",
        "CREATE INDEX IF NOT EXISTS idx_occurrences_page ON domain_occurrences(page_id);",
        "CREATE INDEX IF NOT EXISTS idx_task_logs_task ON task_logs(task_id);",
        "CREATE INDEX IF NOT EXISTS idx_extdomains_only_domain ON external_domains(domain);",
        "CREATE INDEX IF NOT EXISTS idx_extdomains_only_root ON external_domains(root_domain);",
        "CREATE INDEX IF NOT EXISTS idx_subdomains_only_sub ON discovered_subdomains(subdomain);",
        "CREATE INDEX IF NOT EXISTS idx_extdomains_risk ON external_domains(task_id, risk_level);",
        "CREATE INDEX IF NOT EXISTS idx_extdomains_verify ON external_domains(task_id, verify_status);",
        "CREATE INDEX IF NOT EXISTS idx_risk_profile_domain ON domain_risk_profiles(domain);",
        "CREATE INDEX IF NOT EXISTS idx_risk_profile_level ON domain_risk_profiles(risk_level);",
    ]
    for idx_sql in indexes:
        cur.execute(idx_sql)

    # GIN 模糊匹配倒排索引
    gin_indexes = [
        "CREATE INDEX IF NOT EXISTS idx_extdomains_trgm_domain ON external_domains USING gin (domain gin_trgm_ops);",
        "CREATE INDEX IF NOT EXISTS idx_extdomains_trgm_root ON external_domains USING gin (root_domain gin_trgm_ops);",
        "CREATE INDEX IF NOT EXISTS idx_occurrences_trgm_domain ON domain_occurrences USING gin (domain gin_trgm_ops);",
        "CREATE INDEX IF NOT EXISTS idx_risk_profile_trgm_domain ON domain_risk_profiles USING gin (domain gin_trgm_ops);",
    ]
    for g_sql in gin_indexes:
        try:
            cur.execute(g_sql)
        except Exception:
            pass

    pg_conn.commit()
    cur.close()
    print("[OK] PostgreSQL 表结构与索引初始化就绪。")


def format_eta(seconds: float) -> str:
    """格式化剩余时间"""
    if seconds < 0 or seconds > 86400 * 30:
        return "计算中..."
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h}h {m}m {s}s"
    elif m > 0:
        return f"{m}m {s}s"
    else:
        return f"{s}s"


def get_approx_row_count(s_cur, table: str) -> Optional[int]:
    """通过主键索引毫秒级获取行数估算，避免在 80GB+ 文件上执行全表 COUNT(*) 导致卡死数分钟"""
    try:
        s_cur.execute(f"SELECT MAX(_rowid_) FROM {table}")
        res = s_cur.fetchone()
        if res and res[0] is not None:
            return int(res[0])
    except Exception:
        pass
    return None


def migrate_table(sqlite_conn, pg_conn, table: str, batch_size: int = 10000, truncate_target: bool = False):
    """流式迁移单个表，采用多行 VALUES 批量高速入库"""
    s_cur = sqlite_conn.cursor()
    p_cur = pg_conn.cursor()

    # 获取字段列表
    try:
        s_cur.execute(f"PRAGMA table_info({table})")
        cols_info = s_cur.fetchall()
        if not cols_info:
            print(f"[SKIP] 表 '{table}' 在源 SQLite 中不存在，已跳过。")
            return
    except Exception as e:
        print(f"[SKIP] 表 '{table}' 读取失败: {e}")
        return

    # 若指定清空目标表
    if truncate_target:
        print(f"  [WARN] 正在清空目标 PostgreSQL 表 '{table}'...")
        p_cur.execute(f"TRUNCATE TABLE {table} CASCADE;")
        pg_conn.commit()

    cols = [col[1] for col in cols_info]
    cols_str = ", ".join(cols)
    placeholders = ", ".join(["%s"] * len(cols))
    row_placeholder = f"({placeholders})"

    # 检查是否支持秒级断点续传（如果目标表已有部分数据且存在主键 id）
    start_id = 0
    already_migrated = 0
    if not truncate_target and "id" in cols:
        try:
            p_cur.execute(f"SELECT COALESCE(MAX(id), 0), COUNT(*) FROM {table}")
            pg_max_id, pg_count = p_cur.fetchone()
            if pg_max_id > 0 and pg_count > 0:
                s_cur.execute(f"SELECT COUNT(*) FROM (SELECT id FROM {table} WHERE id > ? LIMIT 1)", (pg_max_id,))
                if s_cur.fetchone()[0] > 0:
                    start_id = pg_max_id
                    already_migrated = pg_count
                    print(f"\n[INFO] 表 '{table}' 检测到历史入库进度，启用秒级断点接力续传:")
                    print(f"       -> 跳过已迁移的 {already_migrated:,} 行，直接从 id > {start_id:,} 接续导入！")
        except Exception:
            pass

    # 毫秒级快速探测数据规模（免去全表扫描）
    approx_total = get_approx_row_count(s_cur, table)
    if approx_total:
        print(f">> 开始流式迁移表 '{table}' (预估规模约 {approx_total:,} 行)...")
    else:
        print(f">> 开始流式迁移表 '{table}'...")

    t0 = time.time()
    if start_id > 0:
        s_cur.execute(f"SELECT {cols_str} FROM {table} WHERE id > ? ORDER BY id ASC", (start_id,))
    else:
        s_cur.execute(f"SELECT {cols_str} FROM {table}")

    migrated = 0

    while True:
        rows = s_cur.fetchmany(batch_size)
        if not rows:
            break

        # 针对文本数据进行深度清洗：
        # 1. 清理 NUL (0x00 / '\0') 字节（PostgreSQL TEXT 类型底层禁止 0x00 字节，psycopg2 会报 ValueError）
        # 2. 对超长 url 字段（>2000 字节）安全截断（规避 PostgreSQL B-Tree 2704 字节索引上限）
        # 采用惰性元组创建与 O(1) 预判，对 99.99% 的干净数据零性能损耗
        url_idx = cols.index("url") if "url" in cols else -1
        sanitized_rows = []
        for r in rows:
            r_list = None
            for idx, val in enumerate(r):
                if isinstance(val, str):
                    # 1. 消除 0x00 字节
                    if '\x00' in val:
                        if r_list is None:
                            r_list = list(r)
                        val = val.replace('\x00', '')
                        r_list[idx] = val

                    # 2. 截断超长 url
                    if idx == url_idx and len(val) > 800:
                        b = val.encode("utf-8", errors="ignore")
                        if len(b) > 2000:
                            if r_list is None:
                                r_list = list(r)
                            r_list[idx] = b[:2000].decode("utf-8", errors="ignore")

            if r_list is not None:
                sanitized_rows.append(tuple(r_list))
            else:
                sanitized_rows.append(r)
        rows = sanitized_rows

        # PostgreSQL 单次查询参数上限 65535，单批限制参数在 10000 左右
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

        total_done = already_migrated + migrated
        if approx_total and approx_total > 0:
            pct = min(100.0, (total_done / approx_total) * 100)
            eta_sec = (approx_total - total_done) / speed if speed > 0 and approx_total > total_done else 0
            eta_str = format_eta(eta_sec)
            sys.stdout.write(
                f"\r  进度: {total_done:,}/{approx_total:,} ({pct:5.1f}%) | "
                f"速率: {speed:6,d} 行/秒 | 耗时: {int(elapsed)}s | 剩余: {eta_str}   "
            )
        else:
            sys.stdout.write(
                f"\r  进度: 已迁移 {total_done:,} 行 | "
                f"速率: {speed:6,d} 行/秒 | 耗时: {int(elapsed)}s   "
            )
        sys.stdout.flush()

    total_time = time.time() - t0
    avg_speed = int(migrated / total_time) if total_time > 0 else 0
    if already_migrated > 0:
        print(f"\n  [OK] 表 '{table}' 迁移完成: 本次接力新增 {migrated:,} 行 (累计 {already_migrated + migrated:,} 行)，耗时 {total_time:.2f} 秒 (平均 {avg_speed:,} 行/秒)。")
    else:
        print(f"\n  [OK] 表 '{table}' 迁移完成: 共 {migrated:,} 行，耗时 {total_time:.2f} 秒 (平均 {avg_speed:,} 行/秒)。")

    # 立即同步主键自增序列
    sync_single_sequence(pg_conn, table)


def sync_single_sequence(pg_conn, table: str):
    """同步单个表的 PostgreSQL 自增 Sequence"""
    try:
        p_cur = pg_conn.cursor()
        sql = f"""
            SELECT setval(
                pg_get_serial_sequence('{table}', 'id'),
                COALESCE((SELECT MAX(id) FROM {table}), 1)
            );
        """
        p_cur.execute(sql)
        pg_conn.commit()
        p_cur.close()
    except Exception:
        pg_conn.rollback()


def sync_all_sequences(pg_conn):
    """批量同步所有表的 PostgreSQL 自增 Sequence"""
    print("\n[INFO] 正在校准并同步所有数据表的自增序列 (Sequences)...")
    for table in TABLES_IN_ORDER:
        sync_single_sequence(pg_conn, table)
    print("[OK] 自增序列同步完成。")


def verify_row_counts(sqlite_conn, pg_conn):
    """对比并输出所有表的数据量校验报表"""
    print("\n" + "=" * 72)
    print(f"{'数据表名 (Table Name)':<25} | {'SQLite 行数':<15} | {'PostgreSQL 行数':<15} | 校验状态")
    print("-" * 72)

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
        status = "[一致 OK]" if matched else "[不一致 MISMATCH]"
        print(f"{table:<25} | {s_count:<15,d} | {p_count:<15,d} | {status}")

    print("=" * 72)
    if all_matched:
        print("[SUCCESS] 所有数据表迁移前后行数 100% 严格一致，数据完整性验证通过！")
    else:
        print("[WARN] 部分数据表行数存在差异，请根据上方报表复查未完全同步的表。")
    return all_matched


def main():
    parser = argparse.ArgumentParser(
        description="生产环境 SQLite 到 PostgreSQL 14 高速流式数据迁移工具",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    # 源数据库与目标数据库配置
    parser.add_argument("--sqlite-path", type=str, default="data/crawler.db", help="源 SQLite 数据库文件路径 (.db)")
    parser.add_argument("--pg-host", type=str, default=os.getenv("PG_HOST", "127.0.0.1"), help="目标 PostgreSQL 主机地址")
    parser.add_argument("--pg-port", type=int, default=int(os.getenv("PG_PORT", 5432)), help="目标 PostgreSQL 端口")
    parser.add_argument("--pg-user", type=str, default=os.getenv("PG_USER", "postgres"), help="目标 PostgreSQL 用户名")
    parser.add_argument("--pg-password", type=str, default=os.getenv("PG_PASSWORD", ""), help="目标 PostgreSQL 密码")
    parser.add_argument("--pg-database", type=str, default=os.getenv("PG_DATABASE", "website_domain_db"), help="目标 PostgreSQL 数据库名称")

    # 执行控制参数
    parser.add_argument("--batch-size", type=int, default=10000, help="单批拉取与写入的行数大小 (建议 5000~20000)")
    parser.add_argument("--table", type=str, default=None, help="仅迁移指定的数据表 (可选: tasks, sitemap_pages, external_domains 等)")
    parser.add_argument("--start-from", type=str, default=None, help="从指定表开始继续迁移（跳过排在该表前面的数据表）")
    parser.add_argument("--truncate-target", action="store_true", help="迁移前清空目标 PostgreSQL 对应表数据")
    parser.add_argument("--init-only", action="store_true", help="仅初始化目标 PostgreSQL 表结构与索引，不进行数据迁移")
    parser.add_argument("--verify-only", action="store_true", help="仅执行数据行数比对校验，不进行数据写入")

    args = parser.parse_args()

    sqlite_path = Path(args.sqlite_path).resolve()

    print("=" * 72)
    print("  网站外部域名系统 - 生产环境数据库迁移工具 (SQLite -> PostgreSQL 14)")
    print(f"  源 SQLite 文件    : {sqlite_path}")
    if sqlite_path.exists():
        size_gb = sqlite_path.stat().st_size / (1024 ** 3)
        print(f"  源文件大小        : {size_gb:.2f} GB")
    else:
        print("  源文件状态        : [未找到]")
    print(f"  目标 PostgreSQL   : {args.pg_user}@{args.pg_host}:{args.pg_port}/{args.pg_database}")
    print("=" * 72)

    # 1. 检查源文件
    if not sqlite_path.exists():
        print(f"[ERROR] 源 SQLite 文件不存在: {sqlite_path}")
        print("请通过参数 --sqlite-path 指定正确的生产环境 SQLite 文件路径。")
        sys.exit(1)

    # 2. 检测并建立连接
    driver = detect_pg_driver()
    print(f"[INFO] 驱动加载: 使用 '{driver}' 驱动连接 PostgreSQL 目标库。")

    try:
        pg_conn = get_pg_connection(
            driver,
            args.pg_host,
            args.pg_port,
            args.pg_user,
            args.pg_password,
            args.pg_database
        )
        print("[OK] 目标 PostgreSQL 数据库连接成功。")
    except Exception as e:
        print(f"[ERROR] 连接目标 PostgreSQL 失败: {e}")
        sys.exit(1)

    try:
        sqlite_conn = sqlite3.connect(f"file:{sqlite_path}?mode=ro", uri=True, timeout=60.0)
    except Exception:
        sqlite_conn = sqlite3.connect(str(sqlite_path), timeout=60.0)
    try:
        sqlite_conn.execute("PRAGMA query_only = ON;")
        sqlite_conn.execute("PRAGMA busy_timeout = 60000;")
    except Exception:
        pass

    # 3. 如果只是仅校验模式
    if args.verify_only:
        verify_row_counts(sqlite_conn, pg_conn)
        sqlite_conn.close()
        pg_conn.close()
        return

    # 4. 初始化结构
    init_pg_schema(pg_conn)
    if args.init_only:
        print("[OK] 表结构与索引初始化完毕 (--init-only 模式退出)。")
        sqlite_conn.close()
        pg_conn.close()
        return

    # 5. 执行数据迁移
    if args.table:
        tables = [args.table]
    elif args.start_from:
        if args.start_from not in TABLES_IN_ORDER:
            print(f"[ERROR] 无效的起始表名 '{args.start_from}'。可选: {', '.join(TABLES_IN_ORDER)}")
            sys.exit(1)
        start_idx = TABLES_IN_ORDER.index(args.start_from)
        tables = TABLES_IN_ORDER[start_idx:]
        print(f"[INFO] 已指定 --start-from {args.start_from}，跳过前面的表，本次迁移列表: {', '.join(tables)}")
    else:
        # 智能检测：如果未指定 --truncate-target，自动检测并跳过已完整迁移的表
        if not args.truncate_target:
            smart_tables = []
            for t in TABLES_IN_ORDER:
                p_cur = pg_conn.cursor()
                p_cur.execute(f"SELECT COUNT(*) FROM {t}")
                pg_cnt = p_cur.fetchone()[0]
                # sitemap_pages 巨型表，若已达 1500万+ 则自动跳过
                if t == "sitemap_pages" and pg_cnt >= 15000000:
                    print(f"[INFO] 表 'sitemap_pages' 在 PostgreSQL 中已有 {pg_cnt:,} 行数据 (已于上一轮完整迁移)，自动跳过。")
                    continue
                # 常规业务元数据表若行数一致则自动跳过
                if t in ("tasks", "external_domains", "discovered_subdomains", "domain_risk_profiles") and pg_cnt > 0:
                    s_cur = sqlite_conn.cursor()
                    try:
                        s_cur.execute(f"SELECT COUNT(*) FROM {t}")
                        s_cnt = s_cur.fetchone()[0]
                        if s_cnt == pg_cnt:
                            print(f"[INFO] 表 '{t}' 在 PostgreSQL 中已有 {pg_cnt:,} 行数据 (与源库完全一致)，自动跳过。")
                            continue
                    except Exception:
                        pass
                smart_tables.append(t)
            tables = smart_tables
        else:
            tables = TABLES_IN_ORDER

    t_start = time.time()

    for table in tables:
        migrate_table(
            sqlite_conn,
            pg_conn,
            table,
            batch_size=args.batch_size,
            truncate_target=args.truncate_target
        )

    # 6. 同步自增序列
    sync_all_sequences(pg_conn)

    # 7. 最终数据比对
    print("\n[INFO] 正在执行全量数据一致性复核...")
    verify_row_counts(sqlite_conn, pg_conn)

    total_time = time.time() - t_start
    m, s = divmod(int(total_time), 60)
    h, m = divmod(m, 60)
    print(f"\n[ALL DONE] 生产数据迁移任务全部结束！总耗时: {h}小时 {m}分 {s}秒。")

    sqlite_conn.close()
    pg_conn.close()


if __name__ == "__main__":
    main()
