/**
 * Web Compliance Dashboard - Frontend Application Logic
 * Reactive UI with instant visual feedback on all controls.
 */

// Global App State
let currentPage = 1;
let pageSize = 20;
let currentFilter = 'all';
let searchKeyword = '';
let selectedWorkers = 3;
let selectedBatch = 30;
let selectedDevicePreset = 'dual';
let activeDrawerDomain = '';
let scanPollTimer = null;

// ==============================================================================
// 1. Initialization
// ==============================================================================
document.addEventListener('DOMContentLoaded', () => {
  loadAllData();
  startScanStatusPolling();
});

function loadAllData() {
  loadStats();
  loadTable();
}

// ==============================================================================
// 2. Statistics & Filter Tabs
// ==============================================================================
async function loadStats() {
  try {
    const res = await fetch('/api/stats');
    const data = await res.json();
    if (!data || data.status === 'error') return;

    // Card 1: Total Distinct
    document.getElementById('statDistinctDomains').innerText = (data.distinct_domains || 0).toLocaleString();
    document.getElementById('statTotalRows').innerText = `${(data.total_rows || 0).toLocaleString()} 条`;

    // Card 2: Violations
    document.getElementById('statViolations').innerText = (data.violations_count || 0).toLocaleString();

    // Card 3: Cloaking
    document.getElementById('statCloaking').innerText = (data.cloaking_count || 0).toLocaleString();

    // Card 4: Pending Pool
    document.getElementById('statPendingPool').innerText = (data.pending_count || 0).toLocaleString();
    document.getElementById('statErrorPagesText').innerText = `${data.error_pages_count || 0} 处404保持待判`;

    // Tab Badges
    document.getElementById('tabBadge_all').innerText = `(${data.distinct_domains || 0})`;
    document.getElementById('tabBadge_violation').innerText = data.violations_count || 0;
    document.getElementById('tabBadge_cloaking').innerText = data.cloaking_count || 0;
    document.getElementById('tabBadge_error_pages').innerText = data.error_pages_count || 0;
    document.getElementById('tabBadge_pending').innerText = `(${data.pending_count || 0})`;

  } catch (err) {
    console.error('Failed to load stats:', err);
  }
}

function setFilter(filterType) {
  currentFilter = filterType;
  currentPage = 1;

  // Update tab button styles
  document.querySelectorAll('.tab-btn').forEach(btn => btn.classList.remove('active'));
  const activeBtn = document.getElementById(`tab_${filterType}`);
  if (activeBtn) activeBtn.classList.add('active');

  loadTable();
}

