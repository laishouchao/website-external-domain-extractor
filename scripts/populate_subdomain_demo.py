import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import crud, database

def populate():
    database.init_db()

    task_name = "某大型跨国企业数字资产与全深度子域名探测任务"
    target_url = "https://www.example-enterprise.com/"
    config = {
        "max_depth": 10,
        "max_pages": 500,
        "concurrency": 8,
        "request_delay": 0.05,
        "scope_mode": "root_domain",
        "detect_sitemap": True,
        "ignore_ssl": True,
        "extract_assets": True,
        "extract_text": True,
        "scan_asset_content": True
    }

    task_id = crud.create_task(task_name, target_url, config)
    print(f"Created demo task id: {task_id}")

    subdomains_data = [
        {"subdomain": "api.example-enterprise.com", "root_domain": "example-enterprise.com", "count": 28, "has_link": True, "has_text": True, "sample_page_url": "https://www.example-enterprise.com/developer/v2"},
        {"subdomain": "oa.example-enterprise.com", "root_domain": "example-enterprise.com", "count": 14, "has_link": True, "has_text": False, "sample_page_url": "https://www.example-enterprise.com/internal-portal"},
        {"subdomain": "vpn.example-enterprise.com", "root_domain": "example-enterprise.com", "count": 9, "has_link": False, "has_text": True, "sample_page_url": "https://www.example-enterprise.com/staff/login"},
        {"subdomain": "sso.example-enterprise.com", "root_domain": "example-enterprise.com", "count": 35, "has_link": True, "has_text": True, "sample_page_url": "https://www.example-enterprise.com/oauth2/authorize"},
        {"subdomain": "mail.example-enterprise.com", "root_domain": "example-enterprise.com", "count": 12, "has_link": True, "has_text": False, "sample_page_url": "https://www.example-enterprise.com/contact"},
        {"subdomain": "git.example-enterprise.com", "root_domain": "example-enterprise.com", "count": 8, "has_link": True, "has_text": True, "sample_page_url": "https://www.example-enterprise.com/open-source"},
        {"subdomain": "dev.example-enterprise.com", "root_domain": "example-enterprise.com", "count": 19, "has_link": False, "has_text": True, "sample_page_url": "https://www.example-enterprise.com/static/main.bundle.js"},
        {"subdomain": "admin.example-enterprise.com", "root_domain": "example-enterprise.com", "count": 6, "has_link": False, "has_text": True, "sample_page_url": "https://www.example-enterprise.com/admin-gateway"},
        {"subdomain": "cdn.example-enterprise.com", "root_domain": "example-enterprise.com", "count": 42, "has_link": True, "has_text": False, "sample_page_url": "https://www.example-enterprise.com/assets/theme.css"},
        {"subdomain": "portal.example-enterprise.com", "root_domain": "example-enterprise.com", "count": 16, "has_link": True, "has_text": True, "sample_page_url": "https://www.example-enterprise.com/"},
    ]

    ext_domains_data = [
        {"domain": "analytics.google.com", "root_domain": "google.com", "count": 22, "has_link": True, "has_text": False, "sample_page_url": "https://www.example-enterprise.com/"},
        {"domain": "cdn.cloudflare.com", "root_domain": "cloudflare.com", "count": 45, "has_link": True, "has_text": False, "sample_page_url": "https://www.example-enterprise.com/assets/theme.css"},
        {"domain": "api.stripe.com", "root_domain": "stripe.com", "count": 18, "has_link": True, "has_text": True, "sample_page_url": "https://www.example-enterprise.com/checkout"},
        {"domain": "img.aliyun.com", "root_domain": "aliyun.com", "count": 11, "has_link": True, "has_text": False, "sample_page_url": "https://www.example-enterprise.com/products"},
        {"domain": "github.com", "root_domain": "github.com", "count": 7, "has_link": True, "has_text": False, "sample_page_url": "https://www.example-enterprise.com/about"}
    ]

    occurrences = [
        {"domain": "api.example-enterprise.com", "page_url": "https://www.example-enterprise.com/developer/v2", "source_type": "link_href", "raw_match": "https://api.example-enterprise.com/v2/users", "context_snippet": "<a href=\"https://api.example-enterprise.com/v2/users\">用户数据接口开放文档</a>"},
        {"domain": "api.example-enterprise.com", "page_url": "https://www.example-enterprise.com/developer/v2", "source_type": "script_endpoint", "raw_match": "https://api.example-enterprise.com/graphql", "context_snippet": "fetch(\"https://api.example-enterprise.com/graphql\", { method: \"POST\" })"},
        {"domain": "vpn.example-enterprise.com", "page_url": "https://www.example-enterprise.com/staff/login", "source_type": "plain_text", "raw_match": "vpn.example-enterprise.com", "context_snippet": "远程办公请提前连接集团专网接入点: vpn.example-enterprise.com:443 进行证书认证"},
        {"domain": "admin.example-enterprise.com", "page_url": "https://www.example-enterprise.com/static/main.bundle.js", "source_type": "js_file_code", "raw_match": "admin.example-enterprise.com", "context_snippet": "const BACKSTAGE_HOST = \"https://admin.example-enterprise.com/manage\";"},
        {"domain": "dev.example-enterprise.com", "page_url": "https://www.example-enterprise.com/internal-portal", "source_type": "comment", "raw_match": "dev.example-enterprise.com", "context_snippet": "<!-- 内部开发测试网关 dev.example-enterprise.com 部署于内网联调集群 -->"},
    ]

    page_data = {
        "url": "https://www.example-enterprise.com/",
        "path": "/",
        "depth": 0,
        "status_code": 200,
        "content_type": "text/html; charset=utf-8",
        "title": "集团数字业务全景门户",
        "response_time_ms": 42,
        "external_domains_count": len(ext_domains_data),
        "error": None
    }

    crud.save_crawl_result(
        task_id=task_id,
        page_data=page_data,
        external_domains=ext_domains_data,
        occurrences=occurrences,
        subdomains=subdomains_data
    )

    crud.update_task_progress(
        task_id=task_id,
        pages_crawled=25,
        pages_total=25,
        external_domains_count=len(ext_domains_data),
        subdomains_count=len(subdomains_data),
        current_url="https://www.example-enterprise.com/"
    )
    crud.update_task_status(task_id, "completed")
    crud.add_log(task_id, "INFO", "全深度扫描完成，共识别本站子域名 10 个，外部域名 5 个。")
    print("Demo data populated successfully!")
    return task_id

if __name__ == "__main__":
    populate()
