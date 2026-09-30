"""
Unified Database Manager.
Bridges PostgreSQL (transactional external domains tasks, status & forensic logs)
and ClickHouse (high-speed audit analytics & events stream).
Supports automatic environment variable resolution, domain URL synthesis,
and dual-engine persistence.
"""

import os
import json
import logging
from typing import List, Dict, Any, Optional, Tuple

from db_postgres import PostgresClient
from db_clickhouse import ClickHouseClient

logger = logging.getLogger("compliance_checker.db_manager")


def _find_env_file() -> Optional[str]:
    """Search for .env in current directory or parent directory."""
    candidates = [
        os.path.join(os.getcwd(), ".env"),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"),
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"),
    ]
    for p in candidates:
        if os.path.exists(p):
            return p
    return None


def _load_env_dict() -> Dict[str, str]:
    """Parse key=value pairs from discovered .env file."""
    env_map = {}
    env_path = _find_env_file()
    if env_path and os.path.exists(env_path):
        try:
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        env_map[k.strip()] = v.strip().strip("'\"")
        except Exception:
            pass
    return env_map


ENV_DEFAULTS = _load_env_dict()

DEFAULT_DB_CONFIG = {
    "postgres": {
        "enabled": True,
        "host": ENV_DEFAULTS.get("PG_HOST", os.getenv("PG_HOST", "localhost")),
        "port": int(ENV_DEFAULTS.get("PG_PORT", os.getenv("PG_PORT", 5432))),
        "user": ENV_DEFAULTS.get("PG_USER", os.getenv("PG_USER", "postgres")),
        "password": ENV_DEFAULTS.get("PG_PASSWORD", os.getenv("PG_PASSWORD", "")),
        "database": ENV_DEFAULTS.get("PG_DATABASE", os.getenv("PG_DATABASE", "website_domain_db")),
        "task_table": "external_domains",
        "audit_table": "compliance_audit_logs"
    },
    "clickhouse": {
        "enabled": True,
        "host": ENV_DEFAULTS.get("CH_HOST", os.getenv("CH_HOST", "localhost")),
        "port": int(ENV_DEFAULTS.get("CH_PORT", os.getenv("CH_PORT", 8123))),
        "user": ENV_DEFAULTS.get("CH_USER", os.getenv("CH_USER", "default")),
        "password": ENV_DEFAULTS.get("CH_PASSWORD", os.getenv("CH_PASSWORD", "")),
        "database": ENV_DEFAULTS.get("CH_DATABASE", os.getenv("CH_DATABASE", "website_domain_db")),
        "task_table": "external_domains",
        "audit_table": "compliance_audit_events"
    },
    "default_source": "postgres",  # 'postgres' or 'clickhouse'
    "default_sink": "both",        # 'postgres', 'clickhouse', or 'both'
    "batch_size": 50,
    "poll_interval_seconds": 10,
    "target_field": "domain",      # 'domain' (访问域名 https://domain) 或 'sample_page_url' (访问采样引用页)
    "filters": {
        "task_id": None,
        "risk_level": "pending",
        "verify_status": "unverified"
    }
}


