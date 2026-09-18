import io
import csv
import json
from datetime import datetime
from typing import Optional, List
from fastapi import APIRouter, HTTPException, Query, Response
from pydantic import BaseModel, Field
from app.db import crud

router = APIRouter(prefix="/api/risk-profiles", tags=["risk-profiles"])


class CreateProfileRequest(BaseModel):
    domain: str = Field(..., description="根域名或完整子域名，如 *.evil.com 或 badsite.top")
    match_type: str = Field("root", description="'root' (根域通配) 或 'exact' (精确子域)")
    risk_level: str = Field("high", description="'critical', 'high', 'medium', 'low', 'safe'")
    category: Optional[str] = Field("", description="风险分类，如 '黑产博彩', '暗链挂马', '纯IP外链'")
    tags: Optional[List[str]] = Field(default_factory=list, description="风险标签数组")
    remark: Optional[str] = Field("", description="研判依据 / 风险说明")
    sync_to_history: Optional[bool] = Field(True, description="是否立即回溯应用至现有历史任务")


class BatchImportProfilesRequest(BaseModel):
    items: List[CreateProfileRequest] = Field(..., description="规则列表")
    sync_to_history: Optional[bool] = Field(True, description="是否立即回溯应用至现有历史任务")


class UpdateProfileRequest(BaseModel):
    match_type: Optional[str] = None
    risk_level: Optional[str] = None
    category: Optional[str] = None
    tags: Optional[List[str]] = None
    remark: Optional[str] = None


@router.get("")
def list_profiles_api(
    search: Optional[str] = Query(None, description="按域名或备注搜索"),
    risk_level: Optional[str] = Query(None, description="按风险级别筛选"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0)
):
    """List pre-configured risk intelligence rules with pagination and search."""
    profiles, total = crud.list_risk_profiles(
        search=search,
        risk_level=risk_level,
        limit=limit,
        offset=offset
    )
    return {"profiles": profiles, "total": total}


@router.get("/export/csv")
def export_risk_profiles_csv(
    search: Optional[str] = Query(None),
    risk_level: Optional[str] = Query(None)
):
    """Export threat intelligence rules to CSV format."""
    profiles, _ = crud.list_risk_profiles(
        search=search,
        risk_level=risk_level,
        limit=100000,
        offset=0
    )
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["ID", "目标域名", "匹配模式", "风险等级", "风险分类", "风险标签", "来源", "研判说明/依据", "创建时间", "更新时间"])

    risk_label_map = {
        "critical": "严重(Critical)",
        "high": "高危(High)",
        "medium": "中危(Medium)",
        "low": "低危(Low)",
        "safe": "安全(Safe)",
        "pending": "待研判(Pending)"
    }
    match_type_map = {
        "root": "主根域名通配 (*.)",
        "exact": "精确域名匹配"
    }

    for p in profiles:
        raw_tags = p.get("tags") or []
        tags_str = " / ".join(raw_tags) if isinstance(raw_tags, list) else str(raw_tags)
        writer.writerow([
            p["id"],
            p["domain"],
            match_type_map.get(p.get("match_type", "root"), p.get("match_type", "root")),
            risk_label_map.get(p.get("risk_level", "high"), p.get("risk_level", "high")),
            p.get("category", ""),
            tags_str,
            p.get("source", "manual"),
            p.get("remark", ""),
            p.get("created_at", ""),
            p.get("updated_at", "")
        ])

    csv_content = "\ufeff" + output.getvalue()
    date_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    return Response(
        content=csv_content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="risk_intelligence_profiles_{date_str}.csv"'}
    )


@router.get("/export/json")
def export_risk_profiles_json(
    search: Optional[str] = Query(None),
    risk_level: Optional[str] = Query(None)
):
    """Export threat intelligence rules to structured JSON format."""
    profiles, _ = crud.list_risk_profiles(
        search=search,
        risk_level=risk_level,
        limit=100000,
        offset=0
    )
    date_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    data = {
        "exported_at": datetime.now().isoformat(),
        "total_rules": len(profiles),
        "profiles": profiles
    }
    content = json.dumps(data, ensure_ascii=False, indent=2)
    return Response(
        content=content,
        media_type="application/json; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="risk_intelligence_profiles_{date_str}.json"'}
    )


@router.get("/export/txt")
def export_risk_profiles_txt(
    search: Optional[str] = Query(None),
    risk_level: Optional[str] = Query(None)
):
    """Export threat intelligence domains as plain text (one per line)."""
    profiles, _ = crud.list_risk_profiles(
        search=search,
        risk_level=risk_level,
        limit=100000,
        offset=0
    )
    lines = []
    for p in profiles:
        dom = p.get("domain", "")
        if p.get("match_type") == "root":
            dom = f"*.{dom}"
        lines.append(dom)

    txt_content = "\n".join(lines) + ("\n" if lines else "")
    date_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    return Response(
        content=txt_content,
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="risk_domains_{date_str}.txt"'}
    )


@router.post("")
def create_profile_api(req: CreateProfileRequest):
    """Create a new risk intelligence rule, optionally syncing with historical tasks immediately."""
    if not req.domain or not req.domain.strip():
        raise HTTPException(status_code=400, detail="Domain cannot be empty")

    profile = crud.create_risk_profile(
        domain=req.domain,
        match_type=req.match_type,
        risk_level=req.risk_level,
        category=req.category or "",
        tags=req.tags or [],
        remark=req.remark or "",
        source="manual",
        sync_to_history=bool(req.sync_to_history)
    )
    return {"success": True, "profile": profile}


@router.post("/batch")
def batch_import_profiles_api(req: BatchImportProfilesRequest):
    """Batch import multiple risk intelligence domain rules."""
    items = [it.dict() for it in req.items]
    count = crud.batch_import_risk_profiles(items, sync_to_history=bool(req.sync_to_history))
    return {"success": True, "imported_count": count}


@router.get("/{profile_id}")
def get_profile_api(profile_id: int):
    profile = crud.get_risk_profile(profile_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Risk profile not found")
    return profile


@router.put("/{profile_id}")
def update_profile_api(profile_id: int, req: UpdateProfileRequest):
    updates = {k: v for k, v in req.dict().items() if v is not None}
    profile = crud.update_risk_profile(profile_id, updates)
    if not profile:
        raise HTTPException(status_code=404, detail="Risk profile not found")
    return {"success": True, "profile": profile}


@router.delete("/{profile_id}")
def delete_profile_api(profile_id: int):
    success = crud.delete_risk_profile(profile_id)
    if not success:
        raise HTTPException(status_code=404, detail="Risk profile not found")
    return {"success": True}


@router.post("/sync-history")
def sync_history_api():
    """Manually trigger retrospective matching against all historical scan results."""
    result = crud.sync_risk_profiles_to_history()
    return {"success": True, "result": result}
