"""
High-performance asynchronous domain reachability and DNS probe engine.
Two-stage pipeline:
1. Fast Async DNS Pre-resolution (dnspython / asyncio getaddrinfo)
   - Filters out NXDOMAIN dead domains in 10-30ms without making TCP/HTTP requests.
   - Detects private/reserved/loopback IPs (SSRF attack/misconfiguration prevention).
   - Extracts A/AAAA records and CNAME aliases.
2. Lightweight HTTP/HTTPS Reachability Probe (httpx.AsyncClient)
   - Follows redirects, captures final landing URL, detects cross-domain hops.
   - Short timeouts and SSL bypass.
"""

import time
import asyncio
import socket
import ipaddress
import urllib.parse
from typing import Dict, Any, List, Optional, Set
import httpx

try:
    import dns.asyncresolver
    import dns.resolver
    HAS_DNSPYTHON = True
except ImportError:
    HAS_DNSPYTHON = False


def is_private_ip(ip_str: str) -> bool:
    """
    判断 IP 是否为私网保留、环回、链路本地或未指定地址 (防范 SSRF 与内网扫描)
    """
    try:
        ip = ipaddress.ip_address(ip_str.strip())
        return (
            ip.is_private
            or ip.is_loopback
            or ip.is_reserved
            or ip.is_link_local
            or ip.is_unspecified
        )
    except ValueError:
        return False


