"""
Asynchronous multi-device screenshot capture module.
Includes lazy-load simulation, delayed capture, forensics hashing (SHA-256),
smart height clamping, and high-definition viewport slicing (Tiling / Sliding Window).
"""

import os
import time
import base64
import hashlib
import asyncio
from datetime import datetime
from typing import Dict, Any, List, Optional
from playwright.async_api import Page, Error as PlaywrightError

from browser_pool import AsyncBrowserPool


class AsyncScreenshotEngine:
    def __init__(self, browser_pool: AsyncBrowserPool, output_dir: str = "screenshots"):
        self.browser_pool = browser_pool
        self.output_dir = output_dir
        os.makedirs(self.output_dir, exist_ok=True)

    async def _simulate_smooth_scroll(self, page: Page, delay_seconds: float):
        """
        异步平滑下滚，触发现代化网页的动态懒加载（图片、广告图、浮动弹窗）
        """
        try:
            await page.evaluate("""
                async () => {
                    const scrollHeight = document.body.scrollHeight;
                    const step = Math.max(300, Math.floor(window.innerHeight * 0.8));
                    let current = 0;
                    while (current < scrollHeight && current < 4000) {
                        current += step;
                        window.scrollTo({ top: current, behavior: 'smooth' });
                        await new Promise(r => setTimeout(r, 120));
                    }
                    window.scrollTo({ top: 0, behavior: 'smooth' });
                }
            """)
        except Exception:
            pass

        if delay_seconds > 0:
            await asyncio.sleep(delay_seconds)

    async def _capture_viewport_slices(
        self,
        page: Page,
        clean_url_name: str,
        profile_id: str,
        timestamp_str: str,
        slices_count: int = 1,
        full_page: bool = False,
        max_height: int = 2500
    ) -> List[Dict[str, Any]]:
        """
        高保真分屏切片截屏 (Smart Tiling):
        绝不对超长图进行无脑整页压缩（防止字迹模糊），
        而是按视口原比例切片（如 首屏 Top、中部 Middle、页尾 Bottom），
        保持 100% 原始分辨率与锐利文字细节。
        """
        page_metrics = await page.evaluate("""() => {
            return {
                scrollHeight: Math.max(
                    document.body.scrollHeight || 0,
                    document.documentElement.scrollHeight || 0
                ),
                innerHeight: window.innerHeight || 800
            };
        }""")

        scroll_height = page_metrics["scrollHeight"]
        inner_height = page_metrics["innerHeight"]

        # 如果开启了 full_page 但页面超长，自动进行智能截断 (Smart Clamping) 防止几万像素长图
        if full_page:
            effective_height = min(scroll_height, max_height)
            filepath = os.path.join(
                self.output_dir,
                f"{clean_url_name}_{profile_id}_full_{timestamp_str}.png"
            )
            # 使用 clip 截取限制最大高度的长图
            screenshot_bytes = await page.screenshot(
                path=filepath,
                clip={"x": 0, "y": 0, "width": page.viewport_size["width"], "height": effective_height} if page.viewport_size else None,
                type="png"
            )
            sha256_hash = hashlib.sha256(screenshot_bytes).hexdigest()
            b64_str = base64.b64encode(screenshot_bytes).decode("utf-8")
            return [{
                "slice_id": "full_clamped",
                "slice_name": f"整页截断图 (Max {max_height}px)",
                "screenshot_file": os.path.abspath(filepath),
                "screenshot_sha256": sha256_hash,
                "image_base64": b64_str,
                "scroll_y": 0
            }]

        # 切片规划 (Slicing Schedule)
        # 如果页面高度 <= 视口高度 1.2 倍，说明是单屏网页，无需切片
        if slices_count <= 1 or scroll_height <= inner_height * 1.2:
            schedule = [("top", "首屏视口", 0)]
        elif slices_count == 2:
            bottom_y = max(0, scroll_height - inner_height)
            schedule = [
                ("top", "首屏视口 (Top)", 0),
                ("bottom", "页底/吸附区 (Bottom)", bottom_y)
            ]
        else:  # slices_count >= 3
            bottom_y = max(0, scroll_height - inner_height)
            middle_y = max(0, (scroll_height - inner_height) // 2)
            schedule = [
                ("top", "首屏视口 (Top)", 0),
                ("middle", "中部内容区 (Middle)", middle_y),
                ("bottom", "页底/吸附区 (Bottom)", bottom_y)
            ]

        captured_slices = []
        for slice_id, slice_name, y_offset in schedule:
            try:
                # 平滑滚动到指定切片视口
                await page.evaluate(f"window.scrollTo(0, {y_offset});")
                await asyncio.sleep(0.15)  # 等待重绘

                filename = f"{clean_url_name}_{profile_id}_{slice_id}_{timestamp_str}.png"
                filepath = os.path.join(self.output_dir, filename)

                # 视口截屏（不失真）
                screenshot_bytes = await page.screenshot(
                    path=filepath,
                    full_page=False,
                    type="png"
                )

                sha256_hash = hashlib.sha256(screenshot_bytes).hexdigest()
                b64_str = base64.b64encode(screenshot_bytes).decode("utf-8")

                captured_slices.append({
                    "slice_id": slice_id,
                    "slice_name": slice_name,
                    "screenshot_file": os.path.abspath(filepath),
                    "screenshot_sha256": sha256_hash,
                    "image_base64": b64_str,
                    "scroll_y": y_offset
                })
            except Exception:
                continue

        # 滚回顶部
        try:
            await page.evaluate("window.scrollTo(0, 0);")
        except Exception:
            pass

        return captured_slices

    async def capture_single_device(
        self,
        url: str,
        profile: Dict[str, Any],
        delay_seconds: float = 3.0,
        slices_count: int = 1,
        full_page: bool = False,
        max_height: int = 2500,
        timeout_ms: int = 25000,
        max_retries: int = 2
    ) -> Dict[str, Any]:
        """
        在指定设备环境下对目标 URL 进行异步抓取、分屏切片与存证
        """
        profile_id = profile["id"]
        profile_name = profile["name"]
        ua = profile["user_agent"]
        viewport = profile["viewport"]
        is_mobile = profile.get("is_mobile", False)

        result: Dict[str, Any] = {
            "device_id": profile_id,
            "device_name": profile_name,
            "viewport": viewport,
            "user_agent": ua,
            "is_mobile": is_mobile,
            "status": "pending",
            "initial_url": url,
            "final_url": None,
            "http_status": None,
            "slices": [],
            "captured_at": None,
            "error": None
        }

        timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        clean_name = "".join([c if c.isalnum() else "_" for c in url])[:30]

        for attempt in range(1, max_retries + 1):
            try:
                async with self.browser_pool.acquire_context(profile) as page:
                    # 导航
                    try:
                        response = await page.goto(url, wait_until="networkidle", timeout=timeout_ms)
                    except PlaywrightError:
                        response = await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)

                    result["final_url"] = page.url
                    if response:
                        result["http_status"] = response.status

                    # 延时交互与动态内容渲染 (激发懒加载)
                    await self._simulate_smooth_scroll(page, delay_seconds)

                    # 分屏切片捕获
                    slices = await self._capture_viewport_slices(
                        page=page,
                        clean_url_name=clean_name,
                        profile_id=profile_id,
                        timestamp_str=timestamp_str,
                        slices_count=slices_count,
                        full_page=full_page,
                        max_height=max_height
                    )

                    result["status"] = "success"
                    result["slices"] = slices
                    result["captured_at"] = datetime.now().isoformat()

                    # 兼容快捷字段
                    if slices:
                        result["screenshot_file"] = slices[0]["screenshot_file"]
                        result["screenshot_sha256"] = slices[0]["screenshot_sha256"]
                        result["image_base64"] = slices[0]["image_base64"]

                    return result

            except Exception as e:
                if attempt == max_retries:
                    result["status"] = "error"
                    result["error"] = f"尝试 {max_retries} 次失败: {str(e)}"
                    return result
                await asyncio.sleep(1.0 * attempt)

        return result