// ==============================================================================
// 3. Domains Table & Pagination
// ==============================================================================
async function loadTable() {
  const tbody = document.getElementById('tableBody');
  tbody.innerHTML = `
    <tr>
      <td colspan="6" class="text-center py-12 text-slate-500">
        <div class="animate-spin inline-block w-6 h-6 border-2 border-indigo-500 border-t-transparent rounded-full mb-2"></div>
        <div>正在检索资产数据...</div>
      </td>
    </tr>
  `;

  try {
    const url = `/api/domains?page=${currentPage}&page_size=${pageSize}&filter=${currentFilter}&search=${encodeURIComponent(searchKeyword)}`;
    const res = await fetch(url);
    const data = await res.json();

    if (!data.items || data.items.length === 0) {
      tbody.innerHTML = `
        <tr>
          <td colspan="6" class="text-center py-12 text-slate-500">
            <span class="text-3xl block mb-2">🍃</span>
            未检索到符合条件的域名资产记录
          </td>
        </tr>
      `;
      document.getElementById('paginationInfo').innerText = '显示 0 到 0 条，共 0 条';
      renderPagination(1, 1);
      return;
    }

    // Render Table Rows
    let rowsHtml = '';
    data.items.forEach(item => {
      // Badge Styling
      let badgeHtml = '';
      if (item.badge_type === 'violation') {
        badgeHtml = `<span class="px-2 py-0.5 rounded-full text-[11px] font-bold bg-rose-500/10 text-rose-400 border border-rose-500/30">🚨 违规异常</span>`;
      } else if (item.badge_type === 'ssrf_blocked') {
        badgeHtml = `<span class="px-2 py-0.5 rounded-full text-[11px] font-bold bg-cyan-500/10 text-cyan-400 border border-cyan-500/30">🛡️ 内网阻断(待判)</span>`;
      } else if (item.badge_type === 'error_404') {
        badgeHtml = `<span class="px-2 py-0.5 rounded-full text-[11px] font-bold bg-amber-500/10 text-amber-400 border border-amber-500/30">⚠️ 404失效(待判)</span>`;
      } else if (item.badge_type === 'clean_pending') {
        badgeHtml = `<span class="px-2 py-0.5 rounded-full text-[11px] font-medium bg-sky-500/10 text-sky-400 border border-sky-500/30">⏳ 未见异常(待判)</span>`;
      } else {
        badgeHtml = `<span class="px-2 py-0.5 rounded-full text-[11px] font-medium bg-slate-800 text-slate-400 border border-slate-700">⏳ 待研判</span>`;
      }

      // Format explanation
      let explText = '-';
      if (item.risk_remark) {
        explText = item.risk_remark;
      } else if (item.detail && item.detail.explanation) {
        explText = item.detail.explanation.split('\n')[0];
      }

      // Thumbnail
      let thumbHtml = '<span class="text-slate-600 text-[11px]">无截图</span>';
      if (item.screenshots && item.screenshots.length > 0) {
        const sc = item.screenshots[0];
        thumbHtml = `
          <div class="relative group inline-block cursor-pointer" onclick="openLightbox('/output/${sc.path}', '${item.domain}', '${sc.sha256}')">
            <img src="/output/${sc.path}" alt="取证缩略图" class="w-14 h-9 object-cover rounded border border-slate-700 group-hover:border-indigo-400 transition shadow-sm">
            <span class="absolute inset-0 bg-indigo-900/40 opacity-0 group-hover:opacity-100 rounded flex items-center justify-center text-white text-[10px] font-bold transition">🔍</span>
          </div>
        `;
      } else if (item.is_404 || item.badge_type === 'error_404') {
        thumbHtml = '<span class="text-amber-400 text-[10px] bg-amber-500/10 px-1.5 py-0.5 rounded border border-amber-500/20 whitespace-nowrap">⚠️ 404跳过截屏</span>';
      }

      rowsHtml += `
        <tr class="hover:bg-slate-800/40 transition-colors duration-150">
          <td class="py-3 px-4">
            <div class="font-bold text-white font-mono flex items-center gap-1.5">
              <span>${item.domain}</span>
              <a href="${item.url}" target="_blank" class="text-slate-500 hover:text-indigo-400 text-xs" title="访问目标">↗</a>
            </div>
            <div class="text-[11px] text-slate-400 font-mono truncate max-w-xs mt-0.5">${item.url}</div>
          </td>
          <td class="py-3 px-4 whitespace-nowrap">${badgeHtml}</td>
          <td class="py-3 px-4 max-w-md">
            <div class="text-slate-300 text-xs line-clamp-2 leading-relaxed" title="${explText}">${explText}</div>
            ${item.risk_tags ? `<div class="text-[10px] text-indigo-400 font-mono mt-0.5">${item.risk_tags}</div>` : ''}
          </td>
          <td class="py-3 px-4 whitespace-nowrap">${thumbHtml}</td>
          <td class="py-3 px-4 whitespace-nowrap font-mono text-slate-400 text-[11px]">
            ${item.verify_time ? item.verify_time.slice(0, 16) : '<span class="text-slate-600">未巡检</span>'}
          </td>
          <td class="py-3 px-4 text-right whitespace-nowrap">
            <div class="flex items-center justify-end gap-1.5">
              <button onclick="openInstantAuditModal('${item.domain}')" class="px-2 py-1 rounded bg-slate-800 hover:bg-slate-700 text-indigo-400 hover:text-indigo-300 text-[11px] font-medium border border-slate-700 transition" title="现场即时研判">
                ⚡ 即时诊断
              </button>
              <button onclick="openDetailDrawer('${item.domain}')" class="px-2.5 py-1 rounded bg-indigo-600/30 hover:bg-indigo-600 text-indigo-200 hover:text-white text-[11px] font-semibold border border-indigo-500/30 transition">
                👁️ 取证
              </button>
            </div>
          </td>
        </tr>
      `;
    });

    tbody.innerHTML = rowsHtml;

    // Pagination info
    const startIdx = (data.page - 1) * data.page_size + 1;
    const endIdx = Math.min(data.page * data.page_size, data.total);
    document.getElementById('paginationInfo').innerText = `显示 ${startIdx} 到 ${endIdx} 条，共 ${data.total.toLocaleString()} 条资产`;

    renderPagination(data.page, data.total_pages);

  } catch (err) {
    tbody.innerHTML = `
      <tr>
        <td colspan="6" class="text-center py-12 text-rose-400">
          加载数据失败: ${err.message}
        </td>
      </tr>
    `;
  }
}

