import asyncio
import time
from app.db import crud
from app.crawler.engine import CrawlJob
from app.crawler.extractor import PageExtractor, HTML_PARSER_BACKEND

def test_extractor_backend():
    print(f"Testing PageExtractor backend: {HTML_PARSER_BACKEND}...")
    assert HTML_PARSER_BACKEND in ("lxml", "html.parser"), f"Unexpected backend: {HTML_PARSER_BACKEND}"
    extractor = PageExtractor("https://example.com", {})
    html = '''
    <html>
      <head><title>Test Page</title></head>
      <body>
        <a href="https://api.example.com/v1">Subdomain Link</a>
        <a href="https://external-service.org/about">External Link</a>
        <img src="https://cdn.another-external.net/img.png" />
      </body>
    </html>
    '''
    res = extractor.extract("https://example.com/page1", html)
    assert res["title"] == "Test Page"
    ext_domains = [d["domain"] for d in res["external_domains"]]
    assert "external-service.org" in ext_domains
    assert "cdn.another-external.net" in ext_domains
    sub_domains = [s["subdomain"] for s in res.get("discovered_subdomains", [])]
    assert "api.example.com" in sub_domains
    print("PageExtractor test PASSED.")

def test_batch_crud_operations():
    print("Testing CRUD batch operations...")
    task_id = crud.create_task("Test Batch Task", "https://batch-test.local", {"batch_size": 10})
    try:
        batch_items = []
        for i in range(10):
            page_url = f"https://batch-test.local/p/{i}"
            item = {
                "page_data": {
                    "url": page_url,
                    "path": f"/p/{i}",
                    "depth": 1,
                    "status_code": 200,
                    "content_type": "text/html",
                    "title": f"Batch Page {i}",
                    "response_time_ms": 15,
                    "external_domains_count": 2,
                    "error": None
                },
                "external_domains": [
                    {"domain": "partner.com", "root_domain": "partner.com", "count": 1, "has_link": 1, "has_text": 0, "sample_page_url": page_url},
                    {"domain": f"ext-{i}.org", "root_domain": f"ext-{i}.org", "count": 1, "has_link": 0, "has_text": 1, "sample_page_url": page_url}
                ],
                "subdomains": [
                    {"subdomain": f"sub-{i % 3}.batch-test.local", "root_domain": "batch-test.local", "count": 1, "has_link": 1, "has_text": 0, "sample_page_url": page_url}
                ],
                "occurrences": [
                    {
                        "domain": "partner.com",
                        "page_url": page_url,
                        "source_type": "href",
                        "raw_match": "https://partner.com",
                        "context_snippet": f"<a href='https://partner.com'>Partner {i}</a>"
                    }
                ]
            }
            batch_items.append(item)

        t0 = time.perf_counter()
        crud.save_crawl_results_batch(
            task_id=task_id,
            batch_items=batch_items,
            pages_crawled=10,
            pages_total=20,
            external_domains_count=11,
            subdomains_count=3,
            current_url=batch_items[-1]["page_data"]["url"]
        )
        duration_ms = (time.perf_counter() - t0) * 1000
        print(f"CRUD save_crawl_results_batch (10 items): {duration_ms:.2f}ms")

        pages, total_pages = crud.list_pages(task_id, limit=50)
        assert total_pages == 10, f"Expected 10 pages, got {total_pages}"
        assert len(pages) == 10

        domains, total_domains = crud.list_external_domains(task_id, limit=50)
        assert total_domains == 11, f"Expected 11 external domains, got {total_domains}"
        partner = next((d for d in domains if d["domain"] == "partner.com"), None)
        assert partner is not None
        assert partner["occurrence_count"] == 10, f"Expected partner.com count=10, got {partner['occurrence_count']}"

        subs, total_subs = crud.list_subdomains(task_id, limit=50)
        assert total_subs == 3, f"Expected 3 subdomains, got {total_subs}"

        occs = crud.get_domain_occurrences(task_id, domain="partner.com")
        assert len(occs) == 10, f"Expected 10 occurrences for partner.com, got {len(occs)}"

        test_logs = [
            {"level": "INFO", "message": f"Log message {j}", "created_at": crud.now_iso()}
            for j in range(5)
        ]
        crud.add_logs_batch(task_id, test_logs)
        logs = crud.get_recent_logs(task_id, limit=50)
        assert len(logs) >= 5
        print("CRUD batch operations test PASSED.")
    finally:
        crud.delete_task(task_id)

async def test_crawljob_buffer_and_flush():
    print("Testing CrawlJob buffer & flush mechanism...")
    task_id = crud.create_task("Test Job Buffer Task", "https://buffer-test.local", {"batch_size": 5})
    try:
        job = CrawlJob(task_id, "https://buffer-test.local", {"batch_size": 5})
        job.pages_crawled = 3
        job.enqueued_urls.add("https://buffer-test.local")
        job.enqueued_urls.add("https://buffer-test.local/1")
        job.enqueued_urls.add("https://buffer-test.local/2")

        for i in range(3):
            url = f"https://buffer-test.local/{i}"
            job.batch_buffer.append({
                "page_data": {
                    "url": url,
                    "path": f"/{i}",
                    "depth": 1,
                    "status_code": 200,
                    "content_type": "text/html",
                    "title": f"Item {i}",
                    "response_time_ms": 10,
                    "external_domains_count": 1,
                    "error": None
                },
                "external_domains": [{"domain": "buffered.com", "root_domain": "buffered.com", "count": 1, "has_link": 1, "has_text": 0, "sample_page_url": url}],
                "subdomains": [],
                "occurrences": []
            })
            job.log("INFO", f"Job buffered page {i}")

        assert len(job.batch_buffer) == 3
        assert len(job.batch_logs) == 3

        await job.flush_buffer(force=False)
        assert len(job.batch_buffer) == 3, "Buffer should remain untouched when threshold not met"

        await job.flush_buffer(force=True)
        assert len(job.batch_buffer) == 0, "Buffer should be empty after forced flush"
        assert len(job.batch_logs) == 0, "Logs buffer should be empty after forced flush"

        pages, total = crud.list_pages(task_id)
        assert total == 3
        logs = crud.get_recent_logs(task_id)
        assert len(logs) == 3
        print("CrawlJob buffer & flush test PASSED.")
    finally:
        crud.delete_task(task_id)

def main():
    test_extractor_backend()
    test_batch_crud_operations()
    asyncio.run(test_crawljob_buffer_and_flush())
    print("\nALL BATCH COMMIT & EXTRACTOR OPTIMIZATION TESTS PASSED SUCCESSFULLY!")

if __name__ == '__main__':
    main()