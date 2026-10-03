"""
Lightweight Web Dashboard Server for Web Compliance Checker.
Directly connected to system database (PostgreSQL & ClickHouse website_domain_db).
Zero external dependencies (uses standard library http.server).
Features:
- Master-Detail Split View, Real-Time Database Metrics (Distinct Domain & Row Counts).
- Server-Side Filtering, Pagination, Full-Text Search.
- In-Browser Scan Runner Control:
    1. Dry-Run Inspection Preview (Zero resource cost).
    2. Batch Automated Inspection (Total Distinct Domains Driven, workers=3).
    3. Background Daemon Continuous Loop Mode (Polling DB every 15s).
    4. Stop Running Task / Daemon.
    5. Single Domain Instant Inspection (Inspect Now).
- Real-Time Progress Bar & Streaming Terminal Log Drawer.
"""

import os
import sys
import json
import math
import mimetypes
import urllib.parse
import subprocess
import threading
import collections
import re
from datetime import datetime
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from typing import Dict, Any, List, Optional, Tuple

if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Ensure web_compliance_checker directory is in sys.path
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

from db_manager import UnifiedDatabaseManager
from export_manager import GLOBAL_EXPORT_MANAGER
from history_manager import GLOBAL_HISTORY_MANAGER

# ==============================================================================
# Inspection Job Runner (Global Singleton for Web-Controlled Scanning)
# ==============================================================================
class InspectionJobRunner:
    def __init__(self, output_dir: str = "output"):
        self.output_dir = output_dir
        self.process: Optional[subprocess.Popen] = None
        self.is_running = False
        self.job_id = None
        self.start_time = None
        self.config: Dict[str, Any] = {}
        self.logs = collections.deque(maxlen=600)
        self.lock = threading.RLock()
        self.stats = {
            "total": 0,
            "completed": 0,
            "violations": 0,
            "dead_skipped": 0,
            "current_target": "",
            "message": "巡检引擎待命中",
            "is_loop": False,
            "is_dry_run": False,
            "enable_probe": True
        }

    def _log(self, text: str):
        with self.lock:
            self.logs.append(text)

    def start_job(self, config: Dict[str, Any]) -> Tuple[bool, str]:
        with self.lock:
            if self.is_running and self.process and self.process.poll() is None:
                return False, "当前已有巡检任务正在运行中，请等待其完成或点击中止。"

            workers = int(config.get("workers", 3))
            batch_size = int(config.get("batch_size", 30))
            task_id = config.get("task_id")
            devices = config.get("devices", "all")
            loop = bool(config.get("loop", False))
            poll_interval = int(config.get("poll_interval", 15))
            mock = bool(config.get("mock", False))
            dry_run = bool(config.get("dry_run", False))
            domain_filter = config.get("domain_filter")
            enable_probe = bool(config.get("enable_probe", True))
            probe_timeout = float(config.get("probe_timeout", 2.5))
            enable_dns_probe = bool(config.get("enable_dns_probe", True))
            dns_timeout = float(config.get("dns_timeout", 1.2))
            resume_job_id = config.get("resume_job_id")

            cmd = [
                sys.executable,
                os.path.join(current_dir, "compliance_checker.py"),
                "--db",
                "--workers", str(workers),
                "--db-batch-size", str(batch_size),
                "--output-dir", self.output_dir,
            ]
            if not enable_probe:
                cmd.append("--no-probe")
            else:
                cmd.extend(["--probe-timeout", str(probe_timeout)])
                if not enable_dns_probe:
                    cmd.append("--no-dns-probe")
                else:
                    cmd.extend(["--dns-timeout", str(dns_timeout)])
            if resume_job_id:
                cmd.extend(["--resume-job", str(resume_job_id)])
            if dry_run:
                cmd.append("--dry-run")
            if loop:
                cmd.extend(["--db-loop", "--db-poll-interval", str(poll_interval)])
            if task_id:
                cmd.extend(["--task-id", str(task_id)])
            if devices and devices != "all":
                cmd.extend(["--devices", devices])
            if mock:
                cmd.append("--mock")
            if domain_filter:
                cmd.extend(["--domain-filter", str(domain_filter)])

            self.job_id = resume_job_id or datetime.now().strftime("job_%Y%m%d_%H%M%S")
            cmd.extend(["--job-id", self.job_id])
            self.start_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self.config = config
            self.is_running = True
            self.stats = {
                "total": batch_size if not domain_filter else 1,
                "completed": 0,
                "violations": 0,
                "dead_skipped": 0,
                "current_target": "正在从总域名库抽取去重待审域名...",
                "message": "常驻守护监听中..." if loop else ("预检目标分析中..." if dry_run else "巡检流水线启动中..."),
                "is_loop": loop,
                "is_dry_run": dry_run,
                "enable_probe": enable_probe
            }
            self.logs.clear()
            self._log(f"[{datetime.now().strftime('%H:%M:%S')}] 🚀 启动任务: {' '.join(cmd)}")

            sub_env = os.environ.copy()
            sub_env["PYTHONIOENCODING"] = "utf-8"
            sub_env["PYTHONUTF8"] = "1"

            try:
                self.process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                    encoding="utf-8",
                    errors="replace",
                    cwd=current_dir,
                    env=sub_env
                )
                t = threading.Thread(target=self._monitor_process, daemon=True)
                t.start()
                return True, "巡检任务已成功启动"
            except Exception as e:
                self.is_running = False
                return False, f"启动子进程失败: {e}"

    def stop_job(self) -> Tuple[bool, str]:
        with self.lock:
            if not self.is_running or not self.process:
                return False, "当前无正在运行的巡检任务"
            try:
                if sys.platform.startswith("win"):
                    subprocess.call(["taskkill", "/F", "/T", "/PID", str(self.process.pid)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                else:
                    self.process.terminate()
                self._log(f"[{datetime.now().strftime('%H:%M:%S')}] 🛑 巡检任务已被用户手动终止")
                self.is_running = False
                self.stats["message"] = "已手动中止"
                self.stats["is_loop"] = False
                return True, "巡检任务已成功终止"
            except Exception as e:
                return False, f"终止任务失败: {e}"

    def _monitor_process(self):
        progress_pattern = re.compile(r"\[(\d+)/(\d+)\]\s*(\[.*?\])\s*(\S+)")
        try:
            for line in self.process.stdout:
                line_str = line.rstrip()
                if not line_str:
                    continue
                self._log(line_str)

                # 匹配探活跳过行: -> [探活跳过] 域名: xxx 不可达...
                if "[探活跳过]" in line_str:
                    with self.lock:
                        self.stats["dead_skipped"] += 1
                        self.stats["completed"] += 1
                        self.stats["message"] = line_str.split("->")[-1].strip()

                # 匹配终端进度行: [1/30] [违规!] https://...
                m = progress_pattern.search(line_str)
                if m:
                    cur_idx = int(m.group(1))
                    tot_cnt = int(m.group(2))
                    tag = m.group(3)
                    url = m.group(4)
                    with self.lock:
                        self.stats["completed"] = cur_idx
                        self.stats["total"] = tot_cnt
                        self.stats["current_target"] = url
                        if "违规" in tag:
                            self.stats["violations"] += 1
                        self.stats["message"] = f"正在检测: {url}"

            self.process.wait()
        except Exception as e:
            self._log(f"[异常] 监控进程异常: {e}")
        finally:
            with self.lock:
                self.is_running = False
                self.stats["is_loop"] = False
                self.stats["message"] = f"巡检已完成 (共处理 {self.stats['completed']} 条目标)"
                self._log(f"[{datetime.now().strftime('%H:%M:%S')}] ✅ 巡检进程已退出，结果已全部持久化至数据库")

    def get_status(self) -> Dict[str, Any]:
        with self.lock:
            if self.is_running and self.process and self.process.poll() is not None:
                self.is_running = False
                self.stats["is_loop"] = False

            return {
                "is_running": self.is_running,
                "job_id": self.job_id,
                "start_time": self.start_time,
                "config": self.config,
                "stats": self.stats,
                "logs": list(self.logs)
            }


GLOBAL_RUNNER = InspectionJobRunner()


# ==============================================================================
# Full-Featured Dashboard HTML & Frontend Client
# ==============================================================================
DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>网页多模态合规巡检控制台 - 数据库实时大屏</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <style>
    body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
    .badge { display: inline-flex; align-items: center; padding: 0.125rem 0.5rem; border-radius: 9999px; font-size: 0.75rem; font-weight: 600; }
    ::-webkit-scrollbar { width: 6px; height: 6px; }
    ::-webkit-scrollbar-track { background: rgba(15, 23, 42, 0.6); }
    ::-webkit-scrollbar-thumb { background: rgba(51, 65, 85, 0.8); border-radius: 3px; }
    .terminal-font { font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace; }
  </style>
</head>
<body class="bg-slate-950 text-slate-100 min-h-screen antialiased p-3 sm:p-5 pb-16">
  <div class="max-w-7xl mx-auto space-y-5">

    <!-- Top Header & Scanning Controls -->
    <header class="bg-slate-900/90 border border-slate-800 rounded-2xl p-4 sm:p-5 shadow-xl flex flex-col lg:flex-row justify-between items-start lg:items-center gap-4">
      <div>
        <div class="flex flex-wrap items-center gap-2.5">
          <span class="p-2 bg-indigo-600/20 text-indigo-400 rounded-xl text-xl">🛡️</span>
          <h1 class="text-xl font-bold text-white tracking-tight">网页多端仿真与多模态安全巡检控制台</h1>
          <span class="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
            <span class="w-2 h-2 rounded-full bg-emerald-400 animate-pulse"></span> 🟢 数据库直连 (website_domain_db)
          </span>
        </div>
        <p class="text-xs text-slate-400 mt-1">集成 PostgreSQL (external_domains / compliance_audit_logs) 与 ClickHouse 实时全量数据 · 调度目标: 总域名库去重独立域名</p>
      </div>

      <!-- Action Control Buttons -->
      <div class="flex flex-wrap items-center gap-2">
        <!-- Runner Status Badge -->
        <div id="runnerStatusBadge" class="flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-semibold bg-slate-800 text-slate-300 border border-slate-700">
          <span id="runnerStatusDot" class="w-2 h-2 rounded-full bg-slate-400"></span>
          <span id="runnerStatusText">⚪ 巡检引擎待命</span>
        </div>

        <!-- Dry Run Button -->
        <button onclick="runDryRun()" id="btnDryRun" class="px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 rounded-lg text-xs font-semibold transition flex items-center gap-1.5" title="仅查看即将抽取的去重待审域名，不消耗流量与算力">
          <span>🔍</span> 预检目标
        </button>

        <!-- Start Batch Scan Button -->
        <button onclick="openConfigModal(false)" id="btnStartScan" class="px-3.5 py-1.5 bg-gradient-to-r from-emerald-600 to-teal-600 hover:from-emerald-500 hover:to-teal-500 text-white rounded-lg text-xs font-semibold transition flex items-center gap-1.5 shadow-md">
          <span>▶</span> 启动单批巡检
        </button>

        <!-- Start Loop Daemon Button -->
        <button onclick="openConfigModal(true)" id="btnStartDaemon" class="px-3 py-1.5 bg-indigo-600/30 hover:bg-indigo-600/50 text-indigo-300 border border-indigo-500/40 rounded-lg text-xs font-semibold transition flex items-center gap-1.5" title="启动常驻轮询守护监听，持续消费新外部域名">
          <span>🔄</span> 开启常驻监听
        </button>

        <!-- Stop Button (Visible during running/looping) -->
        <button onclick="stopScan()" id="btnStopScan" class="hidden px-3.5 py-1.5 bg-rose-600 hover:bg-rose-500 text-white rounded-lg text-xs font-semibold transition flex items-center gap-1.5 shadow-md animate-pulse">
          <span>⏹</span> 停止巡检/守护
        </button>

        <!-- Toggle Log Console Button -->
        <button onclick="toggleLogConsole()" id="btnToggleLog" class="px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 rounded-lg text-xs font-semibold transition flex items-center gap-1.5">
          <span>💻</span> 实时日志
        </button>

        <!-- Export Dropdown -->
        <div class="relative inline-block text-left">
          <button onclick="toggleExportMenu()" id="btnExport" class="px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 rounded-lg text-xs font-semibold transition flex items-center gap-1.5 shadow-sm" title="导出审查报表与证据材料">
            <span>📥</span> 导出报表/证据 <span class="text-[10px]">▼</span>
          </button>
          <div id="exportMenu" class="hidden absolute right-0 mt-2 w-56 rounded-xl bg-slate-900 border border-slate-800 shadow-2xl z-50 py-1.5 text-xs text-slate-200">
            <a href="javascript:void(0)" onclick="exportReport('csv_current')" class="flex items-center gap-2 px-3.5 py-2 hover:bg-slate-800 transition">
              <span>📊</span> 导出当前列表 (Excel CSV)
            </a>
            <a href="javascript:void(0)" onclick="exportReport('csv_violations')" class="flex items-center gap-2 px-3.5 py-2 hover:bg-slate-800 transition text-rose-400">
              <span>⚠️</span> 导出全库违规数据报表
            </a>
            <div class="border-t border-slate-800 my-1"></div>
            <a href="javascript:void(0)" onclick="exportReport('zip_violations')" class="flex items-center gap-2 px-3.5 py-2 hover:bg-slate-800 transition text-amber-400">
              <span>📦</span> 导出违规证据包 (ZIP含截图)
            </a>
          </div>
        </div>

        <!-- History Button -->
        <button onclick="openHistoryDrawer()" id="btnHistory" class="px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 rounded-lg text-xs font-semibold transition flex items-center gap-1.5 shadow-sm" title="查看历史巡检批次记录与断点存档">
          <span>📜</span> 历史批次
        </button>

        <!-- Refresh Button -->
        <button onclick="refreshData()" class="px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-300 border border-slate-700 rounded-lg text-xs font-semibold transition flex items-center gap-1.5 shadow-sm">
          <span>🔄</span> 刷新
        </button>
      </div>
    </header>

    <!-- Metrics Cards (Real Database Data) -->
    <div class="grid grid-cols-2 sm:grid-cols-4 gap-4">
      <div class="bg-slate-900/80 border border-slate-800 rounded-xl p-4 shadow-sm">
        <div class="text-xs font-medium text-slate-400 flex items-center justify-between">
          <span>全库独立域名 (去重)</span>
          <span class="text-[10px] text-indigo-400/80 bg-indigo-500/10 px-1.5 py-0.5 rounded font-mono">标准口径</span>
        </div>
        <div id="statTotal" class="text-2xl font-black text-white mt-1">--</div>
        <div id="statAudited" class="text-xs text-indigo-400 mt-1 truncate">全量记录: -- 条 · AI存证: -- 条</div>
      </div>
      <div class="bg-slate-900/80 border border-slate-800 rounded-xl p-4 shadow-sm">
        <div class="text-xs font-medium text-rose-400 flex items-center justify-between">
          <span>检出涉险 / 违规站点</span>
          <span class="text-[10px] text-rose-400/80 bg-rose-500/10 px-1.5 py-0.5 rounded">独立域名</span>
        </div>
        <div id="statViolations" class="text-2xl font-black text-rose-500 mt-1">--</div>
        <div id="statViolRate" class="text-xs text-rose-400/80 mt-1">违规占比: --%</div>
      </div>
      <div class="bg-slate-900/80 border border-slate-800 rounded-xl p-4 shadow-sm">
        <div class="text-xs font-medium text-amber-400 flex items-center justify-between">
          <span>设备端伪装 (Cloaking)</span>
          <span class="text-[10px] text-amber-400/80 bg-amber-500/10 px-1.5 py-0.5 rounded">深度识别</span>
        </div>
        <div id="statCloaking" class="text-2xl font-black text-amber-500 mt-1">--</div>
        <div class="text-xs text-amber-400/80 mt-1">PC正常但移动端违规</div>
      </div>
      <div class="bg-slate-900/80 border border-slate-800 rounded-xl p-4 shadow-sm">
        <div class="text-xs font-medium text-emerald-400 flex items-center justify-between">
          <span>健康合规域名</span>
          <span class="text-[10px] text-emerald-400/80 bg-emerald-500/10 px-1.5 py-0.5 rounded">独立域名</span>
        </div>
        <div id="statClean" class="text-2xl font-black text-emerald-500 mt-1">--</div>
        <div id="statPending" class="text-xs text-slate-400 mt-1 truncate">待研判域名: -- 条</div>
      </div>
    </div>

    <!-- Master-Detail Split View -->
    <div class="grid grid-cols-1 lg:grid-cols-12 gap-5">

      <!-- Left Task List (5 cols) -->
      <div class="lg:col-span-5 bg-slate-900/80 border border-slate-800 rounded-2xl p-4 space-y-3 flex flex-col h-[740px]">
        <div class="flex flex-wrap justify-between items-center text-xs pb-2 border-b border-slate-800 gap-1.5">
          <span class="font-bold text-slate-200">数据库审查存证清单</span>
          <div class="flex flex-wrap gap-1">
            <button onclick="setFilter('all')" id="btnFilterAll" class="filter-btn px-2.5 py-1 rounded text-xs font-medium bg-slate-700 text-white">全部 <span id="cntAll" class="opacity-75 text-[10px]"></span></button>
            <button onclick="setFilter('violation')" id="btnFilterViol" class="filter-btn px-2.5 py-1 rounded text-xs font-medium text-slate-400 hover:text-white">违规 <span id="cntViol" class="opacity-75 text-[10px]"></span></button>
            <button onclick="setFilter('cloaking')" id="btnFilterCloak" class="filter-btn px-2.5 py-1 rounded text-xs font-medium text-slate-400 hover:text-white">伪装 <span id="cntCloak" class="opacity-75 text-[10px]"></span></button>
            <button onclick="setFilter('clean')" id="btnFilterClean" class="filter-btn px-2.5 py-1 rounded text-xs font-medium text-slate-400 hover:text-white">合规 <span id="cntClean" class="opacity-75 text-[10px]"></span></button>
            <button onclick="setFilter('pending')" id="btnFilterPending" class="filter-btn px-2.5 py-1 rounded text-xs font-medium text-slate-400 hover:text-white">待研判 <span id="cntPending" class="opacity-75 text-[10px]"></span></button>
          </div>
        </div>

        <div>
          <input type="text" id="searchInput" oninput="handleSearchInput(this.value)" placeholder="输入域名 / 采样页面 / 任务ID 搜索 (支持模糊即时检索)..." class="w-full bg-slate-950 border border-slate-800 px-3 py-1.5 rounded-lg text-xs text-slate-200 focus:outline-none focus:border-indigo-500">
        </div>

        <!-- Task Items Scroll List -->
        <div id="taskListContainer" class="flex-1 overflow-y-auto space-y-2 pr-1">
          <div class="text-center py-12 text-slate-500 text-xs">正在连接数据库读取真实数据...</div>
        </div>

        <!-- Pagination Controls -->
        <div class="pt-2 border-t border-slate-800 flex items-center justify-between text-xs text-slate-400 select-none">
          <div id="paginationInfo" class="text-[11px] text-slate-400 truncate">
            共 <span id="pageTotalCount" class="text-white font-mono font-medium">0</span> 条 · 第 <span id="pageCurrent" class="text-indigo-400 font-mono font-bold">1</span>/<span id="pageTotal" class="font-mono">1</span> 页
          </div>
          <div class="flex items-center gap-1 shrink-0">
            <button onclick="changePage(1)" id="btnFirstPage" class="px-2 py-1 rounded bg-slate-800 hover:bg-slate-700 text-slate-300 disabled:opacity-40 disabled:pointer-events-none text-[11px]" title="首页">⏮</button>
            <button onclick="changePage(currentPage - 1)" id="btnPrevPage" class="px-2 py-1 rounded bg-slate-800 hover:bg-slate-700 text-slate-300 disabled:opacity-40 disabled:pointer-events-none text-[11px]" title="上一页">◀ 上页</button>
            <button onclick="changePage(currentPage + 1)" id="btnNextPage" class="px-2 py-1 rounded bg-slate-800 hover:bg-slate-700 text-slate-300 disabled:opacity-40 disabled:pointer-events-none text-[11px]" title="下一页">下页 ▶</button>
            <button onclick="changePage(totalPages)" id="btnLastPage" class="px-2 py-1 rounded bg-slate-800 hover:bg-slate-700 text-slate-300 disabled:opacity-40 disabled:pointer-events-none text-[11px]" title="末页">⏭</button>
          </div>
        </div>
      </div>

      <!-- Right Detail Inspector (7 cols) -->
      <div class="lg:col-span-7 bg-slate-900/80 border border-slate-800 rounded-2xl p-5 flex flex-col h-[740px] overflow-hidden">
        <div id="detailPane" class="overflow-y-auto space-y-5 flex-1 pr-1">

          <!-- Detail Header -->
          <div class="pb-3 border-b border-slate-800 flex justify-between items-start gap-2">
            <div>
              <div class="flex items-center gap-2">
                <span id="detailBadge" class="badge">判定中</span>
                <span id="detailRiskBadge" class="badge">风险</span>
                <span id="detailCloakBadge" class="badge hidden">🚨 设备端伪装 (Cloaking)</span>
              </div>
              <div class="flex items-center gap-2 mt-2">
                <h2 id="detailUrl" class="text-sm font-bold text-white break-all">请从左侧列表选择域名任务查看明细</h2>
                <a id="detailExternalLink" href="#" target="_blank" rel="noopener noreferrer" class="hidden px-2 py-0.5 bg-indigo-600/30 hover:bg-indigo-600/50 text-indigo-300 border border-indigo-500/40 rounded text-xs font-medium inline-flex items-center gap-1 transition shrink-0" title="在浏览器新窗口打开此网站">访问 ↗</a>
              </div>
              <p id="detailTime" class="text-xs text-slate-400 mt-1">时间: -</p>
            </div>
            <div class="text-right shrink-0 space-y-1">
              <span class="text-xs text-slate-400 block">主违规分类</span>
              <span id="detailPrimary" class="text-sm font-bold text-indigo-400">normal</span>
              <div>
                <button onclick="inspectCurrentDomain()" id="btnInspectSingle" class="mt-1 px-3 py-1 bg-amber-500/20 hover:bg-amber-500/30 text-amber-300 border border-amber-500/40 rounded-lg text-xs font-semibold inline-flex items-center gap-1 transition shadow-sm">
                  <span>⚡</span> 立即研判此域名
                </button>
              </div>
            </div>
          </div>

          <!-- Cloaking / Verdict Notes Box -->
          <div id="detailNotesBox" class="p-3.5 rounded-xl bg-slate-800/60 border border-slate-700/60 text-xs text-slate-300 leading-relaxed">
            -
          </div>

          <!-- 6 Categories Probability Matrix -->
          <div>
            <div class="text-xs font-semibold text-slate-300 mb-2.5 flex items-center gap-1.5">
              <span>📊</span> 六大合规维度最高检出概率 (VLM 视觉模型推理)
            </div>
            <div id="detailProbGrid" class="grid grid-cols-2 sm:grid-cols-3 gap-2.5">
              <!-- Category Prob Cards -->
            </div>
          </div>

          <!-- Multi-Device Slices & Forensics Screenshots -->
          <div>
            <div class="text-xs font-semibold text-slate-300 mb-2.5 flex items-center gap-1.5">
              <span>📱</span> 多端仿真与存证切片截图 (100% 原始视口高清)
            </div>
            <div id="detailSlicesContainer" class="space-y-3">
              <!-- Slices & Screenshots -->
            </div>
          </div>

        </div>

        <div class="pt-3 border-t border-slate-800 mt-auto flex justify-between items-center text-xs text-slate-400">
          <span>电子存证哈希: <span class="font-mono text-indigo-400">SHA-256 不可篡改留痕</span></span>
          <span id="detailFooterMeta" class="font-mono text-slate-500">模型: qwen2-vl</span>
        </div>
      </div>

    </div>

    <!-- Live Terminal Console Drawer (Bottom Floating Dock) -->
    <div id="terminalConsole" class="fixed bottom-0 left-0 right-0 bg-slate-950/95 border-t border-slate-800 shadow-2xl z-40 transition-all duration-300 translate-y-[calc(100%-42px)]">
      <!-- Terminal Header / Drag Bar -->
      <div onclick="toggleLogConsole()" class="h-[42px] px-4 bg-slate-900/90 border-b border-slate-800 flex items-center justify-between cursor-pointer select-none">
        <div class="flex items-center gap-3">
          <span class="text-xs font-bold text-slate-200 flex items-center gap-1.5">
            <span>💻</span> 巡检执行控制台 (实时终端日志)
          </span>
          <!-- Live Mini Progress -->
          <div id="miniProgress" class="flex items-center gap-2 text-[11px] text-slate-400">
            <span id="miniProgressText">空闲待命中</span>
            <div class="w-32 bg-slate-800 h-2 rounded-full overflow-hidden hidden" id="miniProgressBarBox">
              <div id="miniProgressBar" class="bg-emerald-500 h-full rounded-full transition-all duration-300" style="width: 0%"></div>
            </div>
          </div>
        </div>
        <div class="flex items-center gap-2">
          <button onclick="event.stopPropagation(); clearTerminalLogs()" class="text-[11px] text-slate-400 hover:text-white px-2 py-0.5 rounded bg-slate-800 border border-slate-700">清屏</button>
          <span id="consoleToggleIcon" class="text-xs text-slate-400">▲ 展开</span>
        </div>
      </div>

      <!-- Terminal Output Screen -->
      <div id="terminalLogs" class="h-64 p-3 overflow-y-auto terminal-font text-xs text-emerald-400/90 space-y-1 bg-black/80 leading-relaxed select-text">
        <div class="text-slate-500">[系统就绪] 巡检控制台已加载。调度基于总域名库去重独立域名，支持预检、单批巡检或常驻守护轮询。</div>
      </div>
    </div>

    <!-- Scan Configuration Modal -->
    <div id="configModal" class="fixed inset-0 bg-black/70 backdrop-blur-sm z-50 flex items-center justify-center hidden p-4">
      <div class="bg-slate-900 border border-slate-800 rounded-2xl max-w-lg w-full p-6 shadow-2xl space-y-5">
        <div class="flex justify-between items-center pb-3 border-b border-slate-800">
          <div class="flex items-center gap-2">
            <span class="text-xl">⚙️</span>
            <div>
              <h3 id="modalTitle" class="font-bold text-white text-base">自动化多端巡检调度配置</h3>
              <p class="text-[11px] text-indigo-400 mt-0.5">直连总域名库 (去重独立域名调度，结果自动同步全库)</p>
            </div>
          </div>
          <button onclick="closeConfigModal()" class="text-slate-400 hover:text-white text-lg">✕</button>
        </div>

        <div class="space-y-4 text-xs">
          <!-- Mode Indicator -->
          <div class="p-2.5 rounded-xl bg-slate-950 border border-slate-800 flex items-center justify-between">
            <span class="text-slate-300 font-medium">执行模式:</span>
            <span id="modalModeTag" class="text-[11px] font-bold text-emerald-400 bg-emerald-500/10 px-2 py-0.5 rounded border border-emerald-500/20">单批次全量去重巡检</span>
          </div>

          <!-- Workers Concurrency -->
          <div>
            <label class="block text-slate-300 font-semibold mb-1.5">并发工作线程数 (--workers):</label>
            <div class="grid grid-cols-5 gap-2">
              <label class="flex items-center justify-center p-2 rounded-lg bg-slate-800 border border-slate-700 cursor-pointer hover:border-indigo-500 text-center">
                <input type="radio" name="cfgWorkers" value="1" class="sr-only">
                <span>1 单线程</span>
              </label>
              <label class="flex items-center justify-center p-2 rounded-lg bg-slate-800 border border-slate-700 cursor-pointer hover:border-indigo-500 text-center">
                <input type="radio" name="cfgWorkers" value="2" class="sr-only">
                <span>2 并发</span>
              </label>
              <label class="flex items-center justify-center p-2 rounded-lg bg-indigo-600/30 border border-indigo-500 cursor-pointer text-center font-bold text-indigo-300">
                <input type="radio" name="cfgWorkers" value="3" checked class="sr-only">
                <span>3 (推荐)</span>
              </label>
              <label class="flex items-center justify-center p-2 rounded-lg bg-slate-800 border border-slate-700 cursor-pointer hover:border-indigo-500 text-center">
                <input type="radio" name="cfgWorkers" value="5" class="sr-only">
                <span>5 并发</span>
              </label>
              <label class="flex items-center justify-center p-2 rounded-lg bg-slate-800 border border-slate-700 cursor-pointer hover:border-indigo-500 text-center">
                <input type="radio" name="cfgWorkers" value="8" class="sr-only">
                <span>8 高性能</span>
              </label>
            </div>
          </div>

          <!-- Batch Size -->
          <div>
            <label class="block text-slate-300 font-semibold mb-1.5">单批次提取去重域名数 (--db-batch-size):</label>
            <div class="grid grid-cols-4 gap-2">
              <label class="flex items-center justify-center p-2 rounded-lg bg-slate-800 border border-slate-700 cursor-pointer text-center">
                <input type="radio" name="cfgBatch" value="10" class="sr-only">
                <span>10 条</span>
              </label>
              <label class="flex items-center justify-center p-2 rounded-lg bg-slate-800 border border-slate-700 cursor-pointer text-center">
                <input type="radio" name="cfgBatch" value="20" class="sr-only">
                <span>20 条</span>
              </label>
              <label class="flex items-center justify-center p-2 rounded-lg bg-indigo-600/30 border border-indigo-500 cursor-pointer text-center font-bold text-indigo-300">
                <input type="radio" name="cfgBatch" value="30" checked class="sr-only">
                <span>30 条 (推荐)</span>
              </label>
              <label class="flex items-center justify-center p-2 rounded-lg bg-slate-800 border border-slate-700 cursor-pointer text-center">
                <input type="radio" name="cfgBatch" value="50" class="sr-only">
                <span>50 条</span>
              </label>
            </div>
          </div>

          <!-- Loop Mode & Interval -->
          <div class="p-3 rounded-xl bg-slate-800/60 border border-slate-700/60 space-y-2">
            <div class="flex items-center justify-between">
              <label class="flex items-center gap-2 cursor-pointer font-semibold text-slate-200">
                <input type="checkbox" id="cfgLoop" onchange="onLoopChange(this.checked)" class="rounded text-indigo-600 w-4 h-4">
                <span>开启后台常驻轮询守护 (--db-loop)</span>
              </label>
            </div>
            <div id="pollIntervalBox" class="flex items-center justify-between text-[11px] text-slate-400 pl-6 hidden">
              <span>轮询监听休眠间隔 (--db-poll-interval):</span>
              <div class="flex gap-1.5">
                <button type="button" onclick="setPollInterval(10)" class="interval-btn px-2 py-0.5 rounded bg-slate-800 border border-slate-700">10s</button>
                <button type="button" onclick="setPollInterval(15)" class="interval-btn px-2 py-0.5 rounded bg-indigo-600 text-white font-bold">15s (推荐)</button>
                <button type="button" onclick="setPollInterval(30)" class="interval-btn px-2 py-0.5 rounded bg-slate-800 border border-slate-700">30s</button>
                <button type="button" onclick="setPollInterval(60)" class="interval-btn px-2 py-0.5 rounded bg-slate-800 border border-slate-700">60s</button>
              </div>
            </div>
          </div>

          <!-- Devices Selection -->
          <div>
            <label class="block text-slate-300 font-semibold mb-1.5">多端仿真设备范围 (--devices):</label>
            <div class="grid grid-cols-2 gap-2 text-[11px]">
              <label class="flex items-center gap-2 p-2 rounded bg-slate-800/80 cursor-pointer">
                <input type="checkbox" id="devChrome" checked class="rounded text-indigo-600"> <span>💻 桌面 PC Chrome</span>
              </label>
              <label class="flex items-center gap-2 p-2 rounded bg-slate-800/80 cursor-pointer">
                <input type="checkbox" id="devMac" checked class="rounded text-indigo-600"> <span>🍏 视网膜 Mac Safari</span>
              </label>
              <label class="flex items-center gap-2 p-2 rounded bg-slate-800/80 cursor-pointer">
                <input type="checkbox" id="devIphone" checked class="rounded text-indigo-600"> <span>📱 苹果 iPhone (Cloaking识别)</span>
              </label>
              <label class="flex items-center gap-2 p-2 rounded bg-slate-800/80 cursor-pointer">
                <input type="checkbox" id="devAndroid" checked class="rounded text-indigo-600"> <span>🤖 安卓 Android Chrome</span>
              </label>
            </div>
          </div>

          <!-- Advanced Options -->
          <div class="pt-2 border-t border-slate-800 space-y-2">
            <label class="flex items-center gap-2 cursor-pointer text-emerald-400 font-semibold">
              <input type="checkbox" id="cfgProbe" checked class="rounded text-emerald-600">
              <span>⚡ 开启轻量级快速探活前置过滤 (极速跳过死链/不可达，提升3~5倍吞吐)</span>
            </label>
            <label class="flex items-center gap-2 cursor-pointer text-sky-400 font-semibold pl-6">
              <input type="checkbox" id="cfgDnsProbe" checked class="rounded text-sky-600">
              <span>🌐 探活前启用异步 DNS (nslookup) 预检 (10ms 拦截 NXDOMAIN 与内网 SSRF)</span>
            </label>
            <label class="flex items-center gap-2 cursor-pointer text-slate-400">
              <input type="checkbox" id="cfgMock" class="rounded text-indigo-600">
              <span>开启仿真演练模式 (--mock，跳过真实大模型推理，快速测试全流程)</span>
            </label>
          </div>
        </div>

        <div class="pt-4 border-t border-slate-800 flex justify-between items-center text-xs">
          <button onclick="submitStartScan(true)" class="px-3.5 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 font-semibold flex items-center gap-1.5">
            <span>🔍</span> 仅预检目标 (Dry Run)
          </button>
          <div class="flex gap-2">
            <button onclick="closeConfigModal()" class="px-4 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 font-semibold">取消</button>
            <button onclick="submitStartScan(false)" class="px-5 py-2 rounded-lg bg-gradient-to-r from-emerald-600 to-teal-600 hover:from-emerald-500 hover:to-teal-500 text-white font-bold shadow-lg flex items-center gap-1.5">
              <span>🚀</span> 立即启动巡检
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- History Drawer Modal (Slide-Over) -->
    <div id="historyDrawerModal" class="fixed inset-0 bg-black/75 backdrop-blur-sm z-50 flex justify-end hidden">
      <div class="bg-slate-900 border-l border-slate-800 w-full max-w-2xl h-full flex flex-col shadow-2xl">
        <!-- Drawer Header -->
        <div class="p-4 sm:p-5 border-b border-slate-800 flex justify-between items-center bg-slate-950/80">
          <div class="flex items-center gap-2.5">
            <span class="text-xl">📜</span>
            <div>
              <h3 class="font-bold text-white text-base">历史巡检批次与断点存档</h3>
              <p class="text-xs text-slate-400">本地持久化存储 (output/history) · 支持状态复盘与断点恢复</p>
            </div>
          </div>
          <button onclick="closeHistoryDrawer()" class="text-slate-400 hover:text-white text-xl p-1">✕</button>
        </div>

        <!-- Summary Metrics inside Drawer -->
        <div class="p-4 bg-slate-900/60 border-b border-slate-800 grid grid-cols-4 gap-2.5 text-center text-xs">
          <div class="bg-slate-950/80 p-2.5 rounded-lg border border-slate-800">
            <div class="text-slate-400 text-[10px]">历史巡检批次</div>
            <div id="histTotalJobs" class="text-lg font-bold text-white mt-0.5">0</div>
          </div>
          <div class="bg-slate-950/80 p-2.5 rounded-lg border border-slate-800">
            <div class="text-slate-400 text-[10px]">累计调度域名</div>
            <div id="histTotalTargets" class="text-lg font-bold text-indigo-400 mt-0.5">0</div>
          </div>
          <div class="bg-slate-950/80 p-2.5 rounded-lg border border-slate-800">
            <div class="text-rose-400/90 text-[10px]">累计检出违规</div>
            <div id="histTotalViolations" class="text-lg font-bold text-rose-500 mt-0.5">0</div>
          </div>
          <div class="bg-slate-950/80 p-2.5 rounded-lg border border-slate-800">
            <div class="text-amber-400/90 text-[10px]">累计跳过死链</div>
            <div id="histTotalDead" class="text-lg font-bold text-amber-500 mt-0.5">0</div>
          </div>
        </div>

        <!-- History Job List Container -->
        <div id="historyListContainer" class="flex-1 overflow-y-auto p-4 space-y-3">
          <div class="text-center text-slate-500 text-xs py-8">正在加载历史批次记录...</div>
        </div>
      </div>
    </div>

  </div>

  <script>
    let currentTasks = [];
    let currentFilter = 'all';
    let currentSearch = '';
    let currentPage = 1;
    let pageSize = 30;
    let totalPages = 1;
    let totalCount = 0;
    let selectedIdx = 0;
    let searchDebounceTimer = null;
    let statusPollInterval = null;
    let isConsoleExpanded = false;
    let isRunnerActive = false;
    let chosenPollInterval = 15;

    // ==========================================
    // 1. Data Fetching & Table Rendering
    // ==========================================
    async function fetchData(keepPage = false) {
      if (!keepPage) {
        currentPage = 1;
      }
      try {
        const container = document.getElementById('taskListContainer');
        container.innerHTML = '<div class="text-center py-12 text-slate-500 text-xs">正在从总域名库检索去重数据...</div>';

        const params = new URLSearchParams({
          filter: currentFilter,
          search: currentSearch,
          page: currentPage,
          page_size: pageSize
        });

        const resp = await fetch(`/api/tasks?${params.toString()}`);
        const json = await resp.json();

        // 1. 更新顶部指标卡与筛选按钮 Badge
        if (json.metrics) {
          const m = json.metrics;
          document.getElementById('statTotal').innerText = (m.total || 0).toLocaleString();
          document.getElementById('statAudited').innerText = `全量记录: ${(m.total_rows || 0).toLocaleString()} 条 · AI存证: ${(m.audited_count || 0).toLocaleString()} 条`;
          document.getElementById('statViolations').innerText = (m.violations || 0).toLocaleString();
          document.getElementById('statCloaking').innerText = (m.cloaking || 0).toLocaleString();
          document.getElementById('statClean').innerText = (m.clean || 0).toLocaleString();
          document.getElementById('statPending').innerText = `待研判域名: ${(m.pending || 0).toLocaleString()} 条`;

          const total = m.total || 1;
          const viols = m.violations || 0;
          const rate = ((viols / total) * 100).toFixed(2);
          document.getElementById('statViolRate').innerText = `违规占比: ${rate}%`;

          // 填充筛选按钮数字
          document.getElementById('cntAll').innerText = `(${m.total || 0})`;
          document.getElementById('cntViol').innerText = `(${m.violations || 0})`;
          document.getElementById('cntCloak').innerText = `(${m.cloaking || 0})`;
          document.getElementById('cntClean').innerText = `(${m.clean || 0})`;
          document.getElementById('cntPending').innerText = `(${m.pending || 0})`;
        }

        // 2. 更新分页信息
        if (json.pagination) {
          totalCount = json.pagination.total_count || 0;
          totalPages = json.pagination.total_pages || 1;
          currentPage = json.pagination.page || 1;

          document.getElementById('pageTotalCount').innerText = totalCount.toLocaleString();
          document.getElementById('pageCurrent').innerText = currentPage;
          document.getElementById('pageTotal').innerText = totalPages;

          document.getElementById('btnFirstPage').disabled = currentPage <= 1;
          document.getElementById('btnPrevPage').disabled = currentPage <= 1;
          document.getElementById('btnNextPage').disabled = currentPage >= totalPages;
          document.getElementById('btnLastPage').disabled = currentPage >= totalPages;
        }

        // 3. 渲染列表
        currentTasks = json.tasks || [];
        renderTaskList();

        if (currentTasks.length > 0) {
          selectTask(0);
        } else {
          document.getElementById('detailUrl').innerText = "当前筛选条件下暂无审计记录";
          document.getElementById('detailExternalLink').classList.add('hidden');
          document.getElementById('detailTime').innerText = "可通过运行巡检命令导入新域名审核";
          document.getElementById('detailNotesBox').innerHTML = "暂无详细记录";
          document.getElementById('detailProbGrid').innerHTML = "";
          document.getElementById('detailSlicesContainer').innerHTML = "";
        }
      } catch (e) {
        console.error("未能从数据库加载数据", e);
        document.getElementById('taskListContainer').innerHTML = `
          <div class="text-center py-12 text-rose-400 text-xs">
            连接数据库失败: ${e.message}<br>请确认后端数据库运行正常。
          </div>
        `;
      }
    }

    function refreshData() {
      fetchData(true);
    }

    function setFilter(filter) {
      currentFilter = filter;
      document.querySelectorAll('.filter-btn').forEach(b => {
        b.className = 'filter-btn px-2.5 py-1 rounded text-xs font-medium text-slate-400 hover:text-white';
      });
      const activeBtn = {
        'all': 'btnFilterAll',
        'violation': 'btnFilterViol',
        'cloaking': 'btnFilterCloak',
        'clean': 'btnFilterClean',
        'pending': 'btnFilterPending'
      }[filter];
      if (activeBtn) {
        document.getElementById(activeBtn).className = 'filter-btn px-2.5 py-1 rounded text-xs font-medium bg-slate-700 text-white';
      }
      fetchData(false);
    }

    function handleSearchInput(val) {
      clearTimeout(searchDebounceTimer);
      searchDebounceTimer = setTimeout(() => {
        currentSearch = val.trim();
        fetchData(false);
      }, 350);
    }

    function changePage(newPage) {
      if (newPage < 1 || newPage > totalPages || newPage === currentPage) return;
      currentPage = newPage;
      fetchData(true);
    }

    function renderTaskList() {
      const container = document.getElementById('taskListContainer');

      if (!currentTasks.length) {
        container.innerHTML = `<div class="text-center py-12 text-slate-500 text-xs">暂无匹配的域名审查存证记录</div>`;
        return;
      }

      container.innerHTML = currentTasks.map((item, idx) => {
        const isSelected = idx === selectedIdx;
        const sum = item.verdict_summary || {};
        const isViol = sum.is_violation;
        const isCloak = sum.cloaking_suspected;
        const domain = item.domain || (item.url || '').replace(/https?:\\/\\//, '').split('/')[0];
        const riskLevel = (sum.overall_risk_level || 'PENDING').toUpperCase();

        let violBadge = '';
        if (isViol) {
          violBadge = '<span class="text-[10px] font-bold text-rose-400 bg-rose-500/20 border border-rose-500/30 px-1.5 py-0.5 rounded">违规</span>';
        } else if (riskLevel === 'SAFE') {
          violBadge = '<span class="text-[10px] font-bold text-emerald-400 bg-emerald-500/20 border border-emerald-500/30 px-1.5 py-0.5 rounded">合规</span>';
        } else {
          violBadge = '<span class="text-[10px] font-bold text-amber-400 bg-amber-500/20 border border-amber-500/30 px-1.5 py-0.5 rounded">待判</span>';
        }

        const cloakBadge = isCloak 
          ? '<span class="text-[10px] font-bold text-amber-400 bg-amber-500/20 border border-amber-500/30 px-1.5 py-0.5 rounded">伪装</span>' : '';

        const refInfo = item.ref_count ? `<span class="text-[10px] text-slate-500 font-mono" title="全库关联记录数">关联:${item.ref_count}条</span>` : '';

        const timeStr = item.checked_at ? item.checked_at.substring(0, 19).replace('T', ' ') : '尚未审查';

        return `
          <div onclick="selectTask(${idx})" class="cursor-pointer p-3 rounded-xl border transition ${isSelected ? 'bg-indigo-600/15 border-indigo-500/50 shadow-md' : 'bg-slate-900/60 border-slate-800 hover:border-slate-700'}">
            <div class="flex justify-between items-center text-xs">
              <span class="font-bold text-white truncate max-w-[210px]" title="${item.url || item.domain}">${domain}</span>
              <div class="flex items-center gap-1.5">
                ${refInfo}
                ${cloakBadge}
                ${violBadge}
              </div>
            </div>
            <div class="flex justify-between items-center text-[11px] text-slate-400 mt-2">
              <span class="font-mono text-indigo-400 truncate max-w-[140px]">${sum.primary_violation_cn || sum.primary_violation_category || 'normal'}</span>
              <span class="text-slate-500 text-[10px]">${timeStr}</span>
            </div>
          </div>
        `;
      }).join('');
    }

    function selectTask(idx) {
      selectedIdx = idx;
      renderTaskList();
      const r = currentTasks[idx];
      if (!r) return;

      const targetUrl = r.url || (r.domain ? `https://${r.domain}` : '#');
      document.getElementById('detailUrl').innerText = targetUrl;

      // 外部链接按钮
      const extLink = document.getElementById('detailExternalLink');
      if (targetUrl && targetUrl !== '#') {
        extLink.href = targetUrl;
        extLink.classList.remove('hidden');
      } else {
        extLink.classList.add('hidden');
      }

      document.getElementById('detailTime').innerText = `审查时间: ${r.checked_at || '尚未审查'} | 关联记录数: ${r.ref_count || 1} 条 | 来源: ${r.source || 'website_domain_db'}`;
      document.getElementById('detailFooterMeta').innerText = `模型: ${r.model_used || 'qwen2-vl'} · 数据库: PostgreSQL (website_domain_db)`;

      const sum = r.verdict_summary || {};
      const isViol = sum.is_violation;
      const risk = (sum.overall_risk_level || 'PENDING').toUpperCase();

      // 状态徽章
      const vBadge = document.getElementById('detailBadge');
      if (isViol) {
        vBadge.className = "badge bg-rose-500/20 text-rose-400 border border-rose-500/30";
        vBadge.innerText = "检出违规风险 (Violation)";
      } else if (risk === 'SAFE') {
        vBadge.className = "badge bg-emerald-500/20 text-emerald-400 border border-emerald-500/30";
        vBadge.innerText = "合规安全 (Verified Clean)";
      } else {
        vBadge.className = "badge bg-amber-500/20 text-amber-400 border border-amber-500/30";
        vBadge.innerText = "待研判 / 未审查 (Pending)";
      }

      const riskColorMap = {
        'CRITICAL': 'bg-red-950 text-red-400 border-red-800',
        'HIGH': 'bg-rose-950 text-rose-400 border-rose-800',
        'MEDIUM': 'bg-amber-950 text-amber-400 border-amber-800',
        'LOW': 'bg-blue-950 text-blue-400 border-blue-800',
        'SAFE': 'bg-slate-800 text-slate-400 border-slate-700',
        'PENDING': 'bg-amber-950/40 text-amber-300 border-amber-800/50'
      };
      const rBadge = document.getElementById('detailRiskBadge');
      rBadge.className = `badge ${riskColorMap[risk] || riskColorMap['PENDING']} border`;
      rBadge.innerText = `${risk} 等级`;

      const cBadge = document.getElementById('detailCloakBadge');
      if (sum.cloaking_suspected) {
        cBadge.classList.remove('hidden');
        cBadge.className = "badge bg-amber-500/20 text-amber-400 border border-amber-500/30";
      } else {
        cBadge.classList.add('hidden');
      }

      document.getElementById('detailPrimary').innerText = sum.primary_violation_cn || sum.primary_violation_category || '待研判';

      // DNS 预检情报
      const dnsIps = sum.dns_resolved_ips || r.dns_resolved_ips || [];
      const dnsStatus = sum.dns_status || r.dns_status;
      const cnames = sum.dns_cnames || r.dns_cnames || [];
      let dnsHtml = '';
      if (dnsIps.length > 0 || dnsStatus) {
        const isSsrf = sum.primary_violation_category === 'ssrf_risk' || dnsStatus === 'PRIVATE_IP';
        const tagBg = isSsrf ? 'bg-rose-950/80 text-rose-300 border-rose-800' : 'bg-slate-800 text-sky-300 border-slate-700';
        dnsHtml = `
          <div class="mt-2.5 pt-2 border-t border-slate-700/60 text-xs flex flex-wrap items-center gap-2">
            <span class="text-indigo-400 font-semibold flex items-center gap-1">
              <span>🌐</span> DNS 预检:
            </span>
            ${dnsStatus ? `<span class="px-1.5 py-0.5 rounded font-mono text-[11px] border ${tagBg}">${dnsStatus}</span>` : ''}
            ${dnsIps.length > 0 ? `<span class="text-slate-300 font-mono">解析IP: <strong class="text-sky-300">${dnsIps.join(', ')}</strong></span>` : ''}
            ${cnames.length > 0 ? `<span class="text-slate-400 font-mono">CNAME: ${cnames.join(', ')}</span>` : ''}
          </div>
        `;
      }

      // 研判依据说明
      const notesBox = document.getElementById('detailNotesBox');
      if (risk === 'PENDING') {
        notesBox.innerHTML = `
          <div class="flex items-start gap-2">
            <span class="text-amber-400 text-base">⚠️</span>
            <div>
              <strong class="text-amber-300">【待研判总库域名】</strong> 该外部域名尚未进行多端仿真与视觉大模型安全深度巡检。<br>
              <div class="mt-1 text-slate-400">
                ${r.sample_page_url ? `<strong>采样引用页:</strong> <a href="${r.sample_page_url}" target="_blank" class="text-indigo-400 hover:underline break-all">${r.sample_page_url}</a><br>` : ''}
                <strong>一键研判:</strong> 点击右上角【⚡ 立即研判此域名】或顶部【启动单批巡检】即可开始审查，检测结果将自动同步该域名在全库中的所有历史记录。
              </div>
            </div>
          </div>
          ${dnsHtml}
        `;
      } else {
        notesBox.innerHTML = `<div><strong>研判依据与特征：</strong> ${sum.cloaking_notes || r.risk_remark || "页面各端展示一致，未识别到违规及伪装特征。"}</div>${dnsHtml}`;
      }

      // 6 大分类概率矩阵
      const catMap = sum.category_probabilities || {
        "pornography_vulgarity": {"name": "色情低俗", "max_probability": 0.0},
        "gambling_lottery": {"name": "赌博博彩", "max_probability": 0.0},
        "fraud_scam": {"name": "电信诈骗", "max_probability": 0.0},
        "violence_contraband": {"name": "暴恐违禁", "max_probability": 0.0},
        "political_extremism": {"name": "涉政不良", "max_probability": 0.0},
        "malicious_adware": {"name": "恶意广告", "max_probability": 0.0}
      };
      const grid = document.getElementById('detailProbGrid');
      grid.innerHTML = Object.keys(catMap).map(k => {
        const item = catMap[k];
        const prob = item.max_probability || 0;
        const pct = Math.round(prob * 100);
        const isHigh = prob > 0.5;
        const barColor = isHigh ? 'bg-rose-500' : (prob > 0.2 ? 'bg-amber-500' : 'bg-indigo-500');
        return `
          <div class="bg-slate-900 border border-slate-800 p-2.5 rounded-lg">
            <div class="flex justify-between items-center text-xs">
              <span class="text-slate-300 font-medium">${item.name || k}</span>
              <span class="font-mono font-bold ${isHigh ? 'text-rose-400' : 'text-slate-400'}">${(prob * 100).toFixed(1)}%</span>
            </div>
            <div class="w-full bg-slate-800 h-1.5 rounded-full mt-2 overflow-hidden">
              <div class="${barColor} h-full rounded-full transition-all duration-300" style="width: ${pct}%"></div>
            </div>
          </div>
        `;
      }).join('');

      // 设备切片与截图
      const slicesContainer = document.getElementById('detailSlicesContainer');
      const devs = r.device_inspections || [];

      if (!devs.length) {
        slicesContainer.innerHTML = `
          <div class="bg-slate-900/60 border border-slate-800/80 rounded-xl p-4 text-xs text-slate-400">
            <div class="flex items-center gap-2 text-slate-300 font-semibold mb-1">
              <span>📋</span> 系统审计证据信息
            </div>
            <div>${r.risk_remark || sum.cloaking_notes || "无多端截图切片，当前记录为系统威胁情报与规则研判结果。"}</div>
            ${r.sample_page_url ? `<div class="mt-2 text-slate-500 truncate" title="${r.sample_page_url}">采样引用页: ${r.sample_page_url}</div>` : ''}
          </div>
        `;
        return;
      }

      slicesContainer.innerHTML = devs.map(d => {
        const slices = d.slices_audited || [];
        const isDevViol = d.is_violation;

        const sliceCards = slices.map(s => {
          let filename = s.screenshot_path ? s.screenshot_path.split(/[\\\\/]/).pop() : '';
          let imgTag = '';
          if (filename) {
            const imgUrl = `/screenshots/${encodeURIComponent(filename)}`;
            imgTag = `
              <div class="mt-2 rounded overflow-hidden border border-slate-800 bg-black/40">
                <a href="${imgUrl}" target="_blank" title="点击查看大图">
                  <img src="${imgUrl}" class="w-full h-32 object-cover object-top hover:opacity-90 transition" onerror="this.parentElement.innerHTML='<div class=\\'text-[11px] text-slate-600 p-2\\'>截图文件未在本地暂存</div>'">
                </a>
              </div>
            `;
          }

          const isSliceViol = s.verdict?.is_violation;
          return `
            <div class="bg-slate-950/70 border border-slate-800 rounded-lg p-3 space-y-1">
              <div class="flex justify-between items-center text-xs">
                <span class="font-bold text-slate-200">${s.slice_name || s.slice_id}</span>
                <span class="badge ${isSliceViol ? 'bg-rose-500/20 text-rose-400 border border-rose-500/30' : 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30'}">
                  ${isSliceViol ? '切片检出违规' : '切片安全'}
                </span>
              </div>
              <div class="text-[11px] text-slate-400">${s.verdict?.violation_details || '无异常描述'}</div>
              <div class="text-[10px] font-mono text-slate-500 truncate" title="${s.screenshot_sha256}">SHA256: ${s.screenshot_sha256 ? s.screenshot_sha256.substring(0, 24) + '...' : '-'}</div>
              ${imgTag}
            </div>
          `;
        }).join('');

        return `
          <div class="bg-slate-900 border border-slate-800 rounded-xl p-3.5 space-y-2">
            <div class="flex justify-between items-center">
              <div>
                <span class="font-bold text-white text-xs">${d.device_name || d.device_id}</span>
                <span class="text-[11px] text-slate-400 ml-2">视口: ${d.viewport?.width}x${d.viewport?.height}</span>
              </div>
              <span class="badge ${isDevViol ? 'bg-rose-500/20 text-rose-400 border border-rose-500/30' : 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30'}">
                ${isDevViol ? '设备端违规' : '设备端安全'}
              </span>
            </div>
            <div class="grid grid-cols-1 sm:grid-cols-2 gap-2.5">
              ${sliceCards || '<div class="text-xs text-slate-500">无切片详情</div>'}
            </div>
          </div>
        `;
      }).join('');
    }

    // ==========================================
    // 2. Scan Runner Control & Live Logs
    // ==========================================
    function openConfigModal(isDaemon = false) {
      document.getElementById('configModal').classList.remove('hidden');
      const loopCheck = document.getElementById('cfgLoop');
      loopCheck.checked = isDaemon;
      onLoopChange(isDaemon);
      document.getElementById('modalModeTag').innerText = isDaemon ? "后台常驻守护监听模式" : "单批次总库去重巡检";
    }

    function closeConfigModal() {
      document.getElementById('configModal').classList.add('hidden');
    }

    function onLoopChange(checked) {
      const box = document.getElementById('pollIntervalBox');
      if (checked) {
        box.classList.remove('hidden');
      } else {
        box.classList.add('hidden');
      }
    }

    function setPollInterval(sec) {
      chosenPollInterval = sec;
      document.querySelectorAll('.interval-btn').forEach(b => {
        b.className = 'interval-btn px-2 py-0.5 rounded bg-slate-800 border border-slate-700';
      });
      event.target.className = 'interval-btn px-2 py-0.5 rounded bg-indigo-600 text-white font-bold';
    }

    function toggleLogConsole() {
      const consoleEl = document.getElementById('terminalConsole');
      const icon = document.getElementById('consoleToggleIcon');
      if (isConsoleExpanded) {
        consoleEl.className = 'fixed bottom-0 left-0 right-0 bg-slate-950/95 border-t border-slate-800 shadow-2xl z-40 transition-all duration-300 translate-y-[calc(100%-42px)]';
        icon.innerText = '▲ 展开';
        isConsoleExpanded = false;
      } else {
        consoleEl.className = 'fixed bottom-0 left-0 right-0 bg-slate-950/95 border-t border-slate-800 shadow-2xl z-40 transition-all duration-300 translate-y-0';
        icon.innerText = '▼ 收起';
        isConsoleExpanded = true;
      }
    }

    function clearTerminalLogs() {
      document.getElementById('terminalLogs').innerHTML = '<div class="text-slate-500">[控制台日志已清空]</div>';
    }

    // 快捷执行预检模式 (Dry Run)
    async function runDryRun() {
      if (!isConsoleExpanded) toggleLogConsole();
      try {
        const resp = await fetch('/api/job/start', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            workers: 1,
            batch_size: 15,
            dry_run: true
          })
        });
        const res = await resp.json();
        if (res.success) {
          startStatusPolling();
        } else {
          alert('预检启动失败: ' + res.message);
        }
      } catch (err) {
        alert('预检请求异常: ' + err.message);
      }
    }

    // 导出菜单切换
    function toggleExportMenu() {
      const menu = document.getElementById('exportMenu');
      if (menu) menu.classList.toggle('hidden');
    }

    document.addEventListener('click', (e) => {
      const btn = document.getElementById('btnExport');
      const menu = document.getElementById('exportMenu');
      if (menu && !menu.classList.contains('hidden') && btn && !btn.contains(e.target) && !menu.contains(e.target)) {
        menu.classList.add('hidden');
      }
    });

    function exportReport(type) {
      const menu = document.getElementById('exportMenu');
      if (menu) menu.classList.add('hidden');
      if (type === 'csv_current') {
        window.location.href = `/api/export/csv?filter=${encodeURIComponent(currentFilter)}&search=${encodeURIComponent(currentSearch)}`;
      } else if (type === 'csv_violations') {
        window.location.href = `/api/export/csv?filter=violation`;
      } else if (type === 'zip_violations') {
        window.location.href = `/api/export/zip?filter=violation`;
      }
    }

    // 历史抽屉管理
    function openHistoryDrawer() {
      document.getElementById('historyDrawerModal').classList.remove('hidden');
      loadHistoryJobs();
    }

    function closeHistoryDrawer() {
      document.getElementById('historyDrawerModal').classList.add('hidden');
    }

    async function loadHistoryJobs() {
      const container = document.getElementById('historyListContainer');
      container.innerHTML = '<div class="text-center text-slate-500 text-xs py-8">正在读取历史批次记录...</div>';
      try {
        const resp = await fetch('/api/jobs/history');
        const data = await resp.json();
        const sum = data.summary || {};
        document.getElementById('histTotalJobs').innerText = sum.total_jobs || 0;
        document.getElementById('histTotalTargets').innerText = sum.total_targets_processed || 0;
        document.getElementById('histTotalViolations').innerText = sum.total_violations_found || 0;
        document.getElementById('histTotalDead').innerText = sum.total_dead_skipped || 0;

        const jobs = data.jobs || [];
        if (!jobs.length) {
          container.innerHTML = '<div class="text-center text-slate-500 text-xs py-8">暂无历史巡检批次记录</div>';
          return;
        }

        container.innerHTML = jobs.map(j => {
          const isComp = j.status === 'completed';
          const isRun = j.status === 'running';
          const statusBadge = isComp 
            ? '<span class="badge bg-emerald-500/20 text-emerald-400 border border-emerald-500/30">已完成</span>'
            : (isRun ? '<span class="badge bg-indigo-500/20 text-indigo-400 border border-indigo-500/30 animate-pulse">运行中</span>' 
                     : '<span class="badge bg-slate-800 text-slate-400 border border-slate-700">已中止</span>');

          return `
            <div class="bg-slate-950/80 border border-slate-800 rounded-xl p-3.5 space-y-2 hover:border-slate-700 transition">
              <div class="flex justify-between items-center">
                <div class="flex items-center gap-2">
                  <span class="font-mono font-bold text-white text-xs">${j.job_id}</span>
                  ${statusBadge}
                </div>
                <span class="text-[11px] text-slate-400">${j.start_time ? j.start_time.substring(0, 19).replace('T', ' ') : ''}</span>
              </div>
              <div class="grid grid-cols-4 gap-2 text-[11px] bg-slate-900/60 p-2 rounded-lg border border-slate-800/80">
                <div><span class="text-slate-400">总目标:</span> <strong class="text-slate-200">${j.total_targets || 0}</strong></div>
                <div><span class="text-slate-400">已处理:</span> <strong class="text-slate-200">${j.completed || 0}</strong></div>
                <div><span class="text-rose-400">违规:</span> <strong class="text-rose-400">${j.violations || 0}</strong></div>
                <div><span class="text-amber-400">跳过死链:</span> <strong class="text-amber-400">${j.dead_skipped || 0}</strong></div>
              </div>
              <div class="flex justify-between items-center text-[11px] pt-1">
                <span class="text-slate-400 font-mono">配置: ${j.workers || 3}并发 · ${j.batch_size || 30}批次 ${j.enable_probe ? '· 探活开启' : ''}</span>
                <div class="flex gap-2">
                  <button onclick="resumeFromJob('${j.job_id}')" class="px-2.5 py-1 rounded bg-indigo-600/30 hover:bg-indigo-600/50 text-indigo-300 border border-indigo-500/30 font-semibold transition">
                    从断点继续
                  </button>
                </div>
              </div>
            </div>
          `;
        }).join('');
      } catch (e) {
        container.innerHTML = `<div class="text-center text-rose-400 text-xs py-8">加载历史记录失败: ${e.message}</div>`;
      }
    }

    async function resumeFromJob(jobId) {
      if (!confirm(`确定要从历史批次 [${jobId}] 的断点继续巡检吗？系统将自动跳过该批次已处理完成的域名。`)) return;
      closeHistoryDrawer();
      if (!isConsoleExpanded) toggleLogConsole();

      try {
        const resp = await fetch('/api/job/start', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            workers: 3,
            batch_size: 30,
            resume_job_id: jobId,
            enable_probe: true
          })
        });
        const res = await resp.json();
        if (res.success) {
          startStatusPolling();
        } else {
          alert('恢复批次失败: ' + res.message);
        }
      } catch (err) {
        alert('恢复批次异常: ' + err.message);
      }
    }

    async function submitStartScan(dryRun = false) {
      const workers = document.querySelector('input[name="cfgWorkers"]:checked')?.value || 3;
      const batchSize = document.querySelector('input[name="cfgBatch"]:checked')?.value || 30;
      const loop = document.getElementById('cfgLoop').checked;
      const mock = document.getElementById('cfgMock').checked;
      const enableProbe = document.getElementById('cfgProbe') ? document.getElementById('cfgProbe').checked : true;
      const enableDnsProbe = document.getElementById('cfgDnsProbe') ? document.getElementById('cfgDnsProbe').checked : true;

      // 设备端拼装
      const devs = [];
      if (document.getElementById('devChrome').checked) devs.push('desktop_chrome');
      if (document.getElementById('devMac').checked) devs.push('desktop_safari');
      if (document.getElementById('devIphone').checked) devs.push('mobile_iphone_safari');
      if (document.getElementById('devAndroid').checked) devs.push('mobile_android_chrome');
      const devices = devs.length > 0 ? devs.join(',') : 'all';

      closeConfigModal();

      try {
        const resp = await fetch('/api/job/start', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            workers: parseInt(workers),
            batch_size: parseInt(batchSize),
            devices: devices,
            loop: loop,
            poll_interval: chosenPollInterval,
            mock: mock,
            dry_run: dryRun,
            enable_probe: enableProbe,
            enable_dns_probe: enableDnsProbe
          })
        });
        const res = await resp.json();
        if (res.success) {
          if (!isConsoleExpanded) toggleLogConsole();
          startStatusPolling();
        } else {
          alert('启动失败: ' + res.message);
        }
      } catch (err) {
        alert('请求启动失败: ' + err.message);
      }
    }

    async function stopScan() {
      if (!confirm('确定要停止当前运行的巡检/守护监听任务吗？')) return;
      try {
        const resp = await fetch('/api/job/stop', { method: 'POST' });
        const res = await resp.json();
        if (!res.success) {
          alert('停止失败: ' + res.message);
        }
      } catch (err) {
        alert('请求停止失败: ' + err.message);
      }
    }

    async function inspectCurrentDomain() {
      const r = currentTasks[selectedIdx];
      if (!r || !r.domain) {
        alert('请先选择一个有效的域名');
        return;
      }
      const btn = document.getElementById('btnInspectSingle');
      const origText = btn.innerHTML;
      btn.disabled = true;
      btn.innerHTML = '<span>⏳</span> 正在仿真巡检中...';

      if (!isConsoleExpanded) toggleLogConsole();

      try {
        const resp = await fetch('/api/job/start', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            workers: 1,
            batch_size: 1,
            domain_filter: r.domain,
            devices: 'all'
          })
        });
        const res = await resp.json();
        if (res.success) {
          startStatusPolling();
        } else {
          alert('启动单域名巡检失败: ' + res.message);
        }
      } catch (e) {
        alert('请求单域名巡检异常: ' + e.message);
      } finally {
        setTimeout(() => {
          btn.disabled = false;
          btn.innerHTML = origText;
        }, 1500);
      }
    }

    function startStatusPolling() {
      if (statusPollInterval) clearInterval(statusPollInterval);
      pollJobStatus();
      statusPollInterval = setInterval(pollJobStatus, 1000);
    }

    async function pollJobStatus() {
      try {
        const resp = await fetch('/api/job/status');
        const data = await resp.json();

        const isRunning = data.is_running;
        const stats = data.stats || {};
        const logs = data.logs || [];
        const isLoop = stats.is_loop;
        const isDry = stats.is_dry_run;

        // 1. 顶部控制栏状态更新
        const badge = document.getElementById('runnerStatusBadge');
        const dot = document.getElementById('runnerStatusDot');
        const text = document.getElementById('runnerStatusText');
        const btnStart = document.getElementById('btnStartScan');
        const btnDaemon = document.getElementById('btnStartDaemon');
        const btnStop = document.getElementById('btnStopScan');

        if (isRunning) {
          if (isLoop) {
            badge.className = 'flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-semibold bg-indigo-950/70 text-indigo-400 border border-indigo-500/50';
            dot.className = 'w-2 h-2 rounded-full bg-indigo-400 animate-pulse';
            text.innerText = `🔄 常驻守护监听中 · [${data.config?.workers || 3}并发] 轮询:${data.config?.poll_interval || 15}s`;
          } else if (isDry) {
            badge.className = 'flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-semibold bg-amber-950/60 text-amber-300 border border-amber-500/40';
            dot.className = 'w-2 h-2 rounded-full bg-amber-400 animate-pulse';
            text.innerText = `🔍 正在预检去重目标...`;
          } else {
            badge.className = 'flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-semibold bg-emerald-950/60 text-emerald-400 border border-emerald-500/40';
            dot.className = 'w-2 h-2 rounded-full bg-emerald-400 animate-pulse';
            text.innerText = `🟢 巡检执行中 · [${data.config?.workers || 3}并发] ${stats.completed}/${stats.total || 30}`;
          }

          btnStart.classList.add('hidden');
          btnDaemon.classList.add('hidden');
          btnStop.classList.remove('hidden');

          // Mini progress bar
          document.getElementById('miniProgressBarBox').classList.remove('hidden');
          const total = stats.total || 30;
          const completed = stats.completed || 0;
          const pct = Math.min(100, Math.round((completed / total) * 100));
          const deadSkippedText = stats.dead_skipped ? ` (已跳过死链: ${stats.dead_skipped})` : '';
          document.getElementById('miniProgressBar').style.width = pct + '%';
          document.getElementById('miniProgressText').innerText = `已处理 ${completed}/${total} (${pct}%)${deadSkippedText} · ${stats.current_target ? stats.current_target.substring(0, 30) : ''}`;
        } else {
          badge.className = 'flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-semibold bg-slate-800 text-slate-300 border border-slate-700';
          dot.className = 'w-2 h-2 rounded-full bg-slate-400';
          text.innerText = '⚪ 巡检引擎待命';
          btnStart.classList.remove('hidden');
          btnDaemon.classList.remove('hidden');
          btnStop.classList.add('hidden');

          document.getElementById('miniProgressBarBox').classList.add('hidden');
          document.getElementById('miniProgressText').innerText = stats.message || '空闲待命中';

          if (isRunnerActive && !isRunning) {
            // 从运行切到结束，自动静默刷新大屏数据
            refreshData();
          }
        }

        isRunnerActive = isRunning;

        // 2. 渲染终端日志窗口
        if (logs.length > 0) {
          const logContainer = document.getElementById('terminalLogs');
          const html = logs.map(l => {
            let color = 'text-emerald-400/90';
            if (l.includes('[违规!]') || l.includes('CRITICAL') || l.includes('HIGH') || l.includes('失败') || l.includes('异常')) {
              color = 'text-rose-400 font-semibold';
            } else if (l.includes('[正常]') || l.includes('SAFE') || l.includes('合规')) {
              color = 'text-emerald-400';
            } else if (l.includes('Cloaking') || l.includes('伪装') || l.includes('警告')) {
              color = 'text-amber-400 font-bold';
            } else if (l.includes('【预检模式') || l.includes('休眠') || l.includes('监听')) {
              color = 'text-amber-300';
            } else if (l.startsWith('[*]') || l.includes('启动') || l.includes('完成')) {
              color = 'text-indigo-300';
            }
            return `<div class="${color}">${escapeHtml(l)}</div>`;
          }).join('');

          logContainer.innerHTML = html;
          logContainer.scrollTop = logContainer.scrollHeight;
        }

        if (!isRunning && statusPollInterval) {
          clearInterval(statusPollInterval);
          statusPollInterval = setInterval(pollJobStatus, 3000); // 降频心跳
        }

      } catch (e) {
        console.error("轮询巡检状态异常", e);
      }
    }

    function escapeHtml(str) {
      return str.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
    }

    window.onload = () => {
      fetchData(false);
      startStatusPolling();
    };
  </script>
