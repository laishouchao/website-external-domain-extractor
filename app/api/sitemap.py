import io
import csv
from typing import Optional
from fastapi import APIRouter, HTTPException, Query, Response
from app.db import crud

router = APIRouter(prefix="/api/tasks/{task_id}/pages", tags=["sitemap"])

@router.get("")
def get_sitemap_pages(
    task_id: int,
    depth: Optional[int] = Query(None, description="按深度筛选"),
    status_code: Optional[int] = Query(None, description="按HTTP状态码筛选"),
    search: Optional[str] = Query(None, description="按URL或标题搜索"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0)
):
    task = crud.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    pages, total = crud.list_pages(
        task_id=task_id,
        depth=depth,
        status_code=status_code,
        search=search,
        limit=limit,
        offset=offset
    )
    return {"pages": pages, "total": total}

@router.get("/export/xml")
def export_sitemap_xml(task_id: int):
    task = crud.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    pages = crud.get_all_pages_urls(task_id)
    
    xml_lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
    ]
    for p in pages:
        # Only include successfully retrieved web pages (2xx / 3xx), exclude static script/style assets
        if p["status_code"] and 200 <= p["status_code"] < 400:
            ctype = (p.get("content_type") or "").lower()
            if "javascript" in ctype or "css" in ctype or p["url"].lower().endswith(('.js', '.css')):
                continue
            url = p["url"].replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            lastmod = p["crawled_at"].split()[0] if p.get("crawled_at") else ""
            xml_lines.append("  <url>")
            xml_lines.append(f"    <loc>{url}</loc>")
            if lastmod:
                xml_lines.append(f"    <lastmod>{lastmod}</lastmod>")
            xml_lines.append("  </url>")
    xml_lines.append("</urlset>")

    xml_content = "\n".join(xml_lines)
    return Response(
        content=xml_content,
        media_type="application/xml",
        headers={"Content-Disposition": f'attachment; filename="sitemap_task_{task_id}.xml"'}
    )

@router.get("/export/csv")
def export_pages_csv(task_id: int):
    task = crud.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    pages = crud.get_all_pages_urls(task_id)
    
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["ID", "URL", "Path", "Depth", "Status Code", "Title", "Crawled At"])
    for p in pages:
        writer.writerow([
            p["id"],
            p["url"],
            p["path"],
            p["depth"],
            p["status_code"],
            p.get("title", ""),
            p.get("crawled_at", "")
        ])

    csv_content = "\ufeff" + output.getvalue()  # UTF-8 with BOM for Excel compatibility
    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="pages_task_{task_id}.csv"'}
    )
