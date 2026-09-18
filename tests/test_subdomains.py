import asyncio
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx
from app.crawler.extractor import PageExtractor
from app.db import crud, database
from app.main import app

def test_page_extractor_subdomains():
    print(">>> 1. 测试 PageExtractor 子域名判定与提取...")
    target = 'https://www.testtarget.com/index.html'
    extractor = PageExtractor(target)

    assert extractor.target_root_domain == 'testtarget.com'
    assert extractor.is_subdomain('api.testtarget.com') is True
    assert extractor.is_subdomain('sub.dev.testtarget.com') is True
    assert extractor.is_subdomain('www.testtarget.com') is True
    assert extractor.is_subdomain('testtarget.com') is True
    assert extractor.is_subdomain('google.com') is False
    assert extractor.is_subdomain('cdn.aliyun.com') is False

    html_content = '''
    <!DOCTYPE html>
    <html>
    <head>
        <title>Subdomain Test</title>
        <link rel="canonical" href="https://www.testtarget.com/canonical">
        <link rel="stylesheet" href="https://static.testtarget.com/css/main.css">
        <script src="https://cdn.external.org/lib.js"></script>
    </head>
    <body>
        <a href="https://api.testtarget.com/users">API Endpoint</a>
        <a href="https://partner.other.com/login">External Login</a>
        <!-- Subdomain in comment: dev.testtarget.com -->
        <p>Contact us at support.testtarget.com or visit cloud.testtarget.com</p>
        <script>
            window.location.href = "https://portal.testtarget.com/dashboard";
            var thirdparty = "https://analytics.google.com/collect";
        </script>
    </body>
    </html>
    '''

    res = extractor.extract('https://www.testtarget.com/index.html', html_content)
    discovered_subs = {s['subdomain']: s for s in res['discovered_subdomains']}

    # Should have discovered www.testtarget.com, static.testtarget.com, api.testtarget.com, dev.testtarget.com, support.testtarget.com, cloud.testtarget.com, portal.testtarget.com
    for s in ['api.testtarget.com', 'static.testtarget.com', 'portal.testtarget.com', 'dev.testtarget.com', 'support.testtarget.com', 'cloud.testtarget.com']:
        assert s in discovered_subs, f"Expected {s} in discovered_subdomains"
    assert discovered_subs['api.testtarget.com']['has_link'] is True

    # External domains should NOT include target subdomains
    ext_domains = {d['domain'] for d in res['external_domains']}
    assert 'partner.other.com' in ext_domains
    assert 'cdn.external.org' in ext_domains
    assert 'analytics.google.com' in ext_domains
    assert 'api.testtarget.com' not in ext_domains
    print("    PageExtractor 子域名测试通过!")

def test_asset_subdomain_extraction():
    print(">>> 2. 测试静态 JS/CSS 资源中的子域名探测...")
    extractor = PageExtractor('https://mycorp.com/home')
    js_content = '''
    const API_BASE = "https://gateway.mycorp.com/v2";
    const AUTH_URL = "https://sso.mycorp.com/oauth";
    fetch("https://api.thirdparty.io/data");
    // Internal admin: admin.mycorp.com
    '''
    res = extractor.extract_from_asset('https://mycorp.com/bundle.js', 'js', js_content)
    subdomains = {s['subdomain'] for s in res['discovered_subdomains']}
    assert 'gateway.mycorp.com' in subdomains
    assert 'sso.mycorp.com' in subdomains
    assert 'admin.mycorp.com' in subdomains

    ext = {d['domain'] for d in res['external_domains']}
    assert 'api.thirdparty.io' in ext
    assert 'gateway.mycorp.com' not in ext
    print("    静态资源子域名提取测试通过!")

