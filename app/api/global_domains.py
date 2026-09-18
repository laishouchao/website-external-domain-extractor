import io
import csv
import json
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, HTTPException, Query, Response
from app.db import crud

router = APIRouter(prefix="/api/global-domains", tags=["global-domains"])

@router.get("")
def list_global_domains_api(
    search: Optional[str] = Query(None, description="搜索域名或主根域名"),
    root_domain: Optional[str] = Query(None, description="按主根域名筛选"),
    has_link: Optional[int] = Query(None, description="是否来自链接 (1 或 0)"),
    has_text: Optional[int] = Query(None, description="是否来自非链接文本 (1 或 0)"),
    risk_level: Optional[str] = Query(None, description="按风险级别筛选 (critical, high, medium, low, safe, pending, risk_only)"),
    verify_status: Optional[str] = Query(None, description="按闭环复测状态筛选 (unverified, verified_clean, verified_failed, error)"),
    min_tasks: Optional[int] = Query(None, description="最小关联任务数 (例如 2 表示仅看跨多个任务的公共域名)"),
    sort_by: str = Query("total_occurrences", description="排序字段 (total_occurrences, task_count, domain, root_domain, risk_level, first_seen_at, last_seen_at)"),
    order: str = Query("DESC", description="排序方式 ASC/DESC"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0)
):
    """List aggregated external domains across all tasks."""
    domains, total = crud.list_global_external_domains(
        search=search,
        root_domain=root_domain,
        has_link=has_link,
        has_text=has_text,
        risk_level=risk_level,
        verify_status=verify_status,
        min_tasks=min_tasks,
        sort_by=sort_by,
        order=order,
        limit=limit,
        offset=offset
    )
    return {"domains": domains, "total": total}


@router.get("/stats")
def get_global_domains_stats_api():
    """Get overall global repository statistics."""
    return crud.get_global_domains_stats()


@router.get("/{domain}/tasks")
def get_domain_associated_tasks_api(domain: str):
    """Get all tasks that discovered a specific domain, along with occurrence details."""
    tasks = crud.get_domain_associated_tasks(domain)
    return {
        "domain": domain,
        "total_tasks": len(tasks),
        "tasks": tasks,
        "associated_tasks": tasks
    }


@router.get("/{domain}/tasks/export/csv")
def export_domain_associated_tasks_csv(domain: str):
    """Export all associated tasks and code evidence for a specific domain to CSV with UTF-8 BOM."""
    tasks = crud.get_domain_associated_tasks(domain, max_occurrences_per_task=None)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "外部域名",
        "主根域名",
        "关联任务ID",
        "任务名称",
        "目标站点URL",
        "任务状态",
        "任务内频次",
        "包含链接属性",
        "包含文本代码",
        "示例来源页面",
        "证据来源类型",
        "证据页面URL",
        "匹配原始串",
        "上下文代码片段",
        "发现时间"
    ])

    for t in tasks:
        root_dom = t.get("root_domain", "")
        occurrences = t.get("occurrences", [])
        if occurrences:
            for occ in occurrences:
                writer.writerow([
                    domain,
                    root_dom,
                    t.get("task_id", ""),
                    t.get("task_name", ""),
                    t.get("target_url", ""),
                    t.get("task_status", ""),
                    t.get("occurrence_count", 0),
                    "是" if t.get("has_link") else "否",
                    "是" if t.get("has_text") else "否",
                    t.get("sample_page_url", ""),
                    occ.get("source_type", ""),
                    occ.get("page_url", ""),
                    occ.get("raw_match", ""),
                    occ.get("context_snippet", ""),
                    occ.get("created_at", "")
                ])
        else:
            # Write at least 1 summary line for the task if no occurrences are present
            writer.writerow([
                domain,
                root_dom,
                t.get("task_id", ""),
                t.get("task_name", ""),
                t.get("target_url", ""),
                t.get("task_status", ""),
                t.get("occurrence_count", 0),
                "是" if t.get("has_link") else "否",
                "是" if t.get("has_text") else "否",
                t.get("sample_page_url", ""),
                "",
                "",
                "",
                "",
                t.get("created_at", "")
            ])

    csv_content = "\ufeff" + output.getvalue()
    clean_domain = domain.replace("/", "_").replace("\\", "_").replace(":", "_")
    date_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    return Response(
        content=csv_content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="global_domain_evidence_{clean_domain}_{date_str}.csv"'}
    )


