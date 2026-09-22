<template>
  <div class="space-y-6 w-full min-w-0">
    <!-- Header & 3-Hour Periodic Verification Ribbon -->
    <div class="flex flex-wrap items-center justify-between gap-4">
      <div>
        <h1 class="text-2xl font-bold text-slate-100 flex items-center gap-2.5">
          <ShieldAlert class="w-6 h-6 text-rose-400" />
          风险页面整改处置工作台
        </h1>
        <p class="text-xs text-slate-400 mt-1">
          实时汇聚所有扫描任务中未修复的涉险页面链接，系统后台每 3 小时自动轮询复测，修复后自动移出；每 2 天 15:00 自动进行防回滚复测，支持针对性整改指引与工单流转
        </p>
      </div>

      <div class="flex items-center gap-2">
        <button
          @click="openExportModal"
          class="px-3.5 py-2 bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 rounded-xl text-xs font-medium flex items-center gap-1.5 transition-colors shadow-sm cursor-pointer"
        >
          <Download class="w-4 h-4 text-emerald-400" />
          导出整改清单 (CSV)
        </button>
        <button
          @click="store.syncOccurrences"
          :disabled="store.isSyncing"
          class="px-3.5 py-2 bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 rounded-xl text-xs font-medium flex items-center gap-1.5 transition-colors cursor-pointer"
          title="从扫描历史提取新存证到整改台"
        >
          <FolderSync class="w-4 h-4 text-indigo-400" :class="{ 'animate-spin': store.isSyncing }" />
          同步存证
        </button>
        <button
          @click="refreshAll"
          class="p-2 bg-slate-900 hover:bg-slate-800 text-slate-400 hover:text-slate-200 border border-slate-800 rounded-xl transition-colors cursor-pointer"
          title="刷新数据"
        >
          <RefreshCw class="w-4 h-4" :class="{ 'animate-spin': store.loading }" />
        </button>
      </div>
    </div>

    <!-- 3-Hour Timer Automation Status Bar with Real-time Progress & Rollback Info -->
    <div class="bg-gradient-to-r from-slate-900 via-indigo-950/30 to-slate-900 border border-indigo-500/20 rounded-xl p-4 space-y-3.5 shadow-sm">
      <div class="flex flex-wrap items-center justify-between gap-4">
        <div class="flex items-center gap-3.5">
          <div class="p-2.5 rounded-xl bg-indigo-500/10 border border-indigo-500/20 text-indigo-400 shrink-0">
            <Clock class="w-5 h-5" />
          </div>
          <div>
            <div class="flex items-center gap-2 flex-wrap">
              <span class="text-sm font-semibold text-slate-200">3 小时自动闭环轮询复测</span>
              <span
                v-if="store.timer.is_checking"
                class="px-2 py-0.5 rounded-full text-[11px] font-medium bg-amber-500/10 text-amber-400 border border-amber-500/20 flex items-center gap-1"
              >
                <RefreshCw class="w-3 h-3 animate-spin text-amber-400" />
                {{ store.timer.current_progress?.check_type === 'rollback' ? '防回滚复测执行中...' : '自动复测执行中...' }}
              </span>
              <span
                v-else
                class="px-2 py-0.5 rounded-full text-[11px] font-medium bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 flex items-center gap-1"
              >
                <span class="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse"></span>
                巡检引擎运行中
              </span>
            </div>
            <div class="text-xs text-slate-400 mt-0.5 flex items-center gap-3 flex-wrap">
              <span v-if="store.timer.is_checking" class="text-amber-300 font-medium">
                本次复测进行中，结束后 3 小时启动下次自动复测
              </span>
              <span v-else>
                下次复测倒计时:
                <span class="font-mono font-bold text-indigo-400">{{ formatCountdown(store.timer.remaining_seconds) }}</span>
              </span>
              <span class="text-slate-500">|</span>
              <span>上次复测: {{ store.timer.last_run_time || '刚刚' }}</span>
              <span class="text-slate-500">|</span>
              <span class="text-slate-400" :title="`上次检测: ${store.timer.rollback_audit?.last_audit_time || '尚未运行'}`">
                防回滚再测试计划: <strong class="text-purple-300 font-normal">每2天 15:00</strong>
                <span class="text-slate-500 ml-1">(下次: {{ store.timer.rollback_audit?.next_audit_time ? store.timer.rollback_audit.next_audit_time.split(' ')[0] + ' 15:00' : '已排期' }})</span>
              </span>
            </div>
          </div>
        </div>

        <div class="flex items-center gap-2 shrink-0">
          <button
            @click="store.triggerBatchVerify"
            :disabled="store.isTriggeringBatch || store.timer.is_checking"
            class="px-3.5 py-2 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white rounded-lg text-xs font-semibold flex items-center gap-1.5 transition-colors shadow-sm cursor-pointer"
            title="立即对所有待复测及残留记录重新发起 HTTP 请求校验"
          >
            <RefreshCw class="w-3.5 h-3.5" :class="{ 'animate-spin': store.isTriggeringBatch || (store.timer.is_checking && store.timer.current_progress?.check_type === 'regular') }" />
            立即轮询待复测
          </button>
          <button
            @click="store.triggerRollbackAudit"
            :disabled="store.isTriggeringRollback || store.timer.is_checking"
            class="px-3.5 py-2 bg-purple-700/80 hover:bg-purple-600 border border-purple-500/30 disabled:opacity-50 text-purple-100 rounded-lg text-xs font-semibold flex items-center gap-1.5 transition-colors shadow-sm cursor-pointer"
            title="对所有标记为已修复/已清除的记录做再测试，检测是否被回滚"
          >
            <ShieldAlert class="w-3.5 h-3.5" :class="{ 'animate-pulse': store.timer.is_checking && store.timer.current_progress?.check_type === 'rollback' }" />
            触发防回滚再测试
          </button>
        </div>
      </div>

      <!-- Live Progress Bar & Proportions (During Active Checking) -->
      <div v-if="store.timer.is_checking && store.timer.current_progress" class="bg-slate-950/80 border border-slate-800 rounded-lg p-3 space-y-2">
        <div class="flex items-center justify-between text-xs flex-wrap gap-2">
          <div class="flex items-center gap-2">
            <span class="font-semibold text-slate-200">
              {{ store.timer.current_progress.check_type === 'rollback' ? '【防回滚复测】正在复核已修复记录' : '【常规复测】正在轮询涉险页面' }}
            </span>
            <span class="font-mono text-indigo-400 font-bold">
              {{ store.timer.current_progress.current || 0 }} / {{ store.timer.current_progress.total || 0 }}
            </span>
            <span class="text-slate-500 text-[11px]">({{ store.timer.current_progress.percentage || 0 }}%)</span>
          </div>

          <!-- Proportion breakdown -->
          <div class="flex items-center gap-4 text-xs font-medium">
            <div class="flex items-center gap-1.5 text-emerald-400">
              <span class="w-2 h-2 rounded-full bg-emerald-400"></span>
              <span>已修复清除: <strong>{{ (store.timer.current_progress.cleaned_count || 0) + (store.timer.current_progress.removed_count || 0) }}</strong></span>
              <span class="text-[11px] font-mono opacity-80">({{ store.timer.current_progress.cleaned_ratio || 0 }}%)</span>
            </div>
            <div class="flex items-center gap-1.5 text-rose-400">
              <span class="w-2 h-2 rounded-full bg-rose-400"></span>
              <span>未修复仍存留: <strong>{{ store.timer.current_progress.failed_count || 0 }}</strong></span>
              <span class="text-[11px] font-mono opacity-80">({{ store.timer.current_progress.failed_ratio || 0 }}%)</span>
            </div>
            <div v-if="store.timer.current_progress.error_count" class="flex items-center gap-1 text-slate-400 text-[11px]">
              <span>超时/异常: {{ store.timer.current_progress.error_count }}</span>
            </div>
          </div>
        </div>

        <!-- Visual Progress Bar with dual-proportion fill -->
        <div class="w-full h-2.5 bg-slate-900 rounded-full overflow-hidden flex border border-slate-800">
          <div
            class="bg-gradient-to-r from-emerald-500 to-teal-400 transition-all duration-300"
            :style="{ width: `${(store.timer.current_progress.cleaned_ratio || 0) * ((store.timer.current_progress.percentage || 0) / 100)}%` }"
            title="已修复清除比例"
          ></div>
          <div
            class="bg-gradient-to-r from-rose-500 to-red-500 transition-all duration-300"
            :style="{ width: `${(store.timer.current_progress.failed_ratio || 0) * ((store.timer.current_progress.percentage || 0) / 100)}%` }"
            title="未修复仍存留比例"
          ></div>
        </div>
      </div>

      <!-- Compact Summary of Last Run (When Idle) -->
      <div v-else-if="store.timer.last_run_stats && store.timer.last_run_stats.total_tested > 0" class="bg-slate-950/40 border border-slate-800/80 rounded-lg px-3 py-2 text-xs text-slate-400 flex flex-wrap items-center justify-between gap-2">
        <div class="flex items-center gap-3">
          <span>最近一次完成复测: <strong class="text-slate-200">{{ store.timer.last_run_stats.total_tested }}</strong> 个页面</span>
          <span class="text-emerald-400">已修复: {{ (store.timer.last_run_stats.cleaned_count || 0) + (store.timer.last_run_stats.removed_count || 0) }} 处 ({{ Math.round((((store.timer.last_run_stats.cleaned_count || 0) + (store.timer.last_run_stats.removed_count || 0)) / store.timer.last_run_stats.total_tested) * 100) }}%)</span>
          <span class="text-rose-400">仍残留未修复: {{ store.timer.last_run_stats.failed_count || 0 }} 处 ({{ Math.round(((store.timer.last_run_stats.failed_count || 0) / store.timer.last_run_stats.total_tested) * 100) }}%)</span>
        </div>
        <div class="text-[11px] text-slate-500">
          复测耗时: {{ store.timer.last_run_stats.duration_seconds }}s | 完成于: {{ store.timer.last_run_stats.finished_at || store.timer.last_run_time }}
        </div>
      </div>
    </div>

    <!-- 4 Key Metric Cards -->
    <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
      <MetricCard
        title="待闭环风险页面"
        :value="store.stats.pending_count || 0"
        subtitle="仍存在违规残留或未复测"
        icon="AlertCircle"
        color="rose"
      />
      <MetricCard
        title="复测仍有残留"
        :value="store.stats.failed_count || 0"
        subtitle="自动访问页面仍检出外链"
        icon="ShieldAlert"
        color="amber"
      />
      <MetricCard
        title="已彻底清除整改"
        :value="store.stats.clean_count || 0"
        subtitle="外链已删除或页面已下线"
        icon="CheckCircle2"
        color="emerald"
      />
      <MetricCard
        title="涉及扫描任务"
        :value="store.stats.tasks_affected || 0"
        subtitle="包含未修复页面的任务总数"
        icon="Briefcase"
        color="indigo"
      />
    </div>

    <!-- Filter and Batch Operations Bar -->
    <div class="bg-slate-900 border border-slate-800 rounded-xl p-4 flex flex-col md:flex-row md:items-center justify-between gap-3">
      <div class="flex flex-wrap items-center gap-2.5">
        <!-- Search Input -->
        <div class="relative w-56 sm:w-64">
          <Search class="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
          <input
            v-model="store.filters.search"
            type="text"
            placeholder="搜索URL、域名或任务..."
            class="w-full pl-9 pr-3 py-1.5 bg-slate-950 border border-slate-700 rounded-lg text-xs text-slate-200 placeholder-slate-500 focus:outline-none focus:border-indigo-500"
            @keyup.enter="handleSearch"
          />
        </div>

        <!-- Task Selector -->
        <select
          v-model="store.filters.taskId"
          class="bg-slate-950 border border-slate-700 text-slate-300 text-xs rounded-lg px-2.5 py-1.5 focus:outline-none focus:border-indigo-500 max-w-[180px] truncate"
          @change="handleSearch"
        >
          <option value="">全部扫描任务</option>
          <option
            v-for="t in store.stats.task_summary"
            :key="t.task_id"
            :value="t.task_id"
          >
            {{ t.task_name || `任务 #${t.task_id}` }} ({{ t.pending_count }})
          </option>
        </select>

        <!-- Risk Level Select -->
        <select
          v-model="store.filters.riskLevel"
          class="bg-slate-950 border border-slate-700 text-slate-300 text-xs rounded-lg px-2.5 py-1.5 focus:outline-none focus:border-indigo-500"
          @change="handleSearch"
        >
          <option value="">全部风险等级</option>
          <option value="critical">严重 (Critical)</option>
          <option value="high">高危 (High)</option>
          <option value="medium">中危 (Medium)</option>
          <option value="low">低危 (Low)</option>
        </select>

        <!-- Verify Status Select -->
        <select
          v-model="store.filters.verifyStatus"
          class="bg-slate-950 border border-slate-700 text-slate-300 text-xs rounded-lg px-2.5 py-1.5 focus:outline-none focus:border-indigo-500"
          @change="handleSearch"
        >
          <option value="pending_only">待闭环处置 (未复测+残留)</option>
          <option value="">全部复测状态</option>
          <option value="unverified">未复测</option>
          <option value="verified_failed">仍有残留</option>
          <option value="verified_clean">已彻底清除</option>
          <option value="page_removed">页面已下线</option>
          <option value="error">复测访问异常</option>
        </select>

        <!-- Manual Status Select -->
        <select
          v-model="store.filters.manualStatus"
          class="bg-slate-950 border border-slate-700 text-slate-300 text-xs rounded-lg px-2.5 py-1.5 focus:outline-none focus:border-indigo-500"
          @change="handleSearch"
        >
          <option value="">全部工单状态</option>
          <option value="pending">待处理</option>
          <option value="in_progress">整改中</option>
          <option value="resolved">已修复待复测</option>
          <option value="ignored">忽略/免修</option>
        </select>

        <button
          @click="handleSearch"
          class="px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-medium rounded-lg transition-colors cursor-pointer"
        >
          筛选
        </button>
        <button
          @click="resetFilters"
          class="px-2 py-1.5 text-slate-400 hover:text-slate-200 text-xs transition-colors cursor-pointer"
        >
          重置
        </button>
      </div>

      <!-- Batch Action Tools -->
      <div v-if="store.selectedIds.length > 0" class="flex items-center gap-2 flex-shrink-0">
        <span class="text-xs text-slate-400">已选 {{ store.selectedIds.length }} 项:</span>
        <button
          @click="store.batchUpdateStatus('in_progress')"
          class="px-2.5 py-1 bg-amber-500/20 text-amber-300 border border-amber-500/30 hover:bg-amber-500/30 rounded-lg text-xs font-medium transition-colors cursor-pointer"
        >
          标为整改中
        </button>
        <button
          @click="store.batchUpdateStatus('resolved')"
          class="px-2.5 py-1 bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 hover:bg-emerald-500/30 rounded-lg text-xs font-medium transition-colors cursor-pointer"
        >
          标为已处置
        </button>
        <button
          @click="store.batchUpdateStatus('ignored')"
          class="px-2.5 py-1 bg-slate-800 text-slate-400 hover:text-slate-200 rounded-lg text-xs font-medium transition-colors border border-slate-700 cursor-pointer"
        >
          忽略
        </button>
      </div>
    </div>

    <!-- Remediation Pages Table -->
    <div class="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden shadow-sm">
      <div class="overflow-x-auto">
        <table class="w-full min-w-[920px] lg:min-w-0 table-fixed text-left text-sm text-slate-300">
          <thead class="bg-slate-950/80 text-xs font-semibold uppercase text-slate-400 border-b border-slate-800">
            <tr>
              <th class="p-3.5 w-10 text-center">
                <input
                  type="checkbox"
                  class="rounded bg-slate-900 border-slate-700 text-indigo-600 focus:ring-0 cursor-pointer"
                  :checked="isAllSelected"
                  @change="toggleSelectAll"
                />
              </th>
              <th class="p-3.5 w-[26%]">涉险页面与任务</th>
              <th class="p-3.5 w-[15%]">违规外部域名</th>
              <th class="p-3.5 w-[10%] text-center">风险等级</th>
              <th class="p-3.5 w-[26%]">载体代码存证</th>
              <th class="p-3.5 w-[10%] text-center">复测状态</th>
              <th class="p-3.5 w-[8%] text-center">工单状态</th>
              <th class="p-3.5 w-[5%] min-w-[72px] text-right">操作</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-slate-800/60 font-normal">
            <tr v-if="store.loading" class="text-center py-8">
              <td colspan="8" class="p-8 text-slate-500">
                <div class="flex items-center justify-center gap-2">
                  <Loader2 class="w-5 h-5 animate-spin text-indigo-400" />
                  <span>加载风险待处置页面数据...</span>
                </div>
              </td>
            </tr>
            <tr v-else-if="store.pages.length === 0" class="text-center py-8">
              <td colspan="8" class="p-8 text-slate-500">
                <div class="py-6 space-y-2">
                  <CheckCircle2 class="w-10 h-10 text-emerald-400 mx-auto opacity-70" />
                  <p class="text-slate-400 font-medium">太棒了！当前没有任何未修复的风险页面</p>
                  <p class="text-xs text-slate-500">所有扫描任务检出的违规外链均已彻底清除或页面已下线</p>
                </div>
              </td>
            </tr>
            <tr
              v-for="item in store.pages"
              :key="item.id"
              class="hover:bg-slate-800/40 transition-colors"
            >
              <td class="p-3.5 text-center">
                <input
                  type="checkbox"
                  class="rounded bg-slate-900 border-slate-700 text-indigo-600 focus:ring-0 cursor-pointer"
                  :value="item.id"
                  v-model="store.selectedIds"
                />
              </td>
              <td class="p-3.5">
                <div class="space-y-1 min-w-0">
                  <div class="flex items-start gap-1.5 font-medium text-slate-200">
                    <FileText class="w-3.5 h-3.5 text-slate-400 flex-shrink-0 mt-0.5" />
                    <a
                      :href="item.page_url"
                      target="_blank"
                      class="text-indigo-400 hover:text-indigo-300 hover:underline text-xs font-mono break-all line-clamp-2 leading-relaxed"
                      :title="item.page_url"
                    >
                      {{ item.page_url }}
                    </a>
                  </div>
                  <div class="text-[11px] text-slate-500 flex flex-wrap items-center gap-1.5 pl-5">
                    <span class="truncate max-w-[140px] text-slate-400 font-medium" :title="item.task_name || `任务 #${item.task_id}`">
                      {{ item.task_name || `任务 #${item.task_id}` }}
                    </span>
                    <span v-if="item.page_title" class="text-slate-600">•</span>
                    <span v-if="item.page_title" class="truncate max-w-[140px] text-slate-400" :title="item.page_title">
                      {{ item.page_title }}
                    </span>
                  </div>
                </div>
              </td>
              <td class="p-3.5">
                <div class="space-y-0.5 min-w-0">
                  <div class="flex items-start gap-1 font-mono text-xs font-medium text-rose-300">
                    <Globe class="w-3.5 h-3.5 text-rose-400 flex-shrink-0 mt-0.5" />
                    <span class="select-all break-all leading-snug">{{ item.domain }}</span>
                  </div>
                  <div v-if="item.root_domain" class="text-[10px] text-slate-500 font-mono truncate pl-4.5" :title="item.root_domain">
                    根域: {{ item.root_domain }}
                  </div>
                </div>
              </td>
              <td class="p-3.5 text-center">
                <div class="flex justify-center">
                  <RiskBadge :level="item.risk_level" />
                </div>
              </td>
              <td class="p-3.5">
                <div class="space-y-1 min-w-0">
                  <div class="flex items-center gap-1">
                    <span class="px-1.5 py-0.2 rounded text-[10px] uppercase font-bold font-mono bg-slate-800 text-slate-400 border border-slate-700">
                      {{ item.source_type || 'text' }}
                    </span>
                  </div>
                  <CodeSnippet
                    :code="item.context_snippet || item.raw_match"
                    :highlight-term="item.domain"
                    max-height="max-h-24"
                  />
                </div>
              </td>
              <td class="p-3.5 text-center">
                <div class="flex flex-col items-center">
                  <StatusBadge :status="item.verify_status || 'unverified'" type="verify" />
                  <div class="text-[10px] text-slate-500 font-mono mt-1 whitespace-nowrap">
                    {{ item.last_verified_at ? item.last_verified_at.split(' ')[1] || item.last_verified_at : '等待轮询' }}
                  </div>
                </div>
              </td>
              <td class="p-3.5 text-center">
                <div class="flex justify-center">
                  <StatusBadge :status="item.manual_status || 'pending'" type="manual" />
                </div>
              </td>
              <td class="p-3.5 text-right">
                <div class="flex items-center justify-end gap-1">
                  <!-- One-click test button -->
                  <button
                    @click="store.verifySingle(item.id)"
                    class="p-1.5 text-slate-400 hover:text-emerald-400 hover:bg-slate-800 rounded-lg transition-colors cursor-pointer"
                    :disabled="store.verifyingId === item.id"
                    title="立即对此页面执行复测"
                  >
                    <RefreshCw class="w-4 h-4" :class="{ 'animate-spin': store.verifyingId === item.id }" />
                  </button>

                  <!-- Remediation Guide -->
                  <button
                    @click="openGuideDrawer(item)"
                    class="p-1.5 text-slate-400 hover:text-indigo-400 hover:bg-slate-800 rounded-lg transition-colors cursor-pointer"
                    title="查看整改操作建议与指南"
                  >
                    <BookOpen class="w-4 h-4" />
                  </button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- Pagination -->
      <Pagination
        :current-page="store.page"
        :total="store.total"
        :page-size="store.pageSize"
        @page-change="onPageChange"
      />
    </div>

    <!-- Remediation Guide Drawer -->
    <Drawer
      :model-value="guideDrawerOpen"
      title="涉险页面整改指引与修复方案"
      size="xl"
      @update:model-value="guideDrawerOpen = $event"
    >
      <div v-if="activeItem" class="space-y-6">
        <!-- Target Info Box -->
        <div class="bg-slate-950 border border-slate-800 rounded-xl p-4 space-y-2 text-xs">
          <div class="flex items-center justify-between gap-3">
            <span class="text-slate-400 font-medium flex-shrink-0">涉险违规页面:</span>
            <a :href="activeItem.page_url" target="_blank" class="text-indigo-400 hover:underline font-mono truncate flex-1 text-right ml-2" :title="activeItem.page_url">
              {{ activeItem.page_url }}
            </a>
          </div>
          <div class="flex items-center justify-between">
            <span class="text-slate-400 font-medium">违规外部域名:</span>
            <span class="text-rose-400 font-mono font-bold">{{ activeItem.domain }}</span>
          </div>
          <div class="flex items-center justify-between">
            <span class="text-slate-400 font-medium">代码引用属性:</span>
            <span class="font-mono uppercase text-slate-300">{{ activeItem.source_type }}</span>
          </div>
        </div>

        <!-- Professional Step-by-Step Remediation Guide -->
        <div class="space-y-3">
          <h4 class="text-sm font-semibold text-slate-200 flex items-center gap-2">
            <Wrench class="w-4 h-4 text-amber-400" />
            技术人员操作指引
          </h4>
          <div class="bg-slate-950 border border-slate-800 rounded-xl p-4 whitespace-pre-wrap font-mono text-xs leading-relaxed text-slate-300">
{{ activeItem.remediation_guide }}
          </div>
        </div>

        <!-- Code Snippet Box -->
        <div class="space-y-2">
          <h4 class="text-sm font-semibold text-slate-200 flex items-center gap-2">
            <Code2 class="w-4 h-4 text-indigo-400" />
            涉险代码上下文切片
          </h4>
          <CodeSnippet
            :code="activeItem.context_snippet || activeItem.raw_match"
            :highlight-term="activeItem.domain"
          />
        </div>

        <!-- Actions -->
        <div class="pt-4 border-t border-slate-800 flex items-center justify-between">
          <div class="flex items-center gap-2">
            <button
              @click="markStatus(activeItem.id, 'resolved')"
              class="px-3 py-1.5 bg-emerald-600 hover:bg-emerald-500 text-white rounded-lg text-xs font-medium transition-colors"
            >
              标为已整改
            </button>
            <button
              @click="markStatus(activeItem.id, 'in_progress')"
              class="px-3 py-1.5 bg-amber-600 hover:bg-amber-500 text-white rounded-lg text-xs font-medium transition-colors"
            >
              标为整改中
            </button>
          </div>

          <button
            @click="testActiveItem(activeItem.id)"
            class="px-4 py-1.5 bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg text-xs font-semibold flex items-center gap-1.5 transition-colors"
            :disabled="store.verifyingId === activeItem.id"
          >
            <RefreshCw class="w-3.5 h-3.5" :class="{ 'animate-spin': store.verifyingId === activeItem.id }" />
            立即复测该页面
          </button>
        </div>
      </div>
    </Drawer>

    <!-- Export Modal -->
    <Modal
      :model-value="exportModalOpen"
      title="导出风险页面整改清单 (CSV)"
      @update:model-value="exportModalOpen = $event"
    >
      <form @submit.prevent="executeExport" class="space-y-4">
        <div>
          <label class="block text-xs font-medium text-slate-400 mb-1">限定扫描任务 (可选)</label>
          <select
            v-model="exportForm.taskId"
            class="w-full px-3 py-2 bg-slate-950 border border-slate-700 rounded-lg text-sm text-slate-200 focus:outline-none focus:border-indigo-500"
          >
            <option value="">全部扫描任务</option>
            <option
              v-for="t in store.stats.task_summary"
              :key="t.task_id"
              :value="t.task_id"
            >
              {{ t.task_name || `任务 #${t.task_id}` }}
            </option>
          </select>
        </div>

        <div>
          <label class="block text-xs font-medium text-slate-400 mb-1">状态范围</label>
          <select
            v-model="exportForm.verifyStatus"
            class="w-full px-3 py-2 bg-slate-950 border border-slate-700 rounded-lg text-sm text-slate-200 focus:outline-none focus:border-indigo-500"
          >
            <option value="pending_only">仅导出当前未闭环 (未复测 + 残留)</option>
            <option value="all">导出全部历史处置记录</option>
            <option value="verified_failed">仅导出明确仍有残留的页面</option>
          </select>
        </div>

        <div class="flex justify-end gap-2 pt-4 border-t border-slate-800">
          <button
            type="button"
            @click="exportModalOpen = false"
            class="px-4 py-2 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-lg text-sm"
          >
            取消
          </button>
          <button
            type="submit"
            class="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg text-sm font-medium flex items-center gap-1.5"
          >
            <Download class="w-4 h-4" />
            开始导出下载
          </button>
        </div>
      </form>
    </Modal>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import {
  ShieldAlert, Clock, AlertCircle, CheckCircle2, Briefcase, Download,
  FolderSync, RefreshCw, Search, FileText, Globe, BookOpen, Wrench, Code2, Loader2
} from 'lucide-vue-next'
import { useRemediationStore } from '@/stores/remediation'
import MetricCard from '@/components/common/MetricCard.vue'
import RiskBadge from '@/components/common/RiskBadge.vue'
import StatusBadge from '@/components/common/StatusBadge.vue'
import Pagination from '@/components/common/Pagination.vue'
import Drawer from '@/components/common/Drawer.vue'
import Modal from '@/components/common/Modal.vue'
import CodeSnippet from '@/components/common/CodeSnippet.vue'

