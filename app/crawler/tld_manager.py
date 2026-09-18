import re
from pathlib import Path
from typing import Set, Tuple, Optional

IANA_TLDS_FILE = Path(__file__).resolve().parent / 'iana_tlds.txt'

def load_iana_tlds() -> Set[str]:
    if IANA_TLDS_FILE.exists():
        try:
            content = IANA_TLDS_FILE.read_text(encoding='utf-8')
            tlds = {line.strip().lower() for line in content.splitlines() if line.strip() and not line.startswith('#')}
            if len(tlds) > 100:
                return tlds
        except Exception:
            pass
    return {'com', 'cn', 'net', 'org', 'edu', 'gov', 'io', 'cc', 'co', 'xyz', 'info'}

IANA_TLDS: Set[str] = load_iana_tlds()

FILE_EXTENSIONS_BLOCKLIST = {
    'js', 'css', 'png', 'jpg', 'jpeg', 'gif', 'svg', 'webp', 'ico', 'vue',
    'ts', 'jsx', 'tsx', 'py', 'java', 'c', 'cpp', 'h', 'cs', 'php', 'rb',
    'go', 'rs', 'sh', 'bat', 'cmd', 'ps1', 'json', 'xml', 'yaml', 'yml',
    'md', 'txt', 'pdf', 'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx', 'zip',
    'rar', '7z', 'tar', 'gz', 'mp3', 'mp4', 'avi', 'mov', 'wav', 'wasm',
    'map', 'woff', 'woff2', 'ttf', 'eot', 'swf', 'apk', 'ipa', 'dmg', 'exe',
    'do', 'action', 'jsp', 'asp', 'aspx', 'cgi', 'htm', 'html', 'shtml'
}

CODE_IDENTIFIERS_BLOCKLIST = {
    'window', 'document', 'console', 'location', 'history', 'navigator',
    'screen', 'event', 'math', 'json', 'date', 'array', 'object', 'string',
    'number', 'boolean', 'function', 'symbol', 'promise', 'regexp', 'error',
    'map', 'set', 'intl', 'reflect', 'proxy', 'webassembly', 'chrome',
    'obj', 'item', 'items', 'data', 'res', 'req', 'resp', 'err', 'msg',
    'node', 'element', 'elem', 'el', 'vm', 'ctx', 'this', 'self', 'parent',
    'top', 'sub', 'pub', 'btn', 'form', 'page', 'query', 'result', 'target',
    'source', 'dest', 'val', 'value', 'key', 'name', 'type', 'index', 'idx',
    'count', 'total', 'len', 'length', 'size', 'config', 'options', 'opts',
    'params', 'args', 'param', 'arg', 'props', 'prop', 'state', 'view',
    'model', 'app', 'user', 'info', 'text', 'html', 'body', 'header', 'footer',
    'title', 'content', 'url', 'uri', 'path', 'href', 'src', 'route', 'routes',
    'action', 'method', 'status', 'code', 'temp', 'tmp', 'util', 'utils',
    'helper', 'helpers', 'myplayer', 'player', 'video', 'video1', 'audio', 'image', 'input',
    'win', 'doc', 'pub-title', 'obju0', 'intbro', 'show', 'style', 'time', 'id',
    'e', 't', 'i', 'v', 'k', 'p', 'n', 's', 'm', 'd', 'c', 'b', 'a', 'x', 'y', 'z',
    'var', 'let', 'const', 'return', 'typeof', 'instanceof', 'delete', 'void',
    'null', 'undefined', 'true', 'false', 'nan', 'default', 'import', 'export'
}

DICTIONARY_OR_BRAND_TLDS = {
    'open', 'target', 'play', 'click', 'next', 'now', 'total', 'data',
    'name', 'chrome', 'top', 'do', 'to', 'mp', 'post', 'tab', 'help',
    'link', 'work', 'live', 'page', 'call', 'show', 'like', 'auto', 'car',
    'pub', 'bar', 'movie', 'date', 'review', 'id'
}

def is_iana_tld(tld: str) -> bool:
    if not tld:
        return False
    return tld.lower().strip('.') in IANA_TLDS

def is_valid_domain_syntax(domain: str) -> bool:
    if not domain or len(domain) > 253 or '.' not in domain:
        return False
    parts = domain.split('.')
    if len(parts) < 2:
        return False
    for p in parts:
        if not p or len(p) > 63 or p.startswith('-') or p.endswith('-'):
            return False
        if not re.match(r'^[a-zA-Z0-9-]+$', p):
            return False
    return True

def validate_extracted_domain(domain: str, is_from_url: bool = False) -> bool:
    if not domain:
        return False
    d = domain.strip().lower().rstrip('.')
    if not is_valid_domain_syntax(d):
        return False

    parts = d.split('.')
    tld = parts[-1]

    # 1. Must end in an official international root domain (IANA TLD)
    if not is_iana_tld(tld):
        return False

    # 2. Cannot end in a file/action extension
    if tld in FILE_EXTENSIONS_BLOCKLIST:
        return False

    # 3. If extracted from naked text/code (not part of http/https/href URL)
    if not is_from_url:
        if len(parts) == 2:
            first_label = parts[0]
            if first_label in CODE_IDENTIFIERS_BLOCKLIST and tld in DICTIONARY_OR_BRAND_TLDS:
                return False
            if tld in DICTIONARY_OR_BRAND_TLDS and len(first_label) <= 3:
                return False
        elif len(parts) >= 3:
            root_label = parts[-2]
            if root_label in CODE_IDENTIFIERS_BLOCKLIST and tld in DICTIONARY_OR_BRAND_TLDS:
                return False

    return True