class FastDomainProbeEngine:
    DEFAULT_NAMESERVERS = [
        "223.5.5.5",       # 阿里公共 DNS
        "223.6.6.6",       # 阿里备用 DNS
        "119.29.29.29",   # 腾讯 DNSPod
        "114.114.114.114",# 114 DNS
        "8.8.8.8"         # Google DNS
    ]

    def __init__(
        self,
        default_timeout: float = 2.5,
        dns_timeout: float = 1.2,
        enable_dns_probe: bool = True,
        nameservers: Optional[List[str]] = None,
        user_agent: Optional[str] = None
    ):
        self.default_timeout = default_timeout
        self.dns_timeout = dns_timeout
        self.enable_dns_probe = enable_dns_probe
        self.nameservers = nameservers or self.DEFAULT_NAMESERVERS
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

    def _extract_host(self, raw_target: str) -> str:
        t = raw_target.strip()
        if not t.startswith("http://") and not t.startswith("https://"):
            t = f"http://{t}"
        try:
            parsed = urllib.parse.urlsplit(t)
            host = parsed.hostname or parsed.netloc.split(":")[0]
        except Exception:
            host = t.split("/")[0].split(":")[0]
        return (host or raw_target).strip().rstrip(".").lower()

    async def resolve_dns(
        self,
        host: str,
        timeout: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        执行异步 DNS (nslookup) 预解析。
        支持 A、AAAA、CNAME 查询，检测 NXDOMAIN 及私网保留 IP。
        """
        t0 = time.time()
        eff_timeout = timeout or self.dns_timeout
        ips: Set[str] = set()
        cnames: Set[str] = set()

        # 1. 检查输入是否本身就是 IP 地址字面量
        try:
            ip_obj = ipaddress.ip_address(host)
            is_priv = (
                ip_obj.is_private
                or ip_obj.is_loopback
                or ip_obj.is_reserved
                or ip_obj.is_link_local
                or ip_obj.is_unspecified
            )
            return {
                "resolved": True,
                "ips": [host],
                "cnames": [],
                "is_private": is_priv,
                "error": None,
                "status": "PRIVATE_IP" if is_priv else "RESOLVED",
                "dns_elapsed_ms": int((time.time() - t0) * 1000)
            }
        except ValueError:
            pass

        # 2. 本地特殊保留主机名检测
        if host in ("localhost", "localhost.localdomain", "ip6-localhost", "ip6-loopback"):
            return {
                "resolved": True,
                "ips": ["127.0.0.1"],
                "cnames": [],
                "is_private": True,
                "error": None,
                "status": "PRIVATE_IP",
                "dns_elapsed_ms": int((time.time() - t0) * 1000)
            }

        # 国际化域名 (IDN) Punycode 转换 (如 清华大学.cn -> xn--...)
        host_query = host
        try:
            host_query = host.encode("idna").decode("ascii")
        except Exception:
            pass

        resolved_via_dnspython = False

        # 3. 优先使用 dnspython 异步解析器查询公共 DNS 矩阵
        if HAS_DNSPYTHON:
            try:
                resolver = dns.asyncresolver.Resolver()
                resolver.nameservers = self.nameservers
                resolver.lifetime = eff_timeout

                # 查询 A 记录 (IPv4)
                try:
                    a_answers = await resolver.resolve(host_query, "A")
                    for rdata in a_answers:
                        ips.add(rdata.to_text())
                    resolved_via_dnspython = True
                except dns.resolver.NXDOMAIN:
                    # 确定域名未注册或已注销
                    return {
                        "resolved": False,
                        "ips": [],
                        "cnames": [],
                        "is_private": False,
                        "error": "NXDOMAIN (域名不存在或已注销)",
                        "status": "NXDOMAIN",
                        "dns_elapsed_ms": int((time.time() - t0) * 1000)
                    }
                except (dns.resolver.NoAnswer, dns.resolver.NoNameservers):
                    pass
                except Exception:
                    pass

                # 查询 CNAME 别名
                try:
                    cname_answers = await resolver.resolve(host_query, "CNAME")
                    for c_data in cname_answers:
                        cnames.add(c_data.target.to_text().rstrip("."))
                except Exception:
                    pass

                # 若无 IPv4，尝试查询 AAAA 记录 (IPv6)
                if not ips:
                    try:
                        aaaa_answers = await resolver.resolve(host_query, "AAAA")
                        for rdata in aaaa_answers:
                            ips.add(rdata.to_text())
                        resolved_via_dnspython = True
                    except Exception:
                        pass

            except Exception:
                pass

        # 4. 降级容灾：标准库 asyncio getaddrinfo (利用系统底层 DNS 解析器)
        if not ips and not resolved_via_dnspython:
            try:
                loop = asyncio.get_running_loop()
                addrinfo = await asyncio.wait_for(
                    loop.getaddrinfo(host_query, None, proto=socket.IPPROTO_TCP),
                    timeout=eff_timeout
                )
                for item in addrinfo:
                    sockaddr = item[4]
                    if sockaddr and isinstance(sockaddr, tuple):
                        ips.add(sockaddr[0])
            except (socket.gaierror, asyncio.TimeoutError) as ge:
                err_text = str(ge)
                status = "TIMEOUT" if isinstance(ge, asyncio.TimeoutError) else "NXDOMAIN"
                return {
                    "resolved": False,
                    "ips": [],
                    "cnames": sorted(list(cnames)),
                    "is_private": False,
                    "error": f"DNS解析失败 ({err_text})",
                    "status": status,
                    "dns_elapsed_ms": int((time.time() - t0) * 1000)
                }
            except Exception as e:
                return {
                    "resolved": False,
                    "ips": [],
                    "cnames": sorted(list(cnames)),
                    "is_private": False,
                    "error": f"系统解析异常: {str(e)[:50]}",
                    "status": "ERROR",
                    "dns_elapsed_ms": int((time.time() - t0) * 1000)
                }

        if not ips:
            return {
                "resolved": False,
                "ips": [],
                "cnames": sorted(list(cnames)),
                "is_private": False,
                "error": "NoAnswer (无可用A/AAAA解析记录)",
                "status": "NO_ANSWER",
                "dns_elapsed_ms": int((time.time() - t0) * 1000)
            }

        # 检查是否解析到私网保留地址 (SSRF 检测)
        has_private = any(is_private_ip(ip) for ip in ips)

        return {
            "resolved": True,
            "ips": sorted(list(ips)),
            "cnames": sorted(list(cnames)),
            "is_private": has_private,
            "error": None,
            "status": "PRIVATE_IP" if has_private else "RESOLVED",
            "dns_elapsed_ms": int((time.time() - t0) * 1000)
        }

    async def probe_single(
        self,
        domain_or_url: str,
        timeout: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        对单目标执行“DNS 预解析 ➔ HTTP 探活”两段式极速检测。
        """
        start_time = time.time()
        eff_timeout = timeout or self.default_timeout
        norm_url = self._normalize_target(domain_or_url)
        hostname = self._extract_host(norm_url)

        dns_info: Dict[str, Any] = {
            "resolved": True,
            "ips": [],
            "cnames": [],
            "is_private": False,
            "status": "SKIPPED",
            "dns_elapsed_ms": 0
        }

        # ================= 阶段 1: 异步 DNS 极速预检 =================
        if self.enable_dns_probe:
            dns_info = await self.resolve_dns(hostname, timeout=self.dns_timeout)

            # 1. 域名未解析/已注销/NXDOMAIN -> 立即阻断，无需发起任何 HTTP 请求
            if not dns_info["resolved"]:
                return {
                    "domain": hostname,
                    "initial_url": norm_url,
                    "is_alive": False,
                    "stage": "dns_failed",
                    "status_code": None,
                    "final_url": norm_url,
                    "redirect_history": [],
                    "resolved_ips": [],
                    "cnames": dns_info.get("cnames", []),
                    "dns_status": dns_info.get("status", "NXDOMAIN"),
                    "is_private_ip": False,
                    "is_security_risk": False,
                    "error_reason": f"DNS预检失败 ({dns_info.get('error', 'NXDOMAIN')})",
                    "elapsed_ms": int((time.time() - start_time) * 1000)
                }

            # 2. 解析命中私网/保留地址 -> SSRF 高危阻断，切勿发起 HTTP 请求
            if dns_info["is_private"]:
                ips_str = ", ".join(dns_info["ips"])
                return {
                    "domain": hostname,
                    "initial_url": norm_url,
                    "is_alive": False,
                    "stage": "dns_blocked",
                    "status_code": None,
                    "final_url": norm_url,
                    "redirect_history": [],
                    "resolved_ips": dns_info["ips"],
                    "cnames": dns_info.get("cnames", []),
                    "dns_status": "PRIVATE_IP",
                    "is_private_ip": True,
                    "is_security_risk": True,
                    "error_reason": f"高危内网保留地址阻断 (SSRF: {ips_str})",
                    "elapsed_ms": int((time.time() - start_time) * 1000)
                }

        # ================= 阶段 2: HTTP/HTTPS 存活探活 =================
        headers = {
            "User-Agent": self.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Connection": "close"
        }

        parsed = urllib.parse.urlsplit(norm_url)
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
                    resp = await client.get(probe_url)
                    status_code = resp.status_code
                    final_url = str(resp.url)
                    redirect_history = [str(r.url) for r in resp.history]

                    elapsed_ms = int((time.time() - start_time) * 1000)
                    return {
                        "domain": hostname,
                        "initial_url": norm_url,
                        "is_alive": True,
                        "stage": "http_alive",
                        "status_code": status_code,
                        "final_url": final_url,
                        "redirect_history": redirect_history,
                        "resolved_ips": dns_info["ips"],
                        "cnames": dns_info.get("cnames", []),
                        "dns_status": dns_info.get("status", "RESOLVED"),
                        "is_private_ip": False,
                        "is_security_risk": False,
                        "error_reason": None,
                        "elapsed_ms": elapsed_ms
                    }
                except (httpx.ConnectTimeout, httpx.ReadTimeout, httpx.WriteTimeout, httpx.PoolTimeout) as te:
                    last_error = f"连接超时 ({te.__class__.__name__})"
                except httpx.ConnectError as ce:
                    err_msg = str(ce)
                    if "getaddrinfo failed" in err_msg or "Name or service not known" in err_msg or "11001" in err_msg:
                        last_error = "DNS解析失败 (域名不存在或已注销)"
                        break
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
            "stage": "http_failed",
            "status_code": status_code,
            "final_url": final_url,
            "redirect_history": redirect_history,
            "resolved_ips": dns_info["ips"],
            "cnames": dns_info.get("cnames", []),
            "dns_status": dns_info.get("status", "RESOLVED"),
            "is_private_ip": False,
            "is_security_risk": False,
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
        同时统计 DNS 拦截、死链与正常存活数据。
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
        dns_nxdomain_count = 0
        dns_private_count = 0
        http_dead_count = 0

        for item in targets:
            val = str(item.get(target_field) or item.get("domain") or item.get("url") or "")
            probe_info = results_map.get(val, {
                "domain": val,
                "is_alive": True,
                "stage": "skipped",
                "status_code": None,
                "resolved_ips": [],
                "cnames": [],
                "dns_status": "UNKNOWN",
                "is_private_ip": False,
                "is_security_risk": False,
                "error_reason": None,
                "elapsed_ms": 0
            })
            merged_item = dict(item)
            merged_item["probe_result"] = probe_info

            if probe_info.get("is_alive"):
                alive_tasks.append(merged_item)
            else:
                dead_tasks.append(merged_item)
                stage = probe_info.get("stage")
                if stage == "dns_failed":
                    dns_nxdomain_count += 1
                elif stage == "dns_blocked":
                    dns_private_count += 1
                else:
                    http_dead_count += 1

        return {
            "alive_tasks": alive_tasks,
            "dead_tasks": dead_tasks,
            "stats": {
                "total": len(targets),
                "alive_count": len(alive_tasks),
                "dead_count": len(dead_tasks),
                "dns_nxdomain_count": dns_nxdomain_count,
                "dns_private_ip_count": dns_private_count,
                "http_dead_count": http_dead_count
            }
        }