const store = useRemediationStore()

const guideDrawerOpen = ref(false)
const activeItem = ref(null)

const exportModalOpen = ref(false)
const exportForm = ref({
  taskId: '',
  verifyStatus: 'pending_only'
})

let timerInterval = null

const isAllSelected = computed(() => {
  return store.pages.length > 0 && store.selectedIds.length === store.pages.length
})

const toggleSelectAll = (e) => {
  if (e.target.checked) {
    store.selectedIds = store.pages.map(p => p.id)
  } else {
    store.selectedIds = []
  }
}

const formatCountdown = (seconds) => {
  if (!seconds || seconds <= 0) return '00:00:00'
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  const s = seconds % 60
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
}

const handleSearch = () => {
  store.loadPages(1)
}

const resetFilters = () => {
  store.filters.taskId = ''
  store.filters.riskLevel = ''
  store.filters.verifyStatus = 'pending_only'
  store.filters.manualStatus = ''
  store.filters.search = ''
  store.loadPages(1)
}

const onPageChange = (p) => {
  store.loadPages(p)
}

const refreshAll = async () => {
  await Promise.all([
    store.loadStats(),
    store.loadTimerStatus(),
    store.loadPages(store.page)
  ])
}

const openGuideDrawer = (item) => {
  activeItem.value = item
  guideDrawerOpen.value = true
}