function renderPagination(page, totalPages) {
  currentPage = page;
  document.getElementById('btnPrevPage').disabled = page <= 1;
  document.getElementById('btnNextPage').disabled = page >= totalPages;

  const container = document.getElementById('pageNumbers');
  let btns = '';

  const maxVisible = 5;
  let startPage = Math.max(1, page - 2);
  let endPage = Math.min(totalPages, startPage + maxVisible - 1);
  if (endPage - startPage < maxVisible - 1) {
    startPage = Math.max(1, endPage - maxVisible + 1);
  }

  for (let p = startPage; p <= endPage; p++) {
    const isActive = p === page;
    btns += `
      <button onclick="goToPage(${p})" class="px-2.5 py-1 rounded text-xs font-semibold ${isActive ? 'bg-indigo-600 text-white shadow-sm' : 'bg-slate-800 hover:bg-slate-700 text-slate-300'}">
        ${p}
      </button>
    `;
  }
  container.innerHTML = btns;
}

function goToPage(p) {
  if (p < 1) return;
  currentPage = p;
  loadTable();
}

function handleSearchKey(event) {
  if (event.key === 'Enter') {
    triggerSearch();
  }
}

function triggerSearch() {
  searchKeyword = document.getElementById('searchInput').value.trim();
  currentPage = 1;
  loadTable();
}

function clearSearch() {
  document.getElementById('searchInput').value = '';
  searchKeyword = '';
  currentPage = 1;
  loadTable();
}

// ==============================================================================
// 4. Modal Interactivity (100% Visual Feedback)
// ==============================================================================

function openScanModal() {
  document.getElementById('scanConfigModal').classList.remove('hidden');
}

function closeScanModal() {
  document.getElementById('scanConfigModal').classList.add('hidden');
}

// Device Preset Selection
function selectDevicePreset(preset) {
  selectedDevicePreset = preset;
  ['dual', 'pc', 'full'].forEach(p => {
    const card = document.getElementById(`devCard_${p}`);
    if (card) {
      if (p === preset) {
        card.classList.add('active');
      } else {
        card.classList.remove('active');
      }
    }
  });
}

// Workers Segmented Button Selection
function setWorkers(n) {
  selectedWorkers = n;
  const group = document.getElementById('workersBtnGroup');
  group.querySelectorAll('.btn-seg').forEach(btn => {
    if (parseInt(btn.getAttribute('data-val')) === n) {
      btn.classList.add('active');
    } else {
      btn.classList.remove('active');
    }
  });
}

// Batch Size Segmented Button Selection
function setBatch(n) {
  selectedBatch = n;
  const group = document.getElementById('batchBtnGroup');
  group.querySelectorAll('.btn-seg').forEach(btn => {
    if (parseInt(btn.getAttribute('data-val')) === n) {
      btn.classList.add('active');
    } else {
      btn.classList.remove('active');
    }
  });
}

