import asyncio
import time
from collections import deque
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.crawler.engine import CrawlJob, CrawlEngine
from app.db import crud, database
from fastapi.testclient import TestClient
from app.main import app

def test_crawl_job_speed_calculation():
    print(">>> 1. 测试 CrawlJob 实时速度算法与滑动窗口...")
    job = CrawlJob(
        task_id=9999,
        target_url="https://testspeed.example.com",
        config={"concurrency": 2, "timeout": 5}
    )

    # Initially stopped / not running
    speed = job.get_speed()
    assert speed["current_speed"] == 0.0
    assert speed["avg_speed"] == 0.0
    assert speed["speed_unit"] == "页/秒"

    # Simulate running
    job.is_running = True
    now = time.time()
    job.start_time = now - 2.0
    job.pages_crawled = 10

    # Add 10 timestamps in the last 2 seconds
    for i in range(10):
        job.recent_page_timestamps.append(now - (i * 0.15))

    speed = job.get_speed()
    assert speed["current_speed"] > 0.0
    assert speed["avg_speed"] > 0.0
    print(f"    运行中瞬时速度: {speed['current_speed']} 页/秒, 平均速度: {speed['avg_speed']} 页/秒")

    # Simulate stopping
    job.is_running = False
    speed_stopped = job.get_speed()
    assert speed_stopped["current_speed"] == 0.0
    assert speed_stopped["avg_speed"] > 0.0
    print(f"    停止后瞬时速度: {speed_stopped['current_speed']} 页/秒, 最终均速: {speed_stopped['avg_speed']} 页/秒")
    print("    CrawlJob 实时速度算法测试通过!")


def test_api_speed_fields():
    print(">>> 2. 测试 API 接口返回当前扫描速度字段...")
    client = TestClient(app)
    
    # Check /api/tasks
    res = client.get("/api/tasks")
    assert res.status_code == 200
    data = res.json()
    assert "tasks" in data
    if data["tasks"]:
        first_task = data["tasks"][0]
        assert "current_speed" in first_task
        assert "avg_speed" in first_task
        assert "speed" in first_task
        assert "speed_unit" in first_task
        print(f"    /api/tasks 字段验证成功: {first_task['name']} 速度: {first_task['current_speed']} 页/秒")

        # Check /api/tasks/{task_id}
        tid = first_task["id"]
        detail_res = client.get(f"/api/tasks/{tid}")
        assert detail_res.status_code == 200
        detail = detail_res.json()
        assert "current_speed" in detail
        assert "avg_speed" in detail
        assert "speed" in detail
        assert "speed_unit" in detail
        print(f"    /api/tasks/{tid} 详情接口验证成功!")

    print("    API 接口速度字段测试通过!")


if __name__ == "__main__":
    database.init_db()
    test_crawl_job_speed_calculation()
    test_api_speed_fields()
    print("\n[OK] 所有扫描速度相关测试全部顺利通过！")
