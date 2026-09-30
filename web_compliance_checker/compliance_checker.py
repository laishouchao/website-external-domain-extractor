"""
High-concurrency entry point for Web Compliance Checker.
Supports single URL, batch files, and full Database-Driven operation (PostgreSQL & ClickHouse),
including schema initialization, task queue consumption, and continuous polling daemon mode.
"""

import os
import sys
import json
import asyncio
import argparse
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

# 确保在 Windows 控制台环境下正确输出 UTF-8 字符
if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from config import DEVICE_PROFILES, CONCURRENCY_CONFIG
from pipeline import DecoupledInspectionPipeline
from db_manager import UnifiedDatabaseManager


def progress_reporter(current_idx: int, total_count: int, result: Dict[str, Any]):
    """
    终端实时进度回调展示
    """
    url = result.get("url")
    summary = result.get("verdict_summary", {})
    is_violation = summary.get("is_violation", False)
    risk_level = summary.get("overall_risk_level", "SAFE")
    cloaking = summary.get("cloaking_suspected", False)
    primary_cat = summary.get("primary_violation_category", "normal")

    status_tag = "[违规!]" if is_violation else "[正常]"
    cloaking_tag = " (存在设备伪装/Cloaking)" if cloaking else ""

    print(
        f"[{current_idx}/{total_count}] {status_tag} {url} "
        f"| 风险等级: {risk_level} | 主要类型: {primary_cat}{cloaking_tag}"
    )


