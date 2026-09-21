import io
import csv
import json
import urllib.parse
from datetime import datetime
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, HTTPException, Query, Response
from pydantic import BaseModel, Field

from app.db import crud
from app.crawler.risk_verifier import verify_single_risk_page, PeriodicRiskVerifier

router = APIRouter(prefix="/api/risk-remediation", tags=["risk-remediation"])


class BatchManualStatusRequest(BaseModel):
    ids: List[int]
    manual_status: str
    manual_remark: Optional[str] = ""


class SingleVerifyRequest(BaseModel):
    pass


def get_remediation_guide(source_type: str, domain: str, risk_level: str) -> str:
    """Generate specific, professional remediation guidance for staff."""
    st = (source_type or "").lower()
    if "script" in st or "js" in st:
        return (
            f"【静态脚本/JS代码排查】\n"
            f"1. 打开涉险页面源码或引用的 JS 资源，查找包含 '{domain}' 的外部引入或链接。\n"
            f"2. 若属于被篡改植入或失效废弃的第三方库代码，请直接删除引用，或下载安全版本置于本单位服务器本地加载。\n"
            f"3. 部署后更新前端缓存，确保页面外呼已切断。"
        )
    elif "iframe" in st:
        return (
            f"【暗链/Frame植入排查】\n"
            f"1. 页面中存在指向 '{domain}' 的 <iframe> 嵌入框架，极可能是暗链或恶意劫持投放。\n"
            f"2. 请立即登录网站后台或直接编辑网页模板，删除涉嫌违规的 iframe 标签。\n"
            f"3. 建议对该网页管理权限进行密码重置与安全加固。"
        )
    elif "img" in st or "image" in st:
        return (
            f"【外链图片排查】\n"
            f"1. 页面中直接引用了指向 '{domain}' 的外部图片链接。\n"
            f"2. 请将所需图片下载并转存至本单位自建附件库/静态资源服务器，修改 <img> 标签 src 属性。\n"
            f"3. 避免依赖不可控的第三方域名提供图床。"
        )
    elif "href" in st or "a" in st:
        return (
            f"【超链接处置建议】\n"
            f"1. 登录网站内容管理系统(CMS)，找到本页面的正文或导航栏。\n"
            f"2. 查找并删除指向 '{domain}' 的 <a> 锚点超链接；若为必要引用，请核实其目标地址并替换为官方或权威链接。\n"
            f"3. 保存发布后，点击系统中的【重新校验】验证清除结果。"
        )
    else:
        return (
            f"【综合处置建议】\n"
            f"1. 检查页面 HTML 及内嵌资源中对 '{domain}' 的引用并予以清除。\n"
            f"2. 若该页面为陈旧历史通知或无用测试页面，建议直接在 Web 服务器中将该页面删除并配置 404/410 状态码下线。"
        )


@router.get("/pages")
def list_risk_remediation_pages(
    task_id: Optional[int] = Query(None, description="按所属扫描任务ID筛选"),
    risk_level: Optional[str] = Query(None, description="按风险级别筛选: all_risk, critical, high, medium, low"),
    verify_status: Optional[str] = Query("pending_only", description="按复测状态筛选: pending_only, unverified, verified_failed, verified_clean, page_removed, error"),
    manual_status: Optional[str] = Query(None, description="按工单处置状态: pending, in_progress, resolved, ignored"),
    search: Optional[str] = Query(None, description="按页面URL、域名、页面标题、任务名搜索"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500)
):
    """
    List risk remediation pages with multi-dimensional filtering and pagination.
    """
    offset = (page - 1) * page_size
    items, total = crud.list_risk_remediations(
        task_id=task_id,
        risk_level=risk_level,
        verify_status=verify_status,
        manual_status=manual_status,
        search=search,
        limit=page_size,
        offset=offset
    )

    # Attach remediation suggestion to each item
    for it in items:
        it["remediation_guide"] = get_remediation_guide(
            source_type=it.get("source_type", ""),
            domain=it.get("domain", ""),
            risk_level=it.get("risk_level", "")
        )

    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": (total + page_size - 1) // page_size if page_size > 0 else 0
    }


@router.get("/stats")
def get_risk_remediation_stats():
    """
    Get aggregated dashboard stats for the risk remediation view.
    """
    return crud.get_risk_remediations_stats()


@router.get("/timer-status")
def get_timer_status():
    """
    Get the 10-minute periodic verifier's operational status and next run countdown.
    """
    verifier = PeriodicRiskVerifier.get_instance()
    return verifier.get_status()


