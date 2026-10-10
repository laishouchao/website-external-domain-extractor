"""
Web Compliance Checker - Database Management Layer
Direct, robust PostgreSQL client with strict compliance persistence rules.
"""

import json
import logging
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple

import psycopg2
import psycopg2.extras

from config import DB_CONFIG

logger = logging.getLogger("compliance_checker.db")

class Database:
    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or DB_CONFIG
        self._conn = None

    def get_conn(self):
        if self._conn is None or getattr(self._conn, "closed", 1) != 0:
            self._conn = psycopg2.connect(
                host=self.config["host"],
                port=self.config["port"],
                user=self.config["user"],
                password=self.config["password"],
                dbname=self.config["database"],
                connect_timeout=self.config.get("timeout", 5),
            )
            self._conn.autocommit = True
        return self._conn

    def test_connection(self) -> Dict[str, Any]:
        try:
            conn = self.get_conn()
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
            return {"status": "ok", "message": "PostgreSQL 连通正常"}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def init_schema(self):
        """Ensure compliance_audit_logs table exists."""
        audit_table = self.config.get("audit_table", "compliance_audit_logs")
        ddl = f"""
        CREATE TABLE IF NOT EXISTS {audit_table} (
            id BIGSERIAL PRIMARY KEY,
            task_id INTEGER DEFAULT 0,
            domain VARCHAR(255) NOT NULL,
            url VARCHAR(1024) NOT NULL,
            is_violation BOOLEAN NOT NULL,
            overall_risk_level VARCHAR(32) NOT NULL,
            primary_violation VARCHAR(64) NOT NULL,
            cloaking_suspected BOOLEAN DEFAULT FALSE,
            cloaking_notes TEXT,
            category_probabilities JSONB,
            device_count INTEGER,
            violation_device_count INTEGER,
            model_used VARCHAR(64),
            report_json JSONB,
            checked_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS idx_{audit_table}_task ON {audit_table}(task_id);
        CREATE INDEX IF NOT EXISTS idx_{audit_table}_risk ON {audit_table}(overall_risk_level);
        CREATE INDEX IF NOT EXISTS idx_{audit_table}_domain ON {audit_table}(domain);
        """
        try:
            conn = self.get_conn()
            with conn.cursor() as cur:
                cur.execute(ddl)
        except Exception as e:
            logger.warning(f"init_schema notice: {e}")

    def get_stats(self) -> Dict[str, Any]:
        """Fetch accurate aggregate statistics."""
        task_table = self.config.get("task_table", "external_domains")
        conn = self.get_conn()
        with conn.cursor() as cur:
            # 1. Total row count
            cur.execute(f"SELECT count(*) FROM {task_table}")
            total_rows = cur.fetchone()[0] or 0

            # 2. Distinct domains count
            cur.execute(f"SELECT count(DISTINCT domain) FROM {task_table}")
            distinct_domains = cur.fetchone()[0] or 0

            # 3. Actionable Violations count (distinct domains)
            cur.execute(f"SELECT count(DISTINCT domain) FROM {task_table} WHERE verify_status = 'verified_failed'")
            violations_count = cur.fetchone()[0] or 0

            # 4. Cloaking detected count (distinct domains)
            cur.execute(f"""
                SELECT count(DISTINCT domain) FROM {task_table}
                WHERE risk_tags ILIKE '%cloaking%' 
                   OR risk_tags ILIKE '%伪装%' 
                   OR risk_remark ILIKE '%伪装%' 
                   OR verify_detail ILIKE '%"cloaking_suspected": true%'
            """)
            cloaking_count = cur.fetchone()[0] or 0

            # 5. 404 / Error Pages count (distinct domains)
            cur.execute(f"""
                SELECT count(DISTINCT domain) FROM {task_table}
                WHERE verify_detail ILIKE '%404%'
            """)
            error_pages_count = cur.fetchone()[0] or 0

            # 6. Pending pool count (distinct domains)
            cur.execute(f"SELECT count(DISTINCT domain) FROM {task_table} WHERE verify_status = 'unverified'")
            pending_count = cur.fetchone()[0] or 0

            # 7. Inspected clean count (still kept unverified)
            cur.execute(f"""
                SELECT count(DISTINCT domain) FROM {task_table}
                WHERE verify_status = 'unverified' AND verify_time IS NOT NULL AND verify_detail NOT ILIKE '%404%'
            """)
            clean_pending_count = cur.fetchone()[0] or 0

        return {
            "total_rows": total_rows,
            "distinct_domains": distinct_domains,
            "violations_count": violations_count,
            "cloaking_count": cloaking_count,
            "error_pages_count": error_pages_count,
            "pending_count": pending_count,
            "clean_pending_count": clean_pending_count,
        }

    def fetch_domains(
        self,
        page: int = 1,
        page_size: int = 20,
        filter_type: str = "all",
        search_kw: str = "",
    ) -> Dict[str, Any]:
        """Server-side pagination and filtering."""
        task_table = self.config.get("task_table", "external_domains")
        conn = self.get_conn()

        where_clauses = []
        params = []

        if filter_type == "violation":
            where_clauses.append("verify_status = 'verified_failed'")
        elif filter_type == "cloaking":
            where_clauses.append("(risk_tags ILIKE '%%cloaking%%' OR risk_tags ILIKE '%%伪装%%' OR risk_remark ILIKE '%%伪装%%' OR verify_detail ILIKE '%%\"cloaking_suspected\": true%%')")
        elif filter_type == "error_pages":
            where_clauses.append("verify_detail ILIKE '%%404%%'")
        elif filter_type == "pending":
            where_clauses.append("verify_status = 'unverified'")

        if search_kw:
            where_clauses.append("(domain ILIKE %s OR root_domain ILIKE %s)")
            kw_param = f"%{search_kw}%"
            params.extend([kw_param, kw_param])

        where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

        # Total count query
        count_sql = f"""
            SELECT count(DISTINCT domain)
            FROM {task_table}
            {where_sql}
        """
        with conn.cursor() as cur:
            cur.execute(count_sql, tuple(params))
            total_items = cur.fetchone()[0] or 0

        total_pages = max(1, (total_items + page_size - 1) // page_size)
        offset = max(0, (page - 1) * page_size)

        # Query items (group by domain to deduplicate)
        items_sql = f"""
            SELECT 
                min(id) as id,
                min(task_id) as task_id,
                domain,
                min(root_domain) as root_domain,
                count(*) as occurrence_count,
                max(sample_page_url) as sample_page_url,
                max(risk_level) as risk_level,
                max(risk_tags) as risk_tags,
                max(risk_remark) as risk_remark,
                max(verify_status) as verify_status,
                max(verify_time) as verify_time,
                max(verify_detail) as verify_detail
            FROM {task_table}
            {where_sql}
            GROUP BY domain
            ORDER BY 
                CASE 
                    WHEN max(verify_status) = 'verified_failed' THEN 1
                    WHEN max(verify_detail) ILIKE '%%404%%' THEN 2
                    WHEN max(verify_time) IS NOT NULL THEN 3
                    ELSE 4
                END ASC,
                max(verify_time) DESC NULLS LAST,
                domain ASC
            LIMIT %s OFFSET %s
        """
        query_params = list(params) + [page_size, offset]

        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(items_sql, tuple(query_params))
            rows = [dict(r) for r in cur.fetchall()]

        # Process rows into clean dicts
        items = []
        for r in rows:
            detail_obj = {}
            if r.get("verify_detail"):
                try:
                    detail_obj = json.loads(r["verify_detail"]) if isinstance(r["verify_detail"], str) else r["verify_detail"]
                except Exception:
                    detail_obj = {"raw": str(r["verify_detail"])}

            # Synthesize display badge
            is_failed = r.get("verify_status") == "verified_failed"
            is_404 = bool(detail_obj.get("is_404") or ("404" in str(r.get("verify_detail", ""))))
            is_ssrf = bool(detail_obj.get("is_ssrf") or "内网阻断" in str(r.get("risk_tags", "")) or "127.0.0.1" in str(r.get("risk_remark", "")))
            has_inspected = bool(r.get("verify_time"))

            if is_failed:
                badge_type = "violation"
                badge_label = "🚨 违规异常"
            elif is_ssrf:
                badge_type = "ssrf_blocked"
                badge_label = "🛡️ 内网阻断(待判)"
            elif is_404:
                badge_type = "error_404"
                badge_label = "⚠️ 404失效"
            elif has_inspected:
                badge_type = "clean_pending"
                badge_label = "⏳ 待判(正常)"
            else:
                badge_type = "pending"
                badge_label = "⏳ 待研判"

            # Parse screenshots
            screenshots = []
            if isinstance(detail_obj, dict):
                # Check for devices or slices
                dev_res = detail_obj.get("device_results") or {}
                if isinstance(dev_res, dict):
                    for dev_key, dev_val in dev_res.items():
                        if isinstance(dev_val, dict) and dev_val.get("screenshot_path"):
                            screenshots.append({
                                "device": dev_key,
                                "path": dev_val["screenshot_path"],
                                "sha256": dev_val.get("sha256", "")
                            })
                elif detail_obj.get("screenshots"):
                    screenshots = detail_obj["screenshots"]

            items.append({
                "id": r["id"],
                "task_id": r["task_id"],
                "domain": r["domain"],
                "root_domain": r.get("root_domain") or "",
                "occurrence_count": r.get("occurrence_count", 1),
                "url": r.get("sample_page_url") or f"https://{r['domain']}",
                "risk_level": r.get("risk_level") or "pending",
                "risk_tags": r.get("risk_tags") or "",
                "risk_remark": r.get("risk_remark") or "",
                "verify_status": r.get("verify_status") or "unverified",
                "verify_time": str(r.get("verify_time") or ""),
                "badge_type": badge_type,
                "badge_label": badge_label,
                "is_404": is_404,
                "detail": detail_obj,
                "screenshots": screenshots,
            })

        return {
            "items": items,
            "total": total_items,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages,
        }

    def fetch_single_domain(self, domain: str) -> Optional[Dict[str, Any]]:
        """Fetch complete forensic details for a single domain."""
        task_table = self.config.get("task_table", "external_domains")
        audit_table = self.config.get("audit_table", "compliance_audit_logs")
        conn = self.get_conn()

        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(f"""
                SELECT 
                    min(id) as id,
                    min(task_id) as task_id,
                    domain,
                    min(root_domain) as root_domain,
                    count(*) as occurrence_count,
                    max(sample_page_url) as sample_page_url,
                    max(risk_level) as risk_level,
                    max(risk_tags) as risk_tags,
                    max(risk_remark) as risk_remark,
                    max(verify_status) as verify_status,
                    max(verify_time) as verify_time,
                    max(verify_detail) as verify_detail
                FROM {task_table}
                WHERE domain = %s
                GROUP BY domain
            """, (domain,))
            row = cur.fetchone()
            if not row:
                return None

            # Fetch audit logs
            cur.execute(f"""
                SELECT * FROM {audit_table}
                WHERE domain = %s
                ORDER BY checked_at DESC
                LIMIT 5
            """, (domain,))
            audit_logs = [dict(log) for log in cur.fetchall()]

        detail_obj = {}
        if row.get("verify_detail"):
            try:
                detail_obj = json.loads(row["verify_detail"]) if isinstance(row["verify_detail"], str) else row["verify_detail"]
            except Exception:
                detail_obj = {"raw": str(row["verify_detail"])}

        return {
            "id": row["id"],
            "task_id": row["task_id"],
            "domain": row["domain"],
            "root_domain": row.get("root_domain") or "",
            "occurrence_count": row.get("occurrence_count", 1),
            "url": row.get("sample_page_url") or f"https://{row['domain']}",
            "risk_level": row.get("risk_level") or "pending",
            "risk_tags": row.get("risk_tags") or "",
            "risk_remark": row.get("risk_remark") or "",
            "verify_status": row.get("verify_status") or "unverified",
            "verify_time": str(row.get("verify_time") or ""),
            "detail": detail_obj,
            "audit_logs": audit_logs,
        }

    def fetch_pending_batch(self, limit: int = 30, domain_filter: str = "") -> List[Dict[str, Any]]:
        """Fetch pending domains prioritizing uninspected ones."""
        task_table = self.config.get("task_table", "external_domains")
        conn = self.get_conn()

        where_clauses = ["verify_status = 'unverified'"]
        params = []

        if domain_filter:
            where_clauses.append("domain ILIKE %s")
            params.append(f"%{domain_filter}%")

        where_sql = "WHERE " + " AND ".join(where_clauses)

        sql = f"""
            SELECT 
                min(id) as id,
                min(task_id) as task_id,
                domain,
                min(root_domain) as root_domain,
                max(sample_page_url) as sample_page_url,
                max(risk_level) as risk_level,
                max(verify_status) as verify_status,
                max(verify_time) as verify_time
            FROM {task_table}
            {where_sql}
            GROUP BY domain
            ORDER BY 
                (max(verify_time) IS NOT NULL) ASC,
                max(verify_time) ASC NULLS FIRST,
                min(id) ASC
            LIMIT %s
        """
        params.append(limit)

        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, tuple(params))
            rows = [dict(r) for r in cur.fetchall()]

        return rows

    def write_inspection_result(
        self,
        domain: str,
        is_violation: bool,
        cloaking: bool,
        ssrf: bool,
        is_404: bool,
        primary_violation: str,
        risk_level: str,
        risk_tags: str,
        risk_remark: str,
        detail_dict: Dict[str, Any],
        task_id: int = 0,
        url: str = ""
    ):
        """
        Strict Compliance Persistence:
        - If anomaly (violation, cloaking, ssrf): verify_status = 'verified_failed', risk_level = 'high'/'critical'
        - If clean / 404 / error / dead link: verify_status = 'unverified', risk_level = 'pending' (NEVER safe!)
        """
        task_table = self.config.get("task_table", "external_domains")
        audit_table = self.config.get("audit_table", "compliance_audit_logs")
        conn = self.get_conn()

        is_anomaly = bool(is_violation or cloaking)
        detail_json = json.dumps(detail_dict, ensure_ascii=False)
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        with conn.cursor() as cur:
            if is_anomaly:
                cur.execute(f"""
                    UPDATE {task_table}
                    SET 
                        verify_status = 'verified_failed',
                        risk_level = %s,
                        risk_tags = %s,
                        risk_remark = %s,
                        risk_source = 'ai_vision_inspector',
                        verify_time = %s,
                        verify_detail = %s
                    WHERE domain = %s
                """, (risk_level, risk_tags, risk_remark, now_str, detail_json, domain))
            else:
                # Strictly retain unverified & pending!
                tag = "页面失效(404)" if is_404 else (risk_tags if (risk_tags and "内网阻断" in risk_tags) else None)
                remark = risk_remark if (risk_remark and ("内网" in risk_remark or "私有IP" in risk_remark)) else ("探活404页面失效(保持待研判)" if is_404 else "已完成视觉研判未见异常(保持待研判)")
                cur.execute(f"""
                    UPDATE {task_table}
                    SET 
                        verify_status = 'unverified',
                        risk_level = 'pending',
                        risk_tags = COALESCE(%s, risk_tags),
                        risk_remark = %s,
                        risk_source = 'ai_vision_inspector',
                        verify_time = %s,
                        verify_detail = %s
                    WHERE domain = %s
                """, (tag, remark, now_str, detail_json, domain))

            # Insert audit log for immutable evidence
            try:
                cur.execute(f"""
                    INSERT INTO {audit_table} (
                        task_id, domain, url, is_violation, overall_risk_level,
                        primary_violation, cloaking_suspected, cloaking_notes,
                        category_probabilities, device_count, violation_device_count,
                        model_used, report_json, checked_at
                    ) VALUES (
                        %s, %s, %s, %s, %s,
                        %s, %s, %s,
                        %s, %s, %s,
                        %s, %s, NOW()
                    )
                """, (
                    task_id,
                    domain,
                    url or f"https://{domain}",
                    is_anomaly,
                    risk_level if is_anomaly else "pending",
                    primary_violation,
                    cloaking,
                    risk_remark if cloaking else "",
                    json.dumps(detail_dict.get("probabilities", {})),
                    detail_dict.get("device_count", 1),
                    1 if is_anomaly else 0,
                    detail_dict.get("model", "XiaoAi"),
                    detail_json
                ))
            except Exception as e:
                logger.warning(f"audit log insert warning: {e}")

    def remediate_legacy_clean(self) -> int:
        """Reset legacy 'verified_clean' or 'safe' back to 'unverified' and 'pending'."""
        task_table = self.config.get("task_table", "external_domains")
        conn = self.get_conn()
        with conn.cursor() as cur:
            cur.execute(f"""
                UPDATE {task_table}
                SET 
                    verify_status = 'unverified',
                    risk_level = 'pending'
                WHERE verify_status = 'verified_clean'
            """)
            updated = cur.rowcount
        return updated

# Global singleton
GLOBAL_DB = Database()
