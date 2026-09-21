import re
import json
import asyncio
import httpx
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Any

# Safe / trusted CDN, cloud vendors, and authority infrastructure roots
SAFE_CDN_ROOTS = {
    # Public CDNs & Libraries
    "cloudflare.com", "cdnjs.cloudflare.com", "jsdelivr.net", "jsdelivr.com", "unpkg.com",
    "bootcdn.net", "staticfile.org", "w3.org", "schema.org", "bootstrapcdn.com",
    "fontawesome.com", "jquery.com", "polyfill.io", "cdnjs.com",
    # Mainstream Cloud & Big Tech
    "baidu.com", "bdstatic.com", "qq.com", "gtimg.com", "tencent.com",
    "aliyun.com", "aliyuncs.com", "alicdn.com", "taobao.com", "tmall.com",
    "google.com", "gstatic.com", "googleapis.com", "google-analytics.com", "googletagmanager.com",
    "microsoft.com", "apple.com", "github.com", "githubusercontent.com",
    "weibo.com", "sina.com.cn", "jd.com", "amazon.com", "amazonaws.com",
    "huaweicloud.com", "myhuaweicloud.com", "volcengine.com", "volccdn.com",
    "qiniu.com", "qiniucdn.com", "upyun.com", "bytedance.com", "douyin.com",
    # Official compliance & authority services in China
    "miit.gov.cn", "beian.miit.gov.cn", "conac.cn", "bszs.conac.cn",
    "12377.cn", "12321.cn", "mps.gov.cn", "gov.cn"
}


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


def is_safe_whitelist_domain(dom: str, root: str) -> bool:
    """Check if a domain or root belongs to the safe whitelist."""
    if root in SAFE_CDN_ROOTS or dom in SAFE_CDN_ROOTS:
        return True
    if any(dom == s or dom.endswith(f".{s}") or root == s or root.endswith(f".{s}") for s in SAFE_CDN_ROOTS):
        return True
    if dom.endswith(".gov.cn") or root.endswith(".gov.cn") or dom.endswith(".edu.cn") or root.endswith(".edu.cn"):
        return True
    return False


def evaluate_domain_risk(
    domain: str,
    root_domain: Optional[str] = None,
    profiles: Optional[List[dict]] = None,
    source_type: str = ""
) -> dict:
    """
    Evaluate domain risk level and tags based on intelligence profiles and heuristic rules.
    Per user requirement:
    - 智能规则初筛只研判安全白名单域名（safe 🟢）。
    - 命中预置情报库的域名按情报库级别评定（intel_rule）。
    - 其他所有域名一律保持待研判（pending ⚪），不自动判为中高危.
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

    # 1. Match against user threat intelligence base (Highest priority)
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

    # 2. Heuristic Rule: Only evaluate Safe Whitelist / Public CDN / Official domains
    if is_safe_whitelist_domain(dom, root):
        return {
            "risk_level": "safe",
            "risk_tags": ["主流CDN/白名单"],
            "risk_remark": "公认知名公共云、主流CDN或官方合规基础设施",
            "risk_source": "builtin_rule"
        }

    # 3. All others remain pending (待研判状态)
    return {
        "risk_level": "pending",
        "risk_tags": [],
        "risk_remark": "",
        "risk_source": "pending"
    }


def make_context_snippet(text: str, target: str, max_len: int = 150) -> str:
    """Extract a snippet of text surrounding the target domain."""
    idx = text.lower().find(target.lower())
    if idx == -1:
        return text[:max_len]
    start = max(0, idx - 40)
    end = min(len(text), idx + len(target) + 60)
    snippet = text[start:end].replace("\r", " ").replace("\n", " ")
    if start > 0:
        snippet = "..." + snippet
    if end < len(text):
        snippet = snippet + "..."
    return snippet


async def verify_page_for_domain(client: httpx.AsyncClient, url: str, domain: str) -> dict:
    """Check a single URL to see if target domain still exists in response."""
    start_time = asyncio.get_event_loop().time()
    req_url = url.strip()
    if not req_url.startswith(("http://", "https://")):
        req_url = "http://" + req_url.lstrip("/")
    try:
        resp = await client.get(req_url, timeout=10.0)
        elapsed_ms = int((asyncio.get_event_loop().time() - start_time) * 1000)
        
        if resp.status_code in (404, 410):
            return {
                "url": req_url,
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
                "url": req_url,
                "status_code": resp.status_code,
                "status": "domain_still_present",
                "found": True,
                "snippet": snippet,
                "elapsed_ms": elapsed_ms
            }
        else:
            return {
                "url": req_url,
                "status_code": resp.status_code,
                "status": "domain_cleared",
                "found": False,
                "snippet": f"HTTP {resp.status_code} 正常响应，但在源码中未发现该域名代码",
                "elapsed_ms": elapsed_ms
            }
    except httpx.TimeoutException:
        return {
            "url": req_url,
            "status_code": 0,
            "status": "error",
            "found": None,
            "snippet": "请求超时（超过10秒未能获取响应）",
            "elapsed_ms": 10000
        }
    except Exception as e:
        return {
            "url": req_url,
            "status_code": 0,
            "status": "error",
            "found": None,
            "snippet": f"访问失败: {str(e)[:150]}",
            "elapsed_ms": int((asyncio.get_event_loop().time() - start_time) * 1000)
        }


async def verify_domain_remediation(domain: str, occurrence_urls: List[str], max_urls: Optional[int] = None) -> dict:
    """
    Perform targeted asynchronous re-checks on all pages where the domain was originally spotted.
    Returns audit details and remediation verdict.
    """
    unique_urls = [u for u in dict.fromkeys(occurrence_urls) if u and u.strip()]
    if max_urls:
        unique_urls = unique_urls[:max_urls]
    now_iso = datetime.now().isoformat()

    if not unique_urls:
        return {
            "verify_status": "unverified",
            "verify_time": now_iso,
            "summary": "未找到原始涉险页面 URL 记录，无法执行复测",
            "tested_count": 0,
            "total_pages": 0,
            "still_present_count": 0,
            "remaining_pages": 0,
            "cleared_count": 0,
            "error_count": 0,
            "details": []
        }

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ExternalDomainVerifier/2.0",
        "Accept": "*/*"
    }

    sem = asyncio.Semaphore(30)

    async def sem_verify(client, url):
        async with sem:
            return await verify_page_for_domain(client, url, domain)

    limits = httpx.Limits(max_keepalive_connections=50, max_connections=100)
    async with httpx.AsyncClient(headers=headers, limits=limits, verify=False, follow_redirects=True, timeout=10.0) as client:
        tasks = [sem_verify(client, url) for url in unique_urls]
        results = await asyncio.gather(*tasks, return_exceptions=False)

    still_present_count = sum(1 for r in results if r["found"] is True)
    cleared_count = sum(1 for r in results if r["found"] is False)
    error_count = sum(1 for r in results if r["found"] is None)

    if still_present_count > 0:
        status = "verified_failed"
        summary = f"复测全量 {len(unique_urls)} 个历史页面，在 {still_present_count} 处仍检测到该外部域名代码，未完全清除！"
    elif cleared_count > 0:
        status = "verified_clean"
        summary = f"复测全量 {len(unique_urls)} 个历史页面，均已无该外部域名代码，确认修复已闭环！"
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
        "details": results[:200] if len(results) > 200 else results
    }
