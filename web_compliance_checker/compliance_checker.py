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
from probe_engine import FastDomainProbeEngine
from history_manager import GLOBAL_HISTORY_MANAGER


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
    parser.add_argument("--enable-probe", dest="enable_probe", action="store_true", default=True, help="启用轻量级快速探活前置过滤 (默认开启，毫秒级剔除死链)")
    parser.add_argument("--no-probe", dest="enable_probe", action="store_false", help="禁用轻量级前置探活")
    parser.add_argument("--enable-dns-probe", dest="enable_dns_probe", action="store_true", default=True, help="探活前启用异步 DNS (nslookup) 预解析 (默认开启，毫秒过滤 NXDOMAIN 与 SSRF)")
    parser.add_argument("--no-dns-probe", dest="enable_dns_probe", action="store_false", help="探活前禁用 DNS 预解析")
    parser.add_argument("--dns-timeout", type=float, default=1.2, help="DNS 预解析单目标超时阈值 (秒，默认 1.2s)")
    parser.add_argument("--probe-timeout", type=float, default=2.5, help="前置探活单目标超时阈值 (秒，默认 2.5s)")
    parser.add_argument("--probe-concurrency", type=int, default=30, help="前置探活最大并发数 (默认 30)")
    parser.add_argument("--resume-job", default=None, help="从指定历史批次任务 ID 恢复断点")
    parser.add_argument("--job-id", default=None, help="显式指定批次任务 ID (用于 Web 控制台历史追踪)")

    # 爬虫与审核核心参数
    parser.add_argument("--delay", type=float, default=3.0, help="截图前延迟等待时间 (秒，默认 3.0)")
    parser.add_argument("--api-base", default="http://localhost:11434/v1", help="本地多模态模型 API 服务地址")
    parser.add_argument("--api-key", default="EMPTY", help="API Key")
    parser.add_argument("--model", default="qwen2-vl", help="多模态模型标识名称 (如 qwen2-vl, llava, minicpm-v)")
    parser.add_argument("--devices", default="all", help="测试设备列表 (以逗号分隔，如 desktop_chrome,mobile_iphone_safari 或 all)")
    parser.add_argument("--workers", "-w", dest="workers", type=int, default=None, help="并发巡检工作线程数 (同时设置浏览器与模型并发，如 -w 3)")
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

    if args.workers is not None:
        args.concurrency_browser = args.workers
        args.concurrency_llm = args.workers

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
                if args.resume_job:
                    processed_set = GLOBAL_HISTORY_MANAGER.get_processed_domains(args.resume_job)
                    if processed_set:
                        tasks = [t for t in tasks if t.get("domain") not in processed_set]
                        if not args.quiet:
                            print(f"[*] 断点续爬模式: 已根据批次 [{args.resume_job}] 过滤跳过 {len(processed_set)} 个已完成域名，本批剩余 {len(tasks)} 条", flush=True)

                if not tasks:
                    if args.db_loop:
                        if not args.quiet:
                            print(f"[*] 暂无待处理域名任务，休眠 {args.db_poll_interval}s 后继续监听新任务...", flush=True)
                        await asyncio.sleep(args.db_poll_interval)
                        continue
                    else:
                        if not args.quiet:
                            print("[*] 数据库中没有符合条件的待审核域名任务。", flush=True)
                        break

                current_job_id = args.job_id or args.resume_job or datetime.now().strftime("job_%Y%m%d_%H%M%S")
                GLOBAL_HISTORY_MANAGER.create_job(
                    current_job_id,
                    vars(args),
                    [t.get("domain", "") for t in tasks]
                )

                if not args.quiet:
                    print(f"\n[*] 从 {db_source.upper()} 检索到 {len(tasks)} 条待巡检域名任务 (总域名库去重):", flush=True)
                    for idx, t in enumerate(tasks[:15], start=1):
                        ref_info = f" (关联任务数: {t.get('raw_record', {}).get('ref_count', 1)})" if t.get('raw_record', {}).get('ref_count') else ""
                        print(f"    {idx}. 域名: {t['domain']}{ref_info} | 访问URL: {t['target_url']} | 状态: {t['verify_status']} | 等级: {t['risk_level']}", flush=True)
                    if len(tasks) > 15:
                        print(f"    ... 及其余 {len(tasks) - 15} 条独立域名", flush=True)

                if args.dry_run:
                    print("\n[*] 【预检模式 (DRY RUN)】已列出待巡检去重域名清单，未消耗流量与算力。", flush=True)
                    GLOBAL_HISTORY_MANAGER.finish_job(current_job_id, status="completed", message="预检模式完成")
                    break

                # 2. 前置轻量级极速探活 (若启用)
                if args.enable_probe:
                    if not args.quiet:
                        dns_tip = f", DNS预检: {args.dns_timeout}s" if args.enable_dns_probe else ", DNS预检: 禁用"
                        print(f"[*] 🚀 启动轻量级快速探活前置过滤 (并发: {args.probe_concurrency}, HTTP超时: {args.probe_timeout}s{dns_tip})...", flush=True)
                    probe_engine = FastDomainProbeEngine(
                        default_timeout=args.probe_timeout,
                        dns_timeout=args.dns_timeout,
                        enable_dns_probe=args.enable_dns_probe
                    )
                    probe_res = await probe_engine.probe_batch(
                        tasks,
                        target_field="target_url",
                        max_concurrency=args.probe_concurrency
                    )
                    alive_tasks = probe_res["alive_tasks"]
                    dead_tasks = probe_res["dead_tasks"]
                    p_stats = probe_res.get("stats", {})
                    if not args.quiet:
                        print(
                            f"[*] 探活完成: 共 {len(tasks)} 条 | 存活: {len(alive_tasks)} 条 | "
                            f"DNS未解析(NXDOMAIN): {p_stats.get('dns_nxdomain_count', 0)} 条 | "
                            f"内网/SSRF阻断: {p_stats.get('dns_private_ip_count', 0)} 条 | "
                            f"HTTP不可达: {p_stats.get('http_dead_count', 0)} 条",
                            flush=True
                        )

                    # 处理不可达死链与安全拦截：自动标记并回写数据库
                    for dead_item in dead_tasks:
                        d_info = dead_item.get("probe_result", {})
                        reason = d_info.get("error_reason") or "连接超时/DNS解析失败"
                        dead_dom = dead_item["domain"]
                        is_sec_risk = d_info.get("is_security_risk", False)
                        dns_status = d_info.get("dns_status", "UNKNOWN")
                        resolved_ips = d_info.get("resolved_ips", [])
                        cnames = d_info.get("cnames", [])

                        if is_sec_risk:
                            is_viol = True
                            risk_lvl = "HIGH"
                            p_cat = "ssrf_risk"
                            p_cn = "内网穿透/SSRF风险"
                            remark = f"[DNS安全拦截] {reason}"
                        else:
                            is_viol = False
                            risk_lvl = "SAFE"
                            p_cat = "dead_domain"
                            p_cn = "站点不可达 (DNS未解析)" if dns_status in ("NXDOMAIN", "NO_ANSWER") else "站点不可达"
                            remark = f"[前置探活不可达] {reason}，自动标记合规跳过"

                        dead_record = {
                            "domain": dead_dom,
                            "url": dead_item.get("target_url"),
                            "checked_at": datetime.now(timezone.utc).isoformat(),
                            "model_used": "fast_probe_dns" if d_info.get("stage") in ("dns_failed", "dns_blocked") else "fast_probe_filter",
                            "verdict_summary": {
                                "is_violation": is_viol,
                                "overall_risk_level": risk_lvl,
                                "primary_violation_category": p_cat,
                                "primary_violation_cn": p_cn,
                                "cloaking_suspected": False,
                                "cloaking_notes": remark,
                                "dns_resolved_ips": resolved_ips,
                                "dns_cnames": cnames,
                                "dns_status": dns_status,
                                "category_probabilities": {}
                            },
                            "device_inspections": []
                        }
                        db_mgr.save_audit_result(dead_record, task_item=dead_item, sink=db_sink)
                        GLOBAL_HISTORY_MANAGER.update_checkpoint(current_job_id, dead_dom, is_dead=True)
                        if not args.quiet:
                            tag = "[DNS安全阻断]" if is_sec_risk else "[探活跳过]"
                            print(f"  -> {tag} 域名: {dead_dom} => {reason}，已自动持久化入库", flush=True)

                    tasks = alive_tasks
                    if not tasks:
                        if not args.quiet:
                            print("[*] 本批次所有待审域名均为不可达死链，已全部自动标记并持久化入库。", flush=True)
                        GLOBAL_HISTORY_MANAGER.finish_job(current_job_id, status="completed", message="所有目标均为死链并已跳过")
                        if not args.db_loop:
                            break
                        continue

                # 建立访问 URL 到任务记录的映射 (处理同一域名在多任务中出现的情况)
                url_to_tasks = {}
                for t in tasks:
                    t_url = t["target_url"]
                    if t_url not in url_to_tasks:
                        url_to_tasks[t_url] = []
                    url_to_tasks[t_url].append(t)

                distinct_target_urls = list(url_to_tasks.keys())
                if not args.quiet:
                    print(f"[*] 存活目标去重后实际访问 URL: {len(distinct_target_urls)} 个，启动多端仿真与多模态流水线...")

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

                    summ = res.get("verdict_summary", {})
                    is_viol = summ.get("is_violation", False)

                    for t_item in matched_tasks:
                        probe_info = t_item.get("probe_result") or {}
                        if probe_info.get("resolved_ips"):
                            summ["dns_resolved_ips"] = probe_info["resolved_ips"]
                        if probe_info.get("cnames"):
                            summ["dns_cnames"] = probe_info["cnames"]
                        if probe_info.get("dns_status"):
                            summ["dns_status"] = probe_info["dns_status"]

                        db_mgr.save_audit_result(res, task_item=t_item, sink=db_sink)
                        saved_count += 1
                        GLOBAL_HISTORY_MANAGER.update_checkpoint(
                            current_job_id,
                            t_item["domain"],
                            is_violation=is_viol,
                            detail_info=summ
                        )
                        if not args.quiet:
                            r_lvl = summ.get("overall_risk_level", "SAFE")
                            p_cat = summ.get("primary_violation_category", "normal")
                            v_status = "verified_failed" if is_viol else "verified_clean"
                            print(f"  -> [已回写入库] ID: {t_item['id']} | Task:{t_item['task_id']} | {t_item['domain']} => 状态: {v_status}, 等级: {r_lvl}, 分类: {p_cat}")

                if not args.quiet:
                    print(f"[*] 入库完成！成功同步更新 {saved_count} 条数据库域名记录。")

                GLOBAL_HISTORY_MANAGER.finish_job(current_job_id, status="completed", message=f"处理完成，回写 {saved_count} 条记录")

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
