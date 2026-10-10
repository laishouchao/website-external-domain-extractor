"""
Web Compliance Checker - Unified CLI & Service Runner
"""

import os
import sys
import argparse
import asyncio
import time

# Ensure directory is in sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import DEFAULT_WORKERS, DEFAULT_BATCH_SIZE, DEVICE_PRESETS
from db import GLOBAL_DB
from prober import probe_domain
from inspector import GLOBAL_INSPECTOR
from runner import GLOBAL_RUNNER
from server import run_server

def parse_args():
    parser = argparse.ArgumentParser(description="Web Compliance Checker CLI")
    parser.add_argument("--server", action="store_true", help="启动 Web 控制台大屏服务")
    parser.add_argument("--port", type=int, default=8888, help="Web 服务监听端口 (默认: 8888)")
    parser.add_argument("--db", action="store_true", help="从 PostgreSQL 数据库批量读取待研判域名任务")
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS, help="并发工作线程数")
    parser.add_argument("--db-batch-size", type=int, default=DEFAULT_BATCH_SIZE, help="单批次读取域名条数")
    parser.add_argument("--devices", type=str, default="dual", help="设备选型: dual, pc, full 或逗号分隔设备名")
    parser.add_argument("--domain", type=str, default=None, help="单域名现场审计模式")
    parser.add_argument("--domain-filter", type=str, default="", help="数据库域名模糊过滤 (LIKE)")
    parser.add_argument("--db-loop", action="store_true", help="开启后台常驻守护轮询模式")
    parser.add_argument("--mock", action="store_true", help="仿真演练模式 (跳过写库与真实大模型)")
    return parser.parse_args()

def main():
    args = parse_args()

    # 1. Single domain mode
    if args.domain:
        print(f"[*] 🚀 启动单域名即时合规研判: {args.domain}")
        devs = DEVICE_PRESETS.get(args.devices, DEVICE_PRESETS["dual"])
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        res = loop.run_until_complete(GLOBAL_INSPECTOR.inspect(domain=args.domain, devices=devs))
        loop.close()

        print("=" * 60)
        print(f"[*] 域名: {res['domain']} | 耗时: {res['elapsed_sec']:.2f}s")
        print(f"[*] 状态: {res['status']} | 违规: {res['is_violation']} | 404: {res['is_404']}")
        print(f"[*] 主类别: {res['primary_violation']} | 风险等级: {res['risk_level']}")
        print(f"[*] 研判说明:\n{res['explanation']}")
        print("=" * 60)
        return

    # 2. Database batch scan mode
    if args.db:
        devs = DEVICE_PRESETS.get(args.devices, DEVICE_PRESETS["dual"])
        print(f"[*] 🚀 启动数据库批处理巡检: 并发={args.workers}, 批次={args.db_batch_size}, 设备={args.devices}")
        GLOBAL_RUNNER.start(
            workers=args.workers,
            batch_size=args.db_batch_size,
            devices=devs,
            domain_filter=args.domain_filter,
            is_loop=args.db_loop,
            is_dry_run=args.mock
        )
        try:
            while GLOBAL_RUNNER.is_running:
                time.sleep(1)
        except KeyboardInterrupt:
            GLOBAL_RUNNER.stop()
            print("\n已安全停止。")
        return

    # 3. Default: Start Web Server
    run_server(host="0.0.0.0", port=args.port)

if __name__ == "__main__":
    main()
