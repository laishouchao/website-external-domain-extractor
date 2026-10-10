"""
High-performance asynchronous browser pool management using Playwright.
Manages browser instance reuse, isolated context recycling, and bounded concurrency.
"""

import asyncio
from typing import Dict, Any, Optional
from contextlib import asynccontextmanager
from playwright.async_api import async_playwright, Playwright, Browser, BrowserContext, Page

from stealth_utils import apply_stealth_to_context

try:
    from playwright_stealth import stealth_async
    STEALTH_AVAILABLE = True
except ImportError:
    STEALTH_AVAILABLE = False


class AsyncBrowserPool:
    """
    异步浏览器常驻池：
    1. 进程常驻复用，避免每次抓取重复拉起 Chromium 进程的高昂开销
    2. 基于 Context 隔离每次会话，自动回收内存和 Cookie 缓存
    3. 配合 Semaphore 限制最大并发渲染标签页数，防止内存暴涨
    """
    def __init__(self, max_concurrency: int = 4, headless: bool = True):
        self.max_concurrency = max_concurrency
        self.headless = headless
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._lock = asyncio.Lock()

    async def _launch_browser(self, p: Playwright) -> Browser:
        """
        依次尝试 Chromium、系统自带 Edge、Chrome
        """
        browser_args = [
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-infobars",
            "--disable-web-security",
            "--disable-dev-shm-usage",
            "--disable-gpu"
        ]

        # 1. 尝试默认 chromium
        try:
            return await p.chromium.launch(headless=self.headless, args=browser_args)
        except Exception:
            pass

        # 2. 尝试系统自带 Edge
        try:
            return await p.chromium.launch(headless=self.headless, channel="msedge", args=browser_args)
        except Exception:
            pass

        # 3. 尝试 Google Chrome
        try:
            return await p.chromium.launch(headless=self.headless, channel="chrome", args=browser_args)
        except Exception as e:
            raise RuntimeError(f"无法启动可用浏览器内核 (Chromium/Edge/Chrome): {e}")

    async def start(self):
        """
        启动浏览器常驻进程
        """
        async with self._lock:
            if not self._playwright:
                self._playwright = await async_playwright().start()
                self._browser = await self._launch_browser(self._playwright)

    async def close(self):
        """
        优雅释放所有浏览器资源
        """
        async with self._lock:
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

    @asynccontextmanager
    async def acquire_context(self, profile: Dict[str, Any]):
        """
        从池中获取受控并发槽位并实例化轻量级隔离会话 (Context + Page)
        """
        if not self._browser or not self._browser.is_connected():
            await self.start()

        async with self._semaphore:
            context_kwargs = {
                "user_agent": profile["user_agent"],
                "viewport": profile["viewport"],
                "device_scale_factor": profile.get("device_scale_factor", 1),
                "is_mobile": profile.get("is_mobile", False),
                "has_touch": profile.get("has_touch", False),
                "ignore_https_errors": True,
            }

            context: BrowserContext = await self._browser.new_context(**context_kwargs)
            await apply_stealth_to_context(context, profile)
            page: Page = await context.new_page()

            if STEALTH_AVAILABLE:
                try:
                    await stealth_async(page)
                except Exception:
                    pass

            try:
                yield page
            finally:
                try:
                    await page.close()
                except Exception:
                    pass
                try:
                    await context.close()
                except Exception:
                    pass
