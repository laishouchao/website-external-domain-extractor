"""
Automated high-definition screenshot capture utility for README documentation.
Captures key system functional interfaces from http://192.168.1.207:8000/
"""

import asyncio
import os
import sys
from playwright.async_api import async_playwright

BASE_URL = "http://192.168.1.207:8000"
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs", "images")


async def capture_all():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    print(f"[*] Screenshot target directory: {OUTPUT_DIR}")

    async with async_playwright() as p:
        browser = await p.chromium.launch(channel="msedge", headless=True)
        context = await browser.new_context(
            viewport={"width": 1920, "height": 1080},
            device_scale_factor=1.25,
            locale="zh-CN"
        )
        page = await context.new_page()

        # 1. 登录界面
        print("[1/9] 正在截取: 用户登录界面...")
        await page.goto(f"{BASE_URL}/login", wait_until="networkidle")
        await asyncio.sleep(1.5)
        login_img = os.path.join(OUTPUT_DIR, "01_login_view.png")
        await page.screenshot(path=login_img, full_page=False)
        print(f"  -> 已保存: {login_img}")

        # 执行登录
        print("[*] 正在执行系统认证登录 (admin / admin123)...")
        await page.fill('input[autocomplete="username"]', "admin")
        await page.fill('input[autocomplete="current-password"]', "admin123")
        await page.click('button[type="submit"]')
        await page.wait_for_url(f"{BASE_URL}/dashboard", timeout=10000)
        await asyncio.sleep(3)

        # 2. 态势感知总览大屏
        print("[2/9] 正在截取: 态势感知总览大屏...")
        dashboard_img = os.path.join(OUTPUT_DIR, "02_dashboard_overview.png")
        await page.screenshot(path=dashboard_img, full_page=False)
        print(f"  -> 已保存: {dashboard_img}")

        # 3. 扫描任务管理中心
        print("[3/9] 正在截取: 扫描任务管理中心...")
        await page.goto(f"{BASE_URL}/tasks", wait_until="networkidle")
        await asyncio.sleep(2.5)
        tasks_img = os.path.join(OUTPUT_DIR, "03_tasks_management.png")
        await page.screenshot(path=tasks_img, full_page=False)
        print(f"  -> 已保存: {tasks_img}")

        # 4. 任务工作台 - 外部域名列表
        print("[4/9] 正在截取: 任务工作台 (外部域名提取列表)...")
        # 选择一个已完成且数据丰富的任务，如 94 或 93
        await page.goto(f"{BASE_URL}/tasks/94", wait_until="networkidle")
        await asyncio.sleep(3)
        detail_domains_img = os.path.join(OUTPUT_DIR, "04_task_detail_domains.png")
        await page.screenshot(path=detail_domains_img, full_page=False)
        print(f"  -> 已保存: {detail_domains_img}")

        # 5. 上下文代码证据抽屉
        print("[5/9] 正在截取: 外部域名上下文代码证据抽屉...")
        # 点击表格第一行某个域名或溯源按钮打开抽屉
        try:
            # 找到首个可点击的域名项或查看按钮
            first_row = page.locator("table tbody tr").first
            if await first_row.count() > 0:
                # 尝试点击第一行的域名链接或按钮
                domain_btn = first_row.locator("button, a, td.cursor-pointer, td:nth-child(2)").first
                await domain_btn.click()
                await asyncio.sleep(2)
                drawer_img = os.path.join(OUTPUT_DIR, "05_domain_provenance_drawer.png")
                await page.screenshot(path=drawer_img, full_page=False)
                print(f"  -> 已保存: {drawer_img}")
                # 关闭抽屉，按 ESC 或点击遮罩
                await page.keyboard.press("Escape")
                await asyncio.sleep(1)
        except Exception as e:
            print(f"  -> 打开抽屉跳过或异常: {e}")

        # 6. 任务工作台 - 网站地图拓扑
        print("[6/9] 正在截取: 任务工作台 (网站地图 Sitemap)...")
        try:
            # 点击 Sitemap 选项卡
            sitemap_tab = page.locator("button, a", has_text="网站地图").first
            if await sitemap_tab.count() > 0:
                await sitemap_tab.click()
                await asyncio.sleep(2.5)
            else:
                await page.goto(f"{BASE_URL}/tasks/94?tab=sitemap", wait_until="networkidle")
                await asyncio.sleep(2.5)
            sitemap_img = os.path.join(OUTPUT_DIR, "06_task_detail_sitemap.png")
            await page.screenshot(path=sitemap_img, full_page=False)
            print(f"  -> 已保存: {sitemap_img}")
        except Exception as e:
            print(f"  -> Sitemap Tab 异常: {e}")

        # 7. 全网外部域名知识库
        print("[7/9] 正在截取: 全网外部域名知识库...")
        await page.goto(f"{BASE_URL}/global-domains", wait_until="networkidle")
        await asyncio.sleep(3)
        global_domains_img = os.path.join(OUTPUT_DIR, "07_global_domains_knowledge_base.png")
        await page.screenshot(path=global_domains_img, full_page=False)
        print(f"  -> 已保存: {global_domains_img}")

        # 8. 风险页面待处置中心
        print("[8/9] 正在截取: 风险页面待处置中心...")
        await page.goto(f"{BASE_URL}/remediation", wait_until="networkidle")
        await asyncio.sleep(2.5)
        remediation_img = os.path.join(OUTPUT_DIR, "08_risk_remediation.png")
        await page.screenshot(path=remediation_img, full_page=False)
        print(f"  -> 已保存: {remediation_img}")

        # 9. 威胁情报规则中心
        print("[9/9] 正在截取: 威胁情报规则中心...")
        await page.goto(f"{BASE_URL}/threat-intel", wait_until="networkidle")
        await asyncio.sleep(2.5)
        intel_img = os.path.join(OUTPUT_DIR, "09_threat_intelligence.png")
        await page.screenshot(path=intel_img, full_page=False)
        print(f"  -> 已保存: {intel_img}")

        await browser.close()
        print("[*] 全部截图采集完成！")


if __name__ == "__main__":
    asyncio.run(capture_all())
