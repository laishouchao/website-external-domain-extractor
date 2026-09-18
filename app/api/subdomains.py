import io
import csv
import json
from typing import Optional
from fastapi import APIRouter, HTTPException, Query, Response
from app.db import crud

router = APIRouter(prefix="/api/tasks/{task_id}/subdomains", tags=["subdomains"])

@router.get("")
def list_subdomains_api(
    task_id: int,
    has_link: Optional[int] = Query(None, description="是否来自链接 (1 或 0)"),
    has_text: Optional[int] = Query(None, description="是否来自非链接文本 (1 或 0)"),
    search: Optional[str] = Query(None, description="按子域名关键词搜索"),
    sort_by: str = Query("occurrence_count", description="排序字段"),
    order: str = Query("DESC", description="排序方式 ASC/DESC"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0)
):
    task = crud.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    subdomains, total = crud.list_subdomains(
        task_id=task_id,
        has_link=has_link,
        has_text=has_text,
        search=search,
        sort_by=sort_by,
        order=order,
        limit=limit,
        offset=offset
    )
    return {"subdomains": subdomains, "total": total}

@router.get("/stats")
def get_subdomain_statistics(task_id: int):
    task = crud.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    stats = crud.get_subdomains_stats(task_id)
    return stats

@router.get("/{subdomain}/occurrences")
def get_subdomain_occurrences_api(task_id: int, subdomain: str, limit: int = 50):
    task = crud.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    occurrences = crud.get_domain_occurrences(task_id, subdomain, limit=limit)
    return {"subdomain": subdomain, "occurrences": occurrences}

@router.get("/export/txt")
def export_subdomains_txt(task_id: int):
    task = crud.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    subdomains = crud.get_subdomains_for_export(task_id)
    lines = [d["subdomain"] for d in subdomains]
    content = "\n".join(lines)
    
    return Response(
        content=content,
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="subdomains_{task_id}.txt"'}
    )

@router.get("/export/csv")
def export_subdomains_csv(task_id: int):
    task = crud.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    subdomains = crud.get_subdomains_for_export(task_id)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["子域名", "根域名", "出现频次", "包含链接属性", "包含文本/代码", "示例页面URL", "发现时间"])
    for d in subdomains:
        writer.writerow([
            d["subdomain"],
            d["root_domain"],
            d["occurrence_count"],
            "是" if d["has_link"] else "否",
            "是" if d["has_text"] else "否",
            d.get("sample_page_url", ""),
            d.get("created_at", "")
        ])

    csv_content = "\ufeff" + output.getvalue()
    return Response(
        content=csv_content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="subdomains_{task_id}.csv"'}
    )

@router.get("/export/json")
def export_subdomains_json(task_id: int):
    task = crud.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    subdomains = crud.get_subdomains_for_export(task_id)
    json_content = json.dumps(subdomains, ensure_ascii=False, indent=2)
    return Response(
        content=json_content,
        media_type="application/json; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="subdomains_{task_id}.json"'}
    )
