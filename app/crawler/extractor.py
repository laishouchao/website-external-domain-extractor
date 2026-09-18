import re
import html
from functools import lru_cache
from urllib.parse import urlparse, urljoin, urldefrag, parse_qsl, unquote
from typing import Dict, List, Set, Tuple, Optional
import tldextract
from bs4 import BeautifulSoup, Comment
from app.crawler.tld_manager import (
    is_iana_tld,
    validate_extracted_domain,
    FILE_EXTENSIONS_BLOCKLIST,
    CODE_IDENTIFIERS_BLOCKLIST
)

# Detect ultra-fast C parser backends (selectolax Lexbor C engine & lxml)
try:
    from selectolax.parser import HTMLParser as SelectolaxParser
    HAVE_SELECTOLAX = True
except ImportError:
    SelectolaxParser = None
    HAVE_SELECTOLAX = False

try:
    import lxml
    HTML_PARSER_BACKEND = 'lxml'
except ImportError:
    HTML_PARSER_BACKEND = 'html.parser'

HTML_COMMENT_REGEX = re.compile(r'<!--(.*?)-->', re.DOTALL)

# Initialize tldextract
_extractor = tldextract.TLDExtract(cache_dir=False)

# Regex to find HTTP/HTTPS and protocol-relative URLs in raw text/scripts/comments
URL_REGEX = re.compile(
    r'(?:https?:)?//([a-zA-Z0-9][-a-zA-Z0-9]*(?:\.[a-zA-Z0-9][-a-zA-Z0-9]*)+)(?::\d+)?(?:/[^\s"\'<>{}|\\^`\[\]]*)?',
    re.IGNORECASE
)

# Regex to find naked domain names in text (e.g. www.partner.org, cdn.api.io, service.net)
# Avoids matching within code expressions, paths, or chained properties
NAKED_DOMAIN_REGEX = re.compile(
    r'(?<![a-zA-Z0-9_\-/.])([a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)*\.[a-zA-Z]{2,24})(?::\d+)?(?![a-zA-Z0-9_\-])',
    re.IGNORECASE
)

# Regex for JavaScript string literals and comments to avoid parsing code syntax as domains
JS_STRING_COMMENT_REGEX = re.compile(
    r'/\*[\s\S]*?\*/|//[^\r\n]*|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|`(?:\\.|[^`\\])*`'
)

# Domain validation regex
VALID_DOMAIN_REGEX = re.compile(
    r'^[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)+$'
)