const markStatus = async (id, status) => {
  store.selectedIds = [id]
  await store.batchUpdateStatus(status)
  if (activeItem.value) activeItem.value.manual_status = status
}

const testActiveItem = async (id) => {
  await store.verifySingle(id)
  const updated = store.pages.find(p => p.id === id)
  if (updated) {
    activeItem.value = { ...activeItem.value, ...updated }
  }
}

const openExportModal = () => {
  exportForm.value = {
    taskId: store.filters.taskId || '',
    verifyStatus: store.filters.verifyStatus || 'pending_only'
  }
  exportModalOpen.value = true
}

const executeExport = () => {
  const params = new URLSearchParams()
  if (exportForm.value.taskId) params.append('task_id', exportForm.value.taskId)
  if (exportForm.value.verifyStatus) params.append('verify_status', exportForm.value.verifyStatus)
  window.open(`/api/risk-remediation/export?${params.toString()}`, '_blank')
  exportModalOpen.value = false
}

onMounted(() => {
  refreshAll()
  // Local decrement countdown timer & dynamic polling during verification
  let checkingPollCounter = 0
  timerInterval = setInterval(async () => {
    if (store.timer.is_checking) {
      checkingPollCounter++
      // poll status every 1.5-2 seconds while checking
      if (checkingPollCounter % 2 === 0) {
        await store.loadTimerStatus()
        if (!store.timer.is_checking) {
          // Finished cycle!
          await Promise.all([store.loadPages(store.page), store.loadStats()])
        }
      }
    } else {
      checkingPollCounter = 0
      if (store.timer.remaining_seconds > 0) {
        store.timer.remaining_seconds--
      } else {
        await store.loadTimerStatus()
        await Promise.all([store.loadPages(store.page), store.loadStats()])
      }
    }
  }, 1000)
})

onUnmounted(() => {
  if (timerInterval) clearInterval(timerInterval)
})
</script>
