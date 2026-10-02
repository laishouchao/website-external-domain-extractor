"""
Compliance Audit Evidence & Report Export Module.
Generates Excel-friendly CSV with UTF-8 BOM and packaged ZIP evidence bundles
containing full audit records and high-definition multi-device screenshots.
"""

import os
import io
import csv
import json
import zipfile
from datetime import datetime
from typing import List, Dict, Any, Optional


class ComplianceExportManager:
    def __init__(self, output_dir: str = "output"):
        self.output_dir = output_dir
        self.screenshots_dir = os.path.join(output_dir, "screenshots")

    def generate_csv_report(self, records: List[Dict[str, Any]]) -> bytes:
        """
        导出带有 UTF-8 BOM 的 CSV 报表（确保 Windows Excel 直接打开中文绝不乱码）
        """
        buffer = io.StringIO()
        writer = csv.writer(buffer, quoting=csv.QUOTE_MINIMAL)

        headers = [
            "序号",
            "域名",
            "主任务ID",
            "全库关联引用量",
            "初始检测地址",
            "最终落地URL",
            "跨域跳转检测",
            "研判状态",
            "风险等级",
            "主要违规分类",
            "设备端伪装(Cloaking)",
            "判定依据与存证摘要",
            "审核模型",
            "审核时间",
            "取证截图文件清单"
        ]
        writer.writerow(headers)

        for idx, r in enumerate(records, start=1):
            verdict = r.get("verdict_summary") or {}
            devices = r.get("device_inspections") or []

            # 收集截图路径
            shot_files = []
            final_url_set = set()
            cross_redirect = False

            for dev in devices:
                f_url = dev.get("final_url")
                if f_url:
                    final_url_set.add(f_url)
                if dev.get("is_cross_domain_redirect"):
                    cross_redirect = True
                for s in dev.get("slices", []):
                    s_file = s.get("screenshot_file")
                    if s_file:
                        shot_files.append(os.path.basename(s_file))

            final_url_display = "; ".join(final_url_set) if final_url_set else r.get("url", "")
            shot_display = "; ".join(shot_files) if shot_files else "无截图"

            # 判定描述
            notes = verdict.get("cloaking_notes") or r.get("risk_remark") or ""

            writer.writerow([
                idx,
                r.get("domain", ""),
                r.get("task_id", 0),
                r.get("ref_count", 1),
                r.get("url", f"https://{r.get('domain', '')}"),
                final_url_display,
                "是 (跨域落地)" if (cross_redirect or verdict.get("cross_domain_redirect")) else "否",
                r.get("verify_status") or ("已研判违规" if verdict.get("is_violation") else "已研判合规"),
                verdict.get("overall_risk_level", "SAFE"),
                verdict.get("primary_violation_cn") or verdict.get("primary_violation_category", "正常合规"),
                "疑似伪装" if verdict.get("cloaking_suspected") else "无伪装",
                notes.replace("\r", " ").replace("\n", " "),
                r.get("model_used", "多模态大模型"),
                r.get("checked_at") or r.get("verify_time") or "",
                shot_display
            ])

        # 写入 UTF-8 BOM (0xEF, 0xBB, 0xBF)
        csv_bytes = buffer.getvalue().encode("utf-8")
        return b"\xef\xbb\xbf" + csv_bytes

    def generate_evidence_zip(
        self,
        records: List[Dict[str, Any]],
        include_screenshots: bool = True
    ) -> bytes:
        """
        打包生成包含 CSV 报表、结构化 JSON 及所有关联高清截图的 ZIP 证据链压缩包
        """
        zip_buffer = io.BytesIO()

        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            # 1. 写入汇总 CSV
            csv_bytes = self.generate_csv_report(records)
            zf.writestr("audit_compliance_report.csv", csv_bytes)

            # 2. 写入结构化审计 JSON 清单
            manifest_json = {
                "export_time": datetime.now().isoformat(),
                "total_records": len(records),
                "records": records
            }
            zf.writestr(
                "evidence_manifest.json",
                json.dumps(manifest_json, ensure_ascii=False, indent=2).encode("utf-8")
            )

            # 3. 收集并打包截图文件
            if include_screenshots and os.path.exists(self.screenshots_dir):
                added_files = set()
                for r in records:
                    devices = r.get("device_inspections") or []
                    for dev in devices:
                        for s in dev.get("slices", []):
                            s_file = s.get("screenshot_file")
                            if not s_file:
                                continue
                            filename = os.path.basename(s_file)
                            disk_path = os.path.join(self.screenshots_dir, filename)
                            if os.path.exists(disk_path) and filename not in added_files:
                                zf.write(disk_path, arcname=f"screenshots/{filename}")
                                added_files.add(filename)

        return zip_buffer.getvalue()


GLOBAL_EXPORT_MANAGER = ComplianceExportManager()