</body>
</html>
"""


GLOBAL_DB_MGR: Optional[UnifiedDatabaseManager] = None

def get_db_mgr() -> UnifiedDatabaseManager:
    global GLOBAL_DB_MGR
    if GLOBAL_DB_MGR is None:
        GLOBAL_DB_MGR = UnifiedDatabaseManager(overrides={"clickhouse": {"enabled": False}})
    return GLOBAL_DB_MGR


class ComplianceDashboardHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def __init__(self, *args, output_dir: str = "output", **kwargs):
        self.output_dir = output_dir
        super().__init__(*args, **kwargs)

    def _send_response_bytes(self, data: bytes, content_type: str = "application/json", status: int = 200, filename: Optional[str] = None):
        self.close_connection = True
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        if filename:
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(data)
        self.wfile.flush()

    def do_OPTIONS(self):
        self._send_response_bytes(b"", "text/plain", 200)

    def do_POST(self):
        try:
            parsed = urllib.parse.urlparse(self.path)
            path = parsed.path

            content_len = int(self.headers.get("Content-Length") or 0)
            post_body = self.rfile.read(content_len).decode("utf-8", errors="replace") if content_len > 0 else "{}"
            try:
                payload = json.loads(post_body)
            except Exception:
                payload = {}

            if path == "/api/job/start":
                success, msg = GLOBAL_RUNNER.start_job(payload)
                resp_bytes = json.dumps({"success": success, "message": msg}, ensure_ascii=False).encode("utf-8")
                self._send_response_bytes(resp_bytes, "application/json", 200)
                return

            if path == "/api/job/stop":
                success, msg = GLOBAL_RUNNER.stop_job()
                resp_bytes = json.dumps({"success": success, "message": msg}, ensure_ascii=False).encode("utf-8")
                self._send_response_bytes(resp_bytes, "application/json", 200)
                return

            self._send_response_bytes(b"Not Found", "text/plain", 404)
        except Exception as e:
            err_bytes = json.dumps({"success": False, "message": f"Server Error: {e}"}).encode("utf-8")
            self._send_response_bytes(err_bytes, "application/json", 500)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query_params = urllib.parse.parse_qs(parsed.query)

        if path in ("/", "/index.html"):
            html_bytes = DASHBOARD_HTML.encode("utf-8")
            self._send_response_bytes(html_bytes, "text/html; charset=utf-8", 200)
            return

        if path == "/api/job/status":
            status_data = GLOBAL_RUNNER.get_status()
            resp_bytes = json.dumps(status_data, ensure_ascii=False).encode("utf-8")
            self._send_response_bytes(resp_bytes, "application/json", 200)
            return

        if path == "/api/tasks":
            filter_type = query_params.get("filter", ["all"])[0]
            search_kw = query_params.get("search", [""])[0].strip()
            try:
                page = max(1, int(query_params.get("page", ["1"])[0]))
            except Exception:
                page = 1
            try:
                page_size = max(1, min(200, int(query_params.get("page_size", ["30"])[0])))
            except Exception:
                page_size = 30

            data = self._load_real_database_records(
                filter_type=filter_type,
                search=search_kw,
                page=page,
                page_size=page_size
            )
            resp_bytes = json.dumps(data, ensure_ascii=False).encode("utf-8")
            self._send_response_bytes(resp_bytes, "application/json", 200)
            return

        if path == "/api/export/csv":
            filter_type = query_params.get("filter", ["all"])[0]
            search_kw = query_params.get("search", [""])[0].strip()
            data = self._load_real_database_records(
                filter_type=filter_type,
                search=search_kw,
                page=1,
                page_size=2000,
                include_metrics=False
            )
            tasks = data.get("tasks", [])
            csv_bytes = GLOBAL_EXPORT_MANAGER.generate_csv_report(tasks)
            ts_str = datetime.now().strftime("%Y%m%d_%H%M%S")
            self._send_response_bytes(
                csv_bytes,
                "text/csv; charset=utf-8",
                200,
                filename=f"compliance_audit_{filter_type}_{ts_str}.csv"
            )
            return

        if path == "/api/export/zip":
            filter_type = query_params.get("filter", ["violation"])[0]
            search_kw = query_params.get("search", [""])[0].strip()
            domain = query_params.get("domain", [""])[0].strip()
            if domain:
                data = self._load_real_database_records(filter_type="all", search=domain, page=1, page_size=100, include_metrics=False)
            else:
                data = self._load_real_database_records(filter_type=filter_type, search=search_kw, page=1, page_size=500, include_metrics=False)
            tasks = data.get("tasks", [])
            zip_bytes = GLOBAL_EXPORT_MANAGER.generate_evidence_zip(tasks)
            ts_str = datetime.now().strftime("%Y%m%d_%H%M%S")
            name_prefix = f"domain_{domain}" if domain else f"evidence_{filter_type}"
            self._send_response_bytes(
                zip_bytes,
                "application/zip",
                200,
                filename=f"{name_prefix}_{ts_str}.zip"
            )
            return

        if path == "/api/jobs/history":
            hist_data = GLOBAL_HISTORY_MANAGER.list_jobs(limit=100)
            resp_bytes = json.dumps(hist_data, ensure_ascii=False).encode("utf-8")
            self._send_response_bytes(resp_bytes, "application/json", 200)
            return

        if path.startswith("/api/jobs/history/"):
            job_id = path.replace("/api/jobs/history/", "").strip()
            job_detail = GLOBAL_HISTORY_MANAGER.get_job_detail(job_id)
            if job_detail:
                resp_bytes = json.dumps(job_detail, ensure_ascii=False).encode("utf-8")
                self._send_response_bytes(resp_bytes, "application/json", 200)
            else:
                self._send_response_bytes(b'{"error": "Job not found"}', "application/json", 404)
            return

        if path.startswith("/screenshots/"):
            filename = urllib.parse.unquote(path.replace("/screenshots/", ""))
            safe_name = os.path.basename(filename)
            filepath = os.path.join(self.output_dir, "screenshots", safe_name)

            if os.path.exists(filepath):
                mime, _ = mimetypes.guess_type(filepath)
                with open(filepath, "rb") as f:
                    file_bytes = f.read()
                self._send_response_bytes(file_bytes, mime or "image/png", 200)
                return
            else:
                self._send_response_bytes(b"Screenshot not found", "text/plain", 404)
                return

        self._send_response_bytes(b"Not Found", "text/plain", 404)

    def _load_real_database_records(
        self,
        filter_type: str = "all",
        search: str = "",
        page: int = 1,
        page_size: int = 30,
        include_metrics: bool = True
    ) -> Dict[str, Any]:
        """
        从 PostgreSQL 真实数据库中加载宏观统计（按去重域名统一口径）与服务端分页审查记录
        """
        tasks = []
        metrics = {
            "total": 0,
            "total_rows": 0,
            "audited_count": 0,
            "violations": 0,
            "cloaking": 0,
            "clean": 0,
            "pending": 0
        }
        total_count = 0

        try:
            pg = get_db_mgr().pg_client
            if pg:
                if include_metrics:
                    # 1. 查询全库宏观真实统计数据（按去重独立域名口径与主项目完全对齐）
                    stats_rows = pg.query("""
                        SELECT 
                            count(distinct domain) as total_domains,
                            count(*) as total_rows,
                            count(distinct domain) FILTER (WHERE risk_level IN ('high', 'critical') OR verify_status = 'verified_failed') as viol_domains,
                            count(distinct domain) FILTER (WHERE (risk_level = 'safe' OR verify_status = 'verified_clean') AND risk_level NOT IN ('high', 'critical') AND verify_status != 'verified_failed') as clean_domains,
                            count(distinct domain) FILTER (WHERE (risk_level = 'pending' OR verify_status = 'unverified') AND risk_level NOT IN ('high', 'critical', 'safe') AND verify_status NOT IN ('verified_failed', 'verified_clean')) as pending_domains
                        FROM external_domains;
                    """)
                    if stats_rows:
                        r = stats_rows[0]
                        metrics["total"] = int(r.get("total_domains") or 0)
                        metrics["total_rows"] = int(r.get("total_rows") or 0)
                        metrics["violations"] = int(r.get("viol_domains") or 0)
                        metrics["clean"] = int(r.get("clean_domains") or 0)
                        metrics["pending"] = int(r.get("pending_domains") or 0)

                    # 2. 查询 compliance_audit_logs 审计日志统计
                    audit_stats = pg.query("""
                        SELECT 
                            count(*) as audited_count,
                            count(*) FILTER (WHERE cloaking_suspected = TRUE) as cloaking
                        FROM compliance_audit_logs;
                    """)
                    if audit_stats:
                        metrics["audited_count"] = int(audit_stats[0].get("audited_count") or 0)
                        metrics["cloaking"] = int(audit_stats[0].get("cloaking") or 0)

                # 3. 针对不同筛选条件构建安全分页查询 (按去重域名聚合展示)
                if filter_type == "cloaking":
                    where_conds = ["cloaking_suspected = TRUE"]
                    params = []
                    if search:
                        where_conds.append("(domain ILIKE %s OR url ILIKE %s)")
                        params.extend([f"%{search}%", f"%{search}%"])

                    where_sql = "WHERE " + " AND ".join(where_conds)
                    cnt_res = pg.query(f"SELECT count(*) as c FROM compliance_audit_logs {where_sql}", tuple(params) if params else None)
                    total_count = int(cnt_res[0]["c"]) if cnt_res else 0

                    offset = (page - 1) * page_size
                    q_params = list(params) + [page_size, offset]
                    audit_logs = pg.query(f"""
                        SELECT 
                            id, task_id, domain, url, is_violation, overall_risk_level, primary_violation,
                            cloaking_suspected, cloaking_notes, category_probabilities,
                            device_count, violation_device_count, model_used, report_json, checked_at
                        FROM compliance_audit_logs
                        {where_sql}
                        ORDER BY id DESC
                        LIMIT %s OFFSET %s;
                    """, tuple(q_params))

                    for log in audit_logs:
                        rep = log.get("report_json") or {}
                        if isinstance(rep, str):
                            try:
                                rep = json.loads(rep)
                            except Exception:
                                rep = {}

                        verdict_summary = rep.get("verdict_summary") or {
                            "is_violation": log.get("is_violation"),
                            "overall_risk_level": log.get("overall_risk_level"),
                            "primary_violation_category": log.get("primary_violation"),
                            "primary_violation_cn": log.get("primary_violation"),
                            "cloaking_suspected": log.get("cloaking_suspected"),
                            "cloaking_notes": log.get("cloaking_notes"),
                            "category_probabilities": log.get("category_probabilities") or {}
                        }
                        rep_summ = rep.get("verdict_summary") or {}
                        if "dns_resolved_ips" not in verdict_summary and rep_summ.get("dns_resolved_ips"):
                            verdict_summary["dns_resolved_ips"] = rep_summ.get("dns_resolved_ips")
                        if "dns_status" not in verdict_summary and rep_summ.get("dns_status"):
                            verdict_summary["dns_status"] = rep_summ.get("dns_status")
                        if "dns_cnames" not in verdict_summary and rep_summ.get("dns_cnames"):
                            verdict_summary["dns_cnames"] = rep_summ.get("dns_cnames")
                        dom = log.get("domain") or (log.get("url") or "").replace("https://", "").replace("http://", "").split("/")[0]
                        tasks.append({
                            "id": log.get("id"),
                            "task_id": log.get("task_id", 0),
                            "domain": dom,
                            "url": log.get("url") or f"https://{dom}",
                            "model_used": log.get("model_used", "qwen2-vl"),
                            "checked_at": str(log.get("checked_at") or ""),
                            "source": "compliance_audit_logs",
                            "verdict_summary": verdict_summary,
                            "device_inspections": rep.get("device_inspections", [])
                        })

                else:
                    # 从 external_domains 提取去重记录并支持分页
                    where_conds = []
                    params = []

                    if filter_type == "violation":
                        where_conds.append("(risk_level IN ('high', 'critical') OR verify_status = 'verified_failed')")
                    elif filter_type == "clean":
                        where_conds.append("((risk_level = 'safe' OR verify_status = 'verified_clean') AND risk_level NOT IN ('high', 'critical') AND verify_status != 'verified_failed')")
                    elif filter_type == "pending":
                        where_conds.append("((risk_level = 'pending' OR verify_status = 'unverified') AND risk_level NOT IN ('high', 'critical', 'safe') AND verify_status NOT IN ('verified_failed', 'verified_clean'))")

                    if search:
                        if search.isdigit():
                            where_conds.append("(domain ILIKE %s OR sample_page_url ILIKE %s OR task_id = %s)")
                            params.extend([f"%{search}%", f"%{search}%", int(search)])
                        else:
                            where_conds.append("(domain ILIKE %s OR sample_page_url ILIKE %s)")
                            params.extend([f"%{search}%", f"%{search}%"])

                    where_sql = ("WHERE " + " AND ".join(where_conds)) if where_conds else ""

                    # 按去重独立域名计数
                    cnt_res = pg.query(f"SELECT count(distinct domain) as c FROM external_domains {where_sql}", tuple(params) if params else None)
                    total_count = int(cnt_res[0]["c"]) if cnt_res else 0

                    offset = (page - 1) * page_size
                    q_params = list(params) + [page_size, offset]
                    ext_domains = pg.query(f"""
                        SELECT 
                            min(id) as id, 
                            min(task_id) as task_id, 
                            domain, 
                            min(root_domain) as root_domain, 
                            min(sample_page_url) as sample_page_url, 
                            min(risk_level) as risk_level, 
                            min(risk_tags) as risk_tags, 
                            min(risk_remark) as risk_remark, 
                            min(risk_source) as risk_source, 
                            min(verify_status) as verify_status, 
                            max(verify_time) as verify_time, 
                            max(verify_detail) as verify_detail,
                            count(*) as ref_count
                        FROM external_domains
                        {where_sql}
                        GROUP BY domain
                        ORDER BY min(id) DESC
                        LIMIT %s OFFSET %s;
                    """, tuple(q_params))

                    # 收集本页 domain，批量到 compliance_audit_logs 匹配 AI 存证
                    domains_in_page = [r["domain"] for r in ext_domains if r.get("domain")]
                    audit_map = {}
                    if domains_in_page:
                        try:
                            fmt = ','.join(['%s'] * len(domains_in_page))
                            audit_rows = pg.query(
                                f"""SELECT 
                                    id, task_id, domain, url, is_violation, overall_risk_level, primary_violation,
                                    cloaking_suspected, cloaking_notes, category_probabilities,
                                    device_count, violation_device_count, model_used, report_json, checked_at
                                FROM compliance_audit_logs
                                WHERE domain IN ({fmt})
                                ORDER BY id DESC""",
                                tuple(domains_in_page)
                            )
                            for a in audit_rows:
                                d_key = a.get("domain")
                                if d_key and d_key not in audit_map:
                                    audit_map[d_key] = a
                        except Exception as ex:
                            print(f"[警告] 关联查询 compliance_audit_logs 失败: {ex}")

                    for row in ext_domains:
                        dom = (row.get("domain") or "").strip()
                        r_lvl = (row.get("risk_level") or "pending").lower()
                        v_stat = row.get("verify_status") or "unverified"
                        is_viol = (r_lvl in ("critical", "high") or v_stat == "verified_failed")

                        tags = []
                        try:
                            tags = json.loads(row.get("risk_tags") or "[]")
                        except Exception:
                            pass

                        # 若匹配到 compliance_audit_logs
                        if dom in audit_map:
                            log = audit_map[dom]
                            rep = log.get("report_json") or {}
                            if isinstance(rep, str):
                                try:
                                    rep = json.loads(rep)
                                except Exception:
                                    rep = {}

                            verdict_summary = rep.get("verdict_summary") or {
                                "is_violation": log.get("is_violation"),
                                "overall_risk_level": log.get("overall_risk_level"),
                                "primary_violation_category": log.get("primary_violation"),
                                "primary_violation_cn": log.get("primary_violation"),
                                "cloaking_suspected": log.get("cloaking_suspected"),
                                "cloaking_notes": log.get("cloaking_notes"),
                                "category_probabilities": log.get("category_probabilities") or {}
                            }
                            rep_summ = rep.get("verdict_summary") or {}
                            if "dns_resolved_ips" not in verdict_summary and rep_summ.get("dns_resolved_ips"):
                                verdict_summary["dns_resolved_ips"] = rep_summ.get("dns_resolved_ips")
                            if "dns_status" not in verdict_summary and rep_summ.get("dns_status"):
                                verdict_summary["dns_status"] = rep_summ.get("dns_status")
                            if "dns_cnames" not in verdict_summary and rep_summ.get("dns_cnames"):
                                verdict_summary["dns_cnames"] = rep_summ.get("dns_cnames")

                            tasks.append({
                                "id": row.get("id"),
                                "task_id": row.get("task_id", 0),
                                "domain": dom,
                                "url": f"https://{dom}",
                                "sample_page_url": row.get("sample_page_url", ""),
                                "ref_count": int(row.get("ref_count") or 1),
                                "model_used": log.get("model_used", "qwen2-vl"),
                                "checked_at": str(log.get("checked_at") or row.get("verify_time") or ""),
                                "source": "compliance_audit_logs",
                                "risk_remark": row.get("risk_remark", ""),
                                "verdict_summary": verdict_summary,
                                "device_inspections": rep.get("device_inspections", [])
                            })
                        else:
                            # 仅在 external_domains 中的记录
                            detail_raw = row.get("verify_detail") or ""
                            detail_obj = {}
                            if detail_raw.startswith("{"):
                                try:
                                    detail_obj = json.loads(detail_raw)
                                except Exception:
                                    pass

                            def_cn = "正常合规"
                            if is_viol:
                                def_cn = "涉险违规"
                            elif r_lvl == "pending":
                                def_cn = "待研判"

                            notes = detail_obj.get("summary") or row.get("risk_remark") or detail_raw
                            if not notes:
                                if r_lvl == "pending":
                                    notes = "尚未执行多端仿真截屏与视觉模型深度审核，可直接点击右上角【立即研判此域名】或顶部【启动单批巡检】启动自动化存证。"
                                else:
                                    notes = "系统规则研判记录，尚未进行多端视觉切片存证。"

                            tasks.append({
                                "id": row.get("id"),
                                "task_id": row.get("task_id", 0),
                                "domain": dom,
                                "url": f"https://{dom}",
                                "sample_page_url": row.get("sample_page_url", ""),
                                "ref_count": int(row.get("ref_count") or 1),
                                "model_used": detail_obj.get("model_used", "规则引擎/多模态"),
                                "checked_at": str(row.get("verify_time") or ""),
                                "risk_remark": row.get("risk_remark", ""),
                                "source": "external_domains",
                                "verdict_summary": {
                                    "is_violation": is_viol,
                                    "overall_risk_level": r_lvl.upper(),
                                    "primary_violation_category": tags[0] if tags else ("risk" if is_viol else ("pending" if r_lvl == "pending" else "normal")),
                                    "primary_violation_cn": tags[0] if tags else def_cn,
                                    "cloaking_suspected": bool(detail_obj.get("cloaking_suspected", False)),
                                    "cloaking_notes": notes,
                                    "dns_resolved_ips": detail_obj.get("dns_resolved_ips", []),
                                    "dns_cnames": detail_obj.get("dns_cnames", []),
                                    "dns_status": detail_obj.get("dns_status"),
                                    "category_probabilities": detail_obj.get("category_probabilities") or {}
                                },
                                "device_inspections": detail_obj.get("details", [])
                            })

        except Exception as e:
            print(f"[警告] 从数据库读取审查大屏数据失败: {e}")

        total_pages = max(1, math.ceil(total_count / page_size)) if total_count > 0 else 1

        return {
            "metrics": metrics,
            "pagination": {
                "page": page,
                "page_size": page_size,
                "total_count": total_count,
                "total_pages": total_pages
            },
            "database": "website_domain_db",
            "source": "postgresql",
            "tasks": tasks
        }


def run_dashboard(host: str = "127.0.0.1", port: int = 8888, output_dir: str = "output"):
    handler_factory = lambda *args, **kwargs: ComplianceDashboardHandler(*args, output_dir=output_dir, **kwargs)
    try:
        server = ThreadingHTTPServer((host, port), handler_factory)
    except PermissionError:
        port = 8090
        server = ThreadingHTTPServer((host, port), handler_factory)
    print("=" * 60)
    print(f"[*] 网页合规巡检数据库大屏已启动!")
    print(f"[*] 直连数据库: PostgreSQL (website_domain_db)")
    print(f"[*] 本地浏览器访问地址: http://localhost:{port}")
    print("=" * 60)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[*] 控制台服务已关闭。")
        server.server_close()


if __name__ == "__main__":
    run_dashboard()
