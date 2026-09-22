import asyncio
import json
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from app.db import crud
from app.crawler.engine import CrawlEngine

router = APIRouter(prefix="/api/tasks/{task_id}", tags=["events"])

@router.get("/logs")
async def get_task_logs(task_id: int, limit: int = 100):
    task = await asyncio.to_thread(crud.get_task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    logs = await asyncio.to_thread(crud.get_recent_logs, task_id, limit=limit)
    return {"logs": logs}

@router.get("/events")
async def stream_task_events(task_id: int):
    task = await asyncio.to_thread(crud.get_task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    engine = CrawlEngine.get_instance()
    job = engine.get_job(task_id)

    async def event_generator():
        # First send initial status
        yield f"data: {json.dumps({'type': 'init', 'data': task})}\n\n"

        # If job is not in memory or not running, yield recent logs, status, and clean terminal event
        if not job or not job.is_running:
            recent_logs = await asyncio.to_thread(crud.get_recent_logs, task_id, 50)
            for l in recent_logs:
                yield f"data: {json.dumps({'type': 'log', 'data': l})}\n\n"
            final_status = task.get("status") or "completed"
            yield f"data: {json.dumps({'type': 'complete', 'data': {'status': final_status}})}\n\n"
            return

        # Subscribe to live job stream
        subscriber_queue = job.add_subscriber()
        try:
            while True:
                try:
                    # Wait for message with timeout to send keepalive
                    msg = await asyncio.wait_for(subscriber_queue.get(), timeout=15.0)
                    yield f"data: {json.dumps(msg, ensure_ascii=False)}\n\n"
                    if msg.get("type") in ("complete", "error"):
                        break
                except asyncio.TimeoutError:
                    # Send comment keep-alive
                    yield ": ping\n\n"
        finally:
            job.remove_subscriber(subscriber_queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )
