"""
ClickHouse Client module.
Supports high-speed batch streaming inserts and analytical querying.
Supports clickhouse_connect if installed, with zero-dependency HTTP standard library as fallback.
"""

import json
import urllib.request
import urllib.parse
import urllib.error
import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger("compliance_checker.db_clickhouse")

try:
    import clickhouse_connect
    CLICKHOUSE_CONNECT_AVAILABLE = True
except ImportError:
    CLICKHOUSE_CONNECT_AVAILABLE = False


class ClickHouseClient:
    def __init__(
        self,
        host: str = "localhost",
        port: int = 8123,
        user: str = "default",
        password: str = "",
        database: str = "website_domain_db",
        timeout: int = 30
    ):
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.database = database
        self.timeout = timeout
        self.base_url = f"http://{self.host}:{self.port}"
        self._ch_client = None

        if CLICKHOUSE_CONNECT_AVAILABLE:
            try:
                self._ch_client = clickhouse_connect.get_client(
                    host=self.host,
                    port=self.port,
                    username=self.user,
                    password=self.password,
                    database=self.database,
                    connect_timeout=min(self.timeout, 5),
                    send_receive_timeout=self.timeout
                )
            except Exception:
                self._ch_client = None

    def _send_request(self, query: str, data: Optional[bytes] = None) -> str:
        params = {
            "database": self.database,
            "query": query
        }
        url = f"{self.base_url}/?{urllib.parse.urlencode(params)}"
        headers = {
            "X-ClickHouse-User": self.user,
            "X-ClickHouse-Key": self.password,
            "User-Agent": "WebComplianceChecker-ClickHouse/1.0"
        }

        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return resp.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            err_msg = e.read().decode("utf-8", errors="ignore")
            raise RuntimeError(f"ClickHouse HTTP {e.code} Error: {err_msg.strip()}")
        except urllib.error.URLError as e:
            raise ConnectionError(f"无法连接到 ClickHouse ({self.base_url}): {e.reason}")

    def query(self, sql: str) -> List[Dict[str, Any]]:
        """
        执行查询并返回字典列表 (自动附带 FORMAT JSON)
        """
        clean_sql = sql.strip().rstrip(";")
        if not clean_sql.upper().endswith("FORMAT JSON"):
            clean_sql += " FORMAT JSON"

        resp_text = self._send_request(clean_sql)
        try:
            data = json.loads(resp_text)
            return data.get("data", [])
        except Exception:
            return []

    def execute(self, sql: str):
        """
        执行 DDL 或更新语句
        """
        if self._ch_client:
            try:
                self._ch_client.command(sql.strip())
                return
            except Exception:
                pass
        self._send_request(sql.strip())

    def insert_rows(self, table_name: str, rows: List[Dict[str, Any]]):
        """
        使用高效的 JSONEachRow 格式批量插入
        """
        if not rows:
            return

        query = f"INSERT INTO {table_name} FORMAT JSONEachRow"
        body_lines = [json.dumps(row, ensure_ascii=False) for row in rows]
        payload = ("\n".join(body_lines) + "\n").encode("utf-8")
        self._send_request(query, data=payload)

    def init_schema(self, table_name: str = "compliance_audit_events"):
        """
        初始化 ClickHouse 违规审计日志分析表 (含 task_id 关联与高效时序聚合引擎)
        """
        ddl = f"""
        CREATE TABLE IF NOT EXISTS {table_name} (
            event_time DateTime64(3) DEFAULT now(),
            task_id UInt32 DEFAULT 0,
            domain String,
            url String,
            is_violation UInt8,
            overall_risk_level LowCardinality(String),
            primary_violation LowCardinality(String),
            cloaking_suspected UInt8,
            cloaking_notes String,
            prob_pornography Float32,
            prob_gambling Float32,
            prob_fraud Float32,
            prob_violence Float32,
            prob_political Float32,
            prob_adware Float32,
            total_devices_tested UInt8,
            violation_devices_count UInt8,
            model_used String,
            report_json String
        ) ENGINE = MergeTree()
        ORDER BY (is_violation, overall_risk_level, event_time, domain);
        """
        self.execute(ddl)
        print(f"[*] ClickHouse 表结构就绪: {table_name}")

    def fetch_pending_domains(self, table_name: str = "external_domains", limit: int = 100) -> List[Dict[str, Any]]:
        """
        从 ClickHouse 中读取待审核的域名
        """
        sql = f"""
        SELECT id, domain, sample_page_url as url
        FROM {table_name}
        LIMIT {limit}
        """
        try:
            return self.query(sql)
        except Exception:
            return []

    def close(self):
        if self._ch_client:
            try:
                self._ch_client.close()
            except Exception:
                pass
            self._ch_client = None
