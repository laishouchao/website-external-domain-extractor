import asyncio
import threading
import time
from urllib.parse import urlparse
import uvicorn
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, Response
import httpx

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.main import app as main_app
from app.db import crud


# Create a mock target site with multi-depth pages and diverse path/domain cases
mock_target_app = FastAPI()

PAGES = {
    "/": """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Mock Target Site - Home</title>
        <link rel="stylesheet" href="https://cdn.mock-framework.org/style.css">
        <!-- 内部独立静态资源引用，用于深度扫描测试 -->
        <link rel="stylesheet" href="/static/theme.css">
        <script src="/static/app.bundle.js"></script>
        <script src="https://code.mock-lib.net/core.js"></script>
        <!-- 协议相对 URL 测试 (省略 http/https) -->
        <script src="//cdn.protocol-relative-assets.net/bundle.js"></script>
        <!-- 运维注释: 迁移数据库到 db-cluster.ops-cloud.com 节点 -->
    </head>
    <body>
        <h1>欢迎来到目标演示站点</h1>
        <!-- 省略域名的绝对路径 -->
        <a href="/products">产品中心 (深度1 - 绝对路径)</a>
        <a href="/about">关于我们 (深度1 - 绝对路径)</a>
        <a href="/docs/">开发文档 (深度1 - 带base标签)</a>
        <!-- 内链跳转携带编码的外部目标域名 -->
        <a href="/jump?target=https%3A%2F%2Fpartner-gateway.com%2Fauth">第三方授权跳转</a>
        <a href="https://github.com/external-open-source/repo">GitHub 外部链接</a>
        <img src="https://img.thirdparty-cdn.com/logo.png" alt="第三方CDN图片">
        <p>如需技术合作请联系 support.partner-network.com 商务团队。</p>
        <p>过滤测试: version 2.0.1, config.min.js, photo.jpg, 127.0.0.1</p>
        <script>
            // JS 中省略域名的 API 路径与外部跳转
            fetch("/api/v3/dynamic-data");
            var checkoutUrl = "https://checkout.stripe-payment-hub.com";
        </script>
    </body>
    </html>
    """,
    "/docs/": """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Mock Target Site - Documentation</title>
        <!-- base 标签: 所有相对路径基于 /docs/ 计算 -->
        <base href="http://127.0.0.1:9100/docs/">
    </head>
    <body>
        <h2>文档首页</h2>
        <!-- 相对路径 (省略域名) -->
        <a href="guide.html">入门指南 (相对路径解析为 /docs/guide.html)</a>
        <a href="api/reference.html">API 参考 (相对路径解析为 /docs/api/reference.html)</a>
        <a href="/">返回首页</a>
    </body>
    </html>
    """,
    "/docs/guide.html": """
    <!DOCTYPE html>
    <html>
    <head><title>Documentation Guide</title></head>
    <body>
        <h3>入门指南</h3>
        <p>参考外部文档: <a href="https://developer.mozilla-guide.org/en-US">MDN指南</a></p>
    </body>
    </html>
    """,
    "/docs/api/reference.html": """
    <!DOCTYPE html>
    <html>
    <head>
        <title>API Reference</title>
        <!-- Meta 自动跳转到新页面 -->
        <meta http-equiv="refresh" content="3; url=/special-offer">
    </head>
    <body>
        <h3>API 接口参考</h3>
        <p>外包服务托管于 external-datacenter.cloud-host.io 基础设施</p>
    </body>
    </html>
    """,
    "/special-offer": """
    <!DOCTYPE html>
    <html>
    <head><title>Special Offer</title></head>
    <body>
        <h2>限时优惠页面</h2>
        <a href="/">返回主页</a>
    </body>
    </html>
    """,
    "/api/v3/dynamic-data": """
    {"status": "ok", "message": "API endpoint reached"}
    """,
    "/jump": """
    <!DOCTYPE html>
    <html>
    <head><title>Redirecting...</title></head>
    <body><p>正在跳转...</p></body>
    </html>
    """,
    "/products": """
    <!DOCTYPE html>
    <html>
    <head><title>Mock Target Site - Products</title></head>
    <body>
        <h2>产品列表</h2>
        <a href="/products/item1">产品 1 (深度2)</a>
        <a href="/">返回首页</a>
        <iframe src="https://player.video-cloud.tv/embed/123"></iframe>
        <script>
            var paymentGateway = "https://pay.finance-service.cc/v1/charge";
        </script>
    </body>
    </html>
    """,
    "/products/item1": """
    <!DOCTYPE html>
    <html>
    <head><title>Mock Target Site - Product Item 1</title></head>
    <body>
        <h3>旗舰产品详情</h3>
        <p>技术支持提供方: cloud-service.alibaba.org 官方团队。</p>
        <a href="/products">返回产品列表</a>
    </body>
    </html>
    """,
    "/about": """
    <!DOCTYPE html>
    <html>
    <head><title>Mock Target Site - About</title></head>
    <body>
        <h2>关于我们</h2>
        <p>友情链接: <a href="https://news.external-media.com/article">行业新闻</a></p>
        <p>官网备案号及域名: icp.domain-registry.gov.cn</p>
    </body>
    </html>
    """,
    "/static/app.bundle.js": """
        // 独立 JS 打包文件内部代码
        const STRIPE_API = "https://api.external-stripe.io/v1/tokens";
        const SENTRY_DSN = "https://sentry.external-monitor.org/450";
        fetch("https://analytics.external-tracker.com/collect");
        var nakedDomain = "service.naked-domain-in-js.io";
    """,
    "/static/theme.css": """
        /* 独立 CSS 样式文件内部代码 */
        @import "https://fonts.external-cdn.com/css?family=Roboto";
        .hero {
            background: url('https://img.external-backgrounds.net/bg.webp');
        }
        /* 运维联系: ops.external-cloud.cc */
    """
}

