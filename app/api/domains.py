import io
import csv
import json
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, HTTPException, Query, Response
from app.db import crud

router = APIRouter(prefix="/api/tasks/{task_id}/domains", tags=["domains"])

@router.get("")
def list_domains(
    task_id: int,
    has_link: Optional[int] = Query(None, description="是否来自链接 (1 或 0)"),
    has_text: Optional[int] = Query(None, description="是否来自非链接文本 (1 或 0)"),
    source_type: Optional[str] = Query(None, description="来源类型 (link, text, asset)"),
    root_domain: Optional[str] = Query(None, description="按主域名筛选"),
    search: Optional[str] = Query(None, description="按域名关键词搜索"),
    sort_by: str = Query("occurrence_count", description="排序字段"),
    order: str = Query("DESC", description="排序方式 ASC/DESC"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0)
):
    task = crud.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    domains, total = crud.list_external_domains(
        task_id=task_id,
        has_link=has_link,
        has_text=has_text,
        source_type=source_type,
        root_domain=root_domain,
        search=search,
        sort_by=sort_by,
        order=order,
        limit=limit,
        offset=offset
    )
    return {"domains": domains, "total": total}

@router.get("/stats")
def get_domain_statistics(task_id: int):
    task = crud.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    stats = crud.get_external_domains_stats(task_id)
    return stats

@router.get("/{domain}/occurrences")
def get_domain_occurrences_api(task_id: int, domain: str, limit: int = 50):
    task = crud.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    occurrences = crud.get_domain_occurrences(task_id, domain, limit=limit)
    return {"domain": domain, "occurrences": occurrences}

@router.get("/{domain}/occurrences/export/csv")
def export_domain_occurrences_csv(task_id: int, domain: str, limit: int = 10000):
    """Export evidence occurrences for a specific domain to CSV with UTF-8 BOM."""
    task = crud.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    occurrences = crud.get_domain_occurrences(task_id, domain, limit=limit)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "外部域名",
        "任务ID",
        "任务名称",
        "目标站点",
        "证据来源属性",
        "发现页面URL",
        "匹配原始字符串",
        "上下文代码片段",
        "记录时间"
    ])
    for o in occurrences:
        writer.writerow([
            domain,
            task_id,
            task.get("name", ""),
            task.get("target_url", ""),
            o.get("source_type", ""),
            o.get("page_url", ""),
            o.get("raw_match", ""),
            o.get("context_snippet", ""),
            o.get("created_at", "")
        ])

    csv_content = "\ufeff" + output.getvalue()
    clean_domain = domain.replace("/", "_").replace("\\", "_").replace(":", "_")
    date_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    return Response(
        content=csv_content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="evidence_{clean_domain}_task{task_id}_{date_str}.csv"'}
    )

@router.get("/{domain}/occurrences/export/json")
def export_domain_occurrences_json(task_id: int, domain: str, limit: int = 10000):
    """Export evidence occurrences for a specific domain to structured JSON."""
    task = crud.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    occurrences = crud.get_domain_occurrences(task_id, domain, limit=limit)
    data = {
        "domain": domain,
        "task_id": task_id,
        "task_name": task.get("name", ""),
        "target_url": task.get("target_url", ""),
        "total_occurrences": len(occurrences),
        "exported_at": datetime.now().isoformat(),
        "occurrences": occurrences
    }
    content = json.dumps(data, ensure_ascii=False, indent=2)
    clean_domain = domain.replace("/", "_").replace("\\", "_").replace(":", "_")
    date_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    return Response(
        content=content,
        media_type="application/json; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="evidence_{clean_domain}_task{task_id}_{date_str}.json"'}
    )

@router.get("/export/txt")
def export_domains_txt(task_id: int):
    """Export deduplicated external domains, one per line."""
    task = crud.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    domains = crud.get_external_domains_for_export(task_id)
    lines = [d["domain"] for d in domains]
    content = "\n".join(lines)
    
    return Response(
        content=content,
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="external_domains_{task_id}.txt"'}
    )

@router.get("/export/csv")
def export_domains_csv(task_id: int):
    task = crud.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    domains = crud.get_external_domains_for_export(task_id)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["域名", "根域名", "出现频次", "包含链接属性", "包含文本/代码", "示例页面URL", "发现时间"])
    for d in domains:
        writer.writerow([
            d["domain"],
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
        headers={"Content-Disposition": f'attachment; filename="external_domains_{task_id}.csv"'}
    )

@router.get("/export/json")
def export_domains_json(task_id: int):
    task = crud.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    domains = crud.get_external_domains_for_export(task_id)
    data = {
        "task_id": task_id,
        "target_url": task["target_url"],
        "total_domains": len(domains),
        "domains": domains
    }
    content = json.dumps(data, ensure_ascii=False, indent=2)
    return Response(
        content=content,
        media_type="application/json; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="external_domains_{task_id}.json"'}
    )

@router.post("/clean")
def clean_invalid_domains_api(task_id: int):
    """Clean and purge pseudo-domains and invalid TLDs for this task."""
    task = crud.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    result = crud.clean_invalid_domains_for_task(task_id)
    return result