@router.get("/{domain}/tasks/export/json")
def export_domain_associated_tasks_json(domain: str):
    """Export all associated tasks and code evidence for a specific domain to structured JSON."""
    tasks = crud.get_domain_associated_tasks(domain, max_occurrences_per_task=None)
    data = {
        "domain": domain,
        "exported_at": datetime.now().isoformat(),
        "total_tasks": len(tasks),
        "tasks": tasks
    }
    content = json.dumps(data, ensure_ascii=False, indent=2)
    clean_domain = domain.replace("/", "_").replace("\\", "_").replace(":", "_")
    date_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    return Response(
        content=content,
        media_type="application/json; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="global_domain_evidence_{clean_domain}_{date_str}.json"'}
    )


@router.get("/export/txt")
def export_global_domains_txt(
    search: Optional[str] = Query(None),
    root_domain: Optional[str] = Query(None),
    min_tasks: Optional[int] = Query(None)
):
    """Export all aggregated unique external domains, one per line."""
    domains = crud.get_global_domains_for_export(
        search=search,
        root_domain=root_domain,
        min_tasks=min_tasks
    )
    lines = [d["domain"] for d in domains]
    content = "\n".join(lines)
    date_str = datetime.now().strftime("%Y%m%d_%H%M%S")

    return Response(
        content=content,
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="global_external_domains_{date_str}.txt"'}
    )


@router.get("/export/csv")
def export_global_domains_csv(
    search: Optional[str] = Query(None),
    root_domain: Optional[str] = Query(None),
    risk_level: Optional[str] = Query(None),
    min_tasks: Optional[int] = Query(None)
):
    """Export all aggregated external domains to CSV with rich risk and evidence metadata."""
    domains = crud.get_global_domains_for_export(
        search=search,
        root_domain=root_domain,
        risk_level=risk_level,
        min_tasks=min_tasks
    )
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "外部域名(FQDN)",
        "主根域名(Root)",
        "风险等级",
        "风险标签",
        "研判说明",
        "闭环验证状态",
        "验证时间",
        "全局出现总频次",
        "覆盖任务数",
        "包含链接属性",
        "包含文本代码",
        "首次发现时间",
        "最近发现时间",
        "示例页面URL",
        "关联任务概要"
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
        tasks_summary_str = " | ".join([
            f"{t['task_name']} (ID:{t['task_id']}, {t['occurrence_count']}次)"
            for t in d.get("associated_tasks", [])
        ])
        raw_tags = d.get("risk_tags", [])
        tags_str = " / ".join(raw_tags) if isinstance(raw_tags, list) else str(raw_tags)

        writer.writerow([
            d["domain"],
            d["root_domain"],
            risk_label_map.get(d.get("risk_level", ""), d.get("risk_level", "")),
            tags_str,
            d.get("risk_remark", ""),
            verify_label_map.get(d.get("verify_status", ""), d.get("verify_status", "")),
            d.get("verify_time", ""),
            d["total_occurrences"],
            d["task_count"],
            "是" if d["has_link"] else "否",
            "是" if d["has_text"] else "否",
            d.get("first_seen_at", ""),
            d.get("last_seen_at", ""),
            d.get("sample_page_url", ""),
            tasks_summary_str
        ])

    csv_content = "\ufeff" + output.getvalue()
    date_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    return Response(
        content=csv_content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="global_external_domains_{date_str}.csv"'}
    )


@router.get("/export/json")
def export_global_domains_json(
    search: Optional[str] = Query(None),
    root_domain: Optional[str] = Query(None),
    risk_level: Optional[str] = Query(None),
    min_tasks: Optional[int] = Query(None)
):
    """Export all aggregated external domains to JSON with full nested structure."""
    domains = crud.get_global_domains_for_export(
        search=search,
        root_domain=root_domain,
        risk_level=risk_level,
        min_tasks=min_tasks
    )
    stats = crud.get_global_domains_stats()
    date_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    data = {
        "generated_at": datetime.now().isoformat(),
        "total_unique_domains": len(domains),
        "stats": stats,
        "domains": domains
    }
    content = json.dumps(data, ensure_ascii=False, indent=2)
    return Response(
        content=content,
        media_type="application/json; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="global_external_domains_{date_str}.json"'}
    )
