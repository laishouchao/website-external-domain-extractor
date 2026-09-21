<template>
  <div class="space-y-6">
    <!-- Header & 10-Minute Periodic Verification Ribbon -->
    <div class="flex flex-wrap items-center justify-between gap-4">
      <div>
        <h1 class="text-2xl font-bold text-slate-100 flex items-center gap-2.5">
          <ShieldAlert class="w-6 h-6 text-rose-400" />
          风险页面整改处置工作台
        </h1>
        <p class="text-xs text-slate-400 mt-1">
          实时汇聚所有扫描任务中未修复的涉险页面链接，系统后台每 10 分钟自动轮询复测，支持针对性整改指引与工单流转
        </p>
      </div>

      <div class="flex items-center gap-2">
        <button
          @click="openExportModal"
          class="px-3.5 py-2 bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 rounded-xl text-xs font-medium flex items-center gap-1.5 transition-colors shadow-sm"
        >
          <Download class="w-4 h-4 text-emerald-400" />
          导出整改清单 (CSV)
        </button>
        <button
          @click="store.syncOccurrences"
          :disabled="store.isSyncing"
          class="px-3.5 py-2 bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 rounded-xl text-xs font-medium flex items-center gap-1.5 transition-colors"
          title="从扫描历史提取新存证到整改台"
        >
          <FolderSync class="w-4 h-4 text-indigo-400" :class="{ 'animate-spin': store.isSyncing }" />
          同步存证
        </button>
        <button
          @click="refreshAll"
          class="p-2 bg-slate-900 hover:bg-slate-800 text-slate-400 hover:text-slate-200 border border-slate-800 rounded-xl transition-colors"
          title="刷新数据"
        >
          <RefreshCw class="w-4 h-4" :class="{ 'animate-spin': store.loading }" />
        </button>
      </div>
    </div>

    <!-- 10-Min Timer Automation Status Bar -->
    <div class="bg-gradient-to-r from-slate-900 via-indigo-950/30 to-slate-900 border border-indigo-500/20 rounded-xl p-4 flex flex-wrap items-center justify-between gap-4">
      <div class="flex items-center gap-4">
        <div class="p-2.5 rounded-xl bg-indigo-500/10 border border-indigo-500/20 text-indigo-400">
          <Clock class="w-5 h-5" />
        </div>
        <div>
          <div class="flex items-center gap-2">
            <span class="text-sm font-semibold text-slate-200">10 分钟自动闭环轮询复测</span>
            <span class="px-2 py-0.5 rounded-full text-[11px] font-medium bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 flex items-center gap-1">
              <span class="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse"></span>
              巡检引擎运行中
            </span>
          </div>
          <div class="text-xs text-slate-400 mt-0.5">
            下次自动复测倒计时:
            <span class="font-mono font-bold text-indigo-400">{{ formatCountdown(store.timer.remaining_seconds) }}</span>
            <span class="text-slate-500 ml-2">| 上次复测: {{ store.timer.last_run_time || '刚刚' }}</span>
          </div>
        </div>
      </div>

      <div class="flex items-center gap-2">
        <button
          @click="store.triggerBatchVerify"
          :disabled="store.isTriggeringBatch"
          class="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg text-xs font-semibold flex items-center gap-2 transition-colors shadow-sm"
        >
          <RefreshCw class="w-3.5 h-3.5" :class="{ 'animate-spin': store.isTriggeringBatch }" />
          立即触发全量轮询校验
        </button>
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
    <div class="bg-slate-900 border border-slate-800 rounded-xl p-4 flex flex-wrap items-center justify-between gap-4">
      <div class="flex flex-wrap items-center gap-3">
        <!-- Search Input -->
        <div class="relative w-64">
          <Search class="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
          <input
            v-model="store.filters.search"
            type="text"
            placeholder="搜索页面URL、域名或任务..."
            class="w-full pl-9 pr-3 py-1.5 bg-slate-950 border border-slate-700 rounded-lg text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:border-indigo-500"
            @keyup.enter="handleSearch"
          />
        </div>

        <!-- Task Selector -->
        <select
          v-model="store.filters.taskId"
          class="bg-slate-950 border border-slate-700 text-slate-300 text-sm rounded-lg px-3 py-1.5 focus:outline-none focus:border-indigo-500 max-w-[200px]"
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
          class="bg-slate-950 border border-slate-700 text-slate-300 text-sm rounded-lg px-3 py-1.5 focus:outline-none focus:border-indigo-500"
          @change="handleSearch"
        >
          <option value="">全部风险等级</option>
          <option value="critical">严重风险 (Critical)</option>
          <option value="high">高危风险 (High)</option>
          <option value="medium">中危风险 (Medium)</option>
          <option value="low">低危风险 (Low)</option>
        </select>

        <!-- Verify Status Select -->
        <select
          v-model="store.filters.verifyStatus"
          class="bg-slate-950 border border-slate-700 text-slate-300 text-sm rounded-lg px-3 py-1.5 focus:outline-none focus:border-indigo-500"
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
          class="bg-slate-950 border border-slate-700 text-slate-300 text-sm rounded-lg px-3 py-1.5 focus:outline-none focus:border-indigo-500"
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
          class="px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-200 text-sm font-medium rounded-lg transition-colors"
        >
          筛选
        </button>
        <button
          @click="resetFilters"
          class="px-2.5 py-1.5 text-slate-400 hover:text-slate-200 text-sm transition-colors"
        >
          重置
        </button>
      </div>

      <!-- Batch Action Tools -->
      <div v-if="store.selectedIds.length > 0" class="flex items-center gap-2">
        <span class="text-xs text-slate-400">已选 {{ store.selectedIds.length }} 项:</span>
        <button
          @click="store.batchUpdateStatus('in_progress')"
          class="px-2.5 py-1 bg-amber-500/20 text-amber-300 border border-amber-500/30 hover:bg-amber-500/30 rounded-lg text-xs font-medium transition-colors"
        >
          标为整改中
        </button>
        <button
          @click="store.batchUpdateStatus('resolved')"
          class="px-2.5 py-1 bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 hover:bg-emerald-500/30 rounded-lg text-xs font-medium transition-colors"
        >
          标为已处置
        </button>
        <button
          @click="store.batchUpdateStatus('ignored')"
          class="px-2.5 py-1 bg-slate-800 text-slate-400 hover:text-slate-200 rounded-lg text-xs font-medium transition-colors border border-slate-700"
        >
          忽略
        </button>
      </div>
    </div>

    <!-- Remediation Pages Table -->
    <div class="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden shadow-sm">
      <div class="overflow-x-auto">
        <table class="w-full text-left text-sm text-slate-300">
          <thead class="bg-slate-950/80 text-xs font-semibold uppercase text-slate-400 border-b border-slate-800">
            <tr>
              <th class="p-4 w-10">
                <input
                  type="checkbox"
                  class="rounded bg-slate-900 border-slate-700 text-indigo-600 focus:ring-0 cursor-pointer"
                  :checked="isAllSelected"
                  @change="toggleSelectAll"
                />
              </th>
              <th class="p-4">涉险页面与任务</th>
              <th class="p-4">违规外部域名</th>
              <th class="p-4">风险等级</th>
              <th class="p-4">载体代码存证</th>
              <th class="p-4">10分钟复测状态</th>
              <th class="p-4">工单状态</th>
              <th class="p-4 text-right">操作</th>
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
              <td class="p-4">
                <input
                  type="checkbox"
                  class="rounded bg-slate-900 border-slate-700 text-indigo-600 focus:ring-0 cursor-pointer"
                  :value="item.id"
                  v-model="store.selectedIds"
                />
              </td>
              <td class="p-4">
                <div class="space-y-1">
                  <div class="flex items-center gap-1.5 font-medium text-slate-200">
                    <FileText class="w-3.5 h-3.5 text-slate-400 flex-shrink-0" />
                    <a
                      :href="item.page_url"
                      target="_blank"
                      class="text-indigo-400 hover:underline truncate max-w-md text-xs font-mono"
                    >
                      {{ item.page_url }}
                    </a>
                  </div>
                  <div class="text-[11px] text-slate-500 flex items-center gap-2">
                    <span class="truncate max-w-xs">{{ item.task_name || `任务 #${item.task_id}` }}</span>
                    <span>•</span>
                    <span class="truncate max-w-xs text-slate-400">{{ item.page_title || '无标题' }}</span>
                  </div>
                </div>
              </td>
              <td class="p-4 font-mono text-xs font-medium text-rose-300">
                <div class="flex items-center gap-1">
                  <Globe class="w-3.5 h-3.5 text-rose-400 flex-shrink-0" />
                  <span class="select-all">{{ item.domain }}</span>
                </div>
                <div v-if="item.root_domain" class="text-[10px] text-slate-500 mt-0.5">
                  主根域: {{ item.root_domain }}
                </div>
              </td>
              <td class="p-4">
                <RiskBadge :level="item.risk_level" />
              </td>
              <td class="p-4 max-w-sm">
                <div class="space-y-1">
                  <div class="flex items-center gap-1">
                    <span class="px-1.5 py-0.2 rounded text-[10px] uppercase font-bold font-mono bg-slate-800 text-slate-400 border border-slate-700">
                      {{ item.source_type || 'text' }}
                    </span>
                  </div>
                  <CodeSnippet
                    :code="item.context_snippet || item.raw_match"
                    :highlight-term="item.domain"
                  />
                </div>
              </td>
              <td class="p-4">
                <StatusBadge :status="item.verify_status || 'unverified'" type="verify" />
                <div class="text-[10px] text-slate-500 font-mono mt-1">
                  {{ item.last_verified_at ? item.last_verified_at.split(' ')[1] || item.last_verified_at : '等待轮询' }}
                </div>
              </td>
              <td class="p-4">
                <StatusBadge :status="item.manual_status || 'pending'" type="manual" />
              </td>
              <td class="p-4 text-right">
                <div class="flex items-center justify-end gap-1.5">
                  <!-- One-click test button -->
                  <button
                    @click="store.verifySingle(item.id)"
                    class="p-1.5 text-slate-400 hover:text-emerald-400 hover:bg-slate-800 rounded-lg transition-colors"
                    :disabled="store.verifyingId === item.id"
                    title="立即对此页面执行复测"
                  >
                    <RefreshCw class="w-4 h-4" :class="{ 'animate-spin': store.verifyingId === item.id }" />
                  </button>

                  <!-- Remediation Guide -->
                  <button
                    @click="openGuideDrawer(item)"
                    class="p-1.5 text-slate-400 hover:text-indigo-400 hover:bg-slate-800 rounded-lg transition-colors"
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
      size="lg"
      @update:model-value="guideDrawerOpen = $event"
    >
      <div v-if="activeItem" class="space-y-6">
        <!-- Target Info Box -->
        <div class="bg-slate-950 border border-slate-800 rounded-xl p-4 space-y-2 text-xs">
          <div class="flex items-center justify-between">
            <span class="text-slate-400 font-medium">涉险违规页面:</span>
            <a :href="activeItem.page_url" target="_blank" class="text-indigo-400 hover:underline font-mono truncate max-w-md">
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
  if (!seconds || seconds <= 0) return '00:00'
  const m = Math.floor(seconds / 60)
  const s = seconds % 60
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
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
  // Local decrement countdown timer
  timerInterval = setInterval(() => {
    if (store.timer.remaining_seconds > 0) {
      store.timer.remaining_seconds--
    } else {
      store.loadTimerStatus()
      store.loadPages(store.page)
      store.loadStats()
    }
  }, 1000)
})

onUnmounted(() => {
  if (timerInterval) clearInterval(timerInterval)
})
</script>
