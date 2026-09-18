import re
import json
import asyncio
import httpx
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Any

# Safe / trusted CDN, cloud vendors, and authority infrastructure roots
SAFE_CDN_ROOTS = {
    "cloudflare.com", "cdnjs.cloudflare.com", "jsdelivr.net", "unpkg.com",
    "bootcdn.net", "staticfile.org", "w3.org", "schema.org",
    "baidu.com", "bdstatic.com", "qq.com", "gtimg.com", "tencent.com",
    "aliyun.com", "aliyuncs.com", "alicdn.com", "taobao.com", "tmall.com",
    "google.com", "gstatic.com", "googleapis.com", "google-analytics.com", "googletagmanager.com",
    "microsoft.com", "apple.com", "github.com", "githubusercontent.com",
    "weibo.com", "sina.com.cn", "jd.com", "amazon.com", "amazonaws.com"
}

# Abuse-prone / free / throwaway TLDs often seen in spam/malware/throwaway campaigns
SUSPICIOUS_TLDS = {
    "tk", "ml", "ga", "cf", "gq", "top", "buzz", "work", "fit", "loan",
    "rest", "hair", "beauty", "click"
}

# Dynamic DNS and tunneling services
DDNS_TUNNEL_DOMAINS = {
    "ngrok.io", "ngrok-free.app", "duckdns.org", "ddns.net", "no-ip.org",
    "no-ip.com", "cpolar.top", "localtunnel.me", "serveo.net", "dynu.net",
    "hopto.org", "zapto.org"
}

IPV4_REGEX = re.compile(r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}(?::\d+)?$')
IPV6_REGEX = re.compile(r'^\[?[0-9a-fA-F:]+\]?(?::\d+)?$')


def match_intel_profile(domain: str, root_domain: str, profiles: List[dict]) -> Optional[dict]:
    """
    Match domain or root_domain against threat intelligence profiles.
    Order of precedence:
    1. Exact FQDN match
    2. Wildcard or root_domain match
    """
    domain_lower = domain.lower()
    root_lower = root_domain.lower()

    # Pass 1: exact match
    for p in profiles:
        target = p["domain"].lower().lstrip("*.")
        if p.get("match_type") == "exact":
            if domain_lower == target:
                return p
        else:
            if domain_lower == target:
                return p

    # Pass 2: root domain wildcard match
    for p in profiles:
        target = p["domain"].lower().lstrip("*.")
        if p.get("match_type") == "root" or p.get("match_type") == "wildcard":
            if root_lower == target or domain_lower == target or domain_lower.endswith(f".{target}"):
                return p

    return None


def evaluate_domain_risk(
    domain: str,
    root_domain: Optional[str] = None,
    profiles: Optional[List[dict]] = None,
    source_type: str = ""
) -> dict:
    """
    Evaluate domain risk level and tags based on intelligence profiles and heuristic rules.
    Returns:
    {
        "risk_level": "critical" | "high" | "medium" | "low" | "safe" | "pending",
        "risk_tags": ["..."],
        "risk_remark": "...",
        "risk_source": "intel_rule" | "builtin_rule" | "pending"
    }
    """
    dom = domain.lower().strip()
    if not root_domain:
        try:
            from app.crawler.extractor import extract_domain_parts
            _, extracted_root = extract_domain_parts(dom)
            root = extracted_root.lower().strip() if extracted_root else dom
        except Exception:
            root = dom
    else:
        root = root_domain.lower().strip()

    # If profiles not passed, load active profiles on demand
    if profiles is None:
        try:
            from app.db.crud import get_all_risk_profiles
            profiles = get_all_risk_profiles()
        except Exception:
            profiles = []

    # 1. Match against user intelligence base (Highest priority)
    if profiles:
        matched_profile = match_intel_profile(dom, root, profiles)
        if matched_profile:
            tags = matched_profile.get("tags") or []
            if isinstance(tags, str):
                try:
                    tags = json.loads(tags)
                except Exception:
                    tags = [tags] if tags else []
            
            category = matched_profile.get("category", "")
            if category and category not in tags:
                tags = [category] + tags

            return {
                "risk_level": matched_profile.get("risk_level", "high"),
                "risk_tags": tags,
                "risk_remark": matched_profile.get("remark") or f"命中预设风险情报: {matched_profile.get('domain')}",
                "risk_source": "intel_rule"
            }

    # 2. Heuristic Rule: Pure IP check (Medium risk)
    if IPV4_REGEX.match(dom) or (":" in dom and IPV6_REGEX.match(dom)):
        return {
            "risk_level": "medium",
            "risk_tags": ["纯IP外链"],
            "risk_remark": "外部直连裸IP地址，缺少标准域名解析，常见于测试接口或非标服务",
            "risk_source": "builtin_rule"
        }

    # 3. Heuristic Rule: Dynamic DNS / Tunneling service (Medium risk)
    for ddns in DDNS_TUNNEL_DOMAINS:
        if dom == ddns or dom.endswith(f".{ddns}"):
            return {
                "risk_level": "medium",
                "risk_tags": ["动态域名(DDNS)"],
                "risk_remark": f"动态DNS或内网穿透域名({ddns})，服务极不稳定且常用于隐蔽通道",
                "risk_source": "builtin_rule"
            }

    # 4. Heuristic Rule: Trusted safe CDN / Big Tech whitelist (Safe)
    if root in SAFE_CDN_ROOTS or dom in SAFE_CDN_ROOTS:
        return {
            "risk_level": "safe",
            "risk_tags": ["主流CDN/基础设施"],
            "risk_remark": "公认知名公共云、主流CDN或开源静态加速基础设施",
            "risk_source": "builtin_rule"
        }

    # 5. Heuristic Rule: Suspicious / Abuse-prone TLDs (Medium risk)
    tld = root.split(".")[-1].lower() if "." in root else ""
    if tld in SUSPICIOUS_TLDS:
        return {
            "risk_level": "medium",
            "risk_tags": ["易滥用顶级域"],
            "risk_remark": f"使用廉价或易滥用顶级域名(.{tld})，常见于黑灰产与批量注册站点",
            "risk_source": "builtin_rule"
        }

    # Default: Pending
    return {
        "risk_level": "pending",
        "risk_tags": [],
        "risk_remark": "",
        "risk_source": "pending"
    }


