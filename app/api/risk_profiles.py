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


@router.get("/export")
def export_risk_profiles(
    search: Optional[str] = Query(None, description="搜索过滤"),
    risk_level: Optional[str] = Query(None, description="风险等级过滤")
):
    """
    Export threat intelligence rules in a single unified format strictly matching the batch-import parser:
    Format per line: 域名,风险等级,分类,标签(以/分隔),备注
    Root wildcard domains are prefixed with *.
    """
    profiles, _ = crud.list_risk_profiles(
        search=search,
        risk_level=risk_level,
        limit=100000,
        offset=0
    )
    lines = [
        "# 网站外部域名提取系统 - 风险情报规则库导出文件",
        "# 格式规范: 域名,风险等级,分类,标签(斜杠/分隔),备注说明",
        "# 风险等级支持: critical(严重), high(高危), medium(中危), low(低危), safe(官方安全)",
        "# 规则通配说明: 以 *. 开头表示主根域名通配 (*.domain.com)，无 *. 表示精确子域名匹配",
        "# 本文件可直接在「批量导入」界面中粘贴导入或直接选择文件导入",
    ]
    for p in profiles:
        dom = (p.get("domain") or "").strip()
        if not dom:
            continue
        if p.get("match_type") == "root":
            dom = f"*.{dom}"

        level = p.get("risk_level", "high") or "high"
        category = (p.get("category") or "").replace("\r", " ").replace("\n", " ").replace(",", "，").strip()

        raw_tags = p.get("tags") or []
        if isinstance(raw_tags, list):
            tags_str = "/".join(str(t).strip().replace(",", "，") for t in raw_tags if str(t).strip())
        else:
            tags_str = str(raw_tags).strip().replace(",", "，")

        remark = (p.get("remark") or "").replace("\r", " ").replace("\n", " ").replace(",", "，").strip()

        lines.append(f"{dom},{level},{category},{tags_str},{remark}")

    txt_content = "\ufeff" + "\n".join(lines) + "\n"
    date_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    return Response(
        content=txt_content,
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="risk_rules_{date_str}.txt"'}
    )


@router.get("/export/csv", include_in_schema=False)
@router.get("/export/txt", include_in_schema=False)
def export_risk_profiles_alias(
    search: Optional[str] = Query(None),
    risk_level: Optional[str] = Query(None)
):
    """Backward-compatible alias routing to unified export."""
    return export_risk_profiles(search=search, risk_level=risk_level)


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
