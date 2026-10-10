"""
Multi-device delayed screenshot engine using Playwright.
Handles desktop, tablet, and mobile device emulation, anti-bot bypass, lazy loading, and delayed capture.
"""

import os
import time
import base64
from typing import Dict, List, Any, Optional
from datetime import datetime
from playwright.sync_api import sync_playwright, Playwright, Browser, BrowserContext, Page, Error as PlaywrightError

try:
    from playwright_stealth import stealth_sync
    STEALTH_AVAILABLE = True
except ImportError:
    STEALTH_AVAILABLE = False


class WebScreenshotEngine:
    def __init__(self, output_dir: str = "screenshots", headless: bool = True):
        self.output_dir = output_dir
        self.headless = headless
        os.makedirs(self.output_dir, exist_ok=True)

    def _launch_browser(self, p: Playwright) -> Browser:
        """
        Attempts to launch Chromium browser with auto-fallback to installed Edge/Chrome.
        """
        # 1. 尝试默认 chromium
        try:
            return p.chromium.launch(
                headless=self.headless,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-infobars",
                    "--disable-web-security"
                ]
            )
        except Exception:
            pass

        # 2. 尝试系统自带的 Microsoft Edge (Windows 上通常免额外下载)
        try:
            return p.chromium.launch(
                headless=self.headless,
                channel="msedge",
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-setuid-sandbox"
                ]
            )
        except Exception:
            pass

        # 3. 尝试 Google Chrome
        try:
            return p.chromium.launch(
                headless=self.headless,
                channel="chrome",
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox"
                ]
            )
        except Exception as e:
            raise RuntimeError(
                f"无法启动任何可用浏览器，请安装 Playwright 浏览器或确保系统有 Edge/Chrome: {e}"
            )

    def _simulate_human_interaction_and_lazy_load(self, page: Page, delay_seconds: float):
        """
        模拟向下滚动以触发图片懒加载、弹窗、动态渲染的广告与重定向，然后等待指定延迟。
        """
        try:
            # 获取页面高度并分段平滑下滚
            page.evaluate("""
                async () => {
                    const scrollHeight = document.body.scrollHeight;
                    const step = Math.max(300, Math.floor(window.innerHeight * 0.8));
                    let current = 0;
                    while (current < scrollHeight && current < 4000) {
                        current += step;
                        window.scrollTo({ top: current, behavior: 'smooth' });
                        await new Promise(r => setTimeout(r, 200));
                    }
                    // 滚动回顶部或展示主体区域
                    window.scrollTo({ top: 0, behavior: 'smooth' });
                }
            """)
        except Exception:
            pass

        # 执行用户要求的延迟等待 (确保重定向与异步JS执行完毕)
        if delay_seconds > 0:
            time.sleep(delay_seconds)

    def capture_devices(
        self,
        url: str,
        device_profiles: List[Dict[str, Any]],
        delay_seconds: float = 3.0,
        full_page: bool = False,
        timeout_ms: int = 30000
    ) -> List[Dict[str, Any]]:
        """
        针对指定 URL，依次切换不同的设备分辨率、UA 进行延迟截图。
        """
        results = []
        timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")

        with sync_playwright() as p:
            browser = self._launch_browser(p)
            try:
                for profile in device_profiles:
                    profile_id = profile["id"]
                    profile_name = profile["name"]
                    ua = profile["user_agent"]
                    viewport = profile["viewport"]
                    scale = profile.get("device_scale_factor", 1)
                    is_mobile = profile.get("is_mobile", False)
                    has_touch = profile.get("has_touch", False)

                    context_kwargs = {
                        "user_agent": ua,
                        "viewport": viewport,
                        "device_scale_factor": scale,
                        "is_mobile": is_mobile,
                        "has_touch": has_touch,
                        "ignore_https_errors": True,
                    }

                    context: BrowserContext = browser.new_context(**context_kwargs)
                    page: Page = context.new_page()

                    if STEALTH_AVAILABLE:
                        try:
                            stealth_sync(page)
                        except Exception:
                            pass

                    device_res = {
                        "device_id": profile_id,
                        "device_name": profile_name,
                        "viewport": viewport,
                        "user_agent": ua,
                        "is_mobile": is_mobile,
                        "status": "pending",
                        "final_url": None,
                        "screenshot_file": None,
                        "image_base64": None,
                        "error": None
                    }

                    try:
                        # 导航并等待网络空闲或DOM加载
                        try:
                            response = page.goto(url, wait_until="networkidle", timeout=timeout_ms)
                        except PlaywrightError:
                            # 某些持续有流连接的网站 networkidle 会超时，降级为 domcontentloaded
                            response = page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)

                        # 记录跳转后的最终实际 URL（防止恶意重定向）
                        device_res["final_url"] = page.url

                        # 延迟等待与模拟动态元素加载
                        self._simulate_human_interaction_and_lazy_load(page, delay_seconds)

                        # 生成文件名并保存截图
                        clean_url = "".join([c if c.isalnum() else "_" for c in url])[:30]
                        filename = f"{clean_url}_{profile_id}_{timestamp_str}.png"
                        filepath = os.path.join(self.output_dir, filename)

                        # 执行截图
                        screenshot_bytes = page.screenshot(
                            path=filepath,
                            full_page=full_page,
                            type="png"
                        )

                        # 编码为 base64
                        b64_str = base64.b64encode(screenshot_bytes).decode("utf-8")

                        device_res["status"] = "success"
                        device_res["screenshot_file"] = os.path.abspath(filepath)
                        device_res["image_base64"] = b64_str

                    except Exception as e:
                        device_res["status"] = "error"
                        device_res["error"] = str(e)
                    finally:
                        context.close()

                    results.append(device_res)

            finally:
                browser.close()

        return results
