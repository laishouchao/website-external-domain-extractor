"""
Web Compliance Checker - Background Task Runner & Job Manager
Manages asynchronous scanning batches, worker concurrency, and real-time status/log streaming.
"""

import asyncio
import collections
import logging
import threading
import time
from typing import Dict, Any, List, Optional

from config import DEFAULT_WORKERS, DEFAULT_BATCH_SIZE, DEVICE_PRESETS
from db import GLOBAL_DB
from inspector import GLOBAL_INSPECTOR

logger = logging.getLogger("compliance_checker.runner")

class ScanJobRunner:
    def __init__(self):
        self.lock = threading.RLock()
        self.is_running = False
        self.should_stop = False
        self.thread: Optional[threading.Thread] = None
        self.job_id = None
        self.start_time = None

        self.stats = {
            "total": 0,
            "completed": 0,
            "violations": 0,
            "error_pages": 0,
            "clean_pending": 0,
            "dead_links": 0,
            "current_domain": "",
            "message": "系统空闲中，待命启动",
            "is_loop": False,
            "is_dry_run": False,
        }
        self.logs = collections.deque(maxlen=400)

    def log(self, msg: str):
        with self.lock:
            ts = time.strftime("%H:%M:%S")
            entry = f"[{ts}] {msg}"
            self.logs.append(entry)
            print(entry)

    def get_status(self) -> Dict[str, Any]:
        with self.lock:
            elapsed = int(time.time() - self.start_time) if self.start_time and self.is_running else 0
            return {
                "is_running": self.is_running,
                "job_id": self.job_id,
                "elapsed_sec": elapsed,
                "stats": dict(self.stats),
                "logs": list(self.logs),
            }

    def stop(self):
        with self.lock:
            if self.is_running:
                self.should_stop = True
                self.log("⚠️ 收到用户停止指令，正在安全终止当前巡检批次...")

    def start(
        self,
        workers: int = DEFAULT_WORKERS,
        batch_size: int = DEFAULT_BATCH_SIZE,
        devices: List[str] = None,
        domain_filter: str = "",
        is_loop: bool = False,
        is_dry_run: bool = False
    ) -> Dict[str, Any]:
        with self.lock:
            if self.is_running:
                return {"ok": False, "message": "已有任务正在运行中，请勿重复启动"}

            self.is_running = True
            self.should_stop = False
            self.start_time = time.time()
            self.job_id = f"job_{time.strftime('%Y%m%d_%H%M%S')}"
            self.logs.clear()

            self.stats = {
                "total": 0,
                "completed": 0,
                "violations": 0,
                "error_pages": 0,
                "clean_pending": 0,
                "dead_links": 0,
                "current_domain": "",
                "message": "正在检索待巡检域名...",
                "is_loop": is_loop,
                "is_dry_run": is_dry_run,
            }

        devices = devices or DEVICE_PRESETS["dual"]

        def _worker_thread():
            asyncio.run(self._run_async(workers, batch_size, devices, domain_filter, is_loop, is_dry_run))

        self.thread = threading.Thread(target=_worker_thread, daemon=True)
        self.thread.start()

        return {"ok": True, "job_id": self.job_id, "message": "巡检任务已成功启动"}

    async def _run_async(
        self,
        workers: int,
        batch_size: int,
        devices: List[str],
        domain_filter: str,
        is_loop: bool,
        is_dry_run: bool
    ):
        self.log(f"🚀 巡检任务启动 | JobID: {self.job_id} | 并发: {workers} | 批次: {batch_size} 条 | 设备: {', '.join(devices)}")
        if is_dry_run:
            self.log("🔍 【预检演练模式 (Dry-Run)】已开启：仅检索目标与快速探活，不调用大模型与写库")

        try:
            while not self.should_stop:
                # Fetch pending batch from PostgreSQL
                items = GLOBAL_DB.fetch_pending_batch(limit=batch_size, domain_filter=domain_filter)
                if not items:
                    self.log("✅ 待巡检资产池已全部处理完毕或未检索到符合条件的域名。")
                    if not is_loop:
                        break
                    self.log("⏳ 后台常驻守护等待新资产中，休眠 15 秒...")
                    for _ in range(15):
                        if self.should_stop:
                            break
                        await asyncio.sleep(1)
                    continue

                with self.lock:
                    self.stats["total"] += len(items)
                    self.stats["message"] = f"当前批次获取到 {len(items)} 条域名"

                self.log(f"📦 检索到待研判域名 {len(items)} 条，开始多设备流水线审计...")

                # Worker pool with bounded concurrency
                sem = asyncio.Semaphore(workers)

                async def _process_item(item):
                    if self.should_stop:
                        return
                    domain = item["domain"]
                    task_id = item.get("task_id", 0)
                    url = item.get("sample_page_url") or f"https://{domain}"

                    with self.lock:
                        self.stats["current_domain"] = domain
                        self.stats["message"] = f"正在审计: {domain}"

                    async with sem:
                        if self.should_stop:
                            return
                        try:
                            if is_dry_run:
                                self.log(f"[Dry-Run] 预检目标: {domain} | URL: {url}")
                                await asyncio.sleep(0.1)
                                res = {"status": "dry_run", "is_violation": False, "is_404": False}
                            else:
                                res = await GLOBAL_INSPECTOR.inspect(
                                    domain=domain,
                                    devices=devices,
                                    task_id=task_id,
                                    sample_url=url
                                )

                            with self.lock:
                                self.stats["completed"] += 1
                                st = res.get("status")
                                if res.get("is_violation"):
                                    self.stats["violations"] += 1
                                    self.log(f"🚨 【检出异常违规】{domain} -> 判定: {res.get('primary_violation')} (已标记 verified_failed)")
                                elif res.get("is_404"):
                                    self.stats["error_pages"] += 1
                                    self.log(f"⚠️ 【404失效页面】{domain} -> 保持待研判 (unverified)")
                                elif st == "dead_link":
                                    self.stats["dead_links"] += 1
                                    self.log(f"⏳ 【探活未解析/死链】{domain} -> 保持待研判 (unverified)")
                                else:
                                    self.stats["clean_pending"] += 1
                                    self.log(f"⏳ 【多端未见异常】{domain} -> 保持待研判 (unverified)")

                        except Exception as e:
                            self.log(f"❌ 审计出错 [{domain}]: {e}")
                            with self.lock:
                                self.stats["completed"] += 1

                # Gather batch tasks
                await asyncio.gather(*[_process_item(it) for it in items])

                if not is_loop or self.should_stop:
                    break

            self.log(f"🏁 巡检任务执行结束 | 共处理: {self.stats['completed']} 条 | 检出违规: {self.stats['violations']} 条 | 404失效: {self.stats['error_pages']} 条")

        except Exception as e:
            self.log(f"💥 巡检流程异常中断: {e}")
        finally:
            with self.lock:
                self.is_running = False
                self.stats["current_domain"] = ""
                self.stats["message"] = "巡检任务已完成"

GLOBAL_RUNNER = ScanJobRunner()
