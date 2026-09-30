"""
Fully decoupled asynchronous pipeline (True Producer-Consumer Architecture)
with Multi-Slice Viewport Auditing (Smart Tiling & Height Clamping).
"""

import os
import json
import asyncio
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional, Callable

from config import DEVICE_PROFILES, COMPLIANCE_CATEGORIES, CONCURRENCY_CONFIG
from browser_pool import AsyncBrowserPool
from async_screenshot import AsyncScreenshotEngine
from async_llm_analyzer import AsyncMultimodalSafetyAnalyzer


def aggregate_device_results(url: str, device_inspections: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    聚合单 URL 在所有设备端（及各设备切片）下的审核结果，识别 Cloaking 并计算总风险
    """
    successful_runs = [d for d in device_inspections if d.get("capture_status") == "success"]
    violations = [d for d in successful_runs if d.get("model_verdict", {}).get("is_violation") is True]

    has_violation = len(violations) > 0

    category_summary: Dict[str, Dict[str, Any]] = {}
    for cat in COMPLIANCE_CATEGORIES:
        category_summary[cat["key"]] = {
            "name_cn": cat["name_cn"],
            "max_probability": 0.0,
            "detected_in_devices": []
        }

    for dev in successful_runs:
        verdict = dev.get("model_verdict", {})
        dev_name = dev["device_name"]
        for c in verdict.get("categories", []):
            k = c.get("key")
            if k in category_summary:
                prob = c.get("probability", 0.0)
                if prob > category_summary[k]["max_probability"]:
                    category_summary[k]["max_probability"] = prob
                if c.get("detected") is True:
                    category_summary[k]["detected_in_devices"].append(dev_name)

    # Cloaking 伪装检测
    desktop_viols = [d for d in violations if not d.get("is_mobile")]
    mobile_viols = [d for d in violations if d.get("is_mobile")]

    cloaking_detected = False
    cloaking_notes = ""
    if len(desktop_viols) == 0 and len(mobile_viols) > 0:
        cloaking_detected = True
        cloaking_notes = "检测到设备端伪装：PC端页面正常，但移动端UA下检测到违规违法内容！"
    elif len(desktop_viols) > 0 and len(mobile_viols) == 0:
        cloaking_detected = True
        cloaking_notes = "PC端检测到违规，移动端显示正常。"

    risk_hierarchy = ["SAFE", "LOW", "MEDIUM", "HIGH", "CRITICAL"]
    highest_risk = "SAFE"
    highest_risk_idx = 0

    for dev in successful_runs:
        risk = dev.get("model_verdict", {}).get("risk_level", "SAFE").upper()
        if risk in risk_hierarchy:
            idx = risk_hierarchy.index(risk)
            if idx > highest_risk_idx:
                highest_risk_idx = idx
                highest_risk = risk

    if cloaking_detected and highest_risk_idx < 3:
        highest_risk = "HIGH"

    primary_category = "normal"
    highest_prob = 0.0
    for k, v in category_summary.items():
        if v["max_probability"] > highest_prob:
            highest_prob = v["max_probability"]
            primary_category = k

    if not has_violation:
        primary_category = "normal"

    return {
        "is_violation": has_violation,
        "overall_risk_level": highest_risk,
        "primary_violation_category": primary_category,
        "cloaking_suspected": cloaking_detected,
        "cloaking_notes": cloaking_notes,
        "category_probabilities": {
            k: {
                "name": v["name_cn"],
                "max_probability": round(v["max_probability"], 4),
                "is_detected": len(v["detected_in_devices"]) > 0,
                "detected_devices": v["detected_in_devices"]
            }
            for k, v in category_summary.items()
        },
        "stats": {
            "total_tested_devices": len(device_inspections),
            "successful_captures": len(successful_runs),
            "violation_device_count": len(violations)
        }
    }


class DeviceInspectionCollector:
    """
    单个设备在多切片（Slices）场景下的结果收集与合并器
    """
    def __init__(self, device_id: str, device_name: str, total_slices: int, base_device_info: Dict[str, Any]):
        self.device_id = device_id
        self.device_name = device_name
        self.total_slices = total_slices
        self.base_info = base_device_info
        self.slice_results: List[Dict[str, Any]] = []

    def add_slice_result(self, slice_info: Dict[str, Any], verdict: Dict[str, Any]):
        self.slice_results.append({
            "slice_id": slice_info.get("slice_id", "top"),
            "slice_name": slice_info.get("slice_name", "首屏视口"),
            "screenshot_path": slice_info.get("screenshot_file"),
            "screenshot_sha256": slice_info.get("screenshot_sha256"),
            "verdict": verdict
        })

    def is_complete(self) -> bool:
        return len(self.slice_results) >= self.total_slices

    def aggregate_slices(self) -> Dict[str, Any]:
        """
        汇总该设备的所有切片结果：只要任意切片违规，该设备即判违规
        """
        risk_hierarchy = ["SAFE", "LOW", "MEDIUM", "HIGH", "CRITICAL"]
        has_violation = any(s["verdict"].get("is_violation") for s in self.slice_results)

        max_risk = "SAFE"
        max_risk_idx = 0
        max_confidence = 0.0

        # 分类最高概率合并
        merged_categories = {cat["key"]: {"detected": False, "probability": 0.0, "reason": ""} for cat in COMPLIANCE_CATEGORIES}

        violation_reasons = []
        visual_elements = []

        for s in self.slice_results:
            v = s["verdict"]
            r = v.get("risk_level", "SAFE").upper()
            if r in risk_hierarchy:
                idx = risk_hierarchy.index(r)
                if idx > max_risk_idx:
                    max_risk_idx = idx
                    max_risk = r

            if v.get("confidence", 0) > max_confidence:
                max_confidence = v.get("confidence", 0)

            for c in v.get("categories", []):
                k = c.get("key")
                if k in merged_categories:
                    if c.get("probability", 0) > merged_categories[k]["probability"]:
                        merged_categories[k]["probability"] = c.get("probability", 0)
                        merged_categories[k]["reason"] = f"[{s['slice_name']}] {c.get('reason', '')}"
                    if c.get("detected"):
                        merged_categories[k]["detected"] = True

            if v.get("is_violation") and v.get("violation_details"):
                violation_reasons.append(f"[{s['slice_name']}] {v.get('violation_details')}")

            visual_elements.extend(v.get("visual_elements_found", []))

        # 确定主违规类型
        primary_cat = "normal"
        highest_p = 0.0
        for k, val in merged_categories.items():
            if val["probability"] > highest_p:
                highest_p = val["probability"]
                primary_cat = k

        if not has_violation:
            primary_cat = "normal"
            details_str = "页面切片内容健康合法"
        else:
            details_str = " ; ".join(violation_reasons)

        primary_slice = self.slice_results[0] if self.slice_results else {}

        return {
            "device_id": self.device_id,
            "device_name": self.device_name,
            "is_mobile": self.base_info.get("is_mobile", False),
            "viewport": self.base_info.get("viewport"),
            "user_agent": self.base_info.get("user_agent"),
            "final_url": self.base_info.get("final_url"),
            "http_status": self.base_info.get("http_status"),
            "capture_status": self.base_info.get("capture_status", "success"),
            "screenshot_path": primary_slice.get("screenshot_path"),
            "screenshot_sha256": primary_slice.get("screenshot_sha256"),
            "slices_audited": self.slice_results,
            "model_verdict": {
                "is_violation": has_violation,
                "risk_level": max_risk,
                "confidence": round(max_confidence, 4),
                "primary_violation": primary_cat,
                "categories": [
                    {
                        "key": k,
                        "detected": val["detected"],
                        "probability": round(val["probability"], 4),
                        "reason": val["reason"]
                    }
                    for k, val in merged_categories.items()
                ],
                "violation_details": details_str,
                "visual_elements_found": list(set(visual_elements))
            }
        }


class URLInspectionTracker:
    """
    单个 URL 的异步结果收集器（支持多端及每端多切片）
    """
    def __init__(self, url: str, total_devices: int):
        self.url = url
        self.total_devices = total_devices
        self.device_collectors: Dict[str, DeviceInspectionCollector] = {}
        self._lock = asyncio.Lock()
        self.done_event = asyncio.Event()

    def register_device(self, device_id: str, device_name: str, total_slices: int, base_info: Dict[str, Any]):
        if device_id not in self.device_collectors:
            self.device_collectors[device_id] = DeviceInspectionCollector(
                device_id, device_name, total_slices, base_info
            )

    async def add_slice_result(self, device_id: str, slice_info: Dict[str, Any], verdict: Dict[str, Any]):
        async with self._lock:
            collector = self.device_collectors[device_id]
            collector.add_slice_result(slice_info, verdict)

            # 检查是否全部设备且全部切片均已完成
            all_devices_ready = (
                len(self.device_collectors) >= self.total_devices
                and all(c.is_complete() for c in self.device_collectors.values())
            )
            if all_devices_ready:
                self.done_event.set()

    def get_aggregated_devices(self) -> List[Dict[str, Any]]:
        return [c.aggregate_slices() for c in self.device_collectors.values()]


class DecoupledInspectionPipeline:
    """
    全解耦生产者-消费者流水线（支持多端多视口切片审核）
    """
    def __init__(
        self,
        api_base: str = "http://localhost:11434/v1",
        api_key: str = "EMPTY",
        model: str = "qwen2-vl",
        browser_concurrency: int = 4,
        llm_concurrency: int = 2,
        output_dir: str = "output",
        headless: bool = True,
        is_mock: bool = False
    ):
        self.output_dir = output_dir
        self.is_mock = is_mock
        self.model = model
        self.api_base = api_base
        self.browser_concurrency = browser_concurrency
        self.llm_concurrency = llm_concurrency

        os.makedirs(self.output_dir, exist_ok=True)
        self.screenshot_dir = os.path.join(output_dir, "screenshots")
        os.makedirs(self.screenshot_dir, exist_ok=True)

        self.browser_pool = AsyncBrowserPool(max_concurrency=browser_concurrency, headless=headless)
        self.screenshot_engine = AsyncScreenshotEngine(self.browser_pool, output_dir=self.screenshot_dir)
        self.analyzer = AsyncMultimodalSafetyAnalyzer(
            api_base=api_base,
            api_key=api_key,
            model=model,
            max_concurrency=llm_concurrency
        )

        self.queue: asyncio.Queue = asyncio.Queue(maxsize=CONCURRENCY_CONFIG["queue_max_size"])
        self.trackers: Dict[str, URLInspectionTracker] = {}
        self._write_lock = asyncio.Lock()

    async def _screenshot_producer(
        self,
        url: str,
        profile: Dict[str, Any],
        delay: float,
        slices_count: int,
        full_page: bool,
        max_height: int
    ):
        """
        截图生产者任务：抓取指定设备切片后，立即将切片打散塞入队列，释放浏览器标签页！
        """
        capture = await self.screenshot_engine.capture_single_device(
            url=url,
            profile=profile,
            delay_seconds=delay,
            slices_count=slices_count,
            full_page=full_page,
            max_height=max_height
        )

        tracker = self.trackers[url]
        dev_id = profile["id"]
        dev_name = profile["name"]

        base_info = {
            "device_id": dev_id,
            "device_name": dev_name,
            "is_mobile": profile.get("is_mobile", False),
            "viewport": profile.get("viewport"),
            "user_agent": profile.get("user_agent"),
            "final_url": capture.get("final_url"),
            "http_status": capture.get("http_status"),
            "capture_status": capture.get("status"),
            "error": capture.get("error")
        }

        if capture["status"] == "success" and capture.get("slices"):
            slices = capture["slices"]
            tracker.register_device(dev_id, dev_name, total_slices=len(slices), base_info=base_info)
            for s in slices:
                # 放入队列供消费者大模型并行推理
                await self.queue.put((url, dev_id, s, True, None))
        else:
            # 抓取失败时的处理
            tracker.register_device(dev_id, dev_name, total_slices=1, base_info=base_info)
            fail_slice = {
                "slice_id": "failed",
                "slice_name": "抓取失败",
                "screenshot_file": None,
                "screenshot_sha256": None,
                "image_base64": None
            }
            await self.queue.put((url, dev_id, fail_slice, False, capture.get("error")))

    async def _llm_consumer_worker(
        self,
        worker_id: int,
        f_jsonl,
        progress_callback: Optional[Callable[[int, int, Dict[str, Any]], None]],
        total_urls: int,
        completed_urls_counter: List[int],
        all_results_list: List[Dict[str, Any]]
    ):
        """
        大模型消费者 Worker：从队列持续取出截图切片进行高精度推理
        """
        while True:
            item = await self.queue.get()
            if item is None:
                self.queue.task_done()
                break

            url, dev_id, slice_info, is_success, err_msg = item
            tracker = self.trackers[url]

            if is_success and slice_info.get("image_base64"):
                verdict = await self.analyzer.analyze_image_async(
                    slice_info["image_base64"],
                    is_mock=self.is_mock
                )
            else:
                verdict = {
                    "is_violation": False,
                    "risk_level": "UNKNOWN",
                    "confidence": 0.0,
                    "primary_violation": "capture_failed",
                    "categories": [],
                    "violation_details": f"截图抓取失败: {err_msg}",
                    "visual_elements_found": []
                }

            await tracker.add_slice_result(dev_id, slice_info, verdict)
            self.queue.task_done()

            # 当整个 URL 的全部设备与切片均已完成时触发聚合与流式写入
            if tracker.done_event.is_set():
                async with self._write_lock:
                    if not getattr(tracker, "_processed", False):
                        tracker._processed = True
                        completed_urls_counter[0] += 1
                        current_idx = completed_urls_counter[0]

                        aggregated_devices = tracker.get_aggregated_devices()
                        verdict_summary = aggregate_device_results(url, aggregated_devices)

                        final_record = {
                            "url": url,
                            "checked_at": datetime.now(timezone.utc).isoformat(),
                            "model_used": self.model,
                            "api_endpoint": self.api_base,
                            "verdict_summary": verdict_summary,
                            "device_inspections": aggregated_devices
                        }

                        all_results_list.append(final_record)
                        f_jsonl.write(json.dumps(final_record, ensure_ascii=False) + "\n")
                        f_jsonl.flush()

                        if progress_callback:
                            progress_callback(current_idx, total_urls, final_record)

    async def run_pipeline(
        self,
        urls: List[str],
        selected_profiles: List[Dict[str, Any]],
        delay: float = 3.0,
        slices_count: int = 1,
        full_page: bool = False,
        max_height: int = 2500,
        progress_callback: Optional[Callable[[int, int, Dict[str, Any]], None]] = None
    ) -> Dict[str, Any]:
        """
        启动生产级全异步切片巡检流水线
        """
        clean_urls = []
        seen_urls = set()
        for u in urls:
            u_clean = u.strip()
            if not u_clean or u_clean.startswith("#"):
                continue
            if not u_clean.startswith("http://") and not u_clean.startswith("https://"):
                u_clean = "https://" + u_clean
            if u_clean not in seen_urls:
                seen_urls.add(u_clean)
                clean_urls.append(u_clean)

        total_urls = len(clean_urls)
        total_devices = len(selected_profiles)

        for u in clean_urls:
            self.trackers[u] = URLInspectionTracker(u, total_devices)

        await self.browser_pool.start()
        timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        jsonl_path = os.path.join(self.output_dir, f"batch_results_{timestamp_str}.jsonl")
        summary_path = os.path.join(self.output_dir, f"batch_summary_{timestamp_str}.json")

        all_results: List[Dict[str, Any]] = []
        completed_counter = [0]

        try:
            with open(jsonl_path, "a", encoding="utf-8") as f_jsonl:
                # 1. 启动大模型消费 Workers
                consumer_tasks = [
                    asyncio.create_task(
                        self._llm_consumer_worker(
                            worker_id=i,
                            f_jsonl=f_jsonl,
                            progress_callback=progress_callback,
                            total_urls=total_urls,
                            completed_urls_counter=completed_counter,
                            all_results_list=all_results
                        )
                    )
                    for i in range(self.llm_concurrency)
                ]

                # 2. 调度所有截图生产者任务（支持分屏切片抓取）
                producer_tasks = [
                    asyncio.create_task(
                        self._screenshot_producer(
                            url=url,
                            profile=profile,
                            delay=delay,
                            slices_count=slices_count,
                            full_page=full_page,
                            max_height=max_height
                        )
                    )
                    for url in clean_urls
                    for profile in selected_profiles
                ]

                # 3. 等待所有截图切片产生完毕
                await asyncio.gather(*producer_tasks)

                # 4. 等待队列消费完毕
                await self.queue.join()

                # 5. 发送终止信号并等待 Worker 退出
                for _ in range(self.llm_concurrency):
                    await self.queue.put(None)

                await asyncio.gather(*consumer_tasks)

        finally:
            await self.browser_pool.close()

        # 生成最终汇总报告
        violation_count = sum(
            1 for r in all_results if r.get("verdict_summary", {}).get("is_violation") is True
        )
        summary_report = {
            "batch_metadata": {
                "total_urls": total_urls,
                "violation_urls_count": violation_count,
                "clean_urls_count": total_urls - violation_count,
                "browser_concurrency": self.browser_concurrency,
                "llm_concurrency": self.llm_concurrency,
                "slices_per_device": slices_count,
                "start_time": timestamp_str,
                "end_time": datetime.now().strftime("%Y%m%d_%H%M%S"),
                "jsonl_records_file": os.path.abspath(jsonl_path)
            },
            "results": all_results
        }

        with open(summary_path, "w", encoding="utf-8") as f_sum:
            json.dump(summary_report, f_sum, ensure_ascii=False, indent=2)

        summary_report["summary_file"] = os.path.abspath(summary_path)
        return summary_report
