from app.crawler.tld_manager import is_iana_tld, validate_extracted_domain, IANA_TLDS
from app.crawler.extractor import extract_domain_parts, PageExtractor

def test_iana_tlds_loaded():
    assert len(IANA_TLDS) >= 1400
    assert is_iana_tld('com')
    assert is_iana_tld('cn')
    assert is_iana_tld('net')
    assert is_iana_tld('org')
    assert is_iana_tld('gov')
    assert is_iana_tld('io')
    assert is_iana_tld('top')
    assert not is_iana_tld('invalidfake')
    assert not is_iana_tld('local')
    assert not is_iana_tld('test12345')

def test_validate_extracted_domain_legitimate():
    legit_domains = [
        'www.baidu.com',
        'api.github.com',
        'zj.gov.cn',
        'aliyun.com',
        'cdn.jsdelivr.net',
        'cloud.google.com',
        'cool.xyz',
        'example.org',
        'partner.io',
        'domain.co.uk'
    ]
    for d in legit_domains:
        is_valid = validate_extracted_domain(d, is_from_url=False)
        assert is_valid, f"Expected legitimate domain {d} to be valid"

def test_validate_extracted_domain_pseudo_code():
    pseudo_domains = [
        'window.open',
        'e.target',
        'obj.click',
        'video.play',
        'video1.play',
        'item.now',
        'res.mp',
        'read.do',
        'index.do',
        'style.top',
        'ad.style.top',
        'obju0.style.top',
        'pub-title.pub',
        'win.open',
        'obj.target',
        'time.to',
        'query.page.total',
        'page.next',
        'intbro.chrome',
        'window.name',
        'e.data',
        'myplayer.play',
        'this.state.open',
        'array.prototype.map.call',
        'foo.fakeinvalidtld'
    ]
    for d in pseudo_domains:
        is_valid = validate_extracted_domain(d, is_from_url=False)
        assert not is_valid, f"Expected pseudo-domain {d} to be blocked"

def test_extract_domain_parts():
    fqdn, root = extract_domain_parts('api.thirdparty.com', is_from_url=False)
    assert fqdn == 'api.thirdparty.com'
    assert root == 'thirdparty.com'

    for pseudo in ['window.open', 'e.target', 'video.play', 'style.top', 'read.do']:
        fqdn, root = extract_domain_parts(pseudo, is_from_url=False)
        assert fqdn is None and root is None, f"Expected {pseudo} to return (None, None)"

def test_page_extractor_ignores_js_code():
    extractor = PageExtractor('https://www.target-site.com', {
        'extract_assets': True,
        'extract_text': True,
        'scope_mode': 'root_domain'
    })

    sample_html = '''<!DOCTYPE html>
<html>
<head>
    <title>Test Page</title>
    <script>
        function handleClick(e) {
            if (e.target) {
                window.open("https://legit-partner.com/login", "_blank");
                item.now = 123;
                video.play();
                style.top = "10px";
            }
        }
    </script>
</head>
<body>
    <h1>Welcome</h1>
    <p>Contact us at service.validcompany.org or visit <a href="https://cdn.resource.net/lib.js">CDN</a></p>
</body>
</html>'''

    res = extractor.extract('https://www.target-site.com/index.html', sample_html)
    found_domains = [d['domain'] for d in res['external_domains']]

    assert 'legit-partner.com' in found_domains
    assert 'service.validcompany.org' in found_domains
    assert 'cdn.resource.net' in found_domains

    blocked = ['window.open', 'e.target', 'video.play', 'style.top', 'item.now']
    for b in blocked:
        assert b not in found_domains, f"Code expression {b} was mistakenly extracted!"
