from typing import Optional, Dict, Any, List
from urllib.parse import urlparse
from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel, HttpUrl, Field
from app.db import crud
from app.crawler.engine import CrawlEngine
from app.config import DEFAULT_CRAWLER_CONFIG

router = APIRouter(prefix="/api/tasks", tags=["tasks"])

class TaskCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100, description="任务名称")
    target_url: str = Field(..., min_length=5, description="目标站点URL")
    config: Optional[Dict[str, Any]] = Field(default_factory=dict, description="爬虫配置项")

class TaskBatchCreateRequest(BaseModel):
    urls: List[str] = Field(..., min_items=1, description="待扫描站点URL列表")
    name_prefix: Optional[str] = Field("", description="自定义任务名称前缀")
    name_template: str = Field("domain", description="命名策略: 'domain' 或 'custom_prefix'")
    auto_start: bool = Field(False, description="是否在创建后立即自动启动扫描")
    config: Optional[Dict[str, Any]] = Field(default_factory=dict, description="爬虫配置项")

class BatchActionRequest(BaseModel):
    task_ids: List[int] = Field(..., min_items=1, description="任务ID列表")
    action: str = Field(..., description="操作类型: start, pause, resume, stop, delete")

from datetime import datetime

def _enrich_task_speed(t: dict, engine: CrawlEngine):
    """Inject current rolling speed and average speed into task dictionary."""
    job = engine.get_job(t["id"])
    if job and t.get("status") == "running":
        speed_info = job.get_speed()
        t["current_speed"] = speed_info["current_speed"]
        t["avg_speed"] = speed_info["avg_speed"]
        t["speed"] = speed_info["current_speed"]
        t["speed_unit"] = speed_info["speed_unit"]
    else:
        t["current_speed"] = 0.0
        t["speed"] = 0.0
        t["speed_unit"] = "页/秒"
        avg_speed = 0.0
        if t.get("started_at") and t.get("finished_at") and t.get("pages_crawled", 0) > 0:
            try:
                t1 = datetime.fromisoformat(t["started_at"])
                t2 = datetime.fromisoformat(t["finished_at"])
                dur = max(0.5, (t2 - t1).total_seconds())
                avg_speed = round(t["pages_crawled"] / dur, 1)
            except Exception:
                pass
        t["avg_speed"] = avg_speed

@router.get("")
def list_all_tasks(limit: int = 50, offset: int = 0):
    tasks, total = crud.list_tasks(limit=limit, offset=offset)
    engine = CrawlEngine.get_instance()
    for t in tasks:
        _enrich_task_speed(t, engine)
    return {"tasks": tasks, "total": total}

@router.post("")
async def create_new_task(req: TaskCreateRequest):
    # Ensure scheme
    url = req.target_url.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    merged_config = {**DEFAULT_CRAWLER_CONFIG, **req.config}
    task_id = crud.create_task(name=req.name.strip(), target_url=url, config=merged_config)
    crud.add_log(task_id, "INFO", f"创建任务成功，目标站点: {url}")

    task = crud.get_task(task_id)
    return {"success": True, "task": task}

@router.post("/batch")
async def create_batch_tasks(req: TaskBatchCreateRequest):
    seen_urls = set()
    tasks_to_create = []

    merged_config = {**DEFAULT_CRAWLER_CONFIG, **(req.config or {})}

    for raw in req.urls:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        
        url = line
        if not url.startswith(("http://", "https://")):
            url = "https://" + url

        if url in seen_urls:
            continue
        seen_urls.add(url)

        host = urlparse(url).netloc.split(":")[0] or url
        if req.name_template == "custom_prefix" and req.name_prefix and req.name_prefix.strip():
            task_name = f"{req.name_prefix.strip()}_{host}"
        elif req.name_prefix and req.name_prefix.strip():
            task_name = f"{req.name_prefix.strip()}_{host}"
        else:
            task_name = f"{host}_扫描"

        tasks_to_create.append({
            "name": task_name,
            "target_url": url,
            "config": merged_config
        })

    if not tasks_to_create:
        raise HTTPException(status_code=400, detail="未提供有效待测站点URL")

    created_tasks = crud.create_tasks_batch(tasks_to_create)

    # Log creation
    for t in created_tasks:
        crud.add_log(t["id"], "INFO", f"批量导入创建任务成功，目标站点: {t['target_url']}")

    # If auto_start is requested, launch tasks asynchronously
    started_count = 0
    if req.auto_start:
        engine = CrawlEngine.get_instance()
        for t in created_tasks:
            try:
                if await engine.start_task(t["id"]):
                    started_count += 1
            except Exception:
                pass

    return {
        "success": True,
        "created_count": len(created_tasks),
        "started_count": started_count,
        "tasks": created_tasks
    }