@mock_target_app.get("/{path:path}")
def serve_page(path: str):
    clean_path = "/" + path.strip("/")
    if path.endswith("/"):
        clean_path += "/"
    if clean_path in PAGES:
        content = PAGES[clean_path]
        if clean_path.endswith(".js"):
            return Response(content=content, media_type="application/javascript")
        if clean_path.endswith(".css"):
            return Response(content=content, media_type="text/css")
        return HTMLResponse(content=content)
    if clean_path.rstrip("/") in PAGES:
        return HTMLResponse(content=PAGES[clean_path.rstrip("/")])
    return HTMLResponse(content="<h1>404 Not Found</h1>", status_code=404)


def run_mock_server():
    uvicorn.run(mock_target_app, host="127.0.0.1", port=9100, log_level="error")


async def main():
    print(">>> 1. 启动模拟被测目标站点 (http://127.0.0.1:9100)...")
    target_thread = threading.Thread(target=run_mock_server, daemon=True)
    target_thread.start()
    time.sleep(1.5)

    print(">>> 2. 测试主 Web 系统 API 端点与自动化扫描流程...")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main_app), base_url="http://test") as client:
        # 1. Check Root UI
        resp = await client.get("/")
        assert resp.status_code == 200, f"Root UI returned {resp.status_code}"
        assert "网站外部域名提取与全深度网站地图系统" in resp.text
        print("  [OK] 前端页面成功挂载并渲染！")

        # 2. Create Task
        task_data = {
            "name": "全面审计与优化验证扫描任务",
            "target_url": "http://127.0.0.1:9100/",
            "config": {
                "max_depth": 5,
                "max_pages": 50,
                "concurrency": 4,
                "request_delay": 0.02,
                "scope_mode": "exact_host", # Exact host for 127.0.0.1:9100
                "extract_assets": True,
                "extract_text": True,
                "scan_asset_content": True,
                "detect_sitemap": False
            }
        }
        resp = await client.post("/api/tasks", json=task_data)
        assert resp.status_code == 200
        res_json = resp.json()
        task_id = res_json["task"]["id"]
        print(f"  [OK] 成功创建任务 ID: {task_id}")

        # 3. Start Task
        t_start = time.perf_counter()
        resp = await client.post(f"/api/tasks/{task_id}/start")
        assert resp.status_code == 200
        print("  [OK] 任务启动指令已发出，爬虫开始递归执行...")

        # 4. Wait for crawl completion (poll status)
        for i in range(25):
            await asyncio.sleep(0.4)
            resp = await client.get(f"/api/tasks/{task_id}")
            task = resp.json()
            status = task["status"]
            pages = task["pages_crawled"]
            ext_domains = task["external_domains_count"]
            print(f"       扫描中... 状态: {status}, 已爬页面: {pages}, 提取外部域名: {ext_domains}")
            if status in ("completed", "stopped", "failed"):
                break

        duration = time.perf_counter() - t_start
        assert status == "completed", f"Expected completed but got {status}"
        print(f"  [OK] 任务扫描顺利完成！耗时: {duration:.2f}秒")

        # 5. Verify Sitemap Pages (Check base href, absolute paths, query paths)
        resp = await client.get(f"/api/tasks/{task_id}/pages")
        sitemap_res = resp.json()
        crawled_urls = [p["url"] for p in sitemap_res["pages"]]
        print(f"  [OK] 网站地图共发现 {len(crawled_urls)} 个全深度页面:")
        for p in sitemap_res["pages"]:
            print(f"       - 深度 {p['depth']}: {p['url']} (状态: {p['status_code']}, 外部域名: {p['external_domains_count']} 个, 标题: '{p['title']}')")

        # Verify critical paths:
        # - base href relative path
        assert any("guide.html" in u for u in crawled_urls), "Relative path with <base href> was not crawled!"
        assert any("api/reference.html" in u for u in crawled_urls), "Nested relative path with <base href> was not crawled!"
        # - JS endpoint
        assert any("/api/v3/dynamic-data" in u for u in crawled_urls), "JS fetch API path was not crawled!"
        # - Meta refresh target
        assert any("/special-offer" in u for u in crawled_urls), "Meta refresh redirect path was not crawled!"
        print("  [OK] 验证通过: <base href> 相对路径、省略域名的绝对路径、JS fetch 接口路径、Meta refresh 页面均全部成功探测到并生成网站地图！")

        # 6. Verify External Domains
        resp = await client.get(f"/api/tasks/{task_id}/domains")
        domains_res = resp.json()
        ext_domains = [d["domain"] for d in domains_res["domains"]]
        print(f"  [OK] 成功提取到 {len(ext_domains)} 个外部域名:")
        for d in domains_res["domains"]:
            print(f"       - 域名: {d['domain']:<36} 根域: {d['root_domain']:<22} 频次: {d['occurrence_count']}")

        # Verify key external domains from all sources:
        expected_domains = [
            "github.com",
            "cdn.mock-framework.org",
            "code.mock-lib.net",
            "img.thirdparty-cdn.com",
            "player.video-cloud.tv",
            "news.external-media.com",
            # from text/code/comments:
            "db-cluster.ops-cloud.com",
            "support.partner-network.com",
            "pay.finance-service.cc",
            "cloud-service.alibaba.org",
            "icp.domain-registry.gov.cn",
            # from new enhancements:
            "cdn.protocol-relative-assets.net",  # Protocol-relative //
            "partner-gateway.com",               # Open redirect parameter unquoted
            "checkout.stripe-payment-hub.com",   # JS variable/navigation
            "developer.mozilla-guide.org",       # Link inside base href page
            "external-datacenter.cloud-host.io", # Text inside base href page
            # from standalone JS/CSS content deep scanning:
            "api.external-stripe.io",            # API constant inside .js file
            "sentry.external-monitor.org",       # Sentry DSN inside .js file
            "analytics.external-tracker.com",    # fetch() endpoint inside .js file
            "service.naked-domain-in-js.io",     # Naked domain inside .js file
            "fonts.external-cdn.com",            # @import inside .css file
            "img.external-backgrounds.net",      # url() background inside .css file
            "ops.external-cloud.cc"              # Comment inside .css file
        ]
        for exp in expected_domains:
            assert exp in ext_domains, f"Expected external domain {exp} was not found in {ext_domains}"
        print(f"  [OK] 验证通过: 成功下载并深入扫描独立 JS/CSS 文件内部全部 API 接口、@import、url()背景与裸域名！")

        # 7. Verify source_type=asset filter API
        resp = await client.get(f"/api/tasks/{task_id}/domains?source_type=asset")
        asset_domains_res = resp.json()
        asset_domain_names = [d["domain"] for d in asset_domains_res["domains"]]
        print(f"  [OK] 筛选 source_type=asset 成功获得 {len(asset_domain_names)} 个独立静态资源外部域名:")
        for name in asset_domain_names:
            print(f"       * {name}")
        assert "api.external-stripe.io" in asset_domain_names
        assert "fonts.external-cdn.com" in asset_domain_names

        # 8. Verify False Positives are EXCLUDED
        false_positives = ["config.min.js", "photo.jpg", "version 2.0.1", "127.0.0.1"]
        for fp in false_positives:
            assert fp not in ext_domains, f"False positive {fp} was wrongly recognized as external domain!"
        print("  [OK] 验证通过: 成功杜绝误判，代码文件名、图片后缀、版本号、本地IP均被精准滤除！")

        # 9. Verify Domain Occurrence Evidence Context (including from JS asset)
        test_domain = "api.external-stripe.io"
        resp = await client.get(f"/api/tasks/{task_id}/domains/{test_domain}/occurrences")
        occ_res = resp.json()
        assert len(occ_res["occurrences"]) > 0
        occ = occ_res["occurrences"][0]
        assert "app.bundle.js" in occ["page_url"]
        print(f"  [OK] 独立静态文件外部域名溯源证据链穿透验证 ({test_domain}):")
        print(f"       来源文件: {occ['page_url']}")
        print(f"       来源类型: {occ['source_type']}")
        print(f"       代码上下文: {occ['context_snippet']}")

        # 10. Verify Domain Analytics
        resp = await client.get(f"/api/tasks/{task_id}/domains/stats")
        stats = resp.json()
        assert stats["total_unique_domains"] >= 20
        assert stats["unique_root_domains"] >= 15
        print(f"  [OK] 域名统计分析正常: 独立外部域名 {stats['total_unique_domains']} 个，独立主根域名 {stats['unique_root_domains']} 个")

        # 11. Verify Exports
        # TXT export
        resp = await client.get(f"/api/tasks/{task_id}/export/txt")
        assert resp.status_code == 200
        assert "partner-gateway.com" in resp.text
        # CSV export
        resp = await client.get(f"/api/tasks/{task_id}/export/csv")
        assert resp.status_code == 200
        # JSON export
        resp = await client.get(f"/api/tasks/{task_id}/export/json")
        assert resp.status_code == 200
        # Sitemap XML export
        resp = await client.get(f"/api/tasks/{task_id}/pages/export/xml")
        assert resp.status_code == 200
        assert "<urlset" in resp.text
        print("  [OK] 导出功能全量验证成功: TXT, CSV, JSON 以及标准 Sitemap XML 文件生成全部正常！")

    print("\n===============================================================")
    print("  [SUCCESS] 全部端到端自动化测试顺利通过！系统功能完全符合要求！")
    print("===============================================================")

if __name__ == "__main__":
    import multiprocessing as mp
    mp.freeze_support()
    asyncio.run(main())
