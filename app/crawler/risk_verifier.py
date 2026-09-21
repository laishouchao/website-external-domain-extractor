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
    remediation_id: int,
    client: Optional[httpx.AsyncClient] = None
) -> Dict[str, Any]:
    """
    Verify if a specific risk page still contains the offending external domain.
    Returns the verification verdict and updates the database record.
    """
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
            timeout=8.0,
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

    await asyncio.to_thread(
        crud.update_risk_remediation_verify_result,
        remediation_id=remediation_id,
        verify_status=verify_status,
        verify_time=now_str,
        verify_detail=verify_detail,
        context_snippet=new_snippet
    )

    return {
        "id": remediation_id,
        "page_url": page_url,
        "domain": target_domain,
        "verify_status": verify_status,
        "verify_time": now_str,
        "verify_detail": verify_detail
    }


class PeriodicRiskVerifier:
    """
    Background scheduler that periodically re-verifies pending risk pages (every 10 minutes).
    Supports manual trigger, progress monitoring, and concurrent HTTP requests.
    """
    _instance: Optional["PeriodicRiskVerifier"] = None

    def __init__(self, interval_seconds: int = 600):
        self.interval_seconds = interval_seconds
        self._running = False
        self._task: Optional[asyncio.Task] = None
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

    @classmethod
    def get_instance(cls) -> "PeriodicRiskVerifier":
        if cls._instance is None:
            cls._instance = PeriodicRiskVerifier(interval_seconds=600)
        return cls._instance

    def start(self):
        """Start the background verification loop."""
        if self._running:
            return
        self._running = True
        self._update_next_run_time()
        self._task = asyncio.create_task(self._run_loop())
        logger.info(f"PeriodicRiskVerifier started. Interval: {self.interval_seconds}s (10 min).")

    def stop(self):
        """Stop the background loop."""
        self._running = False
        self._trigger_event.set()
        if self._task and not self._task.done():
            self._task.cancel()
        logger.info("PeriodicRiskVerifier stopped.")

    def trigger_now(self) -> Dict[str, Any]:
        """Manually trigger an immediate verification cycle."""
        if self.is_checking:
            return {"status": "busy", "message": "校验任务已在执行中，请稍候"}
        self._trigger_event.set()
        return {"status": "triggered", "message": "已触发全量待复测风险页面校验"}

    def _update_next_run_time(self):
        next_dt = datetime.now() + timedelta(seconds=self.interval_seconds)
        self.next_run_time = next_dt.strftime("%Y-%m-%d %H:%M:%S")

    def get_status(self) -> Dict[str, Any]:
        remaining_seconds = 0
        if self.next_run_time:
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
            "last_run_stats": self.last_run_stats
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

            self._update_next_run_time()

            try:
                # Wait for interval or explicit trigger
                await asyncio.wait_for(self._trigger_event.wait(), timeout=self.interval_seconds)
                self._trigger_event.clear()
            except asyncio.TimeoutError:
                pass

    async def _run_verification_cycle(self):
        if self.is_checking:
            return
        self.is_checking = True
        t0 = datetime.now()
        self.last_run_time = t0.strftime("%Y-%m-%d %H:%M:%S")

        try:
            # Step 1: Lightweight sync from occurrences (run in worker thread)
            try:
                await asyncio.to_thread(crud.sync_risk_pages_from_occurrences)
            except Exception as e:
                logger.warning(f"Error syncing risk pages before verification: {e}")

            # Step 2: Fetch pending / failed items to verify (run in worker thread)
            pending_items = await asyncio.to_thread(crud.get_unverified_risk_remediations, 100)
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
                return

            semaphore = asyncio.Semaphore(8)  # max 8 concurrent requests
            limits = httpx.Limits(max_keepalive_connections=15, max_connections=20)
            async with httpx.AsyncClient(
                verify=False,
                timeout=8.0,
                limits=limits,
                follow_redirects=True,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 (RiskPageVerifier)"
                }
            ) as client:

                async def sem_worker(item):
                    async with semaphore:
                        return await verify_single_risk_page(item["id"], client=client)

                tasks = [asyncio.create_task(sem_worker(item)) for item in pending_items]
                results = await asyncio.gather(*tasks, return_exceptions=True)

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