# IPv4 regex to exclude pure IPs from domains
IPV4_REGEX = re.compile(r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$')

# CSS url(...) and @import regex
CSS_URL_REGEX = re.compile(r'url\(\s*[\'"]?([^\'")]+)[\'"]?\s*\)', re.IGNORECASE)
CSS_IMPORT_REGEX = re.compile(r'@import\s+[\'"]([^\'"]+)[\'"]', re.IGNORECASE)

# Meta refresh regex
META_REFRESH_REGEX = re.compile(r'url\s*=\s*[\'"]?([^\'";\s]+)', re.IGNORECASE)

# JavaScript navigation and API endpoints regex
JS_NAV_REGEX = re.compile(r"""(?:window\.)?(?:location(?:\.href|\.assign|\.replace)?|open)\s*\(?\s*['"]([^'"]+)['"]""", re.IGNORECASE)
JS_FETCH_REGEX = re.compile(r"""(?:fetch|\$\.(?:get|post|ajax)|axios(?:\.get|\.post)?)\s*\(\s*['"]([^'"]+)['"]""", re.IGNORECASE)
JS_API_PROP_REGEX = re.compile(r"""(?:url|path|endpoint|baseURL|apiUrl|targetUrl)\s*:\s*['"]([^'"]+)['"]""", re.IGNORECASE)

# Extensions that are binary files, attachments, media, documents, or fonts and cannot contain crawlable HTML links
NON_HTML_EXTENSIONS = {
    # Documents & Office
    '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx', '.odt', '.rtf', '.wps',
    # Archives & Installers
    '.zip', '.rar', '.7z', '.tar', '.gz', '.bz2', '.iso', '.apk', '.exe', '.dmg', '.msi', '.pkg',
    # Media: Video & Audio
    '.mp4', '.mp3', '.avi', '.flv', '.mkv', '.mov', '.wmv', '.wav', '.ogg', '.webm', '.m4a',
    # Images (images don't contain HTML links)
    '.png', '.jpg', '.jpeg', '.gif', '.bmp', '.svg', '.webp', '.ico', '.tiff', '.psd',
    # Fonts
    '.woff', '.woff2', '.ttf', '.eot', '.otf',
    # Static CSS/JS assets (handled by asset scanner, not HTML page crawler)
    '.css', '.js'
}

def is_crawlable_html_url(url: str) -> bool:
    """Check whether a URL is likely an HTML webpage and not a binary file or download attachment."""
    if not url:
        return False
    try:
        parsed = urlparse(url)
        path = parsed.path.lower()
        
        # 1. Check file extension in path
        dot_idx = path.rfind('.')
        if dot_idx != -1:
            ext = path[dot_idx:]
            if ext in NON_HTML_EXTENSIONS:
                return False
                
        # 2. Check attachment download indicators in path and query
        if "download" in path or "downloadattach" in path:
            return False
            
        if parsed.query:
            q_lower = parsed.query.lower()
            if "downloadattach" in q_lower or "download.jsp" in path or "urltype=news.download" in q_lower:
                return False
                
        return True
    except Exception:
        return False


@lru_cache(maxsize=16384)
def clean_domain(raw: str) -> Optional[str]:
    """Clean and validate a domain string with LRU caching."""
    if not raw:
        return None
    d = raw.strip().lower()
    # Strip protocol prefix if accidentally included
    if "://" in d:
        d = d.split("://", 1)[1]
    # Strip port, path, query, fragment
    d = d.split("/")[0].split("?")[0].split("#")[0].split(":")[0]
    d = d.strip(". ")
    if not d:
        return None
    # Check invalid patterns
    if ".." in d or d.startswith("-") or d.endswith("-"):
        return None
    if IPV4_REGEX.match(d):
        return None
    if d in ('localhost', 'example.com', 'example.org', 'test.com'):
        return None
    if not VALID_DOMAIN_REGEX.match(d):
        return None
    return d


@lru_cache(maxsize=16384)
def extract_domain_parts(domain: str, is_from_url: bool = False) -> Tuple[Optional[str], Optional[str]]:
    """
    Extract (fqdn, root_domain) using tldextract with LRU caching.
    Validates against official IANA Root Zone TLD list and blocks pseudo-domains.
    Returns (None, None) if not a valid public domain.
    """
    cleaned = clean_domain(domain)
    if not cleaned:
        return None, None

    if not validate_extracted_domain(cleaned, is_from_url=is_from_url):
        return None, None

    res = _extractor(cleaned)
    if not res.domain or not res.suffix:
        return None, None

    # Verify that the suffix ends in a valid IANA TLD
    last_suffix = res.suffix.split('.')[-1].lower()
    if not is_iana_tld(last_suffix):
        return None, None

    # Check against file extension blocklist
    if res.suffix.lower() in FILE_EXTENSIONS_BLOCKLIST or last_suffix in FILE_EXTENSIONS_BLOCKLIST:
        return None, None

    root_domain = f"{res.domain}.{res.suffix}".lower()
    fqdn = cleaned.lower()
    return fqdn, root_domain


def make_snippet(text: str, target: str, max_len: int = 120) -> str:
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


class PageExtractor:
    def __init__(self, target_url: str, config: Optional[dict] = None):
        self.target_url = target_url
        self.config = config or {}
        
        parsed = urlparse(target_url)
        self.target_scheme = parsed.scheme or "http"
        self.target_host = (parsed.hostname or "").lower()
        
        # Target root domain
        target_res = _extractor(self.target_host)
        if target_res.domain and target_res.suffix:
            self.target_root_domain = f"{target_res.domain}.{target_res.suffix}".lower()
        else:
            self.target_root_domain = self.target_host

        # Scope mode: 'root_domain' (all subdomains are internal) or 'exact_host' (only identical host is internal)
        self.scope_mode = self.config.get("scope_mode", "root_domain")
        self.extract_assets = self.config.get("extract_assets", True)
        self.extract_text = self.config.get("extract_text", True)

    def is_internal(self, host_or_domain: str) -> bool:
        """Determine if a host/domain belongs to the target site (internal)."""
        if not host_or_domain:
            return True
        h = host_or_domain.lower().split(":")[0].strip()
        if self.scope_mode == "exact_host":
            return h == self.target_host
        else:
            # root_domain mode: same root domain is internal
            res = _extractor(h)
            if res.domain and res.suffix:
                root = f"{res.domain}.{res.suffix}".lower()
                return root == self.target_root_domain
            return h == self.target_host or h.endswith(f".{self.target_host}")

    def is_subdomain(self, host_or_domain: str) -> bool:
        """Determine if a host/domain belongs to the target site's root domain (i.e. is a subdomain of target)."""
        if not host_or_domain:
            return False
        cleaned = clean_domain(host_or_domain)
        if not cleaned:
            return False
        fqdn, root = extract_domain_parts(cleaned, is_from_url=True)
        if not fqdn or not root:
            return False
        return root == self.target_root_domain


    def normalize_link(self, base_url: str, raw_link: str) -> Optional[str]:
        """
        Normalize and resolve relative or domain-omitted link.
        Handles:
        - Absolute paths: '/path/to/page'
        - Relative paths: './page', '../page', 'sub/page'
        - Query-only paths: '?sort=desc'
        - Protocol-relative URLs: '//cdn.example.com/asset.js'
        - Strips default ports (:80, :443) and URL fragments (#hash)
        Returns None if invalid or unsupported protocol.
        """
        if not raw_link:
            return None
        link = raw_link.strip()
        if not link or link.startswith(('#', 'javascript:', 'mailto:', 'tel:', 'data:', 'vbscript:', 'sms:')):
            return None

        try:
            full_url = urljoin(base_url, link)
            url_no_frag, _ = urldefrag(full_url)
            parsed = urlparse(url_no_frag)
            if parsed.scheme not in ('http', 'https'):
                return None
            
            # Normalize default ports and empty path
            netloc = parsed.netloc
            if (parsed.scheme == 'http' and netloc.endswith(':80')) or (parsed.scheme == 'https' and netloc.endswith(':443')):
                netloc = netloc.rsplit(':', 1)[0]
            
            path = parsed.path or "/"
            query = f"?{parsed.query}" if parsed.query else ""
            return f"{parsed.scheme}://{netloc}{path}{query}"
        except Exception:
            return None

    def extract(self, current_page_url: str, html_content: str) -> dict:
        """
        Parse an HTML page:
        1. Extract page title and <base href="...">
        2. Extract internal links (including absolute paths & domain-omitted paths)
        3. Extract target subdomains & external domains from link attributes and query parameters
        4. Extract target subdomains & external domains from plain text, scripts, and comments
        5. Extract internal and external paths from JavaScript code blocks
        """
        if HAVE_SELECTOLAX:
            try:
                return self._extract_with_selectolax(current_page_url, html_content)
            except Exception:
                pass

        return self._extract_with_bs4(current_page_url, html_content)

    def _extract_with_selectolax(self, current_page_url: str, html_content: str) -> dict:
        discovered_internal_urls: Set[str] = set()
        discovered_assets: List[Dict[str, str]] = []
        external_domains_map: Dict[str, dict] = {}
        discovered_subdomains_map: Dict[str, dict] = {}
        occurrences: List[dict] = []
        occ_counts_by_domain: Dict[str, int] = {}

        tree = SelectolaxParser(html_content)

        # 1. Page Title & Base Href Resolution
        title_node = tree.css_first('title')
        title = title_node.text(strip=True) if title_node else ''

        effective_base = current_page_url
        base_tag = tree.css_first('base[href]')
        if base_tag:
            raw_base = base_tag.attributes.get('href', '').strip()
            if raw_base:
                resolved_base = urljoin(current_page_url, raw_base)
                if urlparse(resolved_base).scheme in ('http', 'https'):
                    effective_base = resolved_base

        def record_external_domain(domain: str, root_domain: str, source_type: str, raw_match: str, context: str, is_link: bool):
            if domain not in external_domains_map:
                external_domains_map[domain] = {
                    "domain": domain,
                    "root_domain": root_domain,
                    "count": 0,
                    "has_link": False,
                    "has_text": False,
                    "sample_page_url": current_page_url
                }
            external_domains_map[domain]["count"] += 1
            if is_link:
                external_domains_map[domain]["has_link"] = True
            else:
                external_domains_map[domain]["has_text"] = True

            domain_occ_count = occ_counts_by_domain.get(domain, 0)
            if domain_occ_count < 5:
                occ_counts_by_domain[domain] = domain_occ_count + 1
                occurrences.append({
                    "domain": domain,
                    "page_url": current_page_url,
                    "source_type": source_type,
                    "raw_match": raw_match,
                    "context_snippet": make_snippet(context, raw_match)
                })

        def record_subdomain(subdomain: str, root_domain: str, source_type: str, raw_match: str, context: str, is_link: bool):
            if subdomain not in discovered_subdomains_map:
                discovered_subdomains_map[subdomain] = {
                    "subdomain": subdomain,
                    "root_domain": root_domain,
                    "count": 0,
                    "has_link": False,
                    "has_text": False,
                    "sample_page_url": current_page_url
                }
            discovered_subdomains_map[subdomain]["count"] += 1
            if is_link:
                discovered_subdomains_map[subdomain]["has_link"] = True
            else:
                discovered_subdomains_map[subdomain]["has_text"] = True

            sub_occ_count = occ_counts_by_domain.get(subdomain, 0)
            if sub_occ_count < 5:
                occ_counts_by_domain[subdomain] = sub_occ_count + 1
                occurrences.append({
                    "domain": subdomain,
                    "page_url": current_page_url,
                    "source_type": source_type,
                    "raw_match": raw_match,
                    "context_snippet": make_snippet(context, raw_match)
                })

        cur_host = (urlparse(current_page_url).hostname or "").lower()
        if self.is_subdomain(cur_host):
            c_fqdn, c_root = extract_domain_parts(cur_host, is_from_url=True)
            if c_fqdn and c_root:
                record_subdomain(c_fqdn, c_root, "page_host", cur_host, current_page_url, is_link=True)

        def inspect_query_parameters(normalized_url: str, context_str: str):
            try:
                parsed = urlparse(normalized_url)
                if not parsed.query:
                    return
                for _, val in parse_qsl(parsed.query, keep_blank_values=False):
                    if not val or len(val) < 4:
                        continue
                    unquoted = unquote(val).strip()
                    if unquoted.startswith(('http://', 'https://', '//')):
                        h = urlparse(unquoted if not unquoted.startswith('//') else 'http:' + unquoted).hostname
                        if h:
                            fqdn, root = extract_domain_parts(h, is_from_url=True)
                            if fqdn and root:
                                if self.is_subdomain(fqdn):
                                    record_subdomain(fqdn, root, "query_param_url", unquoted, context_str, is_link=True)
                                elif not self.is_internal(fqdn):
                                    record_external_domain(fqdn, root, "query_param_url", unquoted, context_str, is_link=True)
                    elif '.' in unquoted and '/' not in unquoted:
                        fqdn, root = extract_domain_parts(unquoted, is_from_url=False)
                        if fqdn and root:
                            if self.is_subdomain(fqdn):
                                record_subdomain(fqdn, root, "query_param_domain", unquoted, context_str, is_link=False)
                            elif not self.is_internal(fqdn):
                                record_external_domain(fqdn, root, "query_param_domain", unquoted, context_str, is_link=False)
            except Exception:
                pass

        # 2. Extract from Links
        for node in tree.css('a[href], area[href]'):
            href = node.attributes.get('href')
            if not href:
                continue
            normalized = self.normalize_link(effective_base, href)
            if not normalized:
                continue

            tag_str = None
            def get_snippet():
                nonlocal tag_str
                if tag_str is None:
                    tag_str = (node.html or '')[:200]
                return tag_str

            parsed = urlparse(normalized)
            host = (parsed.hostname or "").lower()
            if self.is_subdomain(host):
                fqdn, root_domain = extract_domain_parts(host, is_from_url=True)
                if fqdn and root_domain:
                    record_subdomain(fqdn, root_domain, "link_href", href, get_snippet(), is_link=True)

            if self.is_internal(host) and is_crawlable_html_url(normalized):
                discovered_internal_urls.add(normalized)
            else:
                fqdn, root_domain = extract_domain_parts(host, is_from_url=True)
                if fqdn and root_domain:
                    record_external_domain(fqdn, root_domain, "link_href", href, get_snippet(), is_link=True)

            if parsed.query:
                inspect_query_parameters(normalized, get_snippet())

        # Meta refresh
        for meta in tree.css('meta[http-equiv]'):
            if meta.attributes.get('http-equiv', '').lower() == 'refresh':
                content = meta.attributes.get('content', '')
                m = META_REFRESH_REGEX.search(content)
                if m:
                    redirect_url = m.group(1).strip()
                    normalized = self.normalize_link(effective_base, redirect_url)
                    if normalized:
                        h = urlparse(normalized).hostname or ""
                        if self.is_subdomain(h):
                            fqdn, root = extract_domain_parts(h, is_from_url=True)
                            if fqdn and root:
                                record_subdomain(fqdn, root, "meta_refresh", redirect_url, (meta.html or '')[:200], is_link=True)
                        if self.is_internal(h) and is_crawlable_html_url(normalized):
                            discovered_internal_urls.add(normalized)
                        else:
                            fqdn, root = extract_domain_parts(h, is_from_url=True)
                            if fqdn and root:
                                record_external_domain(fqdn, root, "meta_refresh", redirect_url, (meta.html or '')[:200], is_link=True)

        # Canonical
        canonical_tag = tree.css_first('link[rel*=canonical]')
        if canonical_tag and canonical_tag.attributes.get('href'):
            can_norm = self.normalize_link(effective_base, canonical_tag.attributes['href'])
            if can_norm:
                can_host = urlparse(can_norm).hostname or ""
                if self.is_subdomain(can_host):
                    fqdn, root = extract_domain_parts(can_host, is_from_url=True)
                    if fqdn and root:
                        record_subdomain(fqdn, root, "canonical", canonical_tag.attributes['href'], (canonical_tag.html or '')[:200], is_link=True)
                if self.is_internal(can_host) and is_crawlable_html_url(can_norm):
                    discovered_internal_urls.add(can_norm)

        # Assets
        if self.extract_assets:
            asset_selectors = [
                ('img', ['src', 'data-src', 'data-original']),
                ('script', ['src']),
                ('link', ['href']),
                ('iframe, frame', ['src']),
                ('video, audio, source, track', ['src']),
                ('form', ['action']),
                ('object', ['data']),
                ('embed', ['src']),
            ]
            for sel, attrs in asset_selectors:
                for node in tree.css(sel):
                    for attr in attrs:
                        val = node.attributes.get(attr)
                        if not val or not isinstance(val, str):
                            continue
                        normalized = self.normalize_link(effective_base, val)
                        if not normalized:
                            continue

                        tag_str = None
                        def get_asset_snippet():
                            nonlocal tag_str
                            if tag_str is None:
                                tag_str = (node.html or '')[:200]
                            return tag_str

                        parsed = urlparse(normalized)
                        host = (parsed.hostname or "").lower()
                        if self.is_subdomain(host):
                            fqdn, root_domain = extract_domain_parts(host, is_from_url=True)
                            if fqdn and root_domain:
                                record_subdomain(fqdn, root_domain, f"link_{attr}", val, get_asset_snippet(), is_link=True)

                        if not self.is_internal(host):
                            fqdn, root_domain = extract_domain_parts(host, is_from_url=True)
                            if fqdn and root_domain:
                                record_external_domain(fqdn, root_domain, f"link_{attr}", val, get_asset_snippet(), is_link=True)
                        else:
                            clean_url_path = parsed.path.lower()
                            if node.tag == 'script' and attr == 'src':
                                discovered_assets.append({"url": normalized, "type": "js"})
                            elif node.tag == 'link':
                                rel = str(node.attributes.get('rel', '')).lower()
                                if 'stylesheet' in rel or clean_url_path.endswith('.css'):
                                    discovered_assets.append({"url": normalized, "type": "css"})
                                elif clean_url_path.endswith('.js'):
                                    discovered_assets.append({"url": normalized, "type": "js"})
                            elif node.tag in ('form', 'iframe', 'frame') and is_crawlable_html_url(normalized):
                                discovered_internal_urls.add(normalized)

                        if parsed.query:
                            inspect_query_parameters(normalized, get_asset_snippet())

            # CSS url(...) in style tags
            for style_tag in tree.css('style'):
                style_content = style_tag.text() or ''
                for match in CSS_URL_REGEX.finditer(style_content):
                    raw_url = match.group(1).strip()
                    norm = self.normalize_link(effective_base, raw_url)
                    if norm:
                        h = urlparse(norm).hostname or ""
                        if self.is_subdomain(h):
                            fqdn, root = extract_domain_parts(h, is_from_url=True)
                            if fqdn and root:
                                record_subdomain(fqdn, root, "css_url", raw_url, match.group(0), is_link=True)
                        if not self.is_internal(h):
                            fqdn, root = extract_domain_parts(h, is_from_url=True)
                            if fqdn and root:
                                record_external_domain(fqdn, root, "css_url", raw_url, match.group(0), is_link=True)
                        elif norm.endswith('.css'):
                            discovered_assets.append({"url": norm, "type": "css"})

        # 3. Text Extraction
        if self.extract_text:
            # Comments
            for match in HTML_COMMENT_REGEX.finditer(html_content):
                c_text = match.group(1)
                self._extract_domains_from_text(c_text, "comment", record_external_domain, record_subdomain)

            # Inline scripts
            for s in tree.css('script:not([src])'):
                s_text = s.text()
                if s_text:
                    self._extract_from_script(s_text, effective_base, discovered_internal_urls, record_external_domain, record_subdomain)

            # Plain text
            tree.strip_tags(['script', 'style', 'noscript', 'svg'])
            body_node = tree.body
            if body_node:
                body_text = body_node.text(separator=' ')
                self._extract_domains_from_text(body_text, "plain_text", record_external_domain, record_subdomain)

        return {
            "title": title,
            "internal_urls": list(discovered_internal_urls),
            "discovered_assets": discovered_assets,
            "external_domains": list(external_domains_map.values()),
            "discovered_subdomains": list(discovered_subdomains_map.values()),
            "occurrences": occurrences
        }

    def _extract_with_bs4(self, current_page_url: str, html_content: str) -> dict:
        discovered_internal_urls: Set[str] = set()
        discovered_assets: List[Dict[str, str]] = []
        external_domains_map: Dict[str, dict] = {}
        discovered_subdomains_map: Dict[str, dict] = {}
        occurrences: List[dict] = []
        occ_counts_by_domain: Dict[str, int] = {}

        # Parse with BeautifulSoup (lxml / html.parser)
        soup = BeautifulSoup(html_content, HTML_PARSER_BACKEND)

        # 1. Page Title & Base Href Resolution
        title = ""
        if soup.title and soup.title.string:
            title = soup.title.string.strip()

        # Handle <base href="..."> tag if present
        effective_base = current_page_url
        base_tag = soup.find('base', href=True)
        if base_tag and base_tag.get('href'):
            raw_base = base_tag['href'].strip()
            resolved_base = urljoin(current_page_url, raw_base)
            if urlparse(resolved_base).scheme in ('http', 'https'):
                effective_base = resolved_base

        def record_external_domain(domain: str, root_domain: str, source_type: str, raw_match: str, context: str, is_link: bool):
            if domain not in external_domains_map:
                external_domains_map[domain] = {
                    "domain": domain,
                    "root_domain": root_domain,
                    "count": 0,
                    "has_link": False,
                    "has_text": False,
                    "sample_page_url": current_page_url
                }
            external_domains_map[domain]["count"] += 1
            if is_link:
                external_domains_map[domain]["has_link"] = True
            else:
                external_domains_map[domain]["has_text"] = True

            # O(1) occurrence counting per domain per page
            domain_occ_count = occ_counts_by_domain.get(domain, 0)
            if domain_occ_count < 5:
                occ_counts_by_domain[domain] = domain_occ_count + 1
                occurrences.append({
                    "domain": domain,
                    "page_url": current_page_url,
                    "source_type": source_type,
                    "raw_match": raw_match,
                    "context_snippet": make_snippet(context, raw_match)
                })

        def record_subdomain(subdomain: str, root_domain: str, source_type: str, raw_match: str, context: str, is_link: bool):
            if subdomain not in discovered_subdomains_map:
                discovered_subdomains_map[subdomain] = {
                    "subdomain": subdomain,
                    "root_domain": root_domain,
                    "count": 0,
                    "has_link": False,
                    "has_text": False,
                    "sample_page_url": current_page_url
                }
            discovered_subdomains_map[subdomain]["count"] += 1
            if is_link:
                discovered_subdomains_map[subdomain]["has_link"] = True
            else:
                discovered_subdomains_map[subdomain]["has_text"] = True

            # O(1) occurrence counting per subdomain per page
            sub_occ_count = occ_counts_by_domain.get(subdomain, 0)
            if sub_occ_count < 5:
                occ_counts_by_domain[subdomain] = sub_occ_count + 1
                occurrences.append({
                    "domain": subdomain,
                    "page_url": current_page_url,
                    "source_type": source_type,
                    "raw_match": raw_match,
                    "context_snippet": make_snippet(context, raw_match)
                })

        # Record current page host as discovered subdomain if matching target root
        cur_host = (urlparse(current_page_url).hostname or "").lower()
        if self.is_subdomain(cur_host):
            c_fqdn, c_root = extract_domain_parts(cur_host, is_from_url=True)
            if c_fqdn and c_root:
                record_subdomain(c_fqdn, c_root, "page_host", cur_host, current_page_url, is_link=True)

        def inspect_query_parameters(normalized_url: str, context_str: str):
            """
            Check query parameters for embedded external URLs or internal subdomains.
            E.g. /redirect?target=https%3A%2F%2Fother.com or ?to=http://api.target.com
            """
            try:
                parsed = urlparse(normalized_url)
                if not parsed.query:
                    return
                for _, val in parse_qsl(parsed.query, keep_blank_values=False):
                    if not val or len(val) < 4:
                        continue
                    unquoted = unquote(val).strip()
                    # Check if parameter value is a URL or domain
                    if unquoted.startswith(('http://', 'https://', '//')):
                        h = urlparse(unquoted if not unquoted.startswith('//') else 'http:' + unquoted).hostname
                        if h:
                            fqdn, root = extract_domain_parts(h, is_from_url=True)
                            if fqdn and root:
                                if self.is_subdomain(fqdn):
                                    record_subdomain(fqdn, root, "query_param_url", unquoted, context_str, is_link=True)
                                elif not self.is_internal(fqdn):
                                    record_external_domain(fqdn, root, "query_param_url", unquoted, context_str, is_link=True)
                    elif '.' in unquoted and '/' not in unquoted:
                        # Might be naked domain in param: ?domain=foo.com
                        fqdn, root = extract_domain_parts(unquoted, is_from_url=False)
                        if fqdn and root:
                            if self.is_subdomain(fqdn):
                                record_subdomain(fqdn, root, "query_param_domain", unquoted, context_str, is_link=False)
                            elif not self.is_internal(fqdn):
                                record_external_domain(fqdn, root, "query_param_domain", unquoted, context_str, is_link=False)
            except Exception:
                pass

        # 2. Extract from HTML Link Attributes
        # <a> and <area>
        for tag in soup.find_all(['a', 'area']):
            href = tag.get('href')
            if not href:
                continue
            normalized = self.normalize_link(effective_base, href)
            if not normalized:
                continue
            
            tag_str = None
            def get_tag_snippet():
                nonlocal tag_str
                if tag_str is None:
                    tag_str = str(tag)[:200]
                return tag_str

            parsed = urlparse(normalized)
            host = (parsed.hostname or "").lower()
            if self.is_subdomain(host):
                fqdn, root_domain = extract_domain_parts(host, is_from_url=True)
                if fqdn and root_domain:
                    record_subdomain(fqdn, root_domain, "link_href", href, get_tag_snippet(), is_link=True)

            if self.is_internal(host) and is_crawlable_html_url(normalized):
                discovered_internal_urls.add(normalized)
            else:
                fqdn, root_domain = extract_domain_parts(host, is_from_url=True)
                if fqdn and root_domain:
                    record_external_domain(fqdn, root_domain, "link_href", href, get_tag_snippet(), is_link=True)

            # Check query parameters for embedded external targets (e.g. open redirectors)
            if parsed.query:
                inspect_query_parameters(normalized, get_tag_snippet())

        # Meta refresh tag: <meta http-equiv="refresh" content="5;url=/new-page">
        for meta in soup.find_all('meta'):
            if meta.get('http-equiv', '').lower() == 'refresh':
                content = meta.get('content', '')
                m = META_REFRESH_REGEX.search(content)
                if m:
                    redirect_url = m.group(1).strip()
                    normalized = self.normalize_link(effective_base, redirect_url)
                    if normalized:
                        h = urlparse(normalized).hostname or ""
                        if self.is_subdomain(h):
                            fqdn, root = extract_domain_parts(h, is_from_url=True)
                            if fqdn and root:
                                record_subdomain(fqdn, root, "meta_refresh", redirect_url, str(meta)[:200], is_link=True)
                        if self.is_internal(h) and is_crawlable_html_url(normalized):
                            discovered_internal_urls.add(normalized)
                        else:
                            fqdn, root = extract_domain_parts(h, is_from_url=True)
                            if fqdn and root:
                                record_external_domain(fqdn, root, "meta_refresh", redirect_url, str(meta)[:200], is_link=True)

        # Canonical tag: <link rel="canonical" href="...">
        canonical_tag = soup.find('link', rel=lambda r: r and 'canonical' in r.lower())
        if canonical_tag and canonical_tag.get('href'):
            can_norm = self.normalize_link(effective_base, canonical_tag['href'])
            if can_norm:
                can_host = urlparse(can_norm).hostname or ""
                if self.is_subdomain(can_host):
                    fqdn, root = extract_domain_parts(can_host, is_from_url=True)
                    if fqdn and root:
                        record_subdomain(fqdn, root, "canonical", canonical_tag['href'], str(canonical_tag)[:200], is_link=True)
                if self.is_internal(can_host) and is_crawlable_html_url(can_norm):
                    discovered_internal_urls.add(can_norm)

        # Asset tags: img, script, link, iframe, video, audio, source, form, object, embed
        if self.extract_assets:
            asset_specs = [
                (['img'], ['src', 'data-src', 'data-original']),
                (['script'], ['src']),
                (['link'], ['href']),
                (['iframe', 'frame'], ['src']),
                (['video', 'audio', 'source', 'track'], ['src']),
                (['form'], ['action']),
                (['object'], ['data']),
                (['embed'], ['src']),
            ]

            for tag_names, attrs in asset_specs:
                for tag in soup.find_all(tag_names):
                    for attr in attrs:
                        val = tag.get(attr)
                        if not val or not isinstance(val, str):
                            continue
                        normalized = self.normalize_link(effective_base, val)
                        if not normalized:
                            continue
                        tag_str = None
                        def get_asset_tag_snippet():
                            nonlocal tag_str
                            if tag_str is None:
                                tag_str = str(tag)[:200]
                            return tag_str

                        parsed = urlparse(normalized)
                        host = (parsed.hostname or "").lower()
                        if self.is_subdomain(host):
                            fqdn, root_domain = extract_domain_parts(host, is_from_url=True)
                            if fqdn and root_domain:
                                record_subdomain(fqdn, root_domain, f"link_{attr}", val, get_asset_tag_snippet(), is_link=True)

                        if not self.is_internal(host):
                            fqdn, root_domain = extract_domain_parts(host, is_from_url=True)
                            if fqdn and root_domain:
                                record_external_domain(fqdn, root_domain, f"link_{attr}", val, get_asset_tag_snippet(), is_link=True)
                        else:
                            # Internal asset discovery for deep scanning
                            clean_url_path = parsed.path.lower()
                            if tag.name == 'script' and attr == 'src':
                                discovered_assets.append({"url": normalized, "type": "js"})
                            elif tag.name == 'link':
                                rel = str(tag.get('rel', '')).lower()
                                if 'stylesheet' in rel or clean_url_path.endswith('.css'):
                                    discovered_assets.append({"url": normalized, "type": "css"})
                                elif clean_url_path.endswith('.js'):
                                    discovered_assets.append({"url": normalized, "type": "js"})
                            elif tag.name in ('form', 'iframe', 'frame') and is_crawlable_html_url(normalized):
                                discovered_internal_urls.add(normalized)

                        if parsed.query:
                            inspect_query_parameters(normalized, get_asset_tag_snippet())

            # CSS url(...) inside <style> tags and inline style attributes
            for style_tag in soup.find_all('style'):
                style_content = style_tag.get_text()
                for match in CSS_URL_REGEX.finditer(style_content):
                    raw_url = match.group(1).strip()
                    norm = self.normalize_link(effective_base, raw_url)
                    if norm:
                        h = urlparse(norm).hostname or ""
                        if self.is_subdomain(h):
                            fqdn, root = extract_domain_parts(h, is_from_url=True)
                            if fqdn and root:
                                record_subdomain(fqdn, root, "css_url", raw_url, match.group(0), is_link=True)
                        if not self.is_internal(h):
                            fqdn, root = extract_domain_parts(h, is_from_url=True)
                            if fqdn and root:
                                record_external_domain(fqdn, root, "css_url", raw_url, match.group(0), is_link=True)
                        elif norm.endswith('.css'):
                            discovered_assets.append({"url": norm, "type": "css"})

        # 3. Extract Non-Link Domains & JS-embedded paths
        if self.extract_text:
            # (a) HTML Comments
            comments = soup.find_all(string=lambda text: isinstance(text, Comment))
            for c in comments:
                c_text = str(c)
                self._extract_domains_from_text(c_text, "comment", record_external_domain, record_subdomain)

            # (b) Inline Scripts - Extract endpoints, navigation, and domains
            for s in soup.find_all('script'):
                if not s.get('src'):
                    s_text = s.get_text()
                    if s_text:
                        self._extract_from_script(s_text, effective_base, discovered_internal_urls, record_external_domain, record_subdomain)

            # (c) Plain text content (remove scripts/styles first)
            for hidden in soup(["script", "style", "noscript", "svg"]):
                hidden.extract()
            
            body_text = soup.get_text(separator=' ')
            self._extract_domains_from_text(body_text, "plain_text", record_external_domain, record_subdomain)

        return {
            "title": title,
            "internal_urls": list(discovered_internal_urls),
            "discovered_assets": discovered_assets,
            "external_domains": list(external_domains_map.values()),
            "discovered_subdomains": list(discovered_subdomains_map.values()),
            "occurrences": occurrences
        }

    def extract_from_asset(self, asset_url: str, asset_type: str, content: str) -> dict:
        """
        Deep-scan the content of a standalone JS or CSS file.
        Extracts:
        - Third-party APIs, endpoints, CDN links, and naked domains inside JS code
        - Target subdomains discovered inside code, endpoints, and comments
        - @import rules, font/image url(...) in CSS
        - Context snippets with exact code evidence
        """
        external_domains_map: Dict[str, dict] = {}
        discovered_subdomains_map: Dict[str, dict] = {}
        occurrences: List[dict] = []
        discovered_internal_urls: Set[str] = set()
        discovered_sub_assets: List[Dict[str, str]] = []

        def record_external_domain(domain: str, root_domain: str, source_type: str, raw_match: str, context: str, is_link: bool):
            if domain not in external_domains_map:
                external_domains_map[domain] = {
                    "domain": domain,
                    "root_domain": root_domain,
                    "count": 0,
                    "has_link": False,
                    "has_text": False,
                    "sample_page_url": asset_url
                }
            external_domains_map[domain]["count"] += 1
            if is_link:
                external_domains_map[domain]["has_link"] = True
            else:
                external_domains_map[domain]["has_text"] = True

            domain_occ_count = sum(1 for o in occurrences if o["domain"] == domain)
            if domain_occ_count < 5:
                occurrences.append({
                    "domain": domain,
                    "page_url": asset_url,
                    "source_type": source_type,
                    "raw_match": raw_match,
                    "context_snippet": make_snippet(context, raw_match)
                })

        def record_subdomain(subdomain: str, root_domain: str, source_type: str, raw_match: str, context: str, is_link: bool):
            if subdomain not in discovered_subdomains_map:
                discovered_subdomains_map[subdomain] = {
                    "subdomain": subdomain,
                    "root_domain": root_domain,
                    "count": 0,
                    "has_link": False,
                    "has_text": False,
                    "sample_page_url": asset_url
                }
            discovered_subdomains_map[subdomain]["count"] += 1
            if is_link:
                discovered_subdomains_map[subdomain]["has_link"] = True
            else:
                discovered_subdomains_map[subdomain]["has_text"] = True

            sub_occ_count = sum(1 for o in occurrences if o["domain"] == subdomain)
            if sub_occ_count < 5:
                occurrences.append({
                    "domain": subdomain,
                    "page_url": asset_url,
                    "source_type": source_type,
                    "raw_match": raw_match,
                    "context_snippet": make_snippet(context, raw_match)
                })

        if asset_type == 'js':
            # Scan script text (URLs, naked domains in string literals & comments, endpoints)
            self._extract_from_script(content, asset_url, discovered_internal_urls, record_external_domain, record_subdomain)

        elif asset_type == 'css':
            # 1. Parse @import in CSS
            for match in CSS_IMPORT_REGEX.finditer(content):
                target = match.group(1).strip()
                norm = self.normalize_link(asset_url, target)
                if norm:
                    h = urlparse(norm).hostname or ""
                    if self.is_subdomain(h):
                        fqdn, root = extract_domain_parts(h, is_from_url=True)
                        if fqdn and root:
                            record_subdomain(fqdn, root, "css_file_import", target, match.group(0), is_link=True)
                    if not self.is_internal(h):
                        fqdn, root = extract_domain_parts(h, is_from_url=True)
                        if fqdn and root:
                            record_external_domain(fqdn, root, "css_file_import", target, match.group(0), is_link=True)
                    else:
                        discovered_sub_assets.append({"url": norm, "type": "css"})

            # 2. Parse url(...) in CSS
            for match in CSS_URL_REGEX.finditer(content):
                target = match.group(1).strip()
                norm = self.normalize_link(asset_url, target)
                if norm:
                    h = urlparse(norm).hostname or ""
                    if self.is_subdomain(h):
                        fqdn, root = extract_domain_parts(h, is_from_url=True)
                        if fqdn and root:
                            record_subdomain(fqdn, root, "css_file_url", target, match.group(0), is_link=True)
                    if not self.is_internal(h):
                        fqdn, root = extract_domain_parts(h, is_from_url=True)
                        if fqdn and root:
                            record_external_domain(fqdn, root, "css_file_url", target, match.group(0), is_link=True)

            # 3. Raw text scan in CSS (comments, etc.)
            self._extract_domains_from_text(content, "css_file_text", record_external_domain, record_subdomain)

        return {
            "asset_url": asset_url,
            "asset_type": asset_type,
            "external_domains": list(external_domains_map.values()),
            "discovered_subdomains": list(discovered_subdomains_map.values()),
            "occurrences": occurrences,
            "discovered_internal_urls": list(discovered_internal_urls),
            "discovered_sub_assets": discovered_sub_assets
        }


    def _extract_from_script(self, script_text: str, effective_base: str,
                             discovered_internal_urls: Set[str], record_callback, record_subdomain_cb=None):
        """Extract both internal paths, target subdomains, and external URLs/domains from JavaScript code blocks."""
        # 1. In JavaScript, real domains ONLY appear in string literals, template literals, and comments.
        # Unquoted code tokens are member expressions/identifiers (e.g. window.open, e.target, video.play)
        for m in JS_STRING_COMMENT_REGEX.finditer(script_text):
            token = m.group(0)
            if (token.startswith('"') and token.endswith('"')) or \
               (token.startswith("'") and token.endswith("'")) or \
               (token.startswith('`') and token.endswith('`')):
                token_content = token[1:-1]
            elif token.startswith('//'):
                token_content = token[2:]
            elif token.startswith('/*') and token.endswith('*/'):
                token_content = token[2:-2]
            else:
                token_content = token

            if token_content and len(token_content) > 3:
                self._extract_domains_from_text(token_content, "script_code", record_callback, record_subdomain_cb)

        # 2. Extract potential paths and URLs from JS navigation & AJAX calls
        for regex in (JS_NAV_REGEX, JS_FETCH_REGEX, JS_API_PROP_REGEX):
            for match in regex.finditer(script_text):
                target = match.group(1).strip()
                if not target or target.startswith(('#', 'javascript:', 'data:', '{', '$')):
                    continue

                # If it's an absolute path, relative path, or full URL
                norm = self.normalize_link(effective_base, target)
                if norm:
                    h = urlparse(norm).hostname or ""
                    if self.is_subdomain(h):
                        fqdn, root = extract_domain_parts(h, is_from_url=True)
                        if fqdn and root and record_subdomain_cb:
                            record_subdomain_cb(fqdn, root, "script_endpoint", target, match.group(0), is_link=True)
                    if self.is_internal(h) and is_crawlable_html_url(norm):
                        discovered_internal_urls.add(norm)
                    else:
                        fqdn, root = extract_domain_parts(h, is_from_url=True)
                        if fqdn and root:
                            record_callback(fqdn, root, "script_endpoint", target, match.group(0), is_link=True)

    def _extract_domains_from_text(self, text: str, source_type: str, record_callback, record_subdomain_cb=None):
        """Extract domains from raw text content using URL and naked domain regex."""
        if not text or len(text.strip()) == 0:
            return

        # 1. Match full URLs (e.g. https://api.thirdparty.com/v1 or https://oa.target.com)
        for match in URL_REGEX.finditer(text):
            raw_host = match.group(1)
            full_match = match.group(0)
            fqdn, root = extract_domain_parts(raw_host, is_from_url=True)
            if fqdn and root:
                if self.is_subdomain(fqdn):
                    if record_subdomain_cb:
                        record_subdomain_cb(fqdn, root, source_type, full_match, text, is_link=False)
                elif not self.is_internal(fqdn):
                    record_callback(fqdn, root, source_type, full_match, text, is_link=False)

        # 2. Match naked domains (e.g. service.partner.org, cdn.aliyun.com, admin.target.com)
        for match in NAKED_DOMAIN_REGEX.finditer(text):
            raw_domain = match.group(1)
            full_match = match.group(0)
            
            # Avoid re-matching if this was part of an already matched URL
            start = match.start()
            if start > 7 and text[start-7:start].lower() in ('http://', 'https:/'):
                continue
            if start > 2 and text[start-2:start] == '//':
                continue

            # Check character immediately following the match (e.g. window.open(, style.top = 10)
            end_idx = match.end(1)
            if end_idx < len(text):
                next_char = text[end_idx]
                if next_char in ('(', '=', '[', '{', ';', '`', '<', '>'):
                    continue

            # Strip trailing slash or dot
            cleaned_domain = raw_domain.rstrip('.')
            
            # Additional safety: check if the suffix is in file extension blocklist
            parts = cleaned_domain.split('.')
            if len(parts) < 2:
                continue
            if parts[-1].lower() in FILE_EXTENSIONS_BLOCKLIST:
                continue

            fqdn, root = extract_domain_parts(cleaned_domain, is_from_url=False)
            if fqdn and root:
                if self.is_subdomain(fqdn):
                    if record_subdomain_cb:
                        record_subdomain_cb(fqdn, root, source_type, full_match, text, is_link=False)
                elif not self.is_internal(cleaned_domain):
                    record_callback(fqdn, root, source_type, full_match, text, is_link=False)

