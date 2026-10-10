"""
Web Compliance Checker - AI Vision Analysis Engine
Pure Vision-Only Auditor using XiaoAi local model (http://192.168.1.190:8787/v1).
Audits screenshot images directly without agent web-browsing capabilities.
"""

import time
import json
import re
import logging
from typing import Dict, Any, Optional
import requests

from config import AI_CONFIG

logger = logging.getLogger("compliance_checker.ai_vision")

VISION_AUDIT_PROMPT = """你是一名资深网络安全与网站合规审计专家。
请仔细观察所提供的网页首屏截图，针对以下类型进行严格研判：
1. 【色情低俗】(pornography): 淫秽色情、裸露、招嫖、低俗暗示
2. 【赌博博彩】(gambling): 线上博彩、棋牌赌博、六合彩、下注、百家乐、真人视讯
3. 【电信诈骗/黑灰产】(fraud): 仿冒银行、虚假理财、刷单兼职、黑客工具、非法数据交易
4. 【暴恐违禁】(violence): 暴力血腥、枪支弹药、管制器具、毒品违禁
5. 【恶意广告/欺诈劫持】(malicious_ad): 虚假中奖诱导、低俗浮窗广告、恶意跳转欺诈
6. 【页面不存在/报错失效】(page_error_404): 404 Not Found、403 Forbidden、500/502报错、域名出售/停放、Nginx默认错误页
7. 【正常合规】(normal): 正规企业、政府机构、教育科研、新闻媒体、正常个人博客等健康合法站点

【极其重要的业务研判准则】：
- 若截图呈现 404 Not Found、页面不存在、无法访问、Nginx/Apache 报错页面，请将 is_404 设为 true，is_violation 设为 false，并将 primary_category 标为 "page_error_404"。
- 仅当明确存在色情、赌博、诈骗、暴恐、恶意欺诈等实质违规内容时，is_violation 才能设为 true。

请严格仅输出如下 JSON 格式字符串，严禁包含任何多余文字或前后缀：
{
  "is_violation": false,
  "is_404": false,
  "risk_level": "pending",
  "primary_category": "normal",
  "primary_category_cn": "正常合规",
  "confidence": 0.95,
  "explanation": "简要说明截图视觉呈现内容与研判理由"
}
"""