async def test_db_and_api():
    print(">>> 3. 测试数据库持久化与 Subdomains API 及导出接口...")
    database.init_db()

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        # 1. Create a task
        task_id = crud.create_task('Subdomain Test Task', 'https://testsite.org', config={})

        # 2. Simulate crawl save with subdomains
        page_data = {
            'url': 'https://testsite.org/home',
            'path': '/home',
            'depth': 0,
            'status_code': 200,
            'content_type': 'text/html',
            'title': 'Test Site',
            'response_time_ms': 50,
            'external_domains_count': 1,
            'error': None
        }
        ext_domains = [
            {'domain': 'analytics.google.com', 'root_domain': 'google.com', 'count': 1, 'has_link': True, 'has_text': False, 'sample_page_url': 'https://testsite.org/home'}
        ]
        subdomains = [
            {'subdomain': 'api.testsite.org', 'root_domain': 'testsite.org', 'count': 2, 'has_link': True, 'has_text': False, 'sample_page_url': 'https://testsite.org/home'},
            {'subdomain': 'oa.testsite.org', 'root_domain': 'testsite.org', 'count': 1, 'has_link': False, 'has_text': True, 'sample_page_url': 'https://testsite.org/home'}
        ]
        occurrences = [
            {'domain': 'api.testsite.org', 'page_url': 'https://testsite.org/home', 'source_type': 'link_href', 'raw_match': 'https://api.testsite.org', 'context_snippet': 'link to api'}
        ]

        crud.save_crawl_result(task_id, page_data, ext_domains, occurrences, subdomains=subdomains)

        # 3. Test list API
        resp = await client.get(f'/api/tasks/{task_id}/subdomains')
        assert resp.status_code == 200
        data = resp.json()
        assert data['total'] == 2, f"Expected 2 subdomains, got {data['total']}"
        sub_names = [s['subdomain'] for s in data['subdomains']]
        assert 'api.testsite.org' in sub_names
        assert 'oa.testsite.org' in sub_names

        # 4. Test filter by search
        resp_search = await client.get(f'/api/tasks/{task_id}/subdomains?search=api')
        assert resp_search.json()['total'] == 1
        assert resp_search.json()['subdomains'][0]['subdomain'] == 'api.testsite.org'

        # 5. Test stats API
        resp_stats = await client.get(f'/api/tasks/{task_id}/subdomains/stats')
        assert resp_stats.status_code == 200
        stats = resp_stats.json()
        assert stats['total_unique_subdomains'] == 2
        assert stats['link_subdomains'] == 1
        assert stats['text_subdomains'] == 1

        # 6. Test occurrence API
        resp_occ = await client.get(f'/api/tasks/{task_id}/subdomains/api.testsite.org/occurrences')
        assert resp_occ.status_code == 200
        assert len(resp_occ.json()['occurrences']) == 1
        assert resp_occ.json()['occurrences'][0]['domain'] == 'api.testsite.org'

        # 7. Test Export APIs
        resp_txt = await client.get(f'/api/tasks/{task_id}/subdomains/export/txt')
        assert resp_txt.status_code == 200
        assert 'api.testsite.org' in resp_txt.text
        assert 'oa.testsite.org' in resp_txt.text

        resp_csv = await client.get(f'/api/tasks/{task_id}/subdomains/export/csv')
        assert resp_csv.status_code == 200
        assert '子域名' in resp_csv.text
        assert 'api.testsite.org' in resp_csv.text

        resp_json = await client.get(f'/api/tasks/{task_id}/subdomains/export/json')
        assert resp_json.status_code == 200
        sub_json = resp_json.json()
        assert len(sub_json) == 2

        # 8. Test task deletion cleans up subdomains
        crud.delete_task(task_id)
        task_check = crud.get_task(task_id)
        assert task_check is None
        print("    数据库持久化、子域名API、统计及三大格式导出测试通过!")

if __name__ == '__main__':
    test_page_extractor_subdomains()
    test_asset_subdomain_extraction()
    asyncio.run(test_db_and_api())
    print("\n[SUCCESS] All subdomain test cases passed successfully!")
