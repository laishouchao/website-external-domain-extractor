import asyncio
import multiprocessing as mp
import time
import logging
import traceback
from typing import Dict, Optional, List, Any

from app.db import crud
from app.crawler.task_process import run_task_process

logger = logging.getLogger("crawler_engine")


class CrawlJobProxy:
    """Proxy representing a crawl job running in an isolated worker process."""
    def __init__(self, task_id: int, target_url: str, config: dict, process: mp.Process, cmd_queue: mp.Queue, event_queue: mp.Queue):
        self.task_id = task_id
        self.target_url = target_url
        self.config = config
        self.process = process
        self.cmd_queue = cmd_queue
        self.event_queue = event_queue

        self.is_running: bool = True
        self.is_stopped: bool = False
        self.status: str = "running"

        self.pages_crawled: int = 0
        self.pages_total: int = 0
        self.external_domains_count: int = 0
        self.subdomains_count: int = 0

        self.current_speed: float = 0.0
        self.avg_speed: float = 0.0
        self.speed_unit: str = "页/秒"

        self.subscribers: List[asyncio.Queue] = []
        self.listener_task: Optional[asyncio.Task] = None

    def add_subscriber(self) -> asyncio.Queue:
        q = asyncio.Queue(maxsize=200)
        self.subscribers.append(q)
        return q

    def remove_subscriber(self, q: asyncio.Queue):
        if q in self.subscribers:
            self.subscribers.remove(q)

    def broadcast(self, event_type: str, data: Any):
        """Broadcast real-time message to SSE subscribers."""
        msg = {"type": event_type, "data": data}
        for q in list(self.subscribers):
            try:
                q.put_nowait(msg)
            except asyncio.QueueFull:
                try:
                    q.get_nowait()
                    q.put_nowait(msg)
                except Exception:
                    pass

    def get_speed(self) -> dict:
        return {
            "current_speed": self.current_speed,
            "avg_speed": self.avg_speed,
            "speed_unit": self.speed_unit
        }


# Compatibility alias
CrawlJob = CrawlJobProxy


