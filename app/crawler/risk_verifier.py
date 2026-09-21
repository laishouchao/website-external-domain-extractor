import asyncio
import re
import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
import httpx

from app.db import crud

logger = logging.getLogger("risk_verifier")

TITLE_REGEX = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)


def extract_html_title(html: str) -> str:
    match = TITLE_REGEX.search(html)
    if match:
        title = match.group(1).strip()
        # Clean extra whitespaces
        return re.sub(r"\s+", " ", title)[:150]
    return ""


def extract_context_around(content: str, target: str, window: int = 60) -> str:
    """Extract snippet around target keyword."""
    idx = content.lower().find(target.lower())
    if idx == -1:
        return ""
    start = max(0, idx - window)
    end = min(len(content), idx + len(target) + window)
    prefix = "..." if start > 0 else ""
    suffix = "..." if end < len(content) else ""
    snippet = content[start:end].replace("\r", " ").replace("\n", " ")
    return f"{prefix}{snippet}{suffix}"


async def verify_single_risk_page(
    item_or_id: Any,
    client: Optional[httpx.AsyncClient] = None
) -> Dict[str, Any]:
    """
    Verify if a specific risk page still contains the offending external domain.
    Accepts either an existing dict record or an integer ID.
    Returns the verification verdict and updates the database record.
    """
    if isinstance(item_or_id, dict):
        item = item_or_id
        remediation_id = item["id"]
    else:
        remediation_id = int(item_or_id)
        item = await asyncio.to_thread(crud.get_risk_remediation_by_id, remediation_id)

    if not item:
        return {"id": remediation_id, "error": "Record not found", "verify_status": "error"}

    page_url = item["page_url"]
    target_domain = item["domain"].strip().lower()
    raw_match = (item.get("raw_match") or "").strip().lower()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    should_close_client = False
    if client is None:
        client = httpx.AsyncClient(
            verify=False,
            timeout=httpx.Timeout(6.0, connect=3.0),
            follow_redirects=True,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 (RiskPageVerifier)"
            }
        )
        should_close_client = True

    verify_status = "unverified"
    verify_detail = ""
    new_snippet = None

    try:
        resp = await client.get(page_url)
        status_code = resp.status_code

        # Case 1: Page removed / 404 / 410 -> Treated as Remediated
        if status_code in (404, 410):
            verify_status = "page_removed"
            verify_detail = f"页面返回 HTTP {status_code}，涉险页面已下线或删除，风险解除。"
        elif status_code >= 400 and "404" in resp.text:
            verify_status = "page_removed"
            verify_detail = f"页面返回 HTTP {status_code} (包含404提示)，涉险页面已失效。"
        elif status_code >= 500:
            verify_status = "error"
            verify_detail = f"页面服务器内部错误 (HTTP {status_code})，暂无法判定。"
        else:
            # Case 2: Page accessible, check content
            # Try to decode content safely
            content_text = ""
            try:
                content_text = resp.text
            except Exception:
                content_text = resp.content.decode("utf-8", errors="ignore")

            content_lower = content_text.lower()
            domain_found = (target_domain in content_lower)

            # If not found by exact domain, check raw_match if available and meaningful
            if not domain_found and raw_match and len(raw_match) > 6 and raw_match in content_lower:
                domain_found = True

            if domain_found:
                verify_status = "verified_failed"
                snippet = extract_context_around(content_text, target_domain) or extract_context_around(content_text, raw_match)
                new_snippet = snippet
                verify_detail = f"HTTP {status_code} 正常访问，源码中仍检测到违规域名 [{target_domain}]，未完成修复。"
            else:
                verify_status = "verified_clean"
                verify_detail = f"HTTP {status_code} 正常访问，源码中未检测到违规域名 [{target_domain}]，已成功修复清除。"

            # Update page title if empty
            if not item.get("page_title"):
                extracted_title = extract_html_title(content_text)
                if extracted_title:
                    item["page_title"] = extracted_title

    except httpx.TimeoutException:
        verify_status = "error"
        verify_detail = "页面请求超时 (超 8 秒未响应)，暂无法判定。"
    except httpx.ConnectError as e:
        verify_status = "page_removed"
        verify_detail = f"页面连接失败或域名已无法解析 ({type(e).__name__})，可能已下线。"
    except Exception as e:
        verify_status = "error"
        verify_detail = f"请求异常: {str(e)[:120]}"
    finally:
        if should_close_client:
            await client.aclose()

    res_update = await asyncio.to_thread(
        crud.update_risk_remediation_verify_result,
        remediation_id=remediation_id,
        verify_status=verify_status,
        verify_time=now_str,
        verify_detail=verify_detail,
        context_snippet=new_snippet
    )
    manual_status = res_update.get("manual_status", "pending") if isinstance(res_update, dict) else "pending"

    return {
        "id": remediation_id,
        "page_url": page_url,
        "domain": target_domain,
        "verify_status": verify_status,
        "manual_status": manual_status,
        "verify_time": now_str,
        "verify_detail": verify_detail
    }


