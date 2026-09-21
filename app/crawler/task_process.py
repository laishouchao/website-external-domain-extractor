import asyncio
import time
from collections import deque
import logging
import traceback
from urllib.parse import urlparse
from typing import Set, Optional, List, Any
import httpx

from app.config import DEFAULT_CRAWLER_CONFIG
from app.db import crud
from app.crawler.extractor import PageExtractor
from app.crawler.worker import fetch_page, discover_sitemap_urls, fetch_asset_content

logger = logging.getLogger("crawler_process")

class TaskWorkerRunner:
    def __init__(self, task_id: int, target_url: str, config: dict, cmd_queue, event_queue):
        self.task_id = task_id
        self.target_url = target_url
        self.config = {**DEFAULT_CRAWLER_CONFIG, **config}
        self.cmd_queue = cmd_queue
        self.event_queue = event_queue

        self.max_depth = int(self.config.get("max_depth", 10))
        self.max_pages = int(self.config.get("max_pages", 1000))
        self.concurrency = max(1, int(self.config.get("concurrency", 15)))
        self.delay = float(self.config.get("request_delay", 0.0))
        self.timeout = float(self.config.get("timeout", 10.0))
        self.user_agent = self.config.get("user_agent", "")
        self.ignore_ssl = bool(self.config.get("ignore_ssl", True))
        self.detect_sitemap = bool(self.config.get("detect_sitemap", True))
        self.scan_asset_content = bool(self.config.get("scan_asset_content", True))
        self.max_asset_size_bytes = int(self.config.get("max_asset_size_kb", 3072)) * 1024

        # Batch persistence settings
        self.batch_size = max(1, int(self.config.get("batch_size", 30)))
        self.batch_buffer: List[dict] = []
        self.batch_logs: List[dict] = []
        self.last_flush_time: float = time.time()
        self.last_broadcast_time: float = 0.0
        self.batch_lock: asyncio.Lock = asyncio.Lock()

        self.queue: asyncio.Queue = asyncio.Queue()
        self.asset_queue: asyncio.Queue = asyncio.Queue()
        self.visited_urls: Set[str] = set()
        self.enqueued_urls: Set[str] = set()
        self.visited_assets: Set[str] = set()
        self.known_external_domains: Set[str] = set()
        self.known_subdomains: Set[str] = set()

        self.pages_crawled = 0
        self.html_pages_crawled = 0
        self.external_domains_count = 0
        self.subdomains_count = 0
        self.active_workers = 0
        self.active_asset_workers = 0
        self.is_running = False
        self.is_stopped = False

        self.pause_event = asyncio.Event()
        self.pause_event.set()

        self.start_time: float = time.time()
        self.recent_page_timestamps: deque = deque()

        self.extractor = PageExtractor(target_url, self.config)

    @property
    def total_resources(self) -> int:
        return len(self.enqueued_urls) + len(self.visited_assets)

    def get_speed(self) -> dict:
        now = time.time()
        while self.recent_page_timestamps and now - self.recent_page_timestamps[0] > 5.0:
            self.recent_page_timestamps.popleft()

        elapsed = max(0.1, now - self.start_time)
        avg_speed = round(self.pages_crawled / elapsed, 1)

        if not self.is_running or self.is_stopped:
            current_speed = 0.0
        else:
            window = min(5.0, elapsed)
            current_speed = round(len(self.recent_page_timestamps) / max(0.5, window), 1)

        return {
            "current_speed": current_speed,
            "avg_speed": avg_speed,
            "speed_unit": "页/秒"
        }

    def emit_event(self, event_type: str, data: Any):
        """Send message across IPC queue to master process."""
        if self.event_queue is not None:
            try:
                self.event_queue.put_nowait({"type": event_type, "data": data})
            except Exception:
                pass

    def log(self, level: str, message: str):
        now_iso = time.strftime("%Y-%m-%dT%H:%M:%S")
        self.batch_logs.append({
            "task_id": self.task_id,
            "level": level.upper(),
            "message": message,
            "created_at": now_iso
        })
        self.emit_event("log", {
            "task_id": self.task_id,
            "level": level.upper(),
            "message": message,
            "created_at": now_iso
        })

    async def flush_buffer(self, force: bool = False):
        async with self.batch_lock:
            now = time.time()
            if not force:
                buffer_ready = len(self.batch_buffer) >= self.batch_size or (self.batch_buffer and now - self.last_flush_time >= 0.5)
                logs_ready = len(self.batch_logs) >= 50 or (self.batch_logs and now - self.last_flush_time >= 1.0)
                if not buffer_ready and not logs_ready:
                    return

            if self.batch_buffer:
                items_to_save = self.batch_buffer
                self.batch_buffer = []
                self.last_flush_time = now

                try:
                    last_url = items_to_save[-1]['page_data']['url'] if items_to_save else None
                    await asyncio.to_thread(
                        crud.save_crawl_results_batch,
                        self.task_id,
                        items_to_save,
                        self.pages_crawled,
                        self.total_resources,
                        self.external_domains_count,
                        self.subdomains_count,
                        last_url
                    )
                except Exception as e:
                    logger.error(f"Failed to batch save crawl results for task {self.task_id}: {e}\n{traceback.format_exc()}")

            if self.batch_logs:
                logs_to_save = self.batch_logs
                self.batch_logs = []
                try:
                    await asyncio.to_thread(crud.batch_add_logs, logs_to_save)
                except Exception as e:
                    logger.error(f"Failed to batch save logs for task {self.task_id}: {e}")

    async def _cmd_listener_loop(self):
        """Poll commands from master process."""
        while self.is_running and not self.is_stopped:
            try:
                if self.cmd_queue and not self.cmd_queue.empty():
                    cmd_obj = self.cmd_queue.get_nowait()
                    cmd = cmd_obj.get("cmd") if isinstance(cmd_obj, dict) else cmd_obj
                    if cmd == "pause":
                        self.pause_event.clear()
                        await asyncio.to_thread(crud.update_task_status, self.task_id, "paused")
                        self.log("WARN", "任务已暂停")
                        await self.flush_buffer(force=True)
                        self.emit_event("status", {"status": "paused"})
                    elif cmd == "resume":
                        self.pause_event.set()
                        await asyncio.to_thread(crud.update_task_status, self.task_id, "running")
                        self.log("INFO", "任务已继续运行")
                        self.emit_event("status", {"status": "running"})
                    elif cmd == "stop":
                        self.is_stopped = True
                        self.pause_event.set()
                        while not self.queue.empty():
                            try:
                                self.queue.get_nowait()
                                self.queue.task_done()
                            except Exception:
                                break
                        while not self.asset_queue.empty():
                            try:
                                self.asset_queue.get_nowait()
                                self.asset_queue.task_done()
                            except Exception:
                                break
                        await asyncio.to_thread(crud.update_task_status, self.task_id, "stopped")
                        self.log("WARN", "任务已被用户手动停止")
                        await self.flush_buffer(force=True)
                        self.emit_event("status", {"status": "stopped"})
                        break
            except Exception as e:
                logger.error(f"Error checking cmd_queue: {e}")
            await asyncio.sleep(0.1)

    async def run(self):
        self.is_running = True
        self.log("INFO", f"子进程启动，开始执行扫描任务: {self.target_url}")

        cmd_task = asyncio.create_task(self._cmd_listener_loop())

        asset_concurrency = min(20, max(4, self.concurrency // 2)) if self.scan_asset_content else 0
        total_workers = self.concurrency + asset_concurrency
        max_conn = max(100, total_workers * 2)
        max_keep = max(50, total_workers)
        limits = httpx.Limits(max_connections=max_conn, max_keepalive_connections=max_keep, keepalive_expiry=30.0)
        headers = {
            "User-Agent": self.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Accept-Encoding": "gzip, deflate, br, zstd"
        }

        try:
            async with httpx.AsyncClient(
                verify=not self.ignore_ssl,
                timeout=self.timeout,
                limits=limits,
                headers=headers
            ) as client:

                # 1. Sitemap Discovery if enabled
                if self.detect_sitemap:
                    self.log("INFO", "正在探测 /robots.txt 及 /sitemap.xml ...")
                    sitemap_urls = await discover_sitemap_urls(client, self.target_url, timeout=10.0)
                    if sitemap_urls:
                        self.log("INFO", f"通过站点地图预发现 {len(sitemap_urls)} 个页面，已加入队列")
                        for sm_url in sitemap_urls:
                            if self.extractor.is_internal(urlparse(sm_url).hostname or ""):
                                if sm_url not in self.enqueued_urls:
                                    self.enqueued_urls.add(sm_url)
                                    await self.queue.put((sm_url, 1))

                # 2. Add seed URL
                if self.target_url not in self.enqueued_urls:
                    self.enqueued_urls.add(self.target_url)
                    await self.queue.put((self.target_url, 0))

                await asyncio.to_thread(
                    crud.update_task_progress,
                    self.task_id, 0, len(self.enqueued_urls), 0
                )

                # 3. Spawn HTML workers
                workers = [
                    asyncio.create_task(self._worker_loop(client, worker_id))
                    for worker_id in range(self.concurrency)
                ]

                # 4. Spawn decoupled Asset workers
                asset_workers = [
                    asyncio.create_task(self._asset_worker_loop(client, worker_id))
                    for worker_id in range(asset_concurrency)
                ]

                # 5. Wait for both queues to drain completely
                while not self.is_stopped:
                    await self.queue.join()
                    if self.scan_asset_content:
                        await self.asset_queue.join()
                    if self.queue.empty() and (not self.scan_asset_content or self.asset_queue.empty()):
                        break
                    await asyncio.sleep(0.05)

                # Cancel remaining idle workers
                all_workers = workers + asset_workers
                for w in all_workers:
                    w.cancel()
                await asyncio.gather(*all_workers, return_exceptions=True)
                await self.flush_buffer(force=True)

            # Final status update
            final_status = "stopped" if self.is_stopped else "completed"
            await asyncio.to_thread(crud.update_task_status, self.task_id, final_status)
            if self.is_stopped:
                self.log("WARN", f"扫描任务已停止。共抓取 {self.pages_crawled} 个页面/静态资源，发现 {self.external_domains_count} 个外部域名，{self.subdomains_count} 个本站子域名。")
            else:
                self.log("SUCCESS", f"扫描完成！全深度爬取完成，共扫描 {self.pages_crawled} 个页面/静态资源，发现 {self.external_domains_count} 个唯一外部域名，{self.subdomains_count} 个本站子域名。")

            await asyncio.to_thread(
                crud.update_task_progress,
                self.task_id,
                pages_crawled=self.pages_crawled,
                pages_total=max(self.pages_crawled, self.total_resources),
                external_domains_count=self.external_domains_count,
                subdomains_count=self.subdomains_count
            )

            # Auto sync risk pages to remediation table
            try:
                await asyncio.to_thread(crud.sync_risk_pages_from_occurrences, self.task_id)
            except Exception as e:
                self.log("WARN", f"同步待处置风险页面异常: {e}")

            speed_info = self.get_speed()
            self.emit_event("complete", {
                "pages_crawled": self.pages_crawled,
                "external_domains_count": self.external_domains_count,
                "subdomains_count": self.subdomains_count,
                "status": final_status,
                "current_speed": 0.0,
                "speed": 0.0,
                "avg_speed": speed_info["avg_speed"],
                "speed_unit": "页/秒"
            })

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Critical task error: {e}\n{traceback.format_exc()}")
            self.log("ERROR", f"任务异常终止: {e}")
            await asyncio.to_thread(crud.update_task_status, self.task_id, "failed", str(e))
            self.emit_event("status", {"status": "failed", "error": str(e)})
        finally:
            self.is_running = False
            cmd_task.cancel()
            await self.flush_buffer(force=True)

    async def _worker_loop(self, client: httpx.AsyncClient, worker_id: int):
        while not self.is_stopped:
            await self.pause_event.wait()
            if self.is_stopped:
                break

            try:
                try:
                    url, depth = await asyncio.wait_for(self.queue.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue

                if url in self.visited_urls:
                    self.queue.task_done()
                    continue

                self.visited_urls.add(url)
                self.active_workers += 1

                if self.max_pages > 0 and self.html_pages_crawled >= self.max_pages:
                    self.log("WARN", f"达到最大抓取页面上限 ({self.max_pages})，停止抓取新页面")
                    self.queue.task_done()
                    self.active_workers -= 1
                    while not self.queue.empty():
                        try:
                            self.queue.get_nowait()
                            self.queue.task_done()
                        except Exception:
                            break
                    while not self.asset_queue.empty():
                        try:
                            self.asset_queue.get_nowait()
                            self.asset_queue.task_done()
                        except Exception:
                            break
                    break

                if self.delay > 0:
                    await asyncio.sleep(self.delay)

                res = await fetch_page(client, url, timeout=self.timeout)
                path = urlparse(url).path or "/"

                title = ""
                ext_count_this_page = 0
                internal_links: List[str] = []
                external_domains = []
                occurrences = []
                subdomains = []

                if res.html:
                    if res.is_js:
                        extract_res = self.extractor.extract_from_asset(url, 'js', res.html)
                        title = f"[JS] {path}"
                        internal_links = extract_res.get("discovered_internal_urls", [])
                        external_domains = extract_res["external_domains"]
                        subdomains = extract_res.get("discovered_subdomains", [])
                        occurrences = extract_res["occurrences"]
                        ext_count_this_page = len(external_domains)
                    elif res.is_css:
                        extract_res = self.extractor.extract_from_asset(url, 'css', res.html)
                        title = f"[CSS] {path}"
                        internal_links = extract_res.get("discovered_internal_urls", [])
                        external_domains = extract_res["external_domains"]
                        subdomains = extract_res.get("discovered_subdomains", [])
                        occurrences = extract_res["occurrences"]
                        ext_count_this_page = len(external_domains)
                    else:
                        extract_res = self.extractor.extract(url, res.html)
                        title = extract_res["title"]
                        internal_links = extract_res["internal_urls"]
                        external_domains = extract_res["external_domains"]
                        subdomains = extract_res.get("discovered_subdomains", [])
                        occurrences = extract_res["occurrences"]
                        ext_count_this_page = len(external_domains)

                    for d in external_domains:
                        self.known_external_domains.add(d["domain"])
                    self.external_domains_count = len(self.known_external_domains)

                    for s in subdomains:
                        self.known_subdomains.add(s["subdomain"])
                    self.subdomains_count = len(self.known_subdomains)

                    next_depth = depth + 1
                    if self.max_depth == 0 or next_depth <= self.max_depth:
                        for new_url in internal_links:
                            if new_url not in self.visited_urls and new_url not in self.enqueued_urls:
                                self.enqueued_urls.add(new_url)
                                await self.queue.put((new_url, next_depth))

                    if self.scan_asset_content and extract_res.get("discovered_assets"):
                        for asset in extract_res["discovered_assets"]:
                            asset_url = asset["url"]
                            if asset_url not in self.visited_assets:
                                self.visited_assets.add(asset_url)
                                self.asset_queue.put_nowait((asset_url, asset["type"], depth))

                page_data = {
                    "url": url,
                    "path": path,
                    "depth": depth,
                    "status_code": res.status_code,
                    "content_type": res.content_type,
                    "title": title,
                    "response_time_ms": res.response_time_ms,
                    "external_domains_count": ext_count_this_page,
                    "error": res.error
                }

                self.html_pages_crawled += 1
                self.pages_crawled += 1
                now = time.time()
                self.recent_page_timestamps.append(now)

                async with self.batch_lock:
                    self.batch_buffer.append({
                        "page_data": page_data,
                        "external_domains": external_domains,
                        "occurrences": occurrences,
                        "subdomains": subdomains
                    })

                if res.error:
                    self.log("WARN", f"[深度 {depth}] 抓取失败 ({res.error}): {url}")
                else:
                    self.log("INFO", f"[深度 {depth}] HTTP {res.status_code} ({res.response_time_ms}ms) 提取外部域名 {ext_count_this_page} 个，子域名 {len(subdomains)} 个: {url}")

                if len(self.batch_buffer) >= self.batch_size or (now - self.last_flush_time >= 0.5):
                    await self.flush_buffer()

                if now - self.last_broadcast_time >= 0.15:
                    self.last_broadcast_time = now
                    speed_info = self.get_speed()
                    self.emit_event("progress", {
                        "task_id": self.task_id,
                        "pages_crawled": self.pages_crawled,
                        "pages_total": self.total_resources,
                        "external_domains_count": self.external_domains_count,
                        "subdomains_count": self.subdomains_count,
                        "current_url": url,
                        "depth": depth,
                        "status_code": res.status_code,
                        "title": title[:50],
                        "current_speed": speed_info["current_speed"],
                        "speed": speed_info["current_speed"],
                        "avg_speed": speed_info["avg_speed"],
                        "speed_unit": "页/秒"
                    })

                self.queue.task_done()
                self.active_workers -= 1

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Worker exception: {e}")
                self.log("ERROR", f"Worker 处理异常: {str(e)[:100]}")
                try:
                    self.queue.task_done()
                except Exception:
                    pass
                self.active_workers -= 1

    async def _asset_worker_loop(self, client: httpx.AsyncClient, worker_id: int):
        while not self.is_stopped:
            await self.pause_event.wait()
            if self.is_stopped:
                break

            try:
                try:
                    asset_url, asset_type, depth = await asyncio.wait_for(self.asset_queue.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue

                self.active_asset_workers += 1
                await self._scan_asset(client, asset_url, asset_type, depth)
                self.asset_queue.task_done()
                self.active_asset_workers -= 1

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Asset worker exception: {e}")
                try:
                    self.asset_queue.task_done()
                except Exception:
                    pass
                self.active_asset_workers -= 1

    async def _scan_asset(self, client: httpx.AsyncClient, asset_url: str, asset_type: str, depth: int):
        try:
            res = await fetch_asset_content(client, asset_url, timeout=self.timeout, max_size_bytes=self.max_asset_size_bytes)

            ext_domains = []
            subdomains = []
            occurrences = []

            if res.html:
                extract_res = self.extractor.extract_from_asset(asset_url, asset_type, res.html)
                ext_domains = extract_res.get("external_domains", [])
                subdomains = extract_res.get("discovered_subdomains", [])
                occurrences = extract_res.get("occurrences", [])

                if ext_domains:
                    for d in ext_domains:
                        self.known_external_domains.add(d["domain"])
                    self.external_domains_count = len(self.known_external_domains)

                if subdomains:
                    for s in subdomains:
                        self.known_subdomains.add(s["subdomain"])
                    self.subdomains_count = len(self.known_subdomains)

                if ext_domains or subdomains:
                    self.log("INFO", f"[JS/CSS在线访问] 内存分析 {asset_type.upper()} 发现外部域名 {len(ext_domains)} 个，本站子域名 {len(subdomains)} 个: {asset_url}")

                next_depth = depth + 1
                if self.max_depth == 0 or next_depth <= self.max_depth:
                    for new_url in extract_res.get("discovered_internal_urls", []):
                        if new_url not in self.visited_urls and new_url not in self.enqueued_urls:
                            self.enqueued_urls.add(new_url)
                            await self.queue.put((new_url, next_depth))

                sub_assets = extract_res.get("discovered_sub_assets", [])
                for sub in sub_assets:
                    sub_url = sub["url"]
                    if sub_url not in self.visited_assets:
                        self.visited_assets.add(sub_url)
                        self.asset_queue.put_nowait((sub_url, sub["type"], depth))

            parsed_path = urlparse(asset_url).path or "/"
            content_type = res.content_type or f"text/{asset_type}"
            title = f"[{asset_type.upper()}] {parsed_path}"
            page_data = {
                "url": asset_url,
                "path": parsed_path,
                "depth": depth,
                "status_code": res.status_code,
                "content_type": content_type,
                "title": title,
                "response_time_ms": res.response_time_ms,
                "external_domains_count": len(ext_domains),
                "error": res.error
            }

            self.pages_crawled += 1
            now = time.time()
            self.recent_page_timestamps.append(now)

            async with self.batch_lock:
                self.batch_buffer.append({
                    "page_data": page_data,
                    "external_domains": ext_domains,
                    "occurrences": occurrences,
                    "subdomains": subdomains
                })

            if len(self.batch_buffer) >= self.batch_size or (now - self.last_flush_time >= 0.5):
                await self.flush_buffer()

        except Exception as e:
            logger.error(f"Scan asset failed for {asset_url}: {e}")


def run_task_process(task_id: int, target_url: str, config: dict, cmd_queue, event_queue):
    """Entrypoint executed in child process."""
    try:
        runner = TaskWorkerRunner(task_id, target_url, config, cmd_queue, event_queue)
        asyncio.run(runner.run())
    except Exception as e:
        logger.critical(f"Task process {task_id} fatal exception: {e}\n{traceback.format_exc()}")
        try:
            if event_queue is not None:
                event_queue.put_nowait({"type": "status", "data": {"status": "failed", "error": str(e)}})
        except Exception:
            pass
