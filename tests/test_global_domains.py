from fastapi.testclient import TestClient
from app.main import app
from app.db.crud import (
    list_global_external_domains,
    get_global_domains_stats,
    get_domain_associated_tasks,
    get_global_domains_for_export
)

client = TestClient(app)

def test_crud_list_global_external_domains():
    domains, total = list_global_external_domains(limit=10, offset=0)
    assert isinstance(domains, list)
    assert total >= 0
    if len(domains) > 0:
        d = domains[0]
        assert "domain" in d
        assert "root_domain" in d
        assert "total_occurrences" in d
        assert "task_count" in d
        assert "has_link" in d
        assert "has_text" in d
        assert "associated_tasks" in d

def test_crud_global_stats():
    stats = get_global_domains_stats()
    assert "total_unique_domains" in stats
    assert "unique_root_domains" in stats
    assert "total_tasks" in stats
    assert "total_occurrences" in stats
    assert "shared_domains_count" in stats
    assert "top_root_domains" in stats
    assert "top_shared_domains" in stats

def test_crud_domain_associated_tasks():
    domains, total = list_global_external_domains(limit=1, offset=0)
    if domains:
        domain_name = domains[0]["domain"]
        tasks = get_domain_associated_tasks(domain_name)
        assert isinstance(tasks, list)
        assert len(tasks) >= 1
        t = tasks[0]
        assert "task_id" in t
        assert "task_name" in t
        assert "occurrence_count" in t

def test_api_global_domains_list():
    res = client.get("/api/global-domains?limit=10&offset=0")
    assert res.status_code == 200
    data = res.json()
    assert "total" in data
    assert "domains" in data
    assert isinstance(data["domains"], list)

def test_api_global_domains_stats():
    res = client.get("/api/global-domains/stats")
    assert res.status_code == 200
    data = res.json()
    assert "total_unique_domains" in data
    assert "unique_root_domains" in data
    assert "shared_domains_count" in data

def test_api_global_domain_tasks():
    res = client.get("/api/global-domains?limit=1")
    assert res.status_code == 200
    data = res.json()
    if data["domains"]:
        d_name = data["domains"][0]["domain"]
        res2 = client.get(f"/api/global-domains/{d_name}/tasks")
        assert res2.status_code == 200
        data2 = res2.json()
        assert data2["domain"] == d_name
        assert "tasks" in data2

def test_api_exports():
    res_txt = client.get("/api/global-domains/export/txt")
    assert res_txt.status_code == 200
    assert "text/plain" in res_txt.headers.get("content-type", "")

    res_csv = client.get("/api/global-domains/export/csv")
    assert res_csv.status_code == 200
    assert "text/csv" in res_csv.headers.get("content-type", "")

    res_json = client.get("/api/global-domains/export/json")
    assert res_json.status_code == 200
    assert "application/json" in res_json.headers.get("content-type", "")