class UnifiedDatabaseManager:
    def __init__(self, config_path: str = "db_config.json", overrides: Optional[Dict[str, Any]] = None):
        self.config_path = config_path
        self.config = self._load_config(overrides)

        self.pg_client: Optional[PostgresClient] = None
        self.ch_client: Optional[ClickHouseClient] = None

        pg_cfg = self.config.get("postgres", {})
        if pg_cfg.get("enabled", True):
            self.pg_client = PostgresClient(
                host=pg_cfg.get("host") or ENV_DEFAULTS.get("PG_HOST", os.getenv("PG_HOST", "localhost")),
                port=int(pg_cfg.get("port") or ENV_DEFAULTS.get("PG_PORT", os.getenv("PG_PORT", 5432))),
                user=pg_cfg.get("user") or ENV_DEFAULTS.get("PG_USER", os.getenv("PG_USER", "postgres")),
                password=pg_cfg.get("password") or ENV_DEFAULTS.get("PG_PASSWORD", os.getenv("PG_PASSWORD", "")),
                database=pg_cfg.get("database") or ENV_DEFAULTS.get("PG_DATABASE", os.getenv("PG_DATABASE", "website_domain_db"))
            )

        ch_cfg = self.config.get("clickhouse", {})
        if ch_cfg.get("enabled", True):
            self.ch_client = ClickHouseClient(
                host=ch_cfg.get("host") or ENV_DEFAULTS.get("CH_HOST", os.getenv("CH_HOST", "localhost")),
                port=int(ch_cfg.get("port") or ENV_DEFAULTS.get("CH_PORT", os.getenv("CH_PORT", 8123))),
                user=ch_cfg.get("user") or ENV_DEFAULTS.get("CH_USER", os.getenv("CH_USER", "default")),
                password=ch_cfg.get("password") or ENV_DEFAULTS.get("CH_PASSWORD", os.getenv("CH_PASSWORD", "")),
                database=ch_cfg.get("database") or ENV_DEFAULTS.get("CH_DATABASE", os.getenv("CH_DATABASE", "website_domain_db"))
            )

    def _load_config(self, overrides: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        cfg = json.loads(json.dumps(DEFAULT_DB_CONFIG))  # deep copy
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    file_cfg = json.load(f)
                    for k, v in file_cfg.items():
                        if isinstance(v, dict) and k in cfg and isinstance(cfg[k], dict):
                            for sub_k, sub_v in v.items():
                                if sub_v != "" and sub_v is not None:
                                    cfg[k][sub_k] = sub_v
                        else:
                            if v != "" and v is not None:
                                cfg[k] = v
            except Exception:
                pass

        if overrides:
            for k, v in overrides.items():
                if v is not None:
                    if isinstance(v, dict) and k in cfg and isinstance(cfg[k], dict):
                        cfg[k].update(v)
                    else:
                        cfg[k] = v

        # Resolve host and password from .env if empty or localhost
        for engine, env_host, env_pw in [("postgres", "PG_HOST", "PG_PASSWORD"), ("clickhouse", "CH_HOST", "CH_PASSWORD")]:
            if engine in cfg and isinstance(cfg[engine], dict):
                if not cfg[engine].get("host") or cfg[engine].get("host") in ("localhost", "127.0.0.1"):
                    env_h = ENV_DEFAULTS.get(env_host, os.getenv(env_host))
                    if env_h:
                        cfg[engine]["host"] = env_h
                if not cfg[engine].get("password"):
                    env_p = ENV_DEFAULTS.get(env_pw, os.getenv(env_pw))
                    if env_p:
                        cfg[engine]["password"] = env_p

        return cfg

    def init_schemas(self):
        """
        初始化 PostgreSQL 审计日志表与 ClickHouse 分析时序表
        """
        if self.pg_client:
            pg_cfg = self.config["postgres"]
            self.pg_client.init_schema(
                task_table=pg_cfg.get("task_table", "external_domains"),
                audit_table=pg_cfg.get("audit_table", "compliance_audit_logs")
            )

        if self.ch_client:
            ch_cfg = self.config["clickhouse"]
            self.ch_client.init_schema(
                table_name=ch_cfg.get("audit_table", "compliance_audit_events")
            )

    def fetch_pending_tasks(
        self,
        source: str = "postgres",
        limit: int = 50,
        task_id: Optional[int] = None,
        risk_level: Optional[str] = None,
        verify_status: Optional[str] = None,
        domain_filter: Optional[str] = None,
        target_table: Optional[str] = None,
        target_field: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        从数据库获取待审核域名任务，返回包含详细元数据与规范化目标访问 URL 的字典列表。
        返回值格式: [
            {
                "id": 123,
                "task_id": 93,
                "domain": "example.com",
                "root_domain": "example.com",
                "sample_page_url": "https://source.edu.cn/page.html",
                "target_url": "https://example.com",
                "risk_level": "pending",
                "verify_status": "unverified",
                "table_name": "external_domains"
            },
            ...
        ]
        """
        tasks = []
        target_field = target_field or self.config.get("target_field", "domain")

        if source in ("postgres", "pg") and self.pg_client:
            pg_table = target_table or self.config["postgres"].get("task_table", "external_domains")
            rows = self.pg_client.fetch_pending_domains(
                task_table=pg_table,
                limit=limit,
                task_id=task_id,
                risk_level=risk_level,
                verify_status=verify_status,
                domain_filter=domain_filter
            )

            for r in rows:
                item_id = r.get("id")
                domain = (r.get("domain") or "").strip()
                sample_url = (r.get("sample_page_url") or r.get("page_url") or "").strip()
                tid = r.get("task_id", 0)

                # 依据 target_field 决定巡检目标网页
                if target_field == "sample_page_url" and sample_url:
                    visit_url = sample_url
                else:
                    if domain.startswith("http://") or domain.startswith("https://"):
                        visit_url = domain
                    elif domain:
                        visit_url = f"https://{domain}"
                    else:
                        visit_url = sample_url or r.get("url", "")

                if not visit_url:
                    continue

                tasks.append({
                    "id": item_id,
                    "task_id": tid,
                    "domain": domain,
                    "root_domain": r.get("root_domain", ""),
                    "sample_page_url": sample_url,
                    "target_url": visit_url,
                    "risk_level": r.get("risk_level", "pending"),
                    "verify_status": r.get("verify_status", "unverified"),
                    "table_name": pg_table,
                    "raw_record": r
                })

        elif source in ("clickhouse", "ch") and self.ch_client:
            ch_table = target_table or self.config["clickhouse"].get("task_table", "external_domains")
            rows = self.ch_client.fetch_pending_domains(table_name=ch_table, limit=limit)
            for r in rows:
                item_id = r.get("id")
                domain = (r.get("domain") or "").strip()
                url = (r.get("url") or "").strip()
                visit_url = url or (f"https://{domain}" if domain else "")
                if not visit_url:
                    continue
                tasks.append({
                    "id": item_id,
                    "task_id": r.get("task_id", 0),
                    "domain": domain,
                    "root_domain": r.get("root_domain", ""),
                    "sample_page_url": "",
                    "target_url": visit_url,
                    "risk_level": r.get("risk_level", "pending"),
                    "verify_status": r.get("verify_status", "unverified"),
                    "table_name": ch_table,
                    "raw_record": r
                })

        return tasks

    def save_audit_result(
        self,
        result_record: Dict[str, Any],
        task_item: Optional[Dict[str, Any]] = None,
        task_id: Optional[Any] = None,
        sink: str = "both"
    ):
        """
        将审核结果回写到数据库 (PostgreSQL 任务更新与存证表 + ClickHouse 分析表)
        """
        summary = result_record.get("verdict_summary", {})
        is_viol = bool(summary.get("is_violation", False))
        risk_level = summary.get("overall_risk_level", "SAFE")
        primary_cat = summary.get("primary_violation_category", "normal")
        cloaking = int(summary.get("cloaking_suspected", False))
        cloaking_notes = summary.get("cloaking_notes", "")
        url = result_record.get("url", "")
        domain = url.split("://")[-1].split("/")[0]

        cat_probs = summary.get("category_probabilities", {})

        # 提取关联的系统任务属性
        tid = task_id
        db_record_id = None
        table_name = "external_domains"

        if isinstance(task_item, dict):
            db_record_id = task_item.get("id")
            if tid is None:
                tid = task_item.get("task_id", 0)
            table_name = task_item.get("table_name", "external_domains")
            if not domain and task_item.get("domain"):
                domain = task_item.get("domain")
        elif task_id is not None:
            db_record_id = task_id

        # 1. 回写 PostgreSQL
        if sink in ("postgres", "both", "pg") and self.pg_client:
            pg_cfg = self.config["postgres"]
            actual_table = table_name or pg_cfg.get("task_table", "external_domains")
            try:
                # 更新任务表字段 (risk_level, risk_tags, risk_remark, risk_source, verify_status, verify_time, verify_detail)
                if db_record_id is not None:
                    status = "violation" if is_viol else "clean"
                    self.pg_client.update_task_result(
                        task_table=actual_table,
                        domain_id=db_record_id,
                        status=status,
                        risk_level=risk_level,
                        is_violation=is_viol,
                        primary_violation=primary_cat,
                        task_item=task_item,
                        verdict_summary=summary,
                        full_record=result_record
                    )

                # 插入完整审计存证日志表
                self.pg_client.insert_audit_log(
                    audit_table=pg_cfg.get("audit_table", "compliance_audit_logs"),
                    result_record=result_record,
                    task_id=int(tid or 0)
                )
            except Exception as e:
                logger.warning(f"回写 PostgreSQL 失败: {e}")
                print(f"[警告] 回写 PostgreSQL 失败: {e}")

        # 2. 回写 ClickHouse (OLAP 分析日志)
        if sink in ("clickhouse", "both", "ch") and self.ch_client:
            ch_cfg = self.config["clickhouse"]
            try:
                stats = summary.get("stats", {})
                ch_row = {
                    "task_id": int(tid or 0),
                    "domain": domain,
                    "url": url,
                    "is_violation": 1 if is_viol else 0,
                    "overall_risk_level": risk_level,
                    "primary_violation": primary_cat,
                    "cloaking_suspected": cloaking,
                    "cloaking_notes": cloaking_notes,
                    "prob_pornography": float(cat_probs.get("pornography_vulgarity", {}).get("max_probability", 0.0)),
                    "prob_gambling": float(cat_probs.get("gambling_lottery", {}).get("max_probability", 0.0)),
                    "prob_fraud": float(cat_probs.get("fraud_scam", {}).get("max_probability", 0.0)),
                    "prob_violence": float(cat_probs.get("violence_contraband", {}).get("max_probability", 0.0)),
                    "prob_political": float(cat_probs.get("political_extremism", {}).get("max_probability", 0.0)),
                    "prob_adware": float(cat_probs.get("malicious_adware", {}).get("max_probability", 0.0)),
                    "total_devices_tested": int(stats.get("total_tested_devices", 1)),
                    "violation_devices_count": int(stats.get("violation_device_count", 0)),
                    "model_used": result_record.get("model_used", "qwen2-vl"),
                    "report_json": json.dumps(result_record, ensure_ascii=False)
                }

                self.ch_client.insert_rows(
                    table_name=ch_cfg.get("audit_table", "compliance_audit_events"),
                    rows=[ch_row]
                )
            except Exception as e:
                logger.warning(f"回写 ClickHouse 失败: {e}")
                print(f"[警告] 回写 ClickHouse 失败: {e}")

    def close(self):
        if self.pg_client:
            self.pg_client.close()
        if self.ch_client:
            self.ch_client.close()