// AI Connection Test
async function testAiConn() {
  const btn = document.getElementById('btnTestAi');
  const banner = document.getElementById('aiTestBanner');
  btn.innerHTML = '<span class="animate-spin inline-block">⏳</span> 测试中...';
  btn.disabled = true;

  try {
    const res = await fetch('/api/test_ai');
    const data = await res.json();
    banner.classList.remove('hidden');
    if (data.ok) {
      banner.className = 'text-[11px] p-2 rounded bg-emerald-950/60 border border-emerald-500/40 text-emerald-300 font-mono';
      banner.innerHTML = `🟢 连通正常 (延迟 ${data.latency_ms}ms) | 模型: <strong>${data.model}</strong>`;
    } else {
      banner.className = 'text-[11px] p-2 rounded bg-rose-950/60 border border-rose-500/40 text-rose-300 font-mono';
      banner.innerHTML = `🔴 连接失败: ${data.message}`;
    }
  } catch (err) {
    banner.classList.remove('hidden');
    banner.className = 'text-[11px] p-2 rounded bg-rose-950/60 border border-rose-500/40 text-rose-300 font-mono';
    banner.innerHTML = `🔴 请求异常: ${err.message}`;
  } finally {
    btn.innerHTML = '<span>⚡</span> 测试连通性';
    btn.disabled = false;
  }
}