class AiVisionAuditor:
    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or AI_CONFIG

    def test_connection(self) -> Dict[str, Any]:
        """Test API connectivity and measure latency."""
        api_base = self.config.get("api_base", "http://192.168.1.190:8787/v1").rstrip("/")
        model = self.config.get("model", "XiaoAi")
        start = time.time()
        try:
            resp = requests.get(f"{api_base}/models", timeout=4)
            latency = int((time.time() - start) * 1000)
            if resp.status_code == 200:
                data = resp.json()
                models = [m.get("id") for m in data.get("data", [])]
                return {
                    "ok": True,
                    "latency_ms": latency,
                    "message": f"连接正常，发现模型: {', '.join(models) or model}",
                    "models": models,
                    "model": model,
                    "api_base": api_base
                }
            return {
                "ok": False,
                "latency_ms": latency,
                "message": f"服务响应异常 HTTP {resp.status_code}: {resp.text[:100]}"
            }
        except Exception as e:
            return {
                "ok": False,
                "latency_ms": int((time.time() - start) * 1000),
                "message": f"无法连接到 API 服务: {e}"
            }

    def audit_image(
        self,
        base64_data_uri: str,
        domain_name: str = "",
        context_hint: str = ""
    ) -> Dict[str, Any]:
        """Send base64 screenshot directly to XiaoAi Vision API."""
        api_base = self.config.get("api_base", "http://192.168.1.190:8787/v1").rstrip("/")
        model = self.config.get("model", "XiaoAi")
        api_key = self.config.get("api_key", "EMPTY")
        timeout = self.config.get("timeout", 35)

        user_content = [
            {"type": "text", "text": f"待研判域名: {domain_name}\n{context_hint}\n{VISION_AUDIT_PROMPT}"},
            {"type": "image_url", "image_url": {"url": base64_data_uri}}
        ]

        payload = {
            "model": model,
            "messages": [
                {"role": "user", "content": user_content}
            ],
            "temperature": 0.1,
            "max_tokens": 800,
        }

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}"
        }

        start_time = time.time()
        try:
            resp = requests.post(
                f"{api_base}/chat/completions",
                json=payload,
                headers=headers,
                timeout=timeout
            )
            elapsed = time.time() - start_time

            if resp.status_code != 200:
                return {
                    "success": False,
                    "is_violation": False,
                    "is_404": False,
                    "risk_level": "pending",
                    "primary_category": "api_error",
                    "primary_category_cn": "API响应异常",
                    "confidence": 0.0,
                    "explanation": f"API 返回错误 HTTP {resp.status_code}: {resp.text[:150]}",
                    "elapsed_sec": elapsed,
                    "model": model,
                }

            result_data = resp.json()
            raw_text = ""
            choices = result_data.get("choices", [])
            if choices:
                raw_text = choices[0].get("message", {}).get("content", "")

            # Parse structured JSON from model response
            parsed = self._parse_json_response(raw_text)
            parsed["elapsed_sec"] = elapsed
            parsed["model"] = model
            parsed["raw_reply"] = raw_text
            parsed["success"] = True
            return parsed

        except Exception as e:
            elapsed = time.time() - start_time
            return {
                "success": False,
                "is_violation": False,
                "is_404": False,
                "risk_level": "pending",
                "primary_category": "network_error",
                "primary_category_cn": "模型调用失败",
                "confidence": 0.0,
                "explanation": f"模型调用失败: {e}",
                "elapsed_sec": elapsed,
                "model": model,
            }

    def _parse_json_response(self, text: str) -> Dict[str, Any]:
        """Robustly extract and normalize JSON object from text."""
        cleaned = text.strip()
        # Remove markdown fences
        if "```" in cleaned:
            match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", cleaned)
            if match:
                cleaned = match.group(1).strip()

        # Try direct parse
        try:
            data = json.loads(cleaned)
            if isinstance(data, dict):
                return self._normalize_result(data, text)
        except Exception:
            pass

        # Try regex search for first { ... }
        match = re.search(r"\{[\s\S]*\}", cleaned)
        if match:
            try:
                data = json.loads(match.group(0))
                if isinstance(data, dict):
                    return self._normalize_result(data, text)
            except Exception:
                pass

        # Keyword-based fallback
        is_404 = bool(re.search(r"404|not found|不存在|未找到|nginx|错误页面", text, re.I))
        is_violation = bool(re.search(r"违规|赌博|博彩|色情|低俗|诈骗|钓鱼|私彩|真钱", text))

        if is_404:
            return {
                "is_violation": False,
                "is_404": True,
                "risk_level": "pending",
                "primary_category": "page_error_404",
                "primary_category_cn": "页面不存在 (404)",
                "confidence": 0.85,
                "explanation": text.strip() or "页面显示404 Not Found不存在"
            }
        elif is_violation:
            return {
                "is_violation": True,
                "is_404": False,
                "risk_level": "high",
                "primary_category": "gambling_or_porn",
                "primary_category_cn": "疑似违法违规",
                "confidence": 0.8,
                "explanation": text.strip() or "截图检测到疑似违规内容"
            }
        else:
            return {
                "is_violation": False,
                "is_404": False,
                "risk_level": "pending",
                "primary_category": "normal",
                "primary_category_cn": "未见明显异常",
                "confidence": 0.75,
                "explanation": text.strip() or "未检出明显违规内容"
            }

    def _normalize_result(self, data: Dict[str, Any], raw_text: str) -> Dict[str, Any]:
        """Normalize parsed dictionary."""
        is_404 = bool(data.get("is_404"))
        category = str(data.get("primary_category", "")).lower()
        explanation = str(data.get("explanation", ""))

        # Auto-detect 404 from text or category
        if "404" in category or "not_found" in category or "404" in explanation.lower() or "not found" in explanation.lower():
            is_404 = True

        is_violation = bool(data.get("is_violation", False))
        if is_404:
            is_violation = False  # 404 is NOT a violation, strictly keep unverified

        cat_cn = data.get("primary_category_cn")
        if not cat_cn:
            if is_404:
                cat_cn = "页面不存在 (404)"
            elif is_violation:
                cat_cn = "违规内容"
            else:
                cat_cn = "未见异常"

        risk_level = "high" if is_violation else "pending"

        return {
            "is_violation": is_violation,
            "is_404": is_404,
            "risk_level": risk_level,
            "primary_category": category or ("page_error_404" if is_404 else "normal"),
            "primary_category_cn": cat_cn,
            "confidence": float(data.get("confidence", 0.9)),
            "explanation": explanation or ("页面显示404 Not Found" if is_404 else "截图内容未见异常"),
        }

GLOBAL_AI_AUDITOR = AiVisionAuditor()
