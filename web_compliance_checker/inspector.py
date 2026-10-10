"""
Web Compliance Checker - Core Inspector & Compliance Decision Engine
Orchestrates Probing -> Multi-Device Capture -> AI Vision -> Cloaking Cross-Check -> Strict DB Persistence.
Strict Rule: Clean and 404 sites strictly stay unverified & pending; only anomalies are flagged verified_failed.
"""

import time
import logging
from typing import Dict, Any, List, Optional

from config import DEVICE_PRESETS, DEVICE_PROFILES
from prober import probe_domain
from capture import GLOBAL_CAPTURE_ENGINE
from ai_vision import GLOBAL_AI_AUDITOR
from db import GLOBAL_DB

logger = logging.getLogger("compliance_checker.inspector")

class DomainInspector:
    def __init__(self):
        self.capture_engine = GLOBAL_CAPTURE_ENGINE
        self.ai_auditor = GLOBAL_AI_AUDITOR
        self.db = GLOBAL_DB

    async def inspect(
        self,
        domain: str,
        devices: List[str] = None,
        enable_probe: bool = True,
        enable_dns: bool = True,
        task_id: int = 0,
        sample_url: str = ""
    ) -> Dict[str, Any]:
        """Run full end-to-end compliance inspection for a single domain."""
        start_time = time.time()
        devices = devices or DEVICE_PRESETS["dual"]
        target_url = sample_url or f"https://{domain}"

        # -------------------------------------------------------------
        # Step 1: Pre-flight Probe & SSRF Check
        # -------------------------------------------------------------
        probe_res = {}
        if enable_probe:
            probe_res = probe_domain(domain, dns_timeout=1.2, http_timeout=2.5)
            # Check SSRF / Intranet Sinkhole -> 安全阻断，保持待研判，绝不误标为违规
            if probe_res.get("is_ssrf"):
                ip_val = probe_res.get("dns", {}).get("ip") or "私有IP"
                self.db.write_inspection_result(
                    domain=domain,
                    is_violation=False,
                    cloaking=False,
                    ssrf=False,
                    is_404=False,
                    primary_violation="内网阻断",
                    risk_level="pending",
                    risk_tags=f"内网阻断({ip_val})",
                    risk_remark=f"目标解析至私有/回环IP: {ip_val}(网关沉洞或安全阻断，保持待研判)",
                    detail_dict={
                        "probe": probe_res,
                        "is_ssrf": True,
                        "reason": f"解析至私有IP ({ip_val})，已安全阻断，未访问外部页面"
                    },
                    task_id=task_id,
                    url=target_url
                )
                return {
                    "domain": domain,
                    "url": target_url,
                    "status": "ssrf_blocked",
                    "is_violation": False,
                    "is_404": False,
                    "cloaking": False,
                    "primary_violation": "内网阻断",
                    "risk_level": "pending",
                    "explanation": f"目标解析至私有/回环IP ({ip_val})，触发安全防穿透阻断（通常为内网网关或 emn-sec 安全设备下发的沉洞地址），未发起外网渲染，状态保持待研判",
                    "probe": probe_res,
                    "device_results": {},
                    "elapsed_sec": time.time() - start_time
                }

            # Check dead link / NXDOMAIN
            if not probe_res.get("alive"):
                # Dead link / NXDOMAIN -> Keep unverified & pending!
                dead_reason = probe_res.get("dead_reason") or "探活不可达"
                self.db.write_inspection_result(
                    domain=domain,
                    is_violation=False,
                    cloaking=False,
                    ssrf=False,
                    is_404=False,
                    primary_violation="探活不可达",
                    risk_level="pending",
                    risk_tags=None,
                    risk_remark=f"{dead_reason}(保持待研判)",
                    detail_dict={"probe": probe_res, "reason": dead_reason},
                    task_id=task_id,
                    url=target_url
                )
                return {
                    "domain": domain,
                    "url": target_url,
                    "status": "dead_link",
                    "is_violation": False,
                    "is_404": False,
                    "cloaking": False,
                    "primary_violation": "探活不可达",
                    "risk_level": "pending",
                    "explanation": f"域名探活不可达: {dead_reason}，状态保持待研判",
                    "probe": probe_res,
                    "device_results": {},
                    "elapsed_sec": time.time() - start_time
                }

        # -------------------------------------------------------------
        # Step 2: Multi-Device Emulation & Dynamic Capture per Device
        # 针对每个端分别发起仿真访问，在每个端内部独立判定是否 404
        # 若某端为 404 则该端跳过截图与大模型；若某端有真实内容则正常截图并研判
        # -------------------------------------------------------------
        captured_devices = await self.capture_engine.capture_devices(
            url=target_url,
            device_keys=devices,
            domain_name=domain
        )

        # -------------------------------------------------------------
        # Step 3: Per-Device Evaluation & AI Vision Inference
        # -------------------------------------------------------------
        device_results = {}
        has_any_violation = False
        all_are_404 = True
        violation_categories = []
        explanations = []

        desktop_violation = False
        mobile_violation = False
        desktop_is_404 = False
        mobile_is_404 = False

        for dev_key, dev_cap in captured_devices.items():
            # 本端独立判定：如果该端响应或页面特征为 404，本端直接跳过截图与大模型！
            if dev_cap.get("is_404"):
                device_results[dev_key] = {
                    "capture": dev_cap,
                    "ai": {
                        "is_violation": False,
                        "is_404": True,
                        "primary_category_cn": "页面不存在 (404)",
                        "explanation": f"[{dev_cap.get('device_name')}]: 页面特征为 404 Not Found，本端已跳过截图与大模型"
                    }
                }
                if dev_cap.get("is_mobile"):
                    mobile_is_404 = True
                else:
                    desktop_is_404 = True
                explanations.append(f"[{dev_cap.get('device_name')}]: 页面显示 404 Not Found (本端跳过截图与AI)")
                continue

            # 本端非 404，因此全端并非都是 404
            all_are_404 = False

            if not dev_cap["success"] or not dev_cap.get("base64_data_uri"):
                device_results[dev_key] = {
                    "capture": dev_cap,
                    "ai": {
                        "is_violation": False,
                        "is_404": False,
                        "explanation": f"截图失败: {dev_cap.get('error')}"
                    }
                }
                continue

            # 本端非 404 且成功截图，送入视觉大模型审核
            ai_res = self.ai_auditor.audit_image(
                base64_data_uri=dev_cap["base64_data_uri"],
                domain_name=domain,
                context_hint=f"仿真设备: {dev_cap.get('device_name')}"
            )

            is_v = ai_res.get("is_violation", False)
            is_4 = ai_res.get("is_404", False)

            if is_v:
                has_any_violation = True
                cat_cn = ai_res.get("primary_category_cn") or "违规内容"
                if cat_cn not in violation_categories:
                    violation_categories.append(cat_cn)

            if dev_cap.get("is_mobile"):
                if is_v:
                    mobile_violation = True
                if is_4:
                    mobile_is_404 = True
            else:
                if is_v:
                    desktop_violation = True
                if is_4:
                    desktop_is_404 = True

            expl = f"[{dev_cap.get('device_name')}]: {ai_res.get('explanation')}"
            explanations.append(expl)

            # 存证信息中剔除冗长 base64，保留元数据与文件路径
            cap_copy = dict(dev_cap)
            cap_copy.pop("base64_data_uri", None)
            device_results[dev_key] = {
                "capture": cap_copy,
                "ai": ai_res
            }

        # -------------------------------------------------------------
        # Step 4: Cloaking Cross-Check (PC 正常/404 vs 移动端 违规)
        # -------------------------------------------------------------
        cloaking_detected = False
        if mobile_violation and (not desktop_violation or desktop_is_404):
            cloaking_detected = True
            has_any_violation = True
            if "设备伪装(Cloaking)" not in violation_categories:
                violation_categories.insert(0, "设备伪装(Cloaking)")

        # -------------------------------------------------------------
        # Step 5: Final Compliance Decision & Persistence
        # -------------------------------------------------------------
        if has_any_violation:
            # Verified Failed Anomaly!
            primary_v = "、".join(violation_categories) or "违法违规内容"
            risk_lvl = "critical" if any(k in primary_v for k in ["赌博", "色情", "诈骗"]) else "high"
            tags = "违规内容," + ",".join(violation_categories)
            remark = f"检出违规异常: {primary_v}"
            if cloaking_detected:
                tags += ",设备端伪装(Cloaking)"
                remark = f"检出隐蔽伪装: 移动端违规 ({primary_v})，PC端展示正常或报错"

            final_status = "violation"
            primary_cat_cn = primary_v
        elif all_are_404:
            # 404 Not Found -> Retain unverified & pending!
            risk_lvl = "pending"
            primary_v = "页面不存在 (404)"
            tags = "页面失效(404)"
            remark = "视觉研判为404报错页面(保持待研判)"
            final_status = "error_404"
            primary_cat_cn = "页面不存在 (404)"
        else:
            # Clean Normal -> Retain unverified & pending!
            risk_lvl = "pending"
            primary_v = "正常合规"
            tags = None
            remark = "多端视觉研判未见异常(保持待研判)"
            final_status = "clean_pending"
            primary_cat_cn = "未见异常"

        full_explanation = "\n".join(explanations) or "研判完成"

        detail_dict = {
            "probe": probe_res,
            "device_results": device_results,
            "is_violation": has_any_violation,
            "is_404": all_are_404,
            "cloaking_suspected": cloaking_detected,
            "primary_violation_cn": primary_cat_cn,
            "explanation": full_explanation,
            "model": self.ai_auditor.config.get("model", "XiaoAi"),
            "checked_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "device_count": len(devices),
        }

        # Write to Database
        self.db.write_inspection_result(
            domain=domain,
            is_violation=has_any_violation,
            cloaking=cloaking_detected,
            ssrf=False,
            is_404=all_are_404,
            primary_violation=primary_v,
            risk_level=risk_lvl,
            risk_tags=tags or "",
            risk_remark=remark,
            detail_dict=detail_dict,
            task_id=task_id,
            url=target_url
        )

        return {
            "domain": domain,
            "url": target_url,
            "status": final_status,
            "is_violation": has_any_violation,
            "is_404": all_are_404,
            "cloaking": cloaking_detected,
            "primary_violation": primary_cat_cn,
            "risk_level": risk_lvl,
            "explanation": full_explanation,
            "probe": probe_res,
            "device_results": device_results,
            "elapsed_sec": time.time() - start_time
        }

GLOBAL_INSPECTOR = DomainInspector()
