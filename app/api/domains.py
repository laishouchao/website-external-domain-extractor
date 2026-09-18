import io
import csv
import json
from datetime import datetime
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, HTTPException, Query, Response
from app.db import crud

router = APIRouter(prefix="/api/tasks/{task_id}/domains", tags=["domains"])

from pydantic import BaseModel, Field
from app.crawler.risk_engine import verify_domain_remediation

@router.get("")
def list_domains(
    task_id: int,
    has_link: Optional[int] = Query(None, description="是否来自链接 (1 或 0)"),
    has_text: Optional[int] = Query(None, description="是否来自非链接文本 (1 或 0)"),
    source_type: Optional[str] = Query(None, description="来源类型 (link, text, asset)"),
    root_domain: Optional[str] = Query(None, description="按主域名筛选"),
    search: Optional[str] = Query(None, description="按域名关键词搜索"),
    risk_level: Optional[str] = Query(None, description="按风险级别筛选 (critical, high, medium, low, safe, pending, risk_only)"),
    verify_status: Optional[str] = Query(None, description="按闭环复测状态筛选 (unverified, verified_clean, verified_failed, error)"),
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
        risk_level=risk_level,
        verify_status=verify_status,
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

class UpdateDomainRiskRequest(BaseModel):
    risk_level: str = Field(..., description="critical, high, medium, low, safe, pending")
    tags: Optional[List[str]] = Field(default_factory=list)
    remark: Optional[str] = ""
    sync_to_global: Optional[bool] = False
    match_type: Optional[str] = "root"


class BatchUpdateDomainRiskRequest(BaseModel):
    domains: List[str]
    risk_level: str
    tags: Optional[List[str]] = Field(default_factory=list)
    remark: Optional[str] = ""


class BatchVerifyRequest(BaseModel):
    domains: List[str]


@router.post("/{domain}/risk")
def update_domain_risk_api(task_id: int, domain: str, req: UpdateDomainRiskRequest):
    """Manually update risk level and tags for a domain, optionally syncing to global intel."""
    task = crud.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    success = crud.update_external_domain_risk(
        task_id=task_id,
        domain=domain,
        risk_level=req.risk_level,
        tags=req.tags,
        remark=req.remark or "",
        sync_to_global=bool(req.sync_to_global),
        match_type=req.match_type or "root"
    )
    return {"success": success}


@router.post("/batch-risk")
def batch_update_domains_risk_api(task_id: int, req: BatchUpdateDomainRiskRequest):
    """Batch update risk level for multiple domains in this task."""
    task = crud.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    count = crud.batch_update_external_domains_risk(
        task_id=task_id,
        domains=req.domains,
        risk_level=req.risk_level,
        tags=req.tags,
        remark=req.remark or ""
    )
    return {"success": True, "updated_count": count}


@router.post("/{domain}/verify")
async def verify_domain_remediation_api(task_id: int, domain: str):
    """
    Perform one-click targeted verification on historical occurrence pages
    to check if the risk domain code has been completely removed/remediated.
    """
    task = crud.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    urls = crud.get_domain_occurrence_urls(task_id, domain, limit=10)
    verdict = await verify_domain_remediation(domain, urls)

    crud.update_external_domain_verify_result(
        task_id=task_id,
        domain=domain,
        verify_status=verdict["verify_status"],
        verify_time=verdict["verify_time"],
        verify_detail=json.dumps(verdict, ensure_ascii=False)
    )
    return {"success": True, "domain": domain, "verdict": verdict}


@router.post("/batch-verify")
async def batch_verify_domains_api(task_id: int, req: BatchVerifyRequest):
    """Batch verify remediation status for a list of domains."""
    task = crud.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    results = []
    for dom in req.domains[:20]:
        urls = crud.get_domain_occurrence_urls(task_id, dom, limit=5)
        v = await verify_domain_remediation(dom, urls)
        crud.update_external_domain_verify_result(
            task_id=task_id,
            domain=dom,
            verify_status=v["verify_status"],
            verify_time=v["verify_time"],
            verify_detail=json.dumps(v, ensure_ascii=False)
        )
        results.append({
            "domain": dom,
            "verify_status": v["verify_status"],
            "summary": v["summary"]
        })

    return {"success": True, "tested_count": len(results), "results": results}


@router.post("/evaluate-rules")
def evaluate_rules_api(task_id: int):
    """Re-run heuristic rules & threat intel evaluation on all unreviewed domains in this task."""
    task = crud.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    res = crud.evaluate_task_domains_rules(task_id)
    return {"success": True, "result": res}


@router.get("/export/csv")
def export_domains_csv(task_id: int):
    task = crud.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    domains = crud.get_external_domains_for_export(task_id)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "域名", "根域名", "出现频次", "风险等级", "风险标签", "研判说明",
        "闭环复测状态", "复测时间", "包含链接属性", "包含文本/代码", "示例页面URL", "发现时间"
    ])

    risk_label_map = {
        "critical": "严重(Critical)",
        "high": "高危(High)",
        "medium": "中危(Medium)",
        "low": "低危(Low)",
        "safe": "安全(Safe)",
        "pending": "待研判(Pending)"
    }
    verify_label_map = {
        "verified_clean": "已修复/已清除",
        "verified_failed": "未修复/仍存留",
        "unverified": "未复测",
        "error": "复测异常"
    }

    for d in domains:
        raw_tags = d.get("risk_tags", [])
        tags_str = " / ".join(raw_tags) if isinstance(raw_tags, list) else str(raw_tags)
        writer.writerow([
            d["domain"],
            d["root_domain"],
            d["occurrence_count"],
            risk_label_map.get(d.get("risk_level", ""), d.get("risk_level", "")),
            tags_str,
            d.get("risk_remark", ""),
            verify_label_map.get(d.get("verify_status", ""), d.get("verify_status", "")),
            d.get("verify_time", ""),
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