@router.post("/batch-action")
async def execute_batch_action(req: BatchActionRequest, background_tasks: BackgroundTasks):
    engine = CrawlEngine.get_instance()
    action = req.action.lower()
    affected = 0

    if action == "delete":
        for tid in req.task_ids:
            await engine.cancel_and_clean_task(tid)
        affected = crud.mark_tasks_deleting(req.task_ids)
        background_tasks.add_task(crud.purge_tasks_batch, req.task_ids)
        return {"success": True, "action": "delete", "affected_count": affected, "message": "任务已标记删除，后台正在平滑清理数据"}

    for tid in req.task_ids:
        task = crud.get_task(tid)
        if not task:
            continue
        if action == "start":
            if await engine.start_task(tid):
                affected += 1
        elif action == "pause":
            if engine.pause_task(tid):
                affected += 1
        elif action == "resume":
            if await engine.resume_task(tid):
                affected += 1
        elif action == "stop":
            if engine.stop_task(tid):
                affected += 1

    return {"success": True, "action": action, "affected_count": affected}

@router.get("/{task_id}")
def get_task_by_id(task_id: int):
    task = crud.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    engine = CrawlEngine.get_instance()
    _enrich_task_speed(task, engine)
    return task

@router.post("/{task_id}/start")
async def start_task(task_id: int):
    task = crud.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    
    engine = CrawlEngine.get_instance()
    success = await engine.start_task(task_id)
    if not success:
        raise HTTPException(status_code=400, detail="Failed to start task")
    return {"success": True, "message": "Task started"}

@router.post("/{task_id}/pause")
def pause_task(task_id: int):
    engine = CrawlEngine.get_instance()
    if not engine.pause_task(task_id):
        raise HTTPException(status_code=400, detail="Task is not running or cannot be paused")
    return {"success": True, "message": "Task paused"}

@router.post("/{task_id}/resume")
async def resume_task(task_id: int):
    engine = CrawlEngine.get_instance()
    success = await engine.resume_task(task_id)
    if not success:
        raise HTTPException(status_code=400, detail="Task is not paused or cannot be resumed")
    return {"success": True, "message": "Task resumed"}

@router.post("/{task_id}/stop")
def stop_task(task_id: int):
    engine = CrawlEngine.get_instance()
    engine.stop_task(task_id)
    return {"success": True, "message": "Task stop signal sent"}

@router.post("/{task_id}/retry")
async def retry_task(task_id: int):
    task = crud.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    engine = CrawlEngine.get_instance()
    engine.stop_task(task_id)
    
    # Reset data
    crud.reset_task(task_id)
    crud.add_log(task_id, "INFO", "任务数据已重置，准备重新开始扫描")
    
    # Start again
    await engine.start_task(task_id)
    return {"success": True, "message": "Task restarted"}

@router.delete("/{task_id}")
async def delete_task(task_id: int, background_tasks: BackgroundTasks):
    task = crud.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    engine = CrawlEngine.get_instance()
    await engine.cancel_and_clean_task(task_id)
    crud.mark_task_deleting(task_id)
    background_tasks.add_task(crud.purge_task_data, task_id)
    return {"success": True, "message": "任务已标记删除，后台正在平滑清理"}

# Convenient Export Aliases
from app.api.domains import export_domains_txt, export_domains_csv, export_domains_json
router.add_api_route("/{task_id}/export/txt", export_domains_txt, methods=["GET"])
router.add_api_route("/{task_id}/export/csv", export_domains_csv, methods=["GET"])
router.add_api_route("/{task_id}/export/json", export_domains_json, methods=["GET"])

