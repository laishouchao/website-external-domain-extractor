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
        受控并发的大模型推理请求调用。
        智能适配多模态视觉模型与对话/推理大模型 (超级小爱 XiaoAi 局域网引擎)。
        """
        if is_mock:
            await asyncio.sleep(0.05)  # 仿真微量异步耗时
            return self._generate_mock_verdict()

        async with self._semaphore:
            is_ollama_native = "/api/chat" in self.api_base
            is_xiaoai = "xiaoai" in self.model.lower()
            is_vision_model = (
                not is_xiaoai
                and (
                    "vl" in self.model.lower()
                    or "vision" in self.model.lower()
                    or "llava" in self.model.lower()
                    or "minicpm" in self.model.lower()
                    or is_ollama_native
                )
            )

            # 提取页面与网络环境上下文
            ctx = context or {}
            target_url = ctx.get("url", "")
            final_url = ctx.get("final_url") or target_url
            device_name = ctx.get("device_name", "通用设备")
            page_title = ctx.get("page_title", "")
            page_text = ctx.get("page_text", "")
            redirect_notes = ctx.get("redirect_notes", "")
            slice_name = ctx.get("slice_name", "")

            prompt_parts = [USER_PROMPT]
            if target_url:
                prompt_parts.append(f"\n【目标 URL】: {target_url}")
            if final_url and final_url != target_url:
                prompt_parts.append(f"【落地页 URL】: {final_url}")
            if device_name:
                prompt_parts.append(f"【访问设备端】: {device_name}")
            if redirect_notes:
                prompt_parts.append(f"【重定向/跳转信息】: {redirect_notes}")
            if page_title:
                prompt_parts.append(f"【网页标题】: {page_title}")
            if slice_name:
                prompt_parts.append(f"【视口切片位置】: {slice_name}")
            if page_text:
                prompt_parts.append(f"【页面文本内容摘要】:\n{page_text[:1600]}")

            composite_user_prompt = "\n".join(prompt_parts)

            if is_ollama_native:
                endpoint_url = self.api_base
                msg_user = {"role": "user", "content": composite_user_prompt}
                if image_base64 and is_vision_model:
                    msg_user["images"] = [image_base64]
                payload = {
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        msg_user
                    ],
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

                if is_vision_model and image_base64:
                    image_url = f"data:image/png;base64,{image_base64}"
                    user_content = [
                        {"type": "text", "text": composite_user_prompt},
                        {"type": "image_url", "image_url": {"url": image_url}}
                    ]
                else:
                    # XiaoAi 局域网大模型引擎或纯文本审查通道
                    user_content = composite_user_prompt

                payload = {
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": user_content}
                    ],
                    "response_format": {"type": "json_object"},
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
        is_violation = bool(data.get("is_violation", False))
        risk_level = str(data.get("risk_level", "SAFE")).upper()
        confidence = float(data.get("confidence", 0.9 if not is_violation else 0.8))
        confidence = max(0.0, min(1.0, confidence))
        primary_violation = str(data.get("primary_violation", "normal" if not is_violation else "unknown"))

        raw_cats = data.get("categories", [])
        normalized_cats = []

        if isinstance(raw_cats, list):
            for cat in raw_cats:
                if isinstance(cat, dict):
                    prob = float(cat.get("probability", 0.0))
                    normalized_cats.append({
                        "key": cat.get("key", "unknown"),
                        "detected": bool(cat.get("detected", prob > 0.5)),
                        "probability": round(max(0.0, min(1.0, prob)), 4),
                        "reason": cat.get("reason", "")
                    })

        return {
            "is_violation": is_violation,
            "risk_level": risk_level,
            "confidence": round(confidence, 4),
            "primary_violation": primary_violation,
            "categories": normalized_cats,
            "violation_details": data.get("violation_details", ""),
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
