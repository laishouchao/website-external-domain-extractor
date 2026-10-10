"""
Asynchronous Multimodal LLM Client with bounded concurrency for GPU protection.
Supports OpenAI /v1/chat/completions and Ollama /api/chat endpoints.
"""

import json
import re
import asyncio
import urllib.request
import urllib.error
import ssl
import os
import sys

_pkg_dir = os.path.dirname(os.path.abspath(__file__))
if _pkg_dir not in sys.path:
    sys.path.insert(0, _pkg_dir)

from config import SYSTEM_PROMPT, USER_PROMPT, DEFAULT_AI_CONFIG


class AsyncMultimodalSafetyAnalyzer:
    def __init__(
        self,
        api_base: Optional[str] = None,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        max_concurrency: int = 2,
        timeout: int = 60
    ):
        self.api_base = (api_base or DEFAULT_AI_CONFIG.get("api_base", "http://192.168.1.190:8787/v1")).rstrip("/")
        self.api_key = api_key or DEFAULT_AI_CONFIG.get("api_key", "EMPTY")
        self.model = model or DEFAULT_AI_CONFIG.get("model", "XiaoAi")
        self.timeout = timeout
        self._semaphore = asyncio.Semaphore(max_concurrency)

    def _extract_json_from_text(self, text: str) -> Optional[Dict[str, Any]]:
        text = text.strip()
        try:
            return json.loads(text)
        except Exception:
            pass

        code_block = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if code_block:
            try:
                return json.loads(code_block.group(1))
            except Exception:
                pass

        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            json_str = text[start : end + 1]
            try:
                return json.loads(json_str)
            except Exception:
                cleaned = re.sub(r",\s*([\]}])", r"\1", json_str)
                try:
                    return json.loads(cleaned)
                except Exception:
                    pass

        return None

    def _sync_http_post(self, endpoint_url: str, payload: Dict[str, Any]) -> str:
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
            "User-Agent": "WebComplianceCheckerAsync/2.0"
        }
        req_data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(endpoint_url, data=req_data, headers=headers, method="POST")

        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE

        with urllib.request.urlopen(request, timeout=self.timeout, context=context) as response:
            resp_bytes = response.read()
            return resp_bytes.decode("utf-8")

    async def analyze_image_async(
        self,
        image_base64: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
        is_mock: bool = False
    ) -> Dict[str, Any]:
        """
        受控并发的截图视觉大模型推理。
        直接将由 Playwright 截取的网页视觉图片 (image_url base64) 传入多模态大模型，
        大模型仅作为视觉判定引擎直接审视图片内容，不进行任何网络访问。
        """
        if is_mock:
            await asyncio.sleep(0.05)  # 仿真微量异步耗时
            return self._generate_mock_verdict()

        async with self._semaphore:
            is_ollama_native = "/api/chat" in self.api_base

            # 纯视觉审核 Prompt：让大模型直接对输入的截图画面进行合规审查，返回标准结构化 JSON
            audit_prompt = (
                "审查此网页截图是否合规。严格以JSON返回判定结果（需包含 is_violation, risk_level, confidence, primary_violation, violation_details 字段）："
            )

            if is_ollama_native:
                endpoint_url = self.api_base
                msg_user = {"role": "user", "content": audit_prompt}
                if image_base64:
                    msg_user["images"] = [image_base64]
                payload = {
                    "model": self.model,
                    "messages": [msg_user],
                    "stream": False,
                    "format": "json",
                    "options": {"temperature": 0.05, "num_predict": 512}
                }
            else:
                if self.api_base.endswith("/v1"):
                    endpoint_url = f"{self.api_base}/chat/completions"
                elif "/chat/completions" in self.api_base:
                    endpoint_url = self.api_base
                else:
                    endpoint_url = f"{self.api_base}/v1/chat/completions"

                if image_base64:
                    # 标准 Vision 接口：直接传入网页截图与视觉合规判定要求
                    user_content = [
                        {"type": "text", "text": audit_prompt},
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_base64}"}}
                    ]
                else:
                    user_content = [{"type": "text", "text": audit_prompt}]

                payload = {
                    "model": self.model,
                    "messages": [
                        {"role": "user", "content": user_content}
                    ],
                    "temperature": 0.05
                }

            try:
                # 在异步线程池中执行 HTTP 请求，避免阻塞主事件循环
                raw_response_str = await asyncio.to_thread(self._sync_http_post, endpoint_url, payload)
                raw_json = json.loads(raw_response_str)

                raw_content = ""
                if is_ollama_native:
                    raw_content = raw_json.get("message", {}).get("content", "")
                else:
                    choices = raw_json.get("choices", [])
                    if choices:
                        raw_content = choices[0].get("message", {}).get("content", "")

                parsed = self._extract_json_from_text(raw_content)
                if parsed:
                    return self._normalize_verdict(parsed, raw_content)
                else:
                    return {
                        "is_violation": False,
                        "risk_level": "UNKNOWN",
                        "confidence": 0.0,
                        "primary_violation": "parse_error",
                        "categories": [],
                        "violation_details": "模型回复未能解析为标准 JSON 格式",
                        "raw_model_response": raw_content
                    }

            except urllib.error.URLError as e:
                return {
                    "is_violation": False,
                    "risk_level": "ERROR",
                    "confidence": 0.0,
                    "primary_violation": "connection_error",
                    "categories": [],
                    "violation_details": f"连接本地多模态服务失败: {e.reason}",
                    "error": str(e)
                }
            except Exception as e:
                return {
                    "is_violation": False,
                    "risk_level": "ERROR",
                    "confidence": 0.0,
                    "primary_violation": "unknown_error",
                    "categories": [],
                    "violation_details": f"审核推理异常: {str(e)}",
                    "error": str(e)
                }

    def _normalize_verdict(self, data: Dict[str, Any], raw_text: str) -> Dict[str, Any]:
        if "判定" in data:
            is_violation = data.get("判定") in ("违规", "不合规", "违法")
            violation_details = data.get("原因", "") or data.get("说明", "")
        else:
            is_violation = bool(data.get("is_violation", False))
            violation_details = data.get("violation_details", "") or data.get("reason", "")

        if "risk_level" in data:
            risk_level = str(data.get("risk_level", "SAFE")).upper()
        else:
            risk_level = "HIGH" if is_violation else "SAFE"

        confidence = float(data.get("confidence", 0.95 if not is_violation else 0.85))
        confidence = max(0.0, min(1.0, confidence))

        primary_violation = str(
            data.get("primary_violation", data.get("违规类型", "normal" if not is_violation else "unknown"))
        )

        raw_cats = data.get("categories", [])
        normalized_cats = []

        if isinstance(raw_cats, list) and raw_cats:
            for cat in raw_cats:
                if isinstance(cat, dict):
                    prob = float(cat.get("probability", 0.0))
                    normalized_cats.append({
                        "key": cat.get("key", "unknown"),
                        "detected": bool(cat.get("detected", prob > 0.5)),
                        "probability": round(max(0.0, min(1.0, prob)), 4),
                        "reason": cat.get("reason", "")
                    })
        else:
            for cat_key in ["pornography_vulgarity", "gambling_lottery", "fraud_scam", "violence_contraband", "political_extremism", "malicious_adware"]:
                is_hit = is_violation and (cat_key in primary_violation)
                normalized_cats.append({
                    "key": cat_key,
                    "detected": is_hit,
                    "probability": 0.95 if is_hit else 0.01,
                    "reason": violation_details if is_hit else "截图未检出该项违规"
                })

        return {
            "is_violation": is_violation,
            "risk_level": risk_level,
            "confidence": round(confidence, 4),
            "primary_violation": primary_violation,
            "categories": normalized_cats,
            "violation_details": violation_details,
            "visual_elements_found": data.get("visual_elements_found", []),
            "raw_model_response": raw_text
        }

    def _generate_mock_verdict(self) -> Dict[str, Any]:
        return {
            "is_violation": False,
            "risk_level": "SAFE",
            "confidence": 0.98,
            "primary_violation": "normal",
            "categories": [
                {"key": "pornography_vulgarity", "detected": False, "probability": 0.001, "reason": "未见低俗裸露画面"},
                {"key": "gambling_lottery", "detected": False, "probability": 0.002, "reason": "未见博彩转盘或筹码赔率宣传"},
                {"key": "fraud_scam", "detected": False, "probability": 0.005, "reason": "未见虚假中奖或钓鱼诱导"},
                {"key": "violence_contraband", "detected": False, "probability": 0.001, "reason": "未见暴恐违禁品"},
                {"key": "political_extremism", "detected": False, "probability": 0.001, "reason": "未见涉政不良内容"},
                {"key": "malicious_adware", "detected": False, "probability": 0.010, "reason": "未见强制全屏弹窗或欺诈跳转"}
            ],
            "violation_details": "【高并发模拟测试】页面内容健康合法，未识别到违规要素。",
            "visual_elements_found": ["导航栏", "正文内容", "页脚信息"],
            "raw_model_response": "{\"mock\": true}"
        }
