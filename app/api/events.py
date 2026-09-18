import asyncio
import json
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from app.db import crud
from app.crawler.engine import CrawlEngine

router = APIRouter(prefix="/api/tasks/{task_id}", tags=["events"])

@router.get("/logs")
def get_task_logs(task_id: int, limit: int = 100):
    task = crud.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    logs = crud.get_recent_logs(task_id, limit=limit)
    return {"logs": logs}

@router.get("/events")
async def stream_task_events(task_id: int):
    task = crud.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    engine = CrawlEngine.get_instance()
    job = engine.get_job(task_id)

    async def event_generator():
        # First send initial status
        current_task = crud.get_task(task_id)
        if current_task:
            yield f"data: {json.dumps({'type': 'init', 'data': current_task})}\n\n"

        # If job is not in memory or not running, yield heartbeat and exit or wait
        if not job or not job.is_running:
            # Yield recent logs
            recent_logs = crud.get_recent_logs(task_id, limit=50)
            for l in recent_logs:
                yield f"data: {json.dumps({'type': 'log', 'data': l})}\n\n"
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