// Submit Launch Scan
async function submitStartScan(dryRun) {
  const isLoop = document.getElementById('cfgLoop').checked;
  const enableProbe = document.getElementById('cfgProbe').checked;

  const payload = {
    workers: selectedWorkers,
    batch_size: selectedBatch,
    device_preset: selectedDevicePreset,
    is_loop: isLoop,
    is_dry_run: dryRun,
    enable_probe: enableProbe
  };

  try {
    const res = await fetch('/api/scan/start', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    const data = await res.json();
    if (data.ok) {
      closeScanModal();
      document.getElementById('liveScanBanner').classList.remove('hidden');
      loadStats();
    } else {
      alert(`启动失败: ${data.message}`);
    }
  } catch (err) {
    alert(`网络异常: ${err.message}`);
  }
}

// Stop Running Job
async function stopScanJob() {
  if (!confirm('确定要终止当前正在运行的巡检任务吗？')) return;
  try {
    const res = await fetch('/api/scan/stop', { method: 'POST' });
    const data = await res.json();
    alert(data.message || '已发送停止指令');
  } catch (err) {
    alert(`停止请求失败: ${err.message}`);
  }
}

// ==============================================================================
// 5. Live Scan Status Polling & Log Drawer
// ==============================================================================
function startScanStatusPolling() {
  if (scanPollTimer) clearInterval(scanPollTimer);
  scanPollTimer = setInterval(pollScanStatus, 2000);
}

async function pollScanStatus() {
  try {
    const res = await fetch('/api/scan/status');
    const data = await res.json();

    const banner = document.getElementById('liveScanBanner');
    if (data.is_running) {
      banner.classList.remove('hidden');
      document.getElementById('bannerCurrentDomain').innerText = data.stats.current_domain || '调度中...';

      const total = data.stats.total || 1;
      const completed = data.stats.completed || 0;
      const pct = Math.min(100, Math.floor((completed / total) * 100));

      document.getElementById('bannerProgressText').innerText = `${completed} / ${total} (${pct}%)`;
      document.getElementById('bannerProgressBar').style.width = `${pct}%`;
    } else {
      if (!banner.classList.contains('hidden')) {
        banner.classList.add('hidden');
        loadAllData(); // Refresh table & stats upon completion
      }
    }

    // Terminal log streaming
    if (data.logs && data.logs.length > 0) {
      const logBox = document.getElementById('terminalLogContent');
      logBox.innerHTML = data.logs.map(line => `<div>${escapeHtml(line)}</div>`).join('');
      logBox.scrollTop = logBox.scrollHeight;
    }

  } catch (err) {
    // Silent background poll
  }
}

function toggleLogDrawer() {
  const drawer = document.getElementById('logDrawer');
  drawer.classList.toggle('hidden');
}

// ==============================================================================
// 6. Forensic Drawer & Lightbox
// ==============================================================================
async function openDetailDrawer(domain) {
  activeDrawerDomain = domain;
  const drawerBackdrop = document.getElementById('detailDrawerBackdrop');
  drawerBackdrop.classList.remove('hidden');

  document.getElementById('drawerDomain').innerText = domain;
  document.getElementById('drawerUrl').innerText = `https://${domain}`;
  document.getElementById('drawerExplanation').innerText = '正在调取历史研判与取证证据...';
  document.getElementById('drawerScreenshots').innerHTML = '';
  document.getElementById('drawerProbeMeta').innerText = '-';

  try {
    const res = await fetch(`/api/domain/${encodeURIComponent(domain)}`);
    const data = await res.json();
    if (!data || !data.domain) return;

    // Badges
    document.getElementById('drawerRiskLevel').innerText = (data.risk_level || 'pending').toUpperCase();
    document.getElementById('drawerTime').innerText = data.verify_time ? data.verify_time.slice(0, 19) : '未记录';

    if (data.verify_status === 'verified_failed') {
      document.getElementById('drawerBadge').innerHTML = '<span class="text-rose-400 font-bold">🚨 确凿违规异常 (verified_failed)</span>';
    } else if (data.detail && data.detail.is_404) {
      document.getElementById('drawerBadge').innerHTML = '<span class="text-amber-400 font-bold">⚠️ 404失效页面 (保持待研判)</span>';
    } else {
      document.getElementById('drawerBadge').innerHTML = '<span class="text-slate-300 font-medium">⏳ 待研判 (unverified)</span>';
    }

    // Explanation
    let expl = (data.detail && data.detail.explanation) || data.risk_remark || '未见详细文本说明';
    document.getElementById('drawerExplanation').innerText = expl;

    // Screenshots
    const scBox = document.getElementById('drawerScreenshots');
    let scHtml = '';
    const devResults = (data.detail && data.detail.device_results) || {};

    Object.keys(devResults).forEach(devKey => {
      const devObj = devResults[devKey];
      const cap = devObj.capture || {};
      const ai = devObj.ai || {};

      if (cap.screenshot_path) {
        scHtml += `
          <div class="bg-slate-950 p-2.5 rounded-xl border border-slate-800 space-y-2">
            <div class="flex items-center justify-between text-[11px]">
              <span class="font-bold text-slate-200">${cap.device_name || devKey}</span>
              <span class="font-mono text-[10px] text-slate-400">${cap.viewport ? `${cap.viewport.width}x${cap.viewport.height}` : ''}</span>
            </div>
            <img src="/output/${cap.screenshot_path}" onclick="openLightbox('/output/${cap.screenshot_path}', '${domain} (${cap.device_name || devKey})', '${cap.sha256}')" alt="取证截图" class="w-full h-40 object-cover object-top rounded border border-slate-700 cursor-pointer hover:opacity-90 transition">
            <div class="text-[10px] text-slate-400 line-clamp-2">
              <strong>研判:</strong> ${ai.explanation || '正常'}
            </div>
          </div>
        `;
      }
    });

    scBox.innerHTML = scHtml || ((data.detail && data.detail.is_404) ? 
      '<div class="text-amber-400/90 py-4 col-span-2 text-center text-xs p-3 rounded-xl bg-amber-500/10 border border-amber-500/20">⚠️ 该页面为 404 报错失效页面，系统已自动短路跳过无意义的截图与大模型调用，保持待研判。</div>' : 
      '<div class="text-slate-500 py-4 col-span-2 text-center">暂无多端截图存证</div>');

    // Probe meta
    const probe = (data.detail && data.detail.probe) || {};
    document.getElementById('drawerProbeMeta').innerHTML = `
      <div>HTTP 状态: <strong>${probe.http_status || '-'}</strong> | 存活: ${probe.alive ? '🟢 存活' : '🔴 不可达'}</div>
      <div>DNS 解析: <strong>${probe.dns && probe.dns.ip ? probe.dns.ip : '-'}</strong> | SSRF 阻断: ${probe.is_ssrf ? '🚨 触发' : '否'}</div>
      <div>最终访问 URL: ${probe.url || data.url}</div>
    `;

  } catch (err) {
    document.getElementById('drawerExplanation').innerText = `调取失败: ${err.message}`;
  }
}

function closeDetailDrawer() {
  document.getElementById('detailDrawerBackdrop').classList.add('hidden');
}

function triggerDrawerInstantAudit() {
  if (activeDrawerDomain) {
    closeDetailDrawer();
    openInstantAuditModal(activeDrawerDomain);
    executeInstantAudit();
  }
}

// Lightbox
function openLightbox(src, title, sha) {
  document.getElementById('lightboxImg').src = src;
  document.getElementById('lightboxTitle').innerText = title || '取证截图原图';
  document.getElementById('lightboxSha').innerText = sha ? `SHA-256: ${sha.slice(0, 16)}...` : '';
  document.getElementById('lightboxDirectLink').href = src;
  document.getElementById('imageLightboxModal').classList.remove('hidden');
}

function closeLightbox() {
  document.getElementById('imageLightboxModal').classList.add('hidden');
}

// ==============================================================================
// 7. Instant Audit Modal (Single Domain)
// ==============================================================================
function openInstantAuditModal(domain = '') {
  document.getElementById('instantAuditInput').value = domain;
  document.getElementById('instantAuditStatus').classList.add('hidden');
  document.getElementById('instantAuditModal').classList.remove('hidden');
}

function closeInstantAuditModal() {
  document.getElementById('instantAuditModal').classList.add('hidden');
}

async function executeInstantAudit() {
  const domain = document.getElementById('instantAuditInput').value.trim();
  if (!domain) {
    alert('请输入需要研判的域名');
    return;
  }

  const btn = document.getElementById('btnStartInstantAudit');
  const statusBox = document.getElementById('instantAuditStatus');
  const msgBox = document.getElementById('instantAuditStatusMsg');

  btn.disabled = true;
  btn.innerHTML = '<span class="animate-spin">⏳</span> 诊断中 (双端截图中)...';
  statusBox.classList.remove('hidden');
  msgBox.innerHTML = '<span class="text-indigo-400">🚀 正在启动双端 Playwright 仿真渲染与 XiaoAi 视觉多模态研判...</span>';

  try {
    const res = await fetch('/api/audit/single', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ domain: domain, devices: ['desktop_chrome', 'mobile_iphone_safari'] })
    });
    const data = await res.json();

    let resultHtml = '';
    if (data.is_violation) {
      resultHtml = `
        <div class="text-rose-400 font-bold text-sm">🚨 检出确凿违规异常: ${data.primary_violation}</div>
        <div class="text-xs text-slate-300 mt-1">${escapeHtml(data.explanation)}</div>
        <div class="text-[11px] text-rose-300/80 mt-1">处置结果: 已回写数据库 verified_failed (风险等级: ${data.risk_level})</div>
      `;
    } else if (data.is_404) {
      resultHtml = `
        <div class="text-amber-400 font-bold text-sm">⚠️ 页面不存在 (404 报错 / Nginx失效)</div>
        <div class="text-xs text-slate-300 mt-1">${escapeHtml(data.explanation)}</div>
        <div class="text-[11px] text-amber-300/80 mt-1">处置结果: 严格遵循合规审计原则，保持待研判 (unverified / pending)</div>
      `;
    } else {
      resultHtml = `
        <div class="text-emerald-400 font-bold text-sm">⏳ 多端视觉研判未见异常</div>
        <div class="text-xs text-slate-300 mt-1">${escapeHtml(data.explanation)}</div>
        <div class="text-[11px] text-slate-400 mt-1">处置结果: 严格保持待研判记录 (unverified / pending)，绝不误标为安全</div>
      `;
    }

    msgBox.innerHTML = resultHtml;
    loadAllData(); // Refresh table & metrics
  } catch (err) {
    msgBox.innerHTML = `<span class="text-rose-400">诊断出错: ${err.message}</span>`;
  } finally {
    btn.disabled = false;
    btn.innerHTML = '<span>⚡</span> 开始诊断';
  }
}

// Remediation
async function remediateLegacyData() {
  if (!confirm('该操作将把全库历史中被误标为 verified_clean 的记录规范恢复为 unverified (待研判)，确认执行？')) return;
  try {
    const res = await fetch('/api/remediate_legacy', { method: 'POST' });
    const data = await res.json();
    alert(`存量数据规范完成！共恢复待研判记录: ${data.updated} 条`);
    loadAllData();
  } catch (err) {
    alert(`执行失败: ${err.message}`);
  }
}

// Utility
function escapeHtml(str) {
  if (!str) return '';
  return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}