class CrawlEngine:
    """Master crawler engine managing task worker processes."""
    _instance: Optional['CrawlEngine'] = None

    def __init__(self):
        self.jobs: Dict[int, CrawlJobProxy] = {}

    @classmethod
    def get_instance(cls) -> 'CrawlEngine':
        if cls._instance is None:
            cls._instance = CrawlEngine()
        return cls._instance

    def get_job(self, task_id: int) -> Optional[CrawlJobProxy]:
        return self.jobs.get(task_id)

    async def start_task(self, task_id: int) -> bool:
        task = crud.get_task(task_id)
        if not task:
            return False

        existing_job = self.jobs.get(task_id)
        if existing_job and existing_job.is_running and existing_job.process and existing_job.process.is_alive():
            return True

        crud.update_task_status(task_id, "running")

        ctx = mp.get_context("spawn")
        cmd_queue = ctx.Queue()
        event_queue = ctx.Queue()

        cfg = task.get("config") or {}
        p = ctx.Process(
            target=run_task_process,
            args=(task_id, task["target_url"], cfg, cmd_queue, event_queue),
            daemon=True
        )
        p.start()

        proxy = CrawlJobProxy(task_id, task["target_url"], cfg, p, cmd_queue, event_queue)
        proxy.pages_crawled = task.get("pages_crawled", 0)
        proxy.pages_total = task.get("pages_total", 0)
        proxy.external_domains_count = task.get("external_domains_count", 0)
        proxy.subdomains_count = task.get("subdomains_count", 0)
        self.jobs[task_id] = proxy

        proxy.listener_task = asyncio.create_task(self._event_listener_loop(task_id, proxy))
        return True

    def pause_task(self, task_id: int) -> bool:
        job = self.jobs.get(task_id)
        if job and job.is_running and job.process and job.process.is_alive():
            try:
                job.cmd_queue.put({"cmd": "pause"})
                job.status = "paused"
                job.is_running = False
                job.current_speed = 0.0
                crud.update_task_status(task_id, "paused")
                job.broadcast("status", {"status": "paused"})
                return True
            except Exception as e:
                logger.error(f"Failed to pause task {task_id}: {e}")
        return False

    def resume_task(self, task_id: int) -> bool:
        job = self.jobs.get(task_id)
        if job and job.process and job.process.is_alive():
            try:
                job.cmd_queue.put({"cmd": "resume"})
                job.status = "running"
                job.is_running = True
                crud.update_task_status(task_id, "running")
                job.broadcast("status", {"status": "running"})
                return True
            except Exception as e:
                logger.error(f"Failed to resume task {task_id}: {e}")
        return False

    def stop_task(self, task_id: int) -> bool:
        job = self.jobs.get(task_id)
        if job:
            job.status = "stopped"
            job.is_stopped = True
            job.is_running = False
            job.current_speed = 0.0
            try:
                job.cmd_queue.put({"cmd": "stop"})
            except Exception:
                pass
            crud.update_task_status(task_id, "stopped")
            job.broadcast("status", {"status": "stopped"})
            return True
        return False

    async def cancel_and_clean_task(self, task_id: int):
        """Immediately stop and clean task worker process and proxy."""
        job = self.jobs.pop(task_id, None)
        if job:
            job.status = "stopped"
            job.is_stopped = True
            job.is_running = False
            job.current_speed = 0.0
            try:
                job.cmd_queue.put({"cmd": "stop"})
            except Exception:
                pass
            if job.listener_task and not job.listener_task.done():
                job.listener_task.cancel()
            if job.process and job.process.is_alive():
                try:
                    job.process.terminate()
                    await asyncio.to_thread(job.process.join, timeout=1.0)
                except Exception:
                    pass

    async def _event_listener_loop(self, task_id: int, proxy: CrawlJobProxy):
        try:
            while proxy.process and (proxy.process.is_alive() or not proxy.event_queue.empty()):
                try:
                    event = await asyncio.to_thread(proxy.event_queue.get, timeout=0.5)
                except Exception:
                    await asyncio.sleep(0.05)
                    continue

                event_type = event.get("type")
                data = event.get("data", {})

                if event_type == "progress":
                    proxy.pages_crawled = data.get("pages_crawled", proxy.pages_crawled)
                    proxy.pages_total = data.get("pages_total", proxy.pages_total)
                    proxy.external_domains_count = data.get("external_domains_count", proxy.external_domains_count)
                    proxy.subdomains_count = data.get("subdomains_count", proxy.subdomains_count)
                    proxy.current_speed = data.get("current_speed", proxy.current_speed)
                    proxy.avg_speed = data.get("avg_speed", proxy.avg_speed)
                elif event_type == "status":
                    st = data.get("status")
                    proxy.status = st
                    proxy.is_running = (st == "running")
                    proxy.is_stopped = (st == "stopped")
                    if not proxy.is_running:
                        proxy.current_speed = 0.0
                elif event_type == "complete":
                    proxy.is_running = False
                    proxy.status = data.get("status", "completed")
                    proxy.is_stopped = (proxy.status == "stopped")
                    proxy.current_speed = 0.0
                    proxy.pages_crawled = data.get("pages_crawled", proxy.pages_crawled)
                    proxy.external_domains_count = data.get("external_domains_count", proxy.external_domains_count)
                    proxy.subdomains_count = data.get("subdomains_count", proxy.subdomains_count)

                proxy.broadcast(event_type, data)
                if event_type in ("complete", "error"):
                    break
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Event listener loop error for task {task_id}: {e}")
        finally:
            proxy.is_running = False
            if proxy.process and proxy.process.is_alive():
                try:
                    await asyncio.to_thread(proxy.process.join, timeout=1.0)
                except Exception:
                    pass