def make_context_snippet(text: str, target: str, max_len: int = 150) -> str:
    """Create a readable context snippet around the matched string."""
    idx = text.lower().find(target.lower())
    if idx == -1:
        return text[:max_len].strip()
    
    half = max_len // 2
    start = max(0, idx - half)
    end = min(len(text), idx + len(target) + half)
    snippet = text[start:end].replace("\n", " ").replace("\r", " ").strip()
    if start > 0:
        snippet = "..." + snippet
    if end < len(text):
        snippet = snippet + "..."
    return snippet


async def verify_page_for_domain(client: httpx.AsyncClient, url: str, domain: str) -> dict:
    """Check a single URL to see if target domain still exists in response."""
    start_time = asyncio.get_event_loop().time()
    try:
        resp = await client.get(url, timeout=10.0)
        elapsed_ms = int((asyncio.get_event_loop().time() - start_time) * 1000)
        
        if resp.status_code in (404, 410):
            return {
                "url": url,
                "status_code": resp.status_code,
                "status": "page_removed",
                "found": False,
                "snippet": f"页面返回 HTTP {resp.status_code}，原始涉险页面已彻底下线移除",
                "elapsed_ms": elapsed_ms
            }

        body_text = resp.text
        dom_lower = domain.lower()
        if dom_lower in body_text.lower():
            snippet = make_context_snippet(body_text, domain)
            return {
                "url": url,
                "status_code": resp.status_code,
                "status": "domain_still_present",
                "found": True,
                "snippet": snippet,
                "elapsed_ms": elapsed_ms
            }
        else:
            return {
                "url": url,
                "status_code": resp.status_code,
                "status": "domain_cleared",
                "found": False,
                "snippet": f"HTTP {resp.status_code} 正常响应，但在源码中未发现该域名代码",
                "elapsed_ms": elapsed_ms
            }
    except httpx.TimeoutException:
        return {
            "url": url,
            "status_code": 0,
            "status": "error",
            "found": None,
            "snippet": "请求超时（超过10秒未能获取响应）",
            "elapsed_ms": 10000
        }
    except Exception as e:
        return {
            "url": url,
            "status_code": 0,
            "status": "error",
            "found": None,
            "snippet": f"访问失败: {str(e)[:150]}",
            "elapsed_ms": int((asyncio.get_event_loop().time() - start_time) * 1000)
        }


async def verify_domain_remediation(domain: str, occurrence_urls: List[str]) -> dict:
    """
    Perform targeted asynchronous re-checks on all pages where the domain was originally spotted.
    Returns audit details and remediation verdict.
    """
    # Limit to at most 10 distinct URLs to avoid flooding
    unique_urls = list(dict.fromkeys(occurrence_urls))[:10]
    now_iso = datetime.now().isoformat()

    if not unique_urls:
        return {
            "verify_status": "unverified",
            "verify_time": now_iso,
            "summary": "未找到原始涉险页面 URL 记录，无法执行复测",
            "tested_count": 0,
            "details": []
        }

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ExternalDomainVerifier/2.0",
        "Accept": "*/*"
    }

    async with httpx.AsyncClient(headers=headers, verify=False, follow_redirects=True) as client:
        tasks = [verify_page_for_domain(client, url, domain) for url in unique_urls]
        results = await asyncio.gather(*tasks, return_exceptions=False)

    still_present_count = sum(1 for r in results if r["found"] is True)
    cleared_count = sum(1 for r in results if r["found"] is False)
    error_count = sum(1 for r in results if r["found"] is None)

    if still_present_count > 0:
        status = "verified_failed"
        summary = f"复测 {len(unique_urls)} 个历史页面，在 {still_present_count} 处仍检测到该外部域名代码，未完全清除！"
    elif cleared_count > 0:
        status = "verified_clean"
        summary = f"复测 {len(unique_urls)} 个历史页面，均已无该外部域名代码，确认修复已闭环！"
    else:
        status = "error"
        summary = f"复测 {len(unique_urls)} 个页面均访问超时或连接异常，请检查网络或目标服务状态。"

    return {
        "verify_status": status,
        "verify_time": now_iso,
        "summary": summary,
        "tested_count": len(unique_urls),
        "total_pages": len(unique_urls),
        "still_present_count": still_present_count,
        "remaining_pages": still_present_count,
        "cleared_count": cleared_count,
        "error_count": error_count,
        "details": results
    }
