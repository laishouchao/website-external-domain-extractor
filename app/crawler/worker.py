import re
import time
import xml.etree.ElementTree as ET
from urllib.parse import urlparse, urljoin
from typing import Optional, Tuple, List, Set
import httpx

# Fast regex to strip XML namespaces for easier XPath
NAMESPACE_REGEX = re.compile(r'xmlns(:\w+)?="[^"]*"')

class FetchResult:
    def __init__(self, url: str, status_code: int = 0, content_type: str = "",
                 html: str = "", response_time_ms: int = 0, error: Optional[str] = None):
        self.url = url
        self.status_code = status_code
        self.content_type = content_type
        self.html = html
        self.response_time_ms = response_time_ms
        self.error = error

    @property
    def is_html(self) -> bool:
        return "text/html" in self.content_type or "application/xhtml" in self.content_type

    @property
    def is_js(self) -> bool:
        url_path = urlparse(self.url).path.lower()
        return "javascript" in self.content_type or "ecmascript" in self.content_type or url_path.endswith('.js')

    @property
    def is_css(self) -> bool:
        url_path = urlparse(self.url).path.lower()
        return "text/css" in self.content_type or url_path.endswith('.css')


def make_timeout(t: float) -> httpx.Timeout:
    """Create fine-grained timeout preventing hanging sockets on dead or throttled sub-servers."""
    base_t = float(t) if t and t > 0 else 10.0
    read_t = min(7.0, max(2.0, base_t))
    connect_t = min(4.0, max(1.5, base_t / 2))
    return httpx.Timeout(timeout=base_t, connect=connect_t, read=read_t, write=4.0, pool=4.0)


async def fetch_page(client: httpx.AsyncClient, url: str, timeout: float = 10.0) -> FetchResult:
    """Fetch a single URL asynchronously directly in-memory (HTML, JS, CSS) without saving to disk."""
    start = time.perf_counter()
    httpx_timeout = make_timeout(timeout)
    try:
        resp = await client.get(url, timeout=httpx_timeout, follow_redirects=True)
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        
        content_type = resp.headers.get("content-type", "").lower()
        url_path = urlparse(str(resp.url)).path.lower()

        # Decode text directly in memory for HTML, JS, CSS, XML, plain text
        html_text = ""
        is_text_content = (
            "text/" in content_type or
            "javascript" in content_type or
            "ecmascript" in content_type or
            "xml" in content_type or
            "json" in content_type or
            url_path.endswith(('.html', '.htm', '.js', '.css', '.xml', '.txt', '.shtml', '.do', '.action', '.jsp', '.asp', '.php')) or
            not content_type
        )
        if is_text_content:
            html_text = resp.text

        return FetchResult(
            url=str(resp.url),
            status_code=resp.status_code,
            content_type=content_type,
            html=html_text,
            response_time_ms=elapsed_ms
        )
    except httpx.TimeoutException:
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        return FetchResult(url=url, status_code=0, response_time_ms=elapsed_ms, error="Request Timeout")
    except httpx.ConnectError:
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        return FetchResult(url=url, status_code=0, response_time_ms=elapsed_ms, error="Connection Failed")
    except httpx.HTTPStatusError as e:
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        return FetchResult(url=url, status_code=e.response.status_code, response_time_ms=elapsed_ms, error=f"HTTP {e.response.status_code}")
    except Exception as e:
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        return FetchResult(url=url, status_code=0, response_time_ms=elapsed_ms, error=str(e)[:200])


async def fetch_asset_content(client: httpx.AsyncClient, url: str, timeout: float = 10.0, max_size_bytes: int = 3 * 1024 * 1024) -> FetchResult:
    """
    Fetch static text asset (.js or .css) with content-length guard directly in-memory.
    Returns FetchResult with response metrics.
    """
    start = time.perf_counter()
    httpx_timeout = make_timeout(timeout)
    try:
        resp = await client.get(url, timeout=httpx_timeout, follow_redirects=True)
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        content_type = resp.headers.get("content-type", "").lower()

        if resp.status_code != 200:
            return FetchResult(url=str(resp.url), status_code=resp.status_code, content_type=content_type, response_time_ms=elapsed_ms, error=f"HTTP {resp.status_code}")

        # Check size header
        cl = resp.headers.get("content-length")
        if cl and int(cl) > max_size_bytes:
            return FetchResult(url=str(resp.url), status_code=resp.status_code, content_type=content_type, response_time_ms=elapsed_ms, error="Asset exceeds max size limit")

        if len(resp.content) > max_size_bytes:
            return FetchResult(url=str(resp.url), status_code=resp.status_code, content_type=content_type, response_time_ms=elapsed_ms, error="Asset exceeds max size limit")

        return FetchResult(url=str(resp.url), status_code=resp.status_code, content_type=content_type, html=resp.text, response_time_ms=elapsed_ms)
    except httpx.TimeoutException:
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        return FetchResult(url=url, status_code=0, response_time_ms=elapsed_ms, error="Request Timeout")
    except httpx.ConnectError:
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        return FetchResult(url=url, status_code=0, response_time_ms=elapsed_ms, error="Connection Failed")
    except httpx.HTTPStatusError as e:
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        return FetchResult(url=url, status_code=e.response.status_code, response_time_ms=elapsed_ms, error=f"HTTP {e.response.status_code}")
    except Exception as e:
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        return FetchResult(url=url, status_code=0, response_time_ms=elapsed_ms, error=str(e)[:200])



async def discover_sitemap_urls(client: httpx.AsyncClient, base_url: str, timeout: float = 10.0) -> Set[str]:
    """
    Attempt to discover URLs from /robots.txt and /sitemap.xml.
    Returns a set of discovered absolute URLs.
    """
    discovered_urls: Set[str] = set()
    sitemap_candidates: List[str] = [
        urljoin(base_url, "/sitemap.xml"),
        urljoin(base_url, "/sitemap_index.xml"),
    ]

    # 1. Try robots.txt
    try:
        robots_url = urljoin(base_url, "/robots.txt")
        resp = await client.get(robots_url, timeout=make_timeout(timeout), follow_redirects=True)
        if resp.status_code == 200:
            for line in resp.text.splitlines():
                if line.lower().strip().startswith("sitemap:"):
                    parts = line.split(":", 1)
                    if len(parts) == 2:
                        sm_url = parts[1].strip()
                        if sm_url:
                            sitemap_candidates.append(sm_url)
    except Exception:
        pass

    # Deduplicate candidates
    seen_sitemaps = set()
    for sm_url in sitemap_candidates:
        if sm_url in seen_sitemaps:
            continue
        seen_sitemaps.add(sm_url)

        try:
            resp = await client.get(sm_url, timeout=timeout, follow_redirects=True)
            if resp.status_code != 200 or not resp.text:
                continue

            xml_clean = NAMESPACE_REGEX.sub("", resp.text)
            try:
                root = ET.fromstring(xml_clean)
            except Exception:
                continue

            # Check if this is a sitemapindex pointing to more sitemaps
            for sitemap_node in root.findall(".//sitemap/loc"):
                if sitemap_node.text and sitemap_node.text.strip():
                    child_sm = sitemap_node.text.strip()
                    if child_sm not in seen_sitemaps:
                        sitemap_candidates.append(child_sm)

            # Check if this is a standard urlset
            for loc_node in root.findall(".//url/loc"):
                if loc_node.text and loc_node.text.strip():
                    discovered_urls.add(loc_node.text.strip())

        except Exception:
            continue

    return discovered_urls