class PeriodicRiskVerifier:
    """
    Background scheduler that periodically re-verifies pending risk pages (every 1 hour).
    Also runs a rollback re-audit every 2 days at 15:00:00 for remediated pages.
    Supports manual trigger, real-time progress monitoring, and concurrent HTTP requests.
    """
    _instance: Optional["PeriodicRiskVerifier"] = None

    def __init__(self, interval_seconds: int = 3600):
        self.interval_seconds = interval_seconds
        self._running = False
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._task: Optional[asyncio.Task] = None
        self._rollback_task: Optional[asyncio.Task] = None
        self._trigger_event = asyncio.Event()
        self.is_checking = False
        self.last_run_time: Optional[str] = None
        self.next_run_time: Optional[str] = None
        self.last_run_stats: Dict[str, Any] = {
            "total_tested": 0,
            "cleaned_count": 0,
            "failed_count": 0,
            "removed_count": 0,
            "error_count": 0,
            "duration_seconds": 0.0,
            "finished_at": None
        }
        self.current_progress: Dict[str, Any] = {
            "is_checking": False,
            "check_type": "regular",
            "total": 0,
            "current": 0,
            "cleaned_count": 0,
            "failed_count": 0,
            "removed_count": 0,
            "error_count": 0,
            "percentage": 0.0,
            "cleaned_ratio": 0.0,
            "failed_ratio": 0.0,
            "started_at": None
        }
        self.rollback_audit: Dict[str, Any] = {
            "is_auditing": False,
            "last_audit_time": None,
            "next_audit_time": self._calculate_next_rollback_time(),
            "last_stats": None
        }

    @classmethod
    def get_instance(cls) -> "PeriodicRiskVerifier":
        if cls._instance is None:
            cls._instance = PeriodicRiskVerifier(interval_seconds=3600)
        return cls._instance

    def _calculate_next_rollback_time(self, last_audit_dt: Optional[datetime] = None) -> str:
        """Calculate the next scheduled rollback audit time (every 2 days at 15:00:00)."""
        now = datetime.now()
        target_hour = 15
        target_minute = 0
        if last_audit_dt:
            candidate = datetime.combine(last_audit_dt.date() + timedelta(days=2), datetime.min.time()).replace(hour=target_hour, minute=target_minute, second=0)
            if candidate <= now:
                today_target = now.replace(hour=target_hour, minute=target_minute, second=0, microsecond=0)
                if now < today_target and (now.date() - last_audit_dt.date()).days >= 2:
                    candidate = today_target
                else:
                    candidate = today_target + timedelta(days=2)
        else:
            today_target = now.replace(hour=target_hour, minute=target_minute, second=0, microsecond=0)
            if now < today_target:
                candidate = today_target
            else:
                candidate = today_target + timedelta(days=2)
        return candidate.strftime("%Y-%m-%d %H:%M:%S")

    def start(self):
        """Start the background verification and rollback audit loops."""
        if self._running:
            return
        self._running = True
        try:
            self._loop = asyncio.get_running_loop()
        except RuntimeError:
            self._loop = None
        self._task = asyncio.create_task(self._run_loop())
        self._rollback_task = asyncio.create_task(self._rollback_scheduler_loop())
        logger.info(f"PeriodicRiskVerifier started. Interval: {self.interval_seconds}s (1 hour). Rollback audit target: {self.rollback_audit.get('next_audit_time')}")

    def stop(self):
        """Stop the background loops."""
        self._running = False
        self._trigger_event.set()
        if self._task and not self._task.done():
            self._task.cancel()
        if self._rollback_task and not self._rollback_task.done():
            self._rollback_task.cancel()
        logger.info("PeriodicRiskVerifier stopped.")

    def trigger_now(self) -> Dict[str, Any]:
        """Manually trigger an immediate verification cycle."""
        if self.is_checking or self.rollback_audit.get("is_auditing"):
            return {"status": "busy", "message": "复测或防回滚检测已在执行中，请稍候"}
        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._trigger_event.set)
        else:
            self._trigger_event.set()
        return {"status": "triggered", "message": "已触发全量待复测风险页面校验"}

    def trigger_rollback_now(self) -> Dict[str, Any]:
        """Manually trigger an immediate rollback re-audit cycle for remediated pages."""
        if self.is_checking or self.rollback_audit.get("is_auditing"):
            return {"status": "busy", "message": "复测或防回滚检测已在执行中，请稍候"}
        if self._loop and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(self._run_rollback_audit_cycle(), self._loop)
        else:
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self._run_rollback_audit_cycle())
            except Exception:
                asyncio.create_task(self._run_rollback_audit_cycle())
        return {"status": "triggered", "message": "已触发防回滚再测试（全量已修复记录复核）"}

    def _update_next_run_time(self):
        next_dt = datetime.now() + timedelta(seconds=self.interval_seconds)
        self.next_run_time = next_dt.strftime("%Y-%m-%d %H:%M:%S")

    def get_status(self) -> Dict[str, Any]:
        remaining_seconds = 0
        if self.next_run_time and not self.is_checking:
            try:
                nxt = datetime.strptime(self.next_run_time, "%Y-%m-%d %H:%M:%S")
                remaining_seconds = max(0, int((nxt - datetime.now()).total_seconds()))
            except Exception:
                pass

        return {
            "is_running": self._running,
            "is_checking": self.is_checking,
            "interval_seconds": self.interval_seconds,
            "remaining_seconds": remaining_seconds,
            "last_run_time": self.last_run_time,
            "next_run_time": self.next_run_time,
            "last_run_stats": self.last_run_stats,
            "current_progress": self.current_progress,
            "rollback_audit": self.rollback_audit
        }

    async def _run_loop(self):
        # Allow web server 2 seconds to finish startup binding before background loop starts
        await asyncio.sleep(2)
        while self._running:
            try:
                await self._run_verification_cycle()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error during risk verification cycle: {e}", exc_info=True)

            # Update next run time strictly 1 hour after cycle finishes
            self._update_next_run_time()

            try:
                # Wait for interval or explicit trigger
                await asyncio.wait_for(self._trigger_event.wait(), timeout=self.interval_seconds)
                self._trigger_event.clear()
            except asyncio.TimeoutError:
                pass

    async def _rollback_scheduler_loop(self):
        # Check every 30s if scheduled rollback audit time has arrived
        await asyncio.sleep(5)
        while self._running:
            try:
                now = datetime.now()
                target_str = self.rollback_audit.get("next_audit_time")
                if target_str:
                    target_dt = datetime.strptime(target_str, "%Y-%m-%d %H:%M:%S")
                    if now >= target_dt and not self.is_checking and not self.rollback_audit.get("is_auditing"):
                        logger.info(f"Rollback audit triggered by schedule at {now}")
                        await self._run_rollback_audit_cycle()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in rollback scheduler loop: {e}", exc_info=True)
            await asyncio.sleep(30)

    async def _run_verification_cycle(self):
        if self.is_checking or self.rollback_audit.get("is_auditing"):
            return
        self.is_checking = True
        t0 = datetime.now()
        start_str = t0.strftime("%Y-%m-%d %H:%M:%S")
        self.last_run_time = start_str
        self.current_progress["is_checking"] = True
        self.current_progress["check_type"] = "regular"
        self.current_progress["started_at"] = start_str

        try:
            # Step 1: Lightweight sync from occurrences (run in worker thread)
            try:
                await asyncio.to_thread(crud.sync_risk_pages_from_occurrences)
            except Exception as e:
                logger.warning(f"Error syncing risk pages before verification: {e}")

            # Step 2: Fetch pending / failed items to verify (run in worker thread, None = all records)
            pending_items = await asyncio.to_thread(crud.get_unverified_risk_remediations, None)
            if not pending_items:
                self.last_run_stats = {
                    "total_tested": 0,
                    "cleaned_count": 0,
                    "failed_count": 0,
                    "removed_count": 0,
                    "error_count": 0,
                    "duration_seconds": round((datetime.now() - t0).total_seconds(), 2),
                    "finished_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                }
                self.current_progress = {
                    "is_checking": False,
                    "check_type": "regular",
                    "total": 0,
                    "current": 0,
                    "cleaned_count": 0,
                    "failed_count": 0,
                    "removed_count": 0,
                    "error_count": 0,
                    "percentage": 100.0,
                    "cleaned_ratio": 0.0,
                    "failed_ratio": 0.0,
                    "started_at": start_str
                }
                return

            self.current_progress = {
                "is_checking": True,
                "check_type": "regular",
                "total": len(pending_items),
                "current": 0,
                "cleaned_count": 0,
                "failed_count": 0,
                "removed_count": 0,
                "error_count": 0,
                "percentage": 0.0,
                "cleaned_ratio": 0.0,
                "failed_ratio": 0.0,
                "started_at": start_str
            }

            queue = asyncio.Queue()
            for it in pending_items:
                queue.put_nowait(it)

            progress_lock = asyncio.Lock()
            limits = httpx.Limits(max_keepalive_connections=40, max_connections=50)
            num_workers = min(20, max(1, len(pending_items)))
            results = []

            async with httpx.AsyncClient(
                verify=False,
                timeout=httpx.Timeout(6.0, connect=3.0),
                limits=limits,
                follow_redirects=True,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 (RiskPageVerifier)"
                }
            ) as client:

                async def worker():
                    while not queue.empty():
                        try:
                            item = queue.get_nowait()
                        except asyncio.QueueEmpty:
                            break

                        try:
                            res = await verify_single_risk_page(item, client=client)
                        except Exception as ex:
                            res = {"id": item.get("id"), "verify_status": "error", "error": str(ex)}

                        async with progress_lock:
                            results.append(res)
                            self.current_progress["current"] += 1
                            st = res.get("verify_status")
                            if st == "verified_clean":
                                self.current_progress["cleaned_count"] += 1
                            elif st == "page_removed":
                                self.current_progress["removed_count"] += 1
                            elif st == "verified_failed":
                                self.current_progress["failed_count"] += 1
                            else:
                                self.current_progress["error_count"] += 1

                            cur = self.current_progress["current"]
                            tot = self.current_progress["total"]
                            self.current_progress["percentage"] = round((cur / tot) * 100, 1) if tot > 0 else 100.0
                            repaired = self.current_progress["cleaned_count"] + self.current_progress["removed_count"]
                            self.current_progress["cleaned_ratio"] = round((repaired / cur) * 100, 1) if cur > 0 else 0.0
                            self.current_progress["failed_ratio"] = round((self.current_progress["failed_count"] / cur) * 100, 1) if cur > 0 else 0.0

                        queue.task_done()

                workers = [asyncio.create_task(worker()) for _ in range(num_workers)]
                await asyncio.gather(*workers)

            # Aggregate stats
            cleaned = sum(1 for r in results if isinstance(r, dict) and r.get("verify_status") == "verified_clean")
            failed = sum(1 for r in results if isinstance(r, dict) and r.get("verify_status") == "verified_failed")
            removed = sum(1 for r in results if isinstance(r, dict) and r.get("verify_status") == "page_removed")
            errors = sum(1 for r in results if not isinstance(r, dict) or r.get("verify_status") == "error")

            duration = round((datetime.now() - t0).total_seconds(), 2)
            self.last_run_stats = {
                "total_tested": len(pending_items),
                "cleaned_count": cleaned,
                "failed_count": failed,
                "removed_count": removed,
                "error_count": errors,
                "duration_seconds": duration,
                "finished_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            logger.info(f"Risk verification cycle finished: tested={len(pending_items)}, clean={cleaned}, removed={removed}, failed={failed}, err={errors} in {duration}s")

        finally:
            self.is_checking = False
            self.current_progress["is_checking"] = False

    async def _run_rollback_audit_cycle(self):
        """Re-verify all remediated (clean/removed) records every 2 days at 15:00:00 to detect rollback/regression."""
        if self.is_checking or self.rollback_audit.get("is_auditing"):
            return
        self.rollback_audit["is_auditing"] = True
        self.is_checking = True
        t0 = datetime.now()
        start_str = t0.strftime("%Y-%m-%d %H:%M:%S")
        self.current_progress["is_checking"] = True
        self.current_progress["check_type"] = "rollback"
        self.current_progress["started_at"] = start_str

        try:
            # Fetch remediated items (verified_clean, page_removed) - None for ALL records
            remediated_items = await asyncio.to_thread(crud.get_remediated_risk_remediations, None)
            if not remediated_items:
                finish_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                self.rollback_audit["last_audit_time"] = finish_str
                self.rollback_audit["next_audit_time"] = self._calculate_next_rollback_time(datetime.now())
                self.rollback_audit["last_stats"] = {
                    "total_tested": 0,
                    "clean_preserved": 0,
                    "rollback_detected": 0,
                    "page_removed": 0,
                    "error_count": 0,
                    "duration_seconds": 0.0,
                    "finished_at": finish_str
                }
                return

            self.current_progress = {
                "is_checking": True,
                "check_type": "rollback",
                "total": len(remediated_items),
                "current": 0,
                "cleaned_count": 0,
                "failed_count": 0,
                "removed_count": 0,
                "error_count": 0,
                "percentage": 0.0,
                "cleaned_ratio": 0.0,
                "failed_ratio": 0.0,
                "started_at": start_str
            }

            queue = asyncio.Queue()
            for it in remediated_items:
                queue.put_nowait(it)

            progress_lock = asyncio.Lock()
            limits = httpx.Limits(max_keepalive_connections=40, max_connections=50)
            num_workers = min(20, max(1, len(remediated_items)))
            results = []

            async with httpx.AsyncClient(
                verify=False,
                timeout=httpx.Timeout(6.0, connect=3.0),
                limits=limits,
                follow_redirects=True,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 (RiskRollbackAuditor)"
                }
            ) as client:

                async def worker():
                    while not queue.empty():
                        try:
                            item = queue.get_nowait()
                        except asyncio.QueueEmpty:
                            break

                        try:
                            res = await verify_single_risk_page(item, client=client)
                        except Exception as ex:
                            res = {"id": item.get("id"), "verify_status": "error", "error": str(ex)}

                        st = res.get("verify_status")

                        # If rollback is detected (domain reappeared in page source)
                        if st == "verified_failed":
                            try:
                                await asyncio.to_thread(
                                    crud.mark_remediation_rollback_failed,
                                    remediation_id=item["id"],
                                    task_id=item["task_id"],
                                    domain=item["domain"],
                                    verify_time=res.get("verify_time", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
                                    verify_detail=f"【防回滚复测告警】已修复记录重新检测到风险域名！{res.get('verify_detail', '')}",
                                    context_snippet=res.get("context_snippet")
                                )
                            except Exception as ex:
                                logger.error(f"Failed to sync rollback status for item {item['id']}: {ex}")

                        async with progress_lock:
                            results.append(res)
                            self.current_progress["current"] += 1
                            if st == "verified_clean":
                                self.current_progress["cleaned_count"] += 1
                            elif st == "page_removed":
                                self.current_progress["removed_count"] += 1
                            elif st == "verified_failed":
                                self.current_progress["failed_count"] += 1
                            else:
                                self.current_progress["error_count"] += 1

                            cur = self.current_progress["current"]
                            tot = self.current_progress["total"]
                            self.current_progress["percentage"] = round((cur / tot) * 100, 1) if tot > 0 else 100.0
                            repaired = self.current_progress["cleaned_count"] + self.current_progress["removed_count"]
                            self.current_progress["cleaned_ratio"] = round((repaired / cur) * 100, 1) if cur > 0 else 0.0
                            self.current_progress["failed_ratio"] = round((self.current_progress["failed_count"] / cur) * 100, 1) if cur > 0 else 0.0

                        queue.task_done()

                workers = [asyncio.create_task(worker()) for _ in range(num_workers)]
                await asyncio.gather(*workers)

            cleaned = sum(1 for r in results if isinstance(r, dict) and r.get("verify_status") == "verified_clean")
            failed = sum(1 for r in results if isinstance(r, dict) and r.get("verify_status") == "verified_failed")
            removed = sum(1 for r in results if isinstance(r, dict) and r.get("verify_status") == "page_removed")
            errors = sum(1 for r in results if not isinstance(r, dict) or r.get("verify_status") == "error")

            duration = round((datetime.now() - t0).total_seconds(), 2)
            finish_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self.rollback_audit["last_audit_time"] = finish_str
            self.rollback_audit["next_audit_time"] = self._calculate_next_rollback_time(datetime.now())
            self.rollback_audit["last_stats"] = {
                "total_tested": len(remediated_items),
                "clean_preserved": cleaned,
                "rollback_detected": failed,
                "page_removed": removed,
                "error_count": errors,
                "duration_seconds": duration,
                "finished_at": finish_str
            }
            logger.info(f"Rollback audit cycle finished: tested={len(remediated_items)}, preserved={cleaned}, rollback_failed={failed}, removed={removed} in {duration}s")
        finally:
            self.rollback_audit["is_auditing"] = False
            self.is_checking = False
            self.current_progress["is_checking"] = False