@router.post("/trigger-verify")
def trigger_periodic_verify():
    """
    Manually trigger an immediate batch verification cycle of all pending risk pages.
    """
    verifier = PeriodicRiskVerifier.get_instance()
    res = verifier.trigger_now()
    return res


@router.post("/{remediation_id}/verify")
async def verify_page_endpoint(remediation_id: int):
    """
    On-demand verification of a single risk page.
    """
    res = await verify_single_risk_page(remediation_id)
    if "error" in res and res.get("verify_status") == "error" and res.get("error") == "Record not found":
        raise HTTPException(status_code=404, detail="Risk page remediation record not found")
    return res


@router.post("/batch-status")
def batch_update_status(req: BatchManualStatusRequest):
    """
    Batch update manual handling state (e.g. mark as resolved, in_progress, ignored).
    """
    if not req.ids:
        return {"updated_count": 0}
    count = crud.batch_update_risk_remediations_manual_status(
        ids=req.ids,
        manual_status=req.manual_status,
        manual_remark=req.manual_remark
    )
    return {"updated_count": count}


@router.post("/sync")
def sync_occurrences_endpoint(task_id: Optional[int] = Query(None)):
    """
    Manually trigger occurrence extraction into the risk remediation table.
    """
    res = crud.sync_risk_pages_from_occurrences(task_id=task_id)
    return res


@router.get("/export")
def export_risk_remediations(
    task_id: Optional[int] = Query(None, description="按扫描任务ID导出，留空则导出全部"),
    verify_status: Optional[str] = Query("pending_only", description="按状态导出: pending_only, all, verified_failed, etc."),
    risk_level: Optional[str] = Query(None, description="按风险级别导出")
):
    """
    Export risk remediation list into a standard UTF-8 BOM CSV spreadsheet.
    Includes full page URL, offending domain, code evidence snippet, and professional remediation guidance.
    """
    v_status = None if verify_status == "all" else verify_status
    rows = crud.get_risk_remediations_for_export(
        task_id=task_id,
        verify_status=v_status,
        risk_level=risk_level
    )

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "工单序号",
        "所属任务ID",
        "所属任务名称",
        "被测站点入口",
        "涉险页面完整URL",
        "涉险页面标题",
        "违规外链域名",
        "主根域名",
        "风险等级",
        "风险标签",
        "研判说明",
        "外链代码载体",
        "源代码存证切片/位置片段",
        "复测闭环状态",
        "最近复测时间",
        "复测检测结论",
        "人工处置状态",
        "处置建议及整改指引"
    ])

    status_labels = {
        "unverified": "待复测 (未完成)",
        "verified_failed": "未修复 (风险仍残留)",
        "verified_clean": "已修复 (外链已清除)",
        "page_removed": "已下线 (页面404/删除)",
        "error": "访问异常 (超时/无法连接)"
    }

    risk_labels = {
        "critical": "极危",
        "high": "高危",
        "medium": "中危",
        "low": "低危",
        "safe": "安全"
    }

    for idx, r in enumerate(rows, start=1):
        tags_raw = r.get("risk_tags") or "[]"
        if isinstance(tags_raw, str):
            try:
                tags_list = json.loads(tags_raw)
            except Exception:
                tags_list = [tags_raw]
        else:
            tags_list = tags_raw
        tags_str = "、".join(tags_list) if isinstance(tags_list, list) else str(tags_list)

        r_level_str = risk_labels.get(r.get("risk_level"), r.get("risk_level", ""))
        v_status_str = status_labels.get(r.get("verify_status"), r.get("verify_status", ""))

        guide = get_remediation_guide(
            source_type=r.get("source_type", ""),
            domain=r.get("domain", ""),
            risk_level=r.get("risk_level", "")
        )

        writer.writerow([
            idx,
            r.get("task_id", ""),
            r.get("task_name", ""),
            r.get("target_site_url", ""),
            r.get("page_url", ""),
            r.get("page_title", ""),
            r.get("domain", ""),
            r.get("root_domain", ""),
            r_level_str,
            tags_str,
            r.get("risk_remark", ""),
            r.get("source_type", ""),
            r.get("context_snippet", ""),
            v_status_str,
            r.get("last_verified_at", ""),
            r.get("last_verify_detail", ""),
            r.get("manual_status", "pending"),
            guide
        ])

    csv_data = output.getvalue().encode("utf-8-sig")

    time_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    task_prefix = f"任务{task_id}_" if task_id else "全部任务_"
    filename = f"风险页面待处置工单_{task_prefix}{time_str}.csv"
    encoded_filename = urllib.parse.quote(filename)

    headers = {
        "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_filename}",
        "Content-Type": "text/csv; charset=utf-8-sig"
    }

    return Response(content=csv_data, headers=headers)
