"""
PostgreSQL Client module.
Supports standard psycopg2 with automatic connection pooling / auto-reconnect,
and includes a zero-dependency Pure-Python PostgreSQL 3.0 wire protocol client (MiniPgClient) as fallback.
Seamlessly adapted to website_domain_db schema (external_domains, risk_page_remediations, compliance_audit_logs).
"""

import socket
import struct
import hashlib
import json
import logging
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple

logger = logging.getLogger("compliance_checker.db_postgres")

try:
    import psycopg2
    import psycopg2.extras
    PSYCOPG2_AVAILABLE = True
except ImportError:
    PSYCOPG2_AVAILABLE = False


CATEGORY_NAME_MAP = {
    "pornography_vulgarity": "色情低俗",
    "gambling_lottery": "赌博博彩",
    "fraud_scam": "电信诈骗/黑灰产",
    "violence_contraband": "暴恐违禁/违禁品",
    "political_extremism": "涉政暴恐/不良言论",
    "malicious_adware": "恶意广告/欺诈劫持",
    "normal": "正常合规"
}

RISK_LEVEL_MAP = {
    "CRITICAL": "critical",
    "HIGH": "high",
    "MEDIUM": "medium",
    "LOW": "low",
    "SAFE": "safe",
    "UNKNOWN": "pending"
}


class MiniPgClient:
    """
    基于 PostgreSQL Frontend/Backend Protocol 3.0 的轻量级纯 Python 客户端。
    零第三方依赖，支持 Cleartext、MD5 密码认证、Simple Query 与批量操作。
    """
    def __init__(
        self,
        host: str = "localhost",
        port: int = 5432,
        user: str = "postgres",
        password: str = "",
        database: str = "postgres",
        timeout: int = 30
    ):
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.database = database
        self.timeout = timeout
        self.sock: Optional[socket.socket] = None

    def connect(self):
        self.sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        self._startup()

    def close(self):
        if self.sock:
            try:
                # 发送 Terminate 消息 'X'
                self.sock.sendall(b"X\x00\x00\x00\x04")
            except Exception:
                pass
            try:
                self.sock.close()
            except Exception:
                pass
            self.sock = None

    def _recv_exact(self, n: int) -> bytes:
        data = b""
        while len(data) < n:
            chunk = self.sock.recv(n - len(data))
            if not chunk:
                raise ConnectionError("PostgreSQL 连接意外断开")
            data += chunk
        return data

    def _read_message(self) -> Tuple[bytes, bytes]:
        msg_type = self._recv_exact(1)
        length_bytes = self._recv_exact(4)
        length = struct.unpack("!I", length_bytes)[0]
        body = self._recv_exact(length - 4)
        return msg_type, body

    def _startup(self):
        # 协议版本 3.0 (196608)
        params = [
            b"user", self.user.encode("utf-8"),
            b"database", self.database.encode("utf-8"),
            b"client_encoding", b"UTF8"
        ]
        body = b"".join(p + b"\x00" for p in params) + b"\x00"
        total_len = 4 + 4 + len(body)
        packet = struct.pack("!II", total_len, 196608) + body
        self.sock.sendall(packet)

        # 处理认证交互
        while True:
            msg_type, body = self._read_message()
            if msg_type == b"R":  # Authentication
                auth_type = struct.unpack("!I", body[:4])[0]
                if auth_type == 0:  # AuthenticationOk
                    continue
                elif auth_type == 3:  # CleartextPassword
                    pw_body = self.password.encode("utf-8") + b"\x00"
                    pw_packet = b"p" + struct.pack("!I", len(pw_body) + 4) + pw_body
                    self.sock.sendall(pw_packet)
                elif auth_type == 5:  # MD5Password
                    salt = body[4:8]
                    h1 = hashlib.md5((self.password + self.user).encode("utf-8")).hexdigest()
                    h2 = "md5" + hashlib.md5(h1.encode("ascii") + salt).hexdigest()
                    pw_body = h2.encode("ascii") + b"\x00"
                    pw_packet = b"p" + struct.pack("!I", len(pw_body) + 4) + pw_body
                    self.sock.sendall(pw_packet)
                elif auth_type == 10:  # AuthenticationSASL (SCRAM-SHA-256)
                    raise NotImplementedError("当前服务器配置为 SCRAM-SHA-256 认证，请安装 psycopg2-binary 或配置 md5/trust 认证")
                else:
                    raise PermissionError(f"不支持的 PostgreSQL 认证类型: {auth_type}")
            elif msg_type == b"E":  # ErrorResponse
                err_text = body.decode("utf-8", errors="ignore")
                raise RuntimeError(f"PostgreSQL 认证或连接错误: {err_text}")
            elif msg_type == b"Z":  # ReadyForQuery
                break

    def query(self, sql: str) -> List[Dict[str, Any]]:
        """
        执行查询并返回结果字典列表
        """
        if not self.sock:
            self.connect()

        # 发送 Simple Query 'Q'
        query_bytes = sql.encode("utf-8") + b"\x00"
        packet = b"Q" + struct.pack("!I", len(query_bytes) + 4) + query_bytes
        self.sock.sendall(packet)

        columns = []
        rows = []

        while True:
            msg_type, body = self._read_message()
            if msg_type == b"T":  # RowDescription
                num_fields = struct.unpack("!H", body[:2])[0]
                offset = 2
                columns = []
                for _ in range(num_fields):
                    null_idx = body.find(b"\x00", offset)
                    field_name = body[offset:null_idx].decode("utf-8", errors="ignore")
                    columns.append(field_name)
                    offset = null_idx + 1 + 18
            elif msg_type == b"D":  # DataRow
                num_cols = struct.unpack("!H", body[:2])[0]
                offset = 2
                row = {}
                for col_idx in range(num_cols):
                    col_len = struct.unpack("!i", body[offset:offset+4])[0]
                    offset += 4
                    col_name = columns[col_idx] if col_idx < len(columns) else f"col_{col_idx}"
                    if col_len == -1:
                        row[col_name] = None
                    else:
                        val_bytes = body[offset:offset+col_len]
                        offset += col_len
                        row[col_name] = val_bytes.decode("utf-8", errors="ignore")
                rows.append(row)
            elif msg_type == b"C":  # CommandComplete
                continue
            elif msg_type == b"E":  # ErrorResponse
                err_text = body.decode("utf-8", errors="ignore")
                raise RuntimeError(f"PostgreSQL SQL 错误: {err_text}")
            elif msg_type == b"Z":  # ReadyForQuery
                break

        return rows

    def execute(self, sql: str):
        """
        执行 DDL / DML 语句
        """
        self.query(sql)


