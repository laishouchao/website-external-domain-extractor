"""
High-performance asynchronous domain reachability probe engine.
Uses httpx.AsyncClient with short timeouts and SSL bypass to rapidly detect
unreachable domains (DNS NXDOMAIN, timeout, refused connection) before Playwright emulation.
"""

import time
import asyncio
import urllib.parse
from typing import Dict, Any, List, Optional
import httpx


class FastDomainProbeEngine:
    def __init__(self, default_timeout: float = 2.5, user_agent: Optional[str] = None):
        self.default_timeout = default_timeout
        self.user_agent = user_agent or (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/126.0.0.0 Safari/537.36"
        )

    def _normalize_target(self, raw_target: str) -> str:
        t = raw_target.strip()
        if not t.startswith("http://") and not t.startswith("https://"):
            return f"https://{t}"
        return t

    async def probe_single(
        self,
        domain_or_url: str,
        timeout: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        对单目标执行极速探活检测。
        优先测试 HTTPS，若遇握手/连接异常则降级尝试 HTTP。
        """
        start_time = time.time()
        eff_timeout = timeout or self.default_timeout
        norm_url = self._normalize_target(domain_or_url)
        parsed = urllib.parse.urlparse(norm_url)
        hostname = parsed.hostname or domain_or_url.strip()

        headers = {
            "User-Agent": self.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Connection": "close"
        }

        # 依次尝试探测目标：如果是 https，失败可尝试 http
        urls_to_try = [norm_url]
        if norm_url.startswith("https://"):
            urls_to_try.append(f"http://{hostname}{parsed.path or '/'}")

        last_error = "未知网络错误"
        redirect_history = []
        final_url = norm_url
        status_code = None

        limits = httpx.Limits(max_keepalive_connections=0, max_connections=100)
        transport = httpx.AsyncHTTPTransport(verify=False, retries=0)

        async with httpx.AsyncClient(
            transport=transport,
            timeout=httpx.Timeout(eff_timeout, connect=eff_timeout),
            follow_redirects=True,
            headers=headers
        ) as client:
            for probe_url in urls_to_try:
                try:
                    # 使用 GET 请求（部分防爬 WAF 会阻断 HEAD）
                    resp = await client.get(probe_url)
                    status_code = resp.status_code
                    final_url = str(resp.url)
                    redirect_history = [str(r.url) for r in resp.history]

                    elapsed_ms = int((time.time() - start_time) * 1000)
                    return {
                        "domain": hostname,
                        "initial_url": norm_url,
                        "is_alive": True,
                        "status_code": status_code,
                        "final_url": final_url,
                        "redirect_history": redirect_history,
                        "error_reason": None,
                        "elapsed_ms": elapsed_ms
                    }
                except (httpx.ConnectTimeout, httpx.ReadTimeout, httpx.WriteTimeout, httpx.PoolTimeout) as te:
                    last_error = f"连接超时 ({te.__class__.__name__})"
                except httpx.ConnectError as ce:
                    err_msg = str(ce)
                    if "getaddrinfo failed" in err_msg or "Name or service not known" in err_msg or "11001" in err_msg:
                        last_error = "DNS解析失败 (域名不存在或已注销)"
                        break  # DNS 解析失败无需再试 HTTP
                    elif "actively refused" in err_msg or "10061" in err_msg:
                        last_error = "端口拒绝连接 (Connection Refused)"
                    elif "SSL" in err_msg or "certificate" in err_msg:
                        last_error = "SSL证书握手异常"
                    else:
                        last_error = f"网络连接拒绝: {err_msg[:60]}"
                except Exception as e:
                    last_error = f"网络探测异常: {str(e)[:60]}"

        elapsed_ms = int((time.time() - start_time) * 1000)
        return {
            "domain": hostname,
            "initial_url": norm_url,
            "is_alive": False,
            "status_code": status_code,
            "final_url": final_url,
            "redirect_history": redirect_history,
            "error_reason": last_error,
            "elapsed_ms": elapsed_ms
        }

    async def probe_batch(
        self,
        targets: List[Dict[str, Any]],
        target_field: str = "domain",
        max_concurrency: int = 30,
        timeout: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        并发批量快速探活：
        将传入的任务列表拆分为 alive_tasks 与 dead_tasks 两个集合。
        """
        sem = asyncio.Semaphore(max_concurrency)
        results_map: Dict[str, Dict[str, Any]] = {}

        async def _probe_worker(item: Dict[str, Any]):
            val = item.get(target_field) or item.get("domain") or item.get("url")
            if not val:
                return
            async with sem:
                res = await self.probe_single(str(val), timeout=timeout)
                results_map[str(val)] = res

        tasks = [_probe_worker(item) for item in targets]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

        alive_tasks = []
        dead_tasks = []

        for item in targets:
            val = str(item.get(target_field) or item.get("domain") or item.get("url") or "")
            probe_info = results_map.get(val, {
                "domain": val,
                "is_alive": True,
                "status_code": None,
                "error_reason": None,
                "elapsed_ms": 0
            })
            merged_item = dict(item)
            merged_item["probe_result"] = probe_info

            if probe_info.get("is_alive"):
                alive_tasks.append(merged_item)
            else:
                dead_tasks.append(merged_item)

        return {
            "alive_tasks": alive_tasks,
            "dead_tasks": dead_tasks,
            "stats": {
                "total": len(targets),
                "alive_count": len(alive_tasks),
                "dead_count": len(dead_tasks),
            }
        }
