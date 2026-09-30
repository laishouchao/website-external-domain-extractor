"""
Multimodal LLM Client & Content Safety Analyzer.
Communicates with locally deployed vision-language models (e.g., Qwen2-VL, LLaVA, MiniCPM-V)
via OpenAI-compatible /v1/chat/completions or Ollama APIs.
"""

import json
import re
import urllib.request
import urllib.error
import ssl
from typing import Dict, Any, Optional

from config import SYSTEM_PROMPT, USER_PROMPT, COMPLIANCE_CATEGORIES


class MultimodalSafetyAnalyzer:
    def __init__(
        self,
        api_base: str = "http://localhost:11434/v1",
        api_key: str = "EMPTY",
        model: str = "qwen2-vl",
        timeout: int = 60
    ):
        self.api_base = api_base.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    def _extract_json_from_text(self, text: str) -> Optional[Dict[str, Any]]:
        """
        从模型返回的可能包含 Markdown 或额外解释的文本中稳健提取合法 JSON。
        """
        text = text.strip()
        # 1. 尝试直接解析
        try:
            return json.loads(text)
        except Exception:
            pass

        # 2. 匹配 ```json ... ``` 块
        code_block = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if code_block:
            try:
                return json.loads(code_block.group(1))
            except Exception:
                pass

        # 3. 贪婪匹配第一个 '{' 到最后一个 '}'
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            json_str = text[start : end + 1]
            try:
                return json.loads(json_str)
            except Exception:
                # 修复可能存在的多余逗号等常见格式问题
                cleaned = re.sub(r",\s*([\]}])", r"\1", json_str)
                try:
                    return json.loads(cleaned)
                except Exception:
                    pass

        return None

    def _build_openai_payload(self, image_base64: str) -> Dict[str, Any]:
        """
        构建 OpenAI 兼容的多模态 Chat Completion 请求载荷。
        """
        image_url = f"data:image/png;base64,{image_base64}"
        return {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": SYSTEM_PROMPT
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": USER_PROMPT
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": image_url
                            }
                        }
                    ]
                }
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.05,
            "max_tokens": 512
        }

    def _build_ollama_native_payload(self, image_base64: str) -> Dict[str, Any]:
        """
        兼容 Ollama 原生 /api/chat 载荷。
        """
        return {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": SYSTEM_PROMPT
                },
                {
                    "role": "user",
                    "content": USER_PROMPT,
                    "images": [image_base64]
                }
            ],
            "stream": False,
            "format": "json",
            "options": {
                "temperature": 0.05,
                "num_predict": 512
            }
        }

    def analyze_image(self, image_base64: str, is_mock: bool = False) -> Dict[str, Any]:
        """
        调用本地多模态大模型分析网页截图是否存在违规。
        """
        if is_mock:
            return self._generate_mock_verdict()

        # 判断端点类型
        is_ollama_native = "/api/chat" in self.api_base

        if is_ollama_native:
            endpoint_url = self.api_base
            payload = self._build_ollama_native_payload(image_base64)
        else:
            # 默认为 OpenAI 兼容端点 (如 /v1/chat/completions)
            if self.api_base.endswith("/v1"):
                endpoint_url = f"{self.api_base}/chat/completions"
            elif "/chat/completions" in self.api_base:
                endpoint_url = self.api_base
            else:
                endpoint_url = f"{self.api_base}/v1/chat/completions"
            payload = self._build_openai_payload(image_base64)

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
            "User-Agent": "WebComplianceChecker/1.0"
        }

        req_data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(endpoint_url, data=req_data, headers=headers, method="POST")

        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE

        try:
            with urllib.request.urlopen(request, timeout=self.timeout, context=context) as response:
                resp_bytes = response.read()
                raw_json = json.loads(resp_bytes.decode("utf-8"))

                # 提取模型回答文本
                raw_content = ""
                if is_ollama_native:
                    raw_content = raw_json.get("message", {}).get("content", "")
                else:
                    choices = raw_json.get("choices", [])
                    if choices:
                        raw_content = choices[0].get("message", {}).get("content", "")

                parsed_result = self._extract_json_from_text(raw_content)

                if parsed_result:
                    return self._normalize_verdict(parsed_result, raw_content)
                else:
                    return {
                        "is_violation": False,
                        "risk_level": "UNKNOWN",
                        "confidence": 0.0,
                        "primary_violation": "parse_error",
                        "categories": [],
                        "violation_details": "模型返回内容未能解析为标准 JSON",
                        "raw_model_response": raw_content
                    }

        except urllib.error.URLError as e:
            return {
                "is_violation": False,
                "risk_level": "ERROR",
                "confidence": 0.0,
                "primary_violation": "connection_error",
                "categories": [],
                "violation_details": f"连接本地多模态模型服务端点失败 ({endpoint_url}): {e.reason}",
                "error": str(e)
            }
        except Exception as e:
            return {
                "is_violation": False,
                "risk_level": "ERROR",
                "confidence": 0.0,
                "primary_violation": "unknown_error",
                "categories": [],
                "violation_details": f"模型审核调用异常: {str(e)}",
                "error": str(e)
            }

    def _normalize_verdict(self, data: Dict[str, Any], raw_text: str) -> Dict[str, Any]:
        """
        规范化模型输出，保证字段完整性与概率范围。
        """
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
        elif isinstance(raw_cats, dict):
            for k, v in raw_cats.items():
                if isinstance(v, (int, float)):
                    prob = float(v)
                    normalized_cats.append({
                        "key": k,
                        "detected": prob > 0.5,
                        "probability": round(max(0.0, min(1.0, prob)), 4),
                        "reason": ""
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
        """
        用于无本地大模型环境时的仿真测试。
        """
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
            "violation_details": "【模拟测试响应】页面结构规整，内容健康合法，未识别到违规违法要素。",
            "visual_elements_found": ["导航栏", "正文内容区域", "页脚信息"],
            "raw_model_response": "{\"mock\": true}"
        }