class PostgresClient:
    """
    PostgreSQL 业务封装客户端。
    优先采用 psycopg2，支持参数化查询与断线自动重连；降级采用 MiniPgClient。
    """
    def __init__(
        self,
        host: str = "localhost",
        port: int = 5432,
        user: str = "postgres",
        password: str = "",
        database: str = "postgres",
        timeout: int = 30
    ):
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.database = database
        self.timeout = timeout

        self._pg_conn = None
        self.mini_client = None

        if not PSYCOPG2_AVAILABLE:
            self.mini_client = MiniPgClient(host, port, user, password, database, timeout)

    def _ensure_conn(self):
        if not PSYCOPG2_AVAILABLE:
            return

        if self._pg_conn is None or getattr(self._pg_conn, "closed", 1) != 0:
            self._pg_conn = psycopg2.connect(
                host=self.host,
                port=self.port,
                user=self.user,
                password=self.password,
                dbname=self.database,
                connect_timeout=min(self.timeout, 4)
            )
            self._pg_conn.autocommit = True
        else:
            try:
                with self._pg_conn.cursor() as cur:
                    cur.execute("SELECT 1;")
            except Exception:
                try:
                    self._pg_conn.close()
                except Exception:
                    pass
                self._pg_conn = psycopg2.connect(
                    host=self.host,
                    port=self.port,
                    user=self.user,
                    password=self.password,
                    dbname=self.database,
                    connect_timeout=min(self.timeout, 4)
                )
                self._pg_conn.autocommit = True

    def query(self, sql: str, params: Optional[Tuple[Any, ...]] = None) -> List[Dict[str, Any]]:
        if PSYCOPG2_AVAILABLE:
            self._ensure_conn()
            with self._pg_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(sql, params)
                rows = cur.fetchall()
                return [dict(r) for r in rows]
        else:
            if params:
                # 简单格式化 fallback
                formatted_sql = sql % tuple(f"'{p}'" if isinstance(p, str) else str(p) for p in params)
                return self.mini_client.query(formatted_sql)
            return self.mini_client.query(sql)

    def execute(self, sql: str, params: Optional[Tuple[Any, ...]] = None):
        if PSYCOPG2_AVAILABLE:
            self._ensure_conn()
            with self._pg_conn.cursor() as cur:
                cur.execute(sql, params)
        else:
            if params:
                formatted_sql = sql % tuple(f"'{p}'" if isinstance(p, str) else str(p) for p in params)
                self.mini_client.execute(formatted_sql)
            else:
                self.mini_client.execute(sql)

    def init_schema(
        self,
        task_table: str = "external_domains",
        audit_table: str = "compliance_audit_logs"
    ):
        """
        初始化 PostgreSQL 审计存证日志表与通用任务表
        """
        # 1. 审计存证日志表 (带 task_id 外键关联及 JSONB 完整记录)
        ddl_logs = f"""
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
        self.execute(ddl_logs)

        # 2. 如果指定了独立的通用任务表 domain_tasks，则按需创建
        if task_table == "domain_tasks":
            ddl_tasks = f"""
            CREATE TABLE IF NOT EXISTS domain_tasks (
                id SERIAL PRIMARY KEY,
                domain VARCHAR(255) NOT NULL UNIQUE,
                url VARCHAR(1024),
                status VARCHAR(32) DEFAULT 'pending',
                risk_level VARCHAR(32) DEFAULT 'UNKNOWN',
                is_violation BOOLEAN,
                primary_violation VARCHAR(64),
                last_checked_at TIMESTAMP WITH TIME ZONE,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            );
            CREATE INDEX IF NOT EXISTS idx_domain_tasks_status ON domain_tasks(status);
            """
            self.execute(ddl_tasks)

        print(f"[*] PostgreSQL 表结构就绪: {task_table}, {audit_table}")

    def fetch_pending_domains(
        self,
        task_table: str = "external_domains",
        limit: int = 100,
        task_id: Optional[int] = None,
        risk_level: Optional[str] = None,
        verify_status: Optional[str] = None,
        domain_filter: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        根据本系统数据库特征（如 external_domains、risk_page_remediations 等）提取待审核域名任务
        """
        clauses = []
        params = []

        if task_table == "external_domains":
            sql_base = f"""
            SELECT 
                min(id) as id,
                min(task_id) as task_id,
                domain,
                min(root_domain) as root_domain,
                min(sample_page_url) as sample_page_url,
                min(risk_level) as risk_level,
                min(risk_tags) as risk_tags,
                min(risk_remark) as risk_remark,
                min(risk_source) as risk_source,
                min(verify_status) as verify_status,
                count(*) as ref_count
            FROM {task_table}
            WHERE 1=1
            """
            if task_id is not None:
                clauses.append("task_id = %s")
                params.append(task_id)

            if risk_level and risk_level.lower() != "all":
                clauses.append("risk_level = %s")
                params.append(risk_level.lower())

            if verify_status and verify_status.lower() != "all":
                clauses.append("verify_status = %s")
                params.append(verify_status)

            if domain_filter:
                clauses.append("domain ILIKE %s")
                params.append(f"%{domain_filter.strip()}%")

            # 默认提取未验证或风险待判定的记录
            if not risk_level and not verify_status:
                clauses.append("(verify_status = 'unverified' OR risk_level = 'pending')")

            if clauses:
                sql_base += " AND " + " AND ".join(clauses)

            sql_base += f" GROUP BY domain ORDER BY min(id) ASC LIMIT %s;"
            params.append(limit)

            return self.query(sql_base, tuple(params))

        elif task_table == "risk_page_remediations":
            sql_base = f"""
            SELECT id, task_id, domain, root_domain, page_url, risk_level, verify_status
            FROM {task_table}
            WHERE 1=1
            """
            if task_id is not None:
                clauses.append("task_id = %s")
                params.append(task_id)

            if verify_status and verify_status.lower() != "all":
                clauses.append("verify_status = %s")
                params.append(verify_status)
            else:
                clauses.append("verify_status = 'unverified'")

            if domain_filter:
                clauses.append("domain ILIKE %s")
                params.append(f"%{domain_filter.strip()}%")

            if clauses:
                sql_base += " AND " + " AND ".join(clauses)

            sql_base += f" ORDER BY id ASC LIMIT %s;"
            params.append(limit)

            return self.query(sql_base, tuple(params))

        else:
            # 通用 domain_tasks 表
            sql = f"""
            SELECT id, domain, url
            FROM {task_table}
            WHERE status = 'pending' OR status IS NULL
            ORDER BY id ASC
            LIMIT %s;
            """
            return self.query(sql, (limit,))

    def update_task_result(
        self,
        task_table: str,
        domain_id: Any,
        status: str,
        risk_level: str,
        is_violation: bool,
        primary_violation: str,
        task_item: Optional[Dict[str, Any]] = None,
        verdict_summary: Optional[Dict[str, Any]] = None,
        full_record: Optional[Dict[str, Any]] = None
    ):
        """
        将大模型审核裁决结果写回任务表。
        深度适配 external_domains（更新 risk_level、risk_tags、risk_remark、risk_source、verify_status、verify_time、verify_detail）。
        """
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # 映射风险等级为系统标准小写格式
        risk_norm = RISK_LEVEL_MAP.get(risk_level.upper(), risk_level.lower())
        primary_cn = CATEGORY_NAME_MAP.get(primary_violation, primary_violation)

        if task_table == "external_domains":
            # 1. 计算系统标准 verify_status: verified_failed / verified_clean / error
            if status == "error":
                final_verify_status = "error"
            elif is_violation:
                final_verify_status = "verified_failed"
            else:
                final_verify_status = "verified_clean"

            # 2. 构建 risk_tags
            tags_list = []
            if is_violation:
                if primary_cn and primary_cn != "正常合规":
                    tags_list.append(primary_cn)
                if verdict_summary and verdict_summary.get("cloaking_suspected"):
                    tags_list.append("设备伪装(Cloaking)")
            tags_json = json.dumps(tags_list, ensure_ascii=False)

            # 3. 构建 risk_remark
            if is_violation:
                cloaking_str = f" [发现设备伪装: {verdict_summary.get('cloaking_notes')}]" if verdict_summary and verdict_summary.get("cloaking_suspected") else ""
                risk_remark = f"AI多模态审核判定: [{primary_cn}], 风险等级: {risk_norm}.{cloaking_str}"
            else:
                risk_remark = "AI多模态审查正常，未检出违规涉敏内容。"

            # 4. 构建与系统前端弹窗完全兼容的 verify_detail JSON
            detail_obj = {
                "verify_status": final_verify_status,
                "verify_time": now_str,
                "summary": f"AI多模态深度巡检: {'检出违规内容' if is_violation else '合规安全'}",
                "model_used": (full_record or {}).get("model_used", "qwen2-vl"),
                "is_violation": is_violation,
                "overall_risk_level": risk_norm,
                "primary_violation": primary_violation,
                "primary_violation_cn": primary_cn,
                "cloaking_suspected": bool(verdict_summary.get("cloaking_suspected", False)) if verdict_summary else False,
                "cloaking_notes": verdict_summary.get("cloaking_notes", "") if verdict_summary else "",
                "category_probabilities": verdict_summary.get("category_probabilities", {}) if verdict_summary else {},
                "details": [
                    {
                        "device_name": dev.get("device_name", ""),
                        "is_mobile": dev.get("is_mobile", False),
                        "status": dev.get("capture_status", ""),
                        "is_violation": dev.get("model_verdict", {}).get("is_violation", False),
                        "risk_level": dev.get("model_verdict", {}).get("risk_level", "SAFE"),
                        "violation_details": dev.get("model_verdict", {}).get("violation_details", ""),
                        "screenshot_path": dev.get("screenshot_path", ""),
                        "screenshot_hash": dev.get("screenshot_sha256", "")
                    }
                    for dev in (full_record or {}).get("device_inspections", [])
                ]
            }
            detail_json = json.dumps(detail_obj, ensure_ascii=False)

            target_domain = (task_item or {}).get("domain") or (full_record or {}).get("domain")
            if target_domain:
                sql = f"""
                UPDATE {task_table}
                SET risk_level = %s,
                    risk_tags = %s,
                    risk_remark = %s,
                    risk_source = CASE WHEN risk_source = 'manual' THEN risk_source ELSE 'ai_compliance' END,
                    verify_status = %s,
                    verify_time = %s,
                    verify_detail = %s
                WHERE domain = %s;
                """
                self.execute(sql, (risk_norm, tags_json, risk_remark, final_verify_status, now_str, detail_json, target_domain))
            else:
                sql = f"""
                UPDATE {task_table}
                SET risk_level = %s,
                    risk_tags = %s,
                    risk_remark = %s,
                    risk_source = CASE WHEN risk_source = 'manual' THEN risk_source ELSE 'ai_compliance' END,
                    verify_status = %s,
                    verify_time = %s,
                    verify_detail = %s
                WHERE id = %s;
                """
                self.execute(sql, (risk_norm, tags_json, risk_remark, final_verify_status, now_str, detail_json, domain_id))

        elif task_table == "risk_page_remediations":
            final_verify_status = "verified_failed" if is_violation else "verified_clean"
            tags_json = json.dumps([primary_cn] if is_violation else [], ensure_ascii=False)
            detail_json = json.dumps({
                "verify_status": final_verify_status,
                "verify_time": now_str,
                "model_verdict": verdict_summary
            }, ensure_ascii=False)

            sql = f"""
            UPDATE {task_table}
            SET verify_status = %s,
                last_verified_at = %s,
                last_verify_detail = %s,
                risk_level = %s,
                risk_tags = %s,
                risk_remark = %s,
                updated_at = %s
            WHERE id = %s;
            """
            self.execute(sql, (final_verify_status, now_str, detail_json, risk_norm, tags_json, f"AI多模态审核: {primary_cn}", now_str, domain_id))

        else:
            # domain_tasks
            viol_str = "TRUE" if is_violation else "FALSE"
            sql = f"""
            UPDATE {task_table}
            SET status = %s,
                risk_level = %s,
                is_violation = {viol_str},
                primary_violation = %s,
                last_checked_at = NOW()
            WHERE id = %s;
            """
            self.execute(sql, (status, risk_level, primary_violation, domain_id))

    def insert_audit_log(self, audit_table: str, result_record: Dict[str, Any], task_id: int = 0):
        """
        插入高精度多模态审计存证记录 (含 task_id 关联、电子指纹与完整报告)
        """
        url = result_record.get("url", "")
        domain = url.split("://")[-1].split("/")[0]

        summary = result_record.get("verdict_summary", {})
        is_viol = bool(summary.get("is_violation", False))
        risk_level = summary.get("overall_risk_level", "SAFE")
        primary_viol = summary.get("primary_violation_category", "normal")
        cloaking = bool(summary.get("cloaking_suspected", False))
        cloaking_notes = summary.get("cloaking_notes") or ""

        cat_probs = json.dumps(summary.get("category_probabilities", {}), ensure_ascii=False)
        model_used = result_record.get("model_used", "qwen2-vl")
        full_report_json = json.dumps(result_record, ensure_ascii=False)

        stats = summary.get("stats", {})
        devices_tested = stats.get("total_tested_devices", 1)
        violation_devices = stats.get("violation_device_count", 0)

        sql = f"""
        INSERT INTO {audit_table} (
            task_id, domain, url, is_violation, overall_risk_level, primary_violation,
            cloaking_suspected, cloaking_notes, category_probabilities,
            device_count, violation_device_count, model_used, report_json, checked_at
        ) VALUES (
            %s, %s, %s, %s, %s, %s,
            %s, %s, %s::jsonb,
            %s, %s, %s, %s::jsonb, NOW()
        );
        """
        self.execute(
            sql,
            (
                task_id, domain, url, is_viol, risk_level, primary_viol,
                cloaking, cloaking_notes, cat_probs,
                devices_tested, violation_devices, model_used, full_report_json
            )
        )

    def close(self):
        if self._pg_conn:
            try:
                self._pg_conn.close()
            except Exception:
                pass
            self._pg_conn = None
        if self.mini_client:
            self.mini_client.close()
