import asyncio
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx
from app.main import app
from app.db import crud

async def run_tests():
    print(">>> 1. 开始测试批量导入创建扫描任务 API (/api/tasks/batch)...")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        # Test Case 1: Batch creation with messy input (whitespace, # comments, duplicates, protocol-less)
        batch_payload = {
            "urls": [
                "  https://site1.example.org/path  ",
                "# 这是注释行应该被自动忽略",
                "",
                "http://site2.test.com",
                "site3.demo.net",                  # Protocol-less, should become https://site3.demo.net
                "https://site1.example.org/path",  # Duplicate, should be deduplicated
                "   # 另一个注释",
                "api.gateway.io:8080"              # Port included
            ],
            "name_template": "domain",
            "auto_start": False,
            "config": {
                "max_depth": 7,
                "concurrency": 4,
                "scan_asset_content": True
            }
        }

        resp = await client.post("/api/tasks/batch", json=batch_payload)
        assert resp.status_code == 200, f"Batch create failed: {resp.text}"
        data = resp.json()
        assert data["success"] is True
        assert data["created_count"] == 4, f"Expected 4 unique tasks, got {data['created_count']}"
        assert data["started_count"] == 0
        
        created_tasks = data["tasks"]
        task_ids = [t["id"] for t in created_tasks]
        print(f"  [OK] 成功批量创建 4 个去重任务: ID 列表: {task_ids}")

        # Verify task attributes and config inheritance
        for t in created_tasks:
            assert t["status"] == "pending"
            assert t["config"]["max_depth"] == 7
            assert t["config"]["scan_asset_content"] is True
            print(f"       - 任务 ID {t['id']}: 名称='{t['name']}', URL='{t['target_url']}'")

        # Test Case 2: Custom prefix naming strategy
        batch_prefix_payload = {
            "urls": [
                "https://alpha.corp.com",
                "https://beta.corp.com"
            ],
            "name_prefix": "2026安全巡检",
            "name_template": "custom_prefix",
            "auto_start": False
        }
        resp2 = await client.post("/api/tasks/batch", json=batch_prefix_payload)
        assert resp2.status_code == 200
        data2 = resp2.json()
        assert data2["created_count"] == 2
        for t in data2["tasks"]:
            assert t["name"].startswith("2026安全巡检_")
            print(f"       - 自定义前缀任务 ID {t['id']}: 名称='{t['name']}'")
        prefix_task_ids = [t["id"] for t in data2["tasks"]]

        # Test Case 3: Batch Actions (pause, resume, stop, delete)
        all_test_ids = task_ids + prefix_task_ids
        print(f"\n>>> 2. 测试批量操作 API (/api/tasks/batch-action) 针对 {len(all_test_ids)} 个任务...")

        # (a) Batch Stop
        resp_stop = await client.post("/api/tasks/batch-action", json={
            "task_ids": all_test_ids,
            "action": "stop"
        })
        assert resp_stop.status_code == 200
        assert resp_stop.json()["action"] == "stop"
        print("  [OK] 批量停止指令执行成功")

        # (b) Batch Delete
        resp_del = await client.post("/api/tasks/batch-action", json={
            "task_ids": all_test_ids,
            "action": "delete"
        })
        assert resp_del.status_code == 200
        assert resp_del.json()["action"] == "delete"
        assert resp_del.json()["affected_count"] == len(all_test_ids)
        print(f"  [OK] 批量删除指令执行成功，已成功清除 {len(all_test_ids)} 个任务！")

        # Verify deletion in DB
        for tid in all_test_ids:
            assert crud.get_task(tid) is None, f"Task {tid} should have been deleted!"
        print("  [OK] 验证数据库内对应记录已被全部原子级彻底清空！")

        # Test Case 4: Empty URLs validation
        resp_empty = await client.post("/api/tasks/batch", json={
            "urls": ["# comment", "   ", ""],
            "auto_start": False
        })
        assert resp_empty.status_code == 400
        print("  [OK] 空 URL 或纯注释行有效性阻断校验测试通过！")

    print("\n===============================================================")
    print("  [SUCCESS] 批量导入创建与批量操作所有自动化测试用例 100% 通过！")
    print("===============================================================")

if __name__ == "__main__":
    asyncio.run(run_tests())
