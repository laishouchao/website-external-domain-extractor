"""
Web Compliance Checker - Multi-Device Screenshot Capture Engine
High-fidelity browser rendering using Playwright with system Edge/Chrome fallback.
Captures desktop vs mobile viewports for Cloaking fraud detection.
"""

import os
import time
import base64
import hashlib
import asyncio
from datetime import datetime
from typing import Dict, Any, List, Optional

import threading

from playwright.async_api import async_playwright, Playwright, Browser, BrowserContext, Page

from config import DEVICE_PROFILES, OUTPUT_DIR, PROBE_CONFIG

class CaptureEngine:
    def __init__(self, headless: bool = True):
        self.headless = headless
        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._lock = threading.Lock()

    async def _get_browser(self) -> Browser:
        with self._lock:
            if self._browser and self._browser.is_connected():
                return self._browser

        if not self._playwright:
            self._playwright = await async_playwright().start()

        browser_args = [
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-infobars",
            "--disable-web-security",
            "--disable-dev-shm-usage",
            "--disable-gpu",
        ]

        with self._lock:
            if self._browser and self._browser.is_connected():
                return self._browser
            for channel in ["msedge", "chrome", None]:
                try:
                    kwargs = {"headless": self.headless, "args": browser_args}
                    if channel:
                        kwargs["channel"] = channel
                    self._browser = await self._playwright.chromium.launch(**kwargs)
                    return self._browser
                except Exception:
                    continue

        raise RuntimeError("无法启动 Chromium / Edge 浏览器，请检查系统浏览器配置")

    async def capture_device(
        self,
        url: str,
        device_key: str,
        domain_name: str = "",
        save_file: bool = True
    ) -> Dict[str, Any]:
        """Capture screenshot for a single device viewport."""
        profile = DEVICE_PROFILES.get(device_key, DEVICE_PROFILES["desktop_chrome"])
        browser = await self._get_browser()

        # Build context options
        context_opts = {
            "viewport": profile["viewport"],
            "user_agent": profile["user_agent"],
            "is_mobile": profile.get("is_mobile", False),
            "has_touch": profile.get("is_mobile", False),
            "device_scale_factor": profile.get("device_scale_factor", 1),
            "ignore_https_errors": True,
            "bypass_csp": True,
        }

        context: BrowserContext = await browser.new_context(**context_opts)
        page: Page = await context.new_page()

        try:
            # Set stealth headers
            await page.set_extra_http_headers({
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                "Sec-Ch-Ua-Mobile": "?1" if profile.get("is_mobile") else "?0",
            })

            # Navigate with resilient fast fallback
            http_status = None
            try:
                resp = await page.goto(url, timeout=4500, wait_until="domcontentloaded")
                http_status = resp.status if resp else None
            except Exception:
                try:
                    resp = await page.goto(url, timeout=3000, wait_until="commit")
                    http_status = resp.status if resp else None
                except Exception:
                    pass

            # Render wait
            await asyncio.sleep(0.5)

            # Extract title and text
            try:
                title = await page.title()
            except Exception:
                title = ""

            try:
                text_content = await page.evaluate("() => document.body ? document.body.innerText.slice(0, 500) : ''")
            except Exception:
                text_content = ""

            # Capture screenshot buffer (JPEG/PNG)
            # Clip viewport to sensible height
            vp = profile["viewport"]
            clip_rect = {"x": 0, "y": 0, "width": vp["width"], "height": min(vp["height"], 1080)}

            img_bytes = await page.screenshot(
                type="png",
                clip=clip_rect,
                timeout=5000,
            )

            # Compute SHA-256 and Base64
            sha256_hash = hashlib.sha256(img_bytes).hexdigest()
            b64_str = base64.b64encode(img_bytes).decode("utf-8")
            data_uri = f"data:image/png;base64,{b64_str}"

            # Save file if required
            rel_file_path = ""
            if save_file:
                clean_host = (domain_name or url.split("://")[-1].split("/")[0]).replace(":", "_").replace("/", "_")
                date_str = datetime.now().strftime("%Y%m%d")
                save_dir = os.path.join(OUTPUT_DIR, "screenshots", date_str)
                os.makedirs(save_dir, exist_ok=True)
                file_name = f"{clean_host}_{device_key}_{int(time.time())}.png"
                full_path = os.path.join(save_dir, file_name)
                with open(full_path, "wb") as f:
                    f.write(img_bytes)
                rel_file_path = f"screenshots/{date_str}/{file_name}"

            return {
                "success": True,
                "device": device_key,
                "device_name": profile["name"],
                "viewport": profile["viewport"],
                "is_mobile": profile.get("is_mobile", False),
                "title": title,
                "text_snippet": text_content.strip()[:300],
                "http_status": http_status,
                "screenshot_path": rel_file_path,
                "base64_data_uri": data_uri,
                "sha256": sha256_hash,
                "error": None,
            }

        except Exception as e:
            return {
                "success": False,
                "device": device_key,
                "device_name": profile["name"],
                "viewport": profile["viewport"],
                "is_mobile": profile.get("is_mobile", False),
                "title": "",
                "text_snippet": "",
                "http_status": None,
                "screenshot_path": "",
                "base64_data_uri": "",
                "sha256": "",
                "error": str(e),
            }
        finally:
            await page.close()
            await context.close()

    async def capture_devices(
        self,
        url: str,
        device_keys: List[str],
        domain_name: str = ""
    ) -> Dict[str, Dict[str, Any]]:
        """Capture screenshots across multiple device profiles."""
        results = {}
        for dev_key in device_keys:
            res = await self.capture_device(url, dev_key, domain_name=domain_name)
            results[dev_key] = res
        return results

    async def close(self):
        with self._lock:
            if self._browser:
                try:
                    await self._browser.close()
                except Exception:
                    pass
                self._browser = None
            if self._playwright:
                try:
                    await self._playwright.stop()
                except Exception:
                    pass
                self._playwright = None

# Global singleton engine
GLOBAL_CAPTURE_ENGINE = CaptureEngine()
