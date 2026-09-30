"""
Lightweight Web Dashboard Server for Web Compliance Checker.
Directly connected to system database (PostgreSQL & ClickHouse website_domain_db).
Zero external dependencies (uses standard library http.server).
Features Master-Detail Split View, Real-Time Database Metrics, and Forensics Inspection.
"""

import os
import sys
import json
import glob
import mimetypes
import urllib.parse
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Dict, Any, List, Optional

if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from db_manager import UnifiedDatabaseManager

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
  </style>
</head>
<body class="bg-slate-950 text-slate-100 min-h-screen antialiased p-3 sm:p-6">
  <div class="max-w-7xl mx-auto space-y-6">

    <!-- Top Header -->
    <header class="bg-slate-900/90 border border-slate-800 rounded-2xl p-5 shadow-xl flex flex-col md:flex-row justify-between items-start md:items-center gap-4">
      <div>
        <div class="flex items-center gap-2">
          <span class="p-2 bg-indigo-600/20 text-indigo-400 rounded-xl text-xl">🛡️</span>
          <h1 class="text-xl font-bold text-white tracking-tight">网页多端仿真与多模态安全巡检控制台</h1>
          <span class="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
            <span class="w-2 h-2 rounded-full bg-emerald-400 animate-pulse"></span> 🟢 数据库直连 (website_domain_db)
          </span>
        </div>
        <p class="text-xs text-slate-400 mt-1">集成 PostgreSQL (external_domains / compliance_audit_logs) 与 ClickHouse (compliance_audit_events) 实时全量数据</p>
      </div>

      <div class="flex items-center gap-3">
        <button onclick="fetchData()" class="px-3.5 py-1.5 bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg text-xs font-semibold transition flex items-center gap-1.5 shadow-sm">
          <span>🔄</span> 立即刷新
        </button>
        <span class="text-xs text-slate-400 font-mono bg-slate-800/80 px-3 py-1.5 rounded-lg border border-slate-700">
          端口: <strong class="text-slate-200">8888</strong>
        </span>
      </div>
    </header>

    <!-- Metrics Cards (Real Database Data) -->
    <div class="grid grid-cols-2 sm:grid-cols-4 gap-4">
      <div class="bg-slate-900/80 border border-slate-800 rounded-xl p-4 shadow-sm">
        <div class="text-xs font-medium text-slate-400">全库外部域名总量</div>
        <div id="statTotal" class="text-2xl font-black text-white mt-1">--</div>
        <div id="statAudited" class="text-xs text-indigo-400 mt-1">已完成 AI 存证: -- 条</div>
      </div>
      <div class="bg-slate-900/80 border border-slate-800 rounded-xl p-4 shadow-sm">
        <div class="text-xs font-medium text-rose-400">检出涉险 / 违规站点</div>
        <div id="statViolations" class="text-2xl font-black text-rose-500 mt-1">--</div>
        <div id="statViolRate" class="text-xs text-rose-400/80 mt-1">违规占比: --%</div>
      </div>
      <div class="bg-slate-900/80 border border-slate-800 rounded-xl p-4 shadow-sm">
        <div class="text-xs font-medium text-amber-400">设备端伪装 (Cloaking)</div>
        <div id="statCloaking" class="text-2xl font-black text-amber-500 mt-1">--</div>
        <div class="text-xs text-amber-400/80 mt-1">PC正常但移动端违规</div>
      </div>
      <div class="bg-slate-900/80 border border-slate-800 rounded-xl p-4 shadow-sm">
        <div class="text-xs font-medium text-emerald-400">健康合规域名</div>
        <div id="statClean" class="text-2xl font-black text-emerald-500 mt-1">--</div>
        <div id="statPending" class="text-xs text-slate-400 mt-1">待研判域名: -- 条</div>
      </div>
    </div>

    <!-- Master-Detail Split View -->
    <div class="grid grid-cols-1 lg:grid-cols-12 gap-5">

      <!-- Left Task List (5 cols) -->
      <div class="lg:col-span-5 bg-slate-900/80 border border-slate-800 rounded-2xl p-4 space-y-3 flex flex-col h-[740px]">
        <div class="flex justify-between items-center text-xs pb-2 border-b border-slate-800">
          <span class="font-bold text-slate-200">数据库审查存证清单</span>
          <div class="flex gap-1">
            <button onclick="setFilter('all')" id="btnFilterAll" class="filter-btn px-2.5 py-1 rounded text-xs font-medium bg-slate-700 text-white">全部</button>
            <button onclick="setFilter('violation')" id="btnFilterViol" class="filter-btn px-2.5 py-1 rounded text-xs font-medium text-slate-400 hover:text-white">违规</button>
            <button onclick="setFilter('cloaking')" id="btnFilterCloak" class="filter-btn px-2.5 py-1 rounded text-xs font-medium text-slate-400 hover:text-white">伪装</button>
            <button onclick="setFilter('clean')" id="btnFilterClean" class="filter-btn px-2.5 py-1 rounded text-xs font-medium text-slate-400 hover:text-white">合规</button>
            <button onclick="setFilter('pending')" id="btnFilterPending" class="filter-btn px-2.5 py-1 rounded text-xs font-medium text-slate-400 hover:text-white">待研判</button>
          </div>
        </div>

        <div>
          <input type="text" id="searchInput" oninput="renderTaskList()" placeholder="按域名 / URL / 任务ID 搜索..." class="w-full bg-slate-950 border border-slate-800 px-3 py-1.5 rounded-lg text-xs text-slate-200 focus:outline-none focus:border-indigo-500">
        </div>

        <div id="taskListContainer" class="flex-1 overflow-y-auto space-y-2 pr-1">
          <div class="text-center py-12 text-slate-500 text-xs">正在连接数据库读取真实数据...</div>
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
              <h2 id="detailUrl" class="text-sm font-bold text-white mt-2 break-all">请从左侧列表选择域名任务查看明细</h2>
              <p id="detailTime" class="text-xs text-slate-400 mt-0.5">时间: -</p>
            </div>
            <div class="text-right shrink-0">
              <span class="text-xs text-slate-400 block">主违规分类</span>
              <span id="detailPrimary" class="text-sm font-bold text-indigo-400">normal</span>
            </div>
          </div>

          <!-- Cloaking / Verdict Notes Box -->
          <div id="detailNotesBox" class="p-3 rounded-xl bg-slate-800/60 border border-slate-700/60 text-xs text-slate-300 leading-relaxed">
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
  </div>

  <script>
    let allRecords = [];
    let currentFilter = 'all';
    let selectedIdx = 0;

    async function fetchData() {
      try {
        const container = document.getElementById('taskListContainer');
        container.innerHTML = '<div class="text-center py-12 text-slate-500 text-xs">正在从数据库获取最新记录...</div>';

        const resp = await fetch('/api/tasks');
        const json = await resp.json();

        // 1. 更新顶部真实数据库指标卡
        if (json.metrics) {
          document.getElementById('statTotal').innerText = (json.metrics.total || 0).toLocaleString();
          document.getElementById('statAudited').innerText = `已完成 AI 存证: ${(json.metrics.audited_count || 0).toLocaleString()} 条`;
          document.getElementById('statViolations').innerText = (json.metrics.violations || 0).toLocaleString();
          document.getElementById('statCloaking').innerText = (json.metrics.cloaking || 0).toLocaleString();
          document.getElementById('statClean').innerText = (json.metrics.clean || 0).toLocaleString();
          document.getElementById('statPending').innerText = `待研判域名: ${(json.metrics.pending || 0).toLocaleString()} 条`;

          const total = json.metrics.total || 1;
          const viols = json.metrics.violations || 0;
          const rate = ((viols / total) * 100).toFixed(2);
          document.getElementById('statViolRate').innerText = `违规占比: ${rate}%`;
        }

        // 2. 真实域名审查任务列表
        allRecords = json.tasks || [];
        renderTaskList();

        if (allRecords.length > 0) {
          selectTask(0);
        } else {
          document.getElementById('detailUrl').innerText = "当前筛选条件下暂无审计记录";
          document.getElementById('detailTime').innerText = "可通过运行巡检命令导入新域名审核";
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
      renderTaskList();
      if (allRecords.length > 0) {
        selectTask(0);
      }
    }

    function renderTaskList() {
      const q = document.getElementById('searchInput').value.toLowerCase().trim();
      const container = document.getElementById('taskListContainer');

      let filtered = allRecords.filter(item => {
        const url = (item.url || '').toLowerCase();
        const domain = (item.domain || '').toLowerCase();
        const taskIdStr = String(item.task_id || '');
        if (q && !url.includes(q) && !domain.includes(q) && !taskIdStr.includes(q)) return false;

        const sum = item.verdict_summary || {};
        const isViol = sum.is_violation;
        const isCloak = sum.cloaking_suspected;
        const riskLevel = (sum.overall_risk_level || '').toLowerCase();

        if (currentFilter === 'violation') return isViol || riskLevel === 'high' || riskLevel === 'critical';
        if (currentFilter === 'cloaking') return isCloak;
        if (currentFilter === 'clean') return !isViol && riskLevel === 'safe';
        if (currentFilter === 'pending') return riskLevel === 'pending' || riskLevel === 'unknown';
        return true;
      });

      if (!filtered.length) {
        container.innerHTML = `<div class="text-center py-12 text-slate-500 text-xs">暂无匹配的域名审查存证记录</div>`;
        return;
      }

      container.innerHTML = filtered.map((item, idx) => {
        const globalIdx = allRecords.indexOf(item);
        const isSelected = globalIdx === selectedIdx;
        const sum = item.verdict_summary || {};
        const isViol = sum.is_violation;
        const isCloak = sum.cloaking_suspected;
        const domain = item.domain || (item.url || '').replace(/https?:\\/\\//, '').split('/')[0];
        const riskLevel = (sum.overall_risk_level || 'SAFE').toUpperCase();

        const violBadge = isViol 
          ? '<span class="text-[10px] font-bold text-rose-400 bg-rose-500/20 border border-rose-500/30 px-1.5 py-0.5 rounded">违规</span>'
          : (riskLevel === 'SAFE' 
              ? '<span class="text-[10px] font-bold text-emerald-400 bg-emerald-500/20 border border-emerald-500/30 px-1.5 py-0.5 rounded">合规</span>'
              : '<span class="text-[10px] font-bold text-amber-400 bg-amber-500/20 border border-amber-500/30 px-1.5 py-0.5 rounded">待判</span>');

        const cloakBadge = isCloak 
          ? '<span class="text-[10px] font-bold text-amber-400 bg-amber-500/20 border border-amber-500/30 px-1.5 py-0.5 rounded">伪装</span>' : '';

        const taskIdBadge = item.task_id ? `<span class="text-[10px] text-slate-500 font-mono">Task:${item.task_id}</span>` : '';

        return `
          <div onclick="selectTask(${globalIdx})" class="cursor-pointer p-3 rounded-xl border transition ${isSelected ? 'bg-indigo-600/15 border-indigo-500/50 shadow-md' : 'bg-slate-900/60 border-slate-800 hover:border-slate-700'}">
            <div class="flex justify-between items-center text-xs">
              <span class="font-bold text-white truncate max-w-[200px]" title="${item.url}">${domain}</span>
              <div class="flex items-center gap-1.5">
                ${taskIdBadge}
                ${cloakBadge}
                ${violBadge}
              </div>
            </div>
            <div class="flex justify-between items-center text-[11px] text-slate-400 mt-2">
              <span class="font-mono text-indigo-400">${sum.primary_violation_cn || sum.primary_violation_category || 'normal'}</span>
              <span>${(item.checked_at || '').substring(0, 19).replace('T', ' ')}</span>
            </div>
          </div>
        `;
      }).join('');
    }

    function selectTask(idx) {
      selectedIdx = idx;
      renderTaskList();
      const r = allRecords[idx];
      if (!r) return;

      document.getElementById('detailUrl').innerText = r.url || (r.domain ? `https://${r.domain}` : '-');
      document.getElementById('detailTime').innerText = `审查时间: ${r.checked_at || '-'} | 关联主任务 ID: ${r.task_id || '-'} | 来源: ${r.source || 'website_domain_db'}`;
      document.getElementById('detailFooterMeta').innerText = `模型: ${r.model_used || 'qwen2-vl'} · 数据库: PostgreSQL (website_domain_db)`;

      const sum = r.verdict_summary || {};
      const isViol = sum.is_violation;
      const risk = (sum.overall_risk_level || 'SAFE').toUpperCase();

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
        vBadge.innerText = "待研判 / 未审查";
      }

      const riskColorMap = {
        'CRITICAL': 'bg-red-950 text-red-400 border-red-800',
        'HIGH': 'bg-rose-950 text-rose-400 border-rose-800',
        'MEDIUM': 'bg-amber-950 text-amber-400 border-amber-800',
        'LOW': 'bg-blue-950 text-blue-400 border-blue-800',
        'SAFE': 'bg-slate-800 text-slate-400 border-slate-700',
        'PENDING': 'bg-slate-850 text-slate-400 border-slate-700'
      };
      const rBadge = document.getElementById('detailRiskBadge');
      rBadge.className = `badge ${riskColorMap[risk] || riskColorMap['SAFE']} border`;
      rBadge.innerText = `${risk} 风险`;

      const cBadge = document.getElementById('detailCloakBadge');
      if (sum.cloaking_suspected) {
        cBadge.classList.remove('hidden');
        cBadge.className = "badge bg-amber-500/20 text-amber-400 border border-amber-500/30";
      } else {
        cBadge.classList.add('hidden');
      }

      document.getElementById('detailPrimary').innerText = sum.primary_violation_cn || sum.primary_violation_category || 'normal';

      // 研判依据说明
      const notesBox = document.getElementById('detailNotesBox');
      notesBox.innerHTML = `<strong>研判依据与特征：</strong> ${sum.cloaking_notes || r.risk_remark || "页面各端展示一致，未识别到违规及伪装特征。"}`;

      // 6 大分类概率矩阵
      const catMap = sum.category_probabilities || {};
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

    window.onload = fetchData;
  </script>
</body>
</html>
"""


class ComplianceDashboardHandler(BaseHTTPRequestHandler):
    def __init__(self, *args, output_dir: str = "output", **kwargs):
        self.output_dir = output_dir
        self.db_mgr = UnifiedDatabaseManager()
        super().__init__(*args, **kwargs)

    def _set_headers(self, content_type: str = "application/json", status: int = 200):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path in ("/", "/index.html"):
            self._set_headers("text/html; charset=utf-8")
            self.wfile.write(DASHBOARD_HTML.encode("utf-8"))
            return

        # API: 返回真实数据库汇总与任务列表
        if path == "/api/tasks":
            data = self._load_real_database_records()
            self._set_headers("application/json")
            self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))
            return

        # 静态文件服务：图片预览 (/screenshots/...)
        if path.startswith("/screenshots/"):
            filename = urllib.parse.unquote(path.replace("/screenshots/", ""))
            safe_name = os.path.basename(filename)
            filepath = os.path.join(self.output_dir, "screenshots", safe_name)

            if os.path.exists(filepath):
                mime, _ = mimetypes.guess_type(filepath)
                self._set_headers(mime or "image/png")
                with open(filepath, "rb") as f:
                    self.wfile.write(f.read())
                return
            else:
                self._set_headers("text/plain", 404)
                self.wfile.write(b"Screenshot not found")
                return

        self._set_headers("text/plain", 404)
        self.wfile.write(b"Not Found")

    def _load_real_database_records(self) -> Dict[str, Any]:
        """
        从 PostgreSQL 真实数据库中加载全量统计与近期审查存证记录
        """
        tasks = []
        metrics = {
            "total": 0,
            "audited_count": 0,
            "violations": 0,
            "cloaking": 0,
            "clean": 0,
            "pending": 0
        }

        try:
            pg = self.db_mgr.pg_client
            if pg:
                # 1. 查询全库宏观真实统计数据
                stats_rows = pg.query("""
                    SELECT 
                        count(*) as total,
                        count(*) FILTER (WHERE risk_level IN ('high', 'critical') OR verify_status = 'verified_failed') as viol,
                        count(*) FILTER (WHERE risk_level = 'safe' OR verify_status = 'verified_clean') as clean,
                        count(*) FILTER (WHERE risk_level = 'pending' AND verify_status = 'unverified') as pending
                    FROM external_domains;
                """)
                if stats_rows:
                    r = stats_rows[0]
                    metrics["total"] = int(r.get("total") or 0)
                    metrics["violations"] = int(r.get("viol") or 0)
                    metrics["clean"] = int(r.get("clean") or 0)
                    metrics["pending"] = int(r.get("pending") or 0)

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

                # 3. 抽取真实的 compliance_audit_logs AI 存证记录
                audit_logs = pg.query("""
                    SELECT 
                        id, task_id, domain, url, is_violation, overall_risk_level, primary_violation,
                        cloaking_suspected, cloaking_notes, category_probabilities,
                        device_count, violation_device_count, model_used, report_json, checked_at
                    FROM compliance_audit_logs
                    ORDER BY id DESC
                    LIMIT 50;
                """)

                seen_domains = set()
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
                        "cloaking_suspected": log.get("cloaking_suspected"),
                        "cloaking_notes": log.get("cloaking_notes"),
                        "category_probabilities": log.get("category_probabilities") or {}
                    }

                    dom = log.get("domain") or (log.get("url") or "").replace("https://", "").replace("http://", "").split("/")[0]
                    seen_domains.add(dom)

                    chk_time = str(log.get("checked_at") or "")
                    tasks.append({
                        "id": log.get("id"),
                        "task_id": log.get("task_id", 0),
                        "domain": dom,
                        "url": log.get("url") or f"https://{dom}",
                        "model_used": log.get("model_used", "qwen2-vl"),
                        "checked_at": chk_time,
                        "source": "compliance_audit_logs",
                        "verdict_summary": verdict_summary,
                        "device_inspections": rep.get("device_inspections", [])
                    })

                # 4. 抽取 external_domains 中已研判或重点涉险外部域名 (补充丰富展示)
                ext_domains = pg.query("""
                    SELECT 
                        id, task_id, domain, root_domain, sample_page_url, 
                        risk_level, risk_tags, risk_remark, risk_source, 
                        verify_status, verify_time, verify_detail
                    FROM external_domains
                    WHERE verify_status != 'unverified' OR risk_level IN ('critical', 'high', 'medium')
                    ORDER BY id DESC
                    LIMIT 80;
                """)

                for row in ext_domains:
                    dom = (row.get("domain") or "").strip()
                    if dom in seen_domains:
                        continue
                    seen_domains.add(dom)

                    r_lvl = (row.get("risk_level") or "pending").lower()
                    v_stat = row.get("verify_status") or "unverified"
                    is_viol = (r_lvl in ("critical", "high") or v_stat == "verified_failed")

                    # 解析 tags
                    tags = []
                    try:
                        tags = json.loads(row.get("risk_tags") or "[]")
                    except Exception:
                        pass

                    # 解析 verify_detail
                    detail_raw = row.get("verify_detail") or ""
                    detail_obj = {}
                    if detail_raw.startswith("{"):
                        try:
                            detail_obj = json.loads(detail_raw)
                        except Exception:
                            pass

                    summary_notes = detail_obj.get("summary") or row.get("risk_remark") or detail_raw or "系统全量规则研判存证"

                    tasks.append({
                        "id": row.get("id"),
                        "task_id": row.get("task_id", 0),
                        "domain": dom,
                        "url": f"https://{dom}",
                        "sample_page_url": row.get("sample_page_url", ""),
                        "model_used": detail_obj.get("model_used", "知识库安全引擎/AI多模态"),
                        "checked_at": str(row.get("verify_time") or ""),
                        "risk_remark": row.get("risk_remark", ""),
                        "source": "external_domains",
                        "verdict_summary": {
                            "is_violation": is_viol,
                            "overall_risk_level": r_lvl.upper(),
                            "primary_violation_category": tags[0] if tags else ("risk" if is_viol else "normal"),
                            "primary_violation_cn": tags[0] if tags else ("涉险违规" if is_viol else "安全合规"),
                            "cloaking_suspected": bool(detail_obj.get("cloaking_suspected", False)),
                            "cloaking_notes": summary_notes,
                            "category_probabilities": detail_obj.get("category_probabilities") or {
                                "pornography_vulgarity": {"name": "色情低俗", "max_probability": 0.0, "is_detected": False},
                                "gambling_lottery": {"name": "赌博博彩", "max_probability": 0.0, "is_detected": False},
                                "fraud_scam": {"name": "电信诈骗", "max_probability": 0.0, "is_detected": False},
                                "violence_contraband": {"name": "暴恐违禁", "max_probability": 0.0, "is_detected": False},
                                "political_extremism": {"name": "涉政不良", "max_probability": 0.0, "is_detected": False},
                                "malicious_adware": {"name": "恶意广告", "max_probability": 0.0, "is_detected": False}
                            }
                        },
                        "device_inspections": detail_obj.get("details", [])
                    })

        except Exception as e:
            print(f"[警告] 从数据库读取审查大屏数据失败: {e}")

        return {
            "metrics": metrics,
            "database": "website_domain_db",
            "source": "postgresql",
            "tasks": tasks
        }


def run_dashboard(host: str = "127.0.0.1", port: int = 8888, output_dir: str = "output"):
    handler_factory = lambda *args, **kwargs: ComplianceDashboardHandler(*args, output_dir=output_dir, **kwargs)
    try:
        server = HTTPServer((host, port), handler_factory)
    except PermissionError:
        port = 8090
        server = HTTPServer((host, port), handler_factory)
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
