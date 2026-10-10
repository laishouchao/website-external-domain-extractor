"""
Inspection Job History & Checkpoint Persistence Manager.
Maintains execution history, audit batch records, and breakpoint snapshots
under output/history/ for crash recovery, progress auditing, and breakpoint resuming.
"""

import os
import json
import threading
from datetime import datetime
from typing import Dict, Any, List, Optional, Set


class JobHistoryManager:
    def __init__(self, base_dir: str = "output"):
        self.history_dir = os.path.join(base_dir, "history")
        self.index_file = os.path.join(self.history_dir, "history_index.json")
        self.lock = threading.RLock()
        os.makedirs(self.history_dir, exist_ok=True)
        self._ensure_index_file()

    def _ensure_index_file(self):
        with self.lock:
            if not os.path.exists(self.index_file):
                try:
                    with open(self.index_file, "w", encoding="utf-8") as f:
                        json.dump({"jobs": []}, f, ensure_ascii=False, indent=2)
                except Exception:
                    pass

    def _read_index(self) -> List[Dict[str, Any]]:
        with self.lock:
            if not os.path.exists(self.index_file):
                return []
            try:
                with open(self.index_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return data.get("jobs", [])
            except Exception:
                return []

    def _write_index(self, jobs: List[Dict[str, Any]]):
        with self.lock:
            try:
                with open(self.index_file, "w", encoding="utf-8") as f:
                    json.dump({"jobs": jobs, "updated_at": datetime.now().isoformat()}, f, ensure_ascii=False, indent=2)
            except Exception as e:
                print(f"[警告] 写入历史索引文件失败: {e}")

    def create_job(
        self,
        job_id: str,
        config: Dict[str, Any],
        target_domains: List[str]
    ) -> Dict[str, Any]:
        """
        创建并初始化批次任务快照
        """
        now_str = datetime.now().isoformat()
        job_data = {
            "job_id": job_id,
            "status": "running",
            "start_time": now_str,
            "end_time": None,
            "config": config,
            "stats": {
                "total_targets": len(target_domains),
                "completed": 0,
                "violations": 0,
                "clean": 0,
                "dead_skipped": 0,
                "errors": 0,
            },
            "checkpoint": {
                "last_domain": None,
                "processed_domains": [],
                "last_update_time": now_str
            },
            "target_domains": target_domains,
            "violations_list": []
        }

        with self.lock:
            # 写入单任务独立快照文件
            job_file = os.path.join(self.history_dir, f"{job_id}.json")
            try:
                with open(job_file, "w", encoding="utf-8") as f:
                    json.dump(job_data, f, ensure_ascii=False, indent=2)
            except Exception as e:
                print(f"[警告] 写入任务快照文件失败: {e}")

            # 更新索引文件摘要列表
            jobs = self._read_index()
            # 移除旧的同名条目
            jobs = [j for j in jobs if j.get("job_id") != job_id]
            summary_item = {
                "job_id": job_id,
                "status": "running",
                "start_time": now_str,
                "end_time": None,
                "workers": config.get("workers", 3),
                "batch_size": config.get("batch_size", len(target_domains)),
                "is_loop": bool(config.get("loop", False)),
                "is_dry_run": bool(config.get("dry_run", False)),
                "enable_probe": bool(config.get("enable_probe", True)),
                "total_targets": len(target_domains),
                "completed": 0,
                "violations": 0,
                "dead_skipped": 0
            }
            jobs.insert(0, summary_item)
            self._write_index(jobs[:100])  # 保留最近 100 批次索引

        return job_data

    def update_checkpoint(
        self,
        job_id: str,
        domain: str,
        is_violation: bool = False,
        is_dead: bool = False,
        is_error: bool = False,
        detail_info: Optional[Dict[str, Any]] = None
    ):
        """
        实时更新断点快照（完成单域名即落盘，防止断电或崩溃丢失状态）
        """
        with self.lock:
            job_file = os.path.join(self.history_dir, f"{job_id}.json")
            if not os.path.exists(job_file):
                return

            try:
                with open(job_file, "r", encoding="utf-8") as f:
                    job_data = json.load(f)

                stats = job_data["stats"]
                checkpoint = job_data["checkpoint"]

                stats["completed"] += 1
                if is_dead:
                    stats["dead_skipped"] += 1
                elif is_violation:
                    stats["violations"] += 1
                    if detail_info:
                        job_data.setdefault("violations_list", []).append({
                            "domain": domain,
                            "time": datetime.now().isoformat(),
                            "risk_level": detail_info.get("overall_risk_level", "HIGH"),
                            "category": detail_info.get("primary_violation", "unknown")
                        })
                elif is_error:
                    stats["errors"] += 1
                else:
                    stats["clean"] += 1

                checkpoint["last_domain"] = domain
                if domain not in checkpoint["processed_domains"]:
                    checkpoint["processed_domains"].append(domain)
                checkpoint["last_update_time"] = datetime.now().isoformat()

                with open(job_file, "w", encoding="utf-8") as f:
                    json.dump(job_data, f, ensure_ascii=False, indent=2)

                # 同步更新索引
                jobs = self._read_index()
                for j in jobs:
                    if j.get("job_id") == job_id:
                        j["completed"] = stats["completed"]
                        j["violations"] = stats["violations"]
                        j["dead_skipped"] = stats["dead_skipped"]
                        break
                self._write_index(jobs)

            except Exception as e:
                pass

    def finish_job(
        self,
        job_id: str,
        status: str = "completed",
        message: str = ""
    ):
        """
        标记批次任务结束并归档状态
        """
        with self.lock:
            job_file = os.path.join(self.history_dir, f"{job_id}.json")
            if not os.path.exists(job_file):
                return

            now_str = datetime.now().isoformat()
            try:
                with open(job_file, "r", encoding="utf-8") as f:
                    job_data = json.load(f)

                job_data["status"] = status
                job_data["end_time"] = now_str
                job_data["finish_message"] = message

                with open(job_file, "w", encoding="utf-8") as f:
                    json.dump(job_data, f, ensure_ascii=False, indent=2)

                jobs = self._read_index()
                for j in jobs:
                    if j.get("job_id") == job_id:
                        j["status"] = status
                        j["end_time"] = now_str
                        break
                self._write_index(jobs)

            except Exception as e:
                print(f"[警告] 归档任务结束状态失败: {e}")

    def list_jobs(self, limit: int = 50) -> Dict[str, Any]:
        """
        获取历史批次摘要列表及汇总卡片统计
        """
        with self.lock:
            jobs = self._read_index()
            total_jobs = len(jobs)
            total_targets = sum(j.get("total_targets", 0) for j in jobs)
            total_violations = sum(j.get("violations", 0) for j in jobs)
            total_dead_skipped = sum(j.get("dead_skipped", 0) for j in jobs)

            return {
                "summary": {
                    "total_jobs": total_jobs,
                    "total_targets_processed": total_targets,
                    "total_violations_found": total_violations,
                    "total_dead_skipped": total_dead_skipped
                },
                "jobs": jobs[:limit]
            }

    def get_job_detail(self, job_id: str) -> Optional[Dict[str, Any]]:
        """
        获取指定历史批次的完整快照
        """
        with self.lock:
            job_file = os.path.join(self.history_dir, f"{job_id}.json")
            if not os.path.exists(job_file):
                return None
            try:
                with open(job_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return None

    def get_processed_domains(self, job_id: str) -> Set[str]:
        """
        提取某批次已处理完成的域名集合（供断点续爬剔除）
        """
        detail = self.get_job_detail(job_id)
        if detail and "checkpoint" in detail:
            return set(detail["checkpoint"].get("processed_domains", []))
        return set()


GLOBAL_HISTORY_MANAGER = JobHistoryManager()
