"""
Web Compliance Checker - Fast DNS & HTTP Prober
Ultra-lightweight pre-flight probe:
- 10ms DNS resolution & SSRF intranet blocklist check
- Fast HTTP probe for dead-link & 404 filtering
"""

import ipaddress
import socket
import logging
from typing import Dict, Any, Optional
import urllib3
import requests

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
logger = logging.getLogger("compliance_checker.prober")

PRIVATE_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
]

def check_ip_ssrf(ip_str: str) -> bool:
    """Return True if IP is private/loopback/reserved (SSRF risk)."""
    try:
        ip = ipaddress.ip_address(ip_str)
        for net in PRIVATE_NETWORKS:
            if ip in net:
                return True
        return False
    except ValueError:
        return False

def resolve_dns(domain: str, timeout: float = 1.2) -> Dict[str, Any]:
    """Resolve domain to IP with SSRF protection."""
    clean_domain = domain.strip().lower()
    if clean_domain.startswith("http://"):
        clean_domain = clean_domain[7:].split("/")[0]
    elif clean_domain.startswith("https://"):
        clean_domain = clean_domain[8:].split("/")[0]
    if ":" in clean_domain:
        clean_domain = clean_domain.split(":")[0]

    try:
        old_timeout = socket.getdefaulttimeout()
        socket.setdefaulttimeout(timeout)
        try:
            addr_info = socket.getaddrinfo(clean_domain, None)
        finally:
            socket.setdefaulttimeout(old_timeout)

        ips = list({res[4][0] for res in addr_info})
        primary_ip = ips[0] if ips else ""

        # Check for SSRF
        for ip in ips:
            if check_ip_ssrf(ip):
                return {
                    "resolved": True,
                    "ip": ip,
                    "ips": ips,
                    "is_ssrf": True,
                    "error": f"SSRF阻断: 命中私有/保留IP ({ip})"
                }

        return {
            "resolved": True,
            "ip": primary_ip,
            "ips": ips,
            "is_ssrf": False,
            "error": None
        }
    except socket.gaierror:
        return {
            "resolved": False,
            "ip": "",
            "ips": [],
            "is_ssrf": False,
            "error": "NXDOMAIN (域名无解析记录/已过期)"
        }
    except Exception as e:
        return {
            "resolved": False,
            "ip": "",
            "ips": [],
            "is_ssrf": False,
            "error": f"DNS解析超时或失败: {e}"
        }

def probe_domain(
    domain: str,
    dns_timeout: float = 1.2,
    http_timeout: float = 2.5
) -> Dict[str, Any]:
    """Fast pre-flight check combining DNS and HTTP probe."""
    clean_domain = domain.strip().lower()
    if clean_domain.startswith("http://") or clean_domain.startswith("https://"):
        url = clean_domain
        host = clean_domain.split("://")[1].split("/")[0].split(":")[0]
    else:
        url = f"https://{clean_domain}"
        host = clean_domain.split("/")[0].split(":")[0]

    # Step 1: DNS & SSRF check
    dns_res = resolve_dns(host, timeout=dns_timeout)
    if not dns_res["resolved"]:
        return {
            "alive": False,
            "domain": host,
            "url": url,
            "http_status": None,
            "dns": dns_res,
            "is_ssrf": False,
            "is_404": False,
            "dead_reason": "NXDOMAIN (未解析)",
        }

    if dns_res.get("is_ssrf"):
        return {
            "alive": False,
            "domain": host,
            "url": url,
            "http_status": None,
            "dns": dns_res,
            "is_ssrf": True,
            "is_404": False,
            "dead_reason": "SSRF_BLOCKED",
        }

    # Step 2: Fast HTTP Probe
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }

    status_code = None
    final_url = url
    is_404 = False

    # Try HTTPS first, then HTTP fallback
    for scheme in ["https://", "http://"]:
        target_url = f"{scheme}{host}"
        try:
            resp = requests.get(target_url, headers=headers, timeout=http_timeout, verify=False, allow_redirects=True)
            status_code = resp.status_code
            final_url = resp.url
            body_sample = resp.text[:1500].lower() if resp.text else ""
            if status_code in [404, 410] or "404 not found" in body_sample or "页面不存在" in body_sample or "<title>404" in body_sample:
                is_404 = True
            break
        except Exception:
            continue

    if status_code is None:
        return {
            "alive": False,
            "domain": host,
            "url": url,
            "http_status": None,
            "dns": dns_res,
            "is_ssrf": False,
            "is_404": False,
            "dead_reason": "HTTP连接超时/不可达",
        }

    return {
        "alive": True,
        "domain": host,
        "url": final_url,
        "http_status": status_code,
        "dns": dns_res,
        "is_ssrf": False,
        "is_404": is_404,
        "dead_reason": None,
    }