async def async_main():
    parser = argparse.ArgumentParser(
        description="高并发多端仿真与本地多模态模型网页违规合规审查系统 (支持 PostgreSQL 与 ClickHouse)"
    )
    # 输入源模式
    parser.add_argument("urls", nargs="*", help="待检测的目标网页 URL (支持传入单个或多个)")
    parser.add_argument("--url", dest="single_url", help="待审核的目标网页 URL (显式参数)")
    parser.add_argument("--file", "-f", help="包含批量待审核 URL 的文本文件路径 (每行一个 URL)")

    # 数据库模式参数
    parser.add_argument("--db", action="store_true", help="启用数据库模式 (从数据库读取待巡检域名并将结果回写入库)")
    parser.add_argument("--db-config", default="db_config.json", help="数据库配置文件路径 (默认 db_config.json)")
    parser.add_argument("--db-source", choices=["postgres", "clickhouse", "pg", "ch"], default=None, help="待巡检域名的读取源数据库")
    parser.add_argument("--db-sink", choices=["postgres", "clickhouse", "both", "pg", "ch"], default=None, help="审核结果回写目标数据库 (默认 both 写入 PG与CH)")
    parser.add_argument("--db-batch-size", type=int, default=None, help="单次从数据库中提取的域名任务批次数量")
    parser.add_argument("--db-loop", action="store_true", help="启用守护进程轮询模式 (持续监听数据库新任务)")
    parser.add_argument("--db-poll-interval", type=int, default=10, help="轮询模式下无新任务时的休眠秒数 (默认 10s)")
    parser.add_argument("--db-init", action="store_true", help="自动在 PostgreSQL 与 ClickHouse 中创建所需表结构")

    # 本系统数据库特征适配参数
    parser.add_argument("--task-id", type=int, default=None, help="仅提取指定主任务 ID 的外部域名 (如 --task-id 93)")
    parser.add_argument("--target-table", default=None, help="数据库源任务表名 (默认 external_domains，亦支持 risk_page_remediations 等)")
    parser.add_argument("--target-field", choices=["domain", "sample_page_url"], default=None, help="巡检目标地址字段 (默认 domain 即 https://domain，可选 sample_page_url 巡检溯源采样页)")
    parser.add_argument("--risk-level", default=None, help="按风险等级筛选域名 (如 pending, high, safe 或 all)")
    parser.add_argument("--verify-status", default=None, help="按研判状态筛选域名 (如 unverified, verified_clean, verified_failed 或 all)")
    parser.add_argument("--domain-filter", default=None, help="按域名关键字模糊筛选 (如 qq.com)")
    parser.add_argument("--dry-run", action="store_true", help="仅从数据库检索并打印匹配的域名任务清单，不执行爬虫和模型推理")

    # 爬虫与审核核心参数
    parser.add_argument("--delay", type=float, default=3.0, help="截图前延迟等待时间 (秒，默认 3.0)")
    parser.add_argument("--api-base", default="http://localhost:11434/v1", help="本地多模态模型 API 服务地址")
    parser.add_argument("--api-key", default="EMPTY", help="API Key")
    parser.add_argument("--model", default="qwen2-vl", help="多模态模型标识名称 (如 qwen2-vl, llava, minicpm-v)")
    parser.add_argument("--devices", default="all", help="测试设备列表 (以逗号分隔，如 desktop_chrome,mobile_iphone_safari 或 all)")
    parser.add_argument("--concurrency-browser", type=int, default=CONCURRENCY_CONFIG["default_browser_concurrency"], help="浏览器池最大并发渲染标签页数")
    parser.add_argument("--concurrency-llm", type=int, default=CONCURRENCY_CONFIG["default_llm_concurrency"], help="多模态模型最大并行推理请求数 (保护本地显存)")
    parser.add_argument("--slices", type=int, default=1, help="单设备分屏切片数量 (1=仅首屏, 2=首屏+页底, 3=首屏+中部+页底，不失真)")
    parser.add_argument("--max-height", type=int, default=2500, help="整页截图模式下的智能高度截断阈值 (px，防止万像素大图模糊)")
    parser.add_argument("--output-dir", default="output", help="截图及审核结果保存目录")
    parser.add_argument("--web", action="store_true", help="启动可视化 Web 监控控制台 (在浏览器中查看实时进度与证据链截图)")
    parser.add_argument("--web-port", type=int, default=8888, help="可视化 Web 控制台端口 (默认 8888)")
    parser.add_argument("--full-page", action="store_true", help="是否截取整页长图 (开启后受 max-height 智能截断保护)")
    parser.add_argument("--no-headless", action="store_true", help="显示浏览器窗口进行可视化调试")
    parser.add_argument("--mock", action="store_true", help="开启仿真测试模式 (跳过真实大模型调用)")
    parser.add_argument("--quiet", action="store_true", help="静默模式，仅在标准输出打印最终 JSON")

    args = parser.parse_args()

    # 可视化 Web 控制台启动模式
    if args.web:
        from dashboard_server import run_dashboard
        run_dashboard(port=args.web_port, output_dir=args.output_dir)
        return

    # 数据库管理器初始化
    db_mgr: Optional[UnifiedDatabaseManager] = None
    if args.db or args.db_init:
        db_mgr = UnifiedDatabaseManager(config_path=args.db_config)
        if args.db_init:
            print("[*] 正在执行数据库表结构初始化...")
            db_mgr.init_schemas()
            if not args.db and not args.urls and not args.file:
                print("[*] 表结构初始化完成，程序退出。")
                return

    # 筛选设备 Profiles
    selected_profiles = []
    if args.devices == "all":
        selected_profiles = DEVICE_PROFILES
    else:
        req_ids = [d.strip() for d in args.devices.split(",")]
        selected_profiles = [p for p in DEVICE_PROFILES if p["id"] in req_ids]
        if not selected_profiles:
            selected_profiles = DEVICE_PROFILES

    # 实例化流水线
    pipeline = DecoupledInspectionPipeline(
        api_base=args.api_base,
        api_key=args.api_key,
        model=args.model,
        browser_concurrency=args.concurrency_browser,
        llm_concurrency=args.concurrency_llm,
        output_dir=args.output_dir,
        headless=not args.no_headless,
        is_mock=args.mock
    )

    callback = None if args.quiet else progress_reporter

    # ==================== 1. 数据库驱动模式 ====================
    if args.db:
        if not db_mgr:
            db_mgr = UnifiedDatabaseManager(config_path=args.db_config)

        db_source = args.db_source or db_mgr.config.get("default_source", "postgres")
        if db_source in ("pg", "postgres"):
            db_source = "postgres"
        elif db_source in ("ch", "clickhouse"):
            db_source = "clickhouse"

        db_sink = args.db_sink or db_mgr.config.get("default_sink", "both")
        batch_limit = args.db_batch_size or db_mgr.config.get("batch_size", 50)

        target_table = args.target_table or db_mgr.config.get("postgres", {}).get("task_table", "external_domains")
        target_field = args.target_field or db_mgr.config.get("target_field", "domain")

        if not args.quiet:
            print("=" * 60)
            print("   【数据库驱动模式启动】PostgreSQL & ClickHouse 集成")
            print("=" * 60)
            print(f"[*] 任务读取源: {db_source.upper()} (表: {target_table}) | 结果回写目标: {db_sink.upper()}")
            print(f"[*] 巡检目标字段: {target_field} | 单批上限: {batch_limit} 条 | 运行模式: {'常驻轮询守护进程' if args.db_loop else '单次批处理'}")
            if args.task_id is not None:
                print(f"[*] 关联任务过滤: task_id = {args.task_id}")
            if args.risk_level:
                print(f"[*] 风险等级过滤: risk_level = {args.risk_level}")
            if args.verify_status:
                print(f"[*] 研判状态过滤: verify_status = {args.verify_status}")
            if args.domain_filter:
                print(f"[*] 域名模糊过滤: domain LIKE '%{args.domain_filter}%'")
            print(f"[*] 启用设备数量: {len(selected_profiles)} 个 | 切片数: {args.slices}")
            print("=" * 60)

        while True:
            try:
                # 获取待巡检任务
                tasks = db_mgr.fetch_pending_tasks(
                    source=db_source,
                    limit=batch_limit,
                    task_id=args.task_id,
                    risk_level=args.risk_level,
                    verify_status=args.verify_status,
                    domain_filter=args.domain_filter,
                    target_table=target_table,
                    target_field=target_field
                )
                if not tasks:
                    if args.db_loop:
                        if not args.quiet:
                            print(f"[*] 暂无待处理域名任务，休眠 {args.db_poll_interval}s 后重试...", end="\r")
                        await asyncio.sleep(args.db_poll_interval)
                        continue
                    else:
                        if not args.quiet:
                            print("[*] 数据库中没有符合条件的待审核域名任务。")
                        break

                if not args.quiet:
                    print(f"\n[*] 从 {db_source.upper()} 检索到 {len(tasks)} 条待巡检域名任务:")
                    for idx, t in enumerate(tasks[:10], start=1):
                        print(f"    {idx}. [ID:{t['id']}] Task:{t['task_id']} | 域名: {t['domain']} | 访问URL: {t['target_url']} | 状态: {t['verify_status']} | 等级: {t['risk_level']}")
                    if len(tasks) > 10:
                        print(f"    ... 及其余 {len(tasks) - 10} 条域名记录")

                if args.dry_run:
                    print("\n[*] 【预检模式 (DRY RUN)】已列出待巡检目标，未执行网页访问与数据回写。")
                    break

                # 建立访问 URL 到任务记录的映射 (处理同一域名在多任务中出现的情况)
                url_to_tasks = {}
                for t in tasks:
                    t_url = t["target_url"]
                    if t_url not in url_to_tasks:
                        url_to_tasks[t_url] = []
                    url_to_tasks[t_url].append(t)

                distinct_target_urls = list(url_to_tasks.keys())
                if not args.quiet:
                    print(f"[*] 去重后实际访问目标 URL 数量: {len(distinct_target_urls)} 个，启动全异步流水线...")

                # 运行流水线
                batch_summary = await pipeline.run_pipeline(
                    urls=distinct_target_urls,
                    selected_profiles=selected_profiles,
                    delay=args.delay,
                    slices_count=args.slices,
                    full_page=args.full_page,
                    max_height=args.max_height,
                    progress_callback=callback
                )

                # 将审核结果回写入库 (PG 更新任务+存证，CH 写入分析时序表)
                if not args.quiet:
                    print(f"\n[*] 正在将 {len(batch_summary['results'])} 条检测结果回写至数据库 ({db_sink.upper()})...")

                saved_count = 0
                for res in batch_summary["results"]:
                    res_url = res.get("url")
                    matched_tasks = url_to_tasks.get(res_url, [])
                    if not matched_tasks:
                        res_clean = (res_url or "").rstrip("/")
                        for k, v in url_to_tasks.items():
                            if k.rstrip("/") == res_clean:
                                matched_tasks = v
                                break

                    for t_item in matched_tasks:
                        db_mgr.save_audit_result(res, task_item=t_item, sink=db_sink)
                        saved_count += 1
                        if not args.quiet:
                            summ = res.get("verdict_summary", {})
                            r_lvl = summ.get("overall_risk_level", "SAFE")
                            p_cat = summ.get("primary_violation_category", "normal")
                            v_status = "verified_failed" if summ.get("is_violation") else "verified_clean"
                            print(f"  -> [已回写入库] ID: {t_item['id']} | Task:{t_item['task_id']} | {t_item['domain']} => 状态: {v_status}, 等级: {r_lvl}, 分类: {p_cat}")

                if not args.quiet:
                    print(f"[*] 入库完成！成功同步更新 {saved_count} 条数据库域名记录。")

                if not args.db_loop:
                    break

            except KeyboardInterrupt:
                print("\n[*] 收到退出信号，安全退出守护进程。")
                break
            except Exception as e:
                print(f"[错误] 数据库模式运行异常: {e}")
                if args.db_loop:
                    await asyncio.sleep(args.db_poll_interval)
                else:
                    break

        db_mgr.close()
        return

    # ==================== 2. CLI 参数 / 文件模式 ====================
    target_urls = []
    if args.urls:
        target_urls.extend(args.urls)
    if args.single_url:
        target_urls.append(args.single_url)
    if args.file:
        if os.path.exists(args.file):
            with open(args.file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#"):
                        target_urls.append(line)
        else:
            print(f"[错误] 未找到指定的 URL 文件: {args.file}", file=sys.stderr)
            sys.exit(1)

    if not target_urls:
        parser.print_help()
        sys.exit(1)

    if not args.quiet:
        print("=" * 60)
        print("   高并发多端仿真 & 本地多模态网页安全审核流水线启动")
        print("=" * 60)
        print(f"[*] 待巡检 URL 数量: {len(target_urls)}")
        print(f"[*] 启用设备数量: {len(selected_profiles)} 个 ({', '.join(p['id'] for p in selected_profiles)})")
        print(f"[*] 单端切片数: {args.slices} (100% 原始视口高清不失真)")
        print(f"[*] 延迟截屏等待: {args.delay}s")
        print(f"[*] 并发控制: 浏览器渲染并发 = {args.concurrency_browser} | 模型推理并发 = {args.concurrency_llm}")
        print(f"[*] 审核模型: {args.model} | 服务端点: {args.api_base}")
        print(f"[*] 模式: {'【仿真测试 (MOCK)】' if args.mock else '【生产模型推理】'}")
        print("-" * 60)

    # 执行批处理巡检
    batch_summary = await pipeline.run_pipeline(
        urls=target_urls,
        selected_profiles=selected_profiles,
        delay=args.delay,
        slices_count=args.slices,
        full_page=args.full_page,
        max_height=args.max_height,
        progress_callback=callback
    )

    if not args.quiet:
        print("-" * 60)
        meta = batch_summary["batch_metadata"]
        print(f"[*] 批量审核完成!")
        print(f"[*] 总数: {meta['total_urls']} | 违规: {meta['violation_urls_count']} | 正常: {meta['clean_urls_count']}")
        print(f"[*] 实时行流文件 (JSONL): {meta['jsonl_records_file']}")
        print(f"[*] 批量汇总文件 (JSON): {batch_summary['summary_file']}")
        print("=" * 60)

    if len(target_urls) == 1:
        single_result = batch_summary["results"][0]
        print(json.dumps(single_result, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(batch_summary, ensure_ascii=False, indent=2))


def main():
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
