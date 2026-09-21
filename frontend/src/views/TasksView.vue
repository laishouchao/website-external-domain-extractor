<template>
  <div class="space-y-6">
    <!-- Header & Search Toolbar -->
    <div class="bg-slate-900 border border-slate-800 rounded-2xl p-4.5 space-y-4 shadow-lg">
      <div class="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <!-- Search & Filter Controls -->
        <div class="flex flex-wrap items-center gap-3 flex-1">
          <div class="relative w-full sm:w-72">
            <input
              v-model="searchQuery"
              placeholder="搜索任务名称或目标域名..."
              class="w-full bg-slate-950 border border-slate-800 rounded-xl pl-8 pr-3 py-2 text-xs text-slate-200 placeholder-slate-500 focus:outline-none focus:border-sky-500"
            />
            <Search class="w-3.5 h-3.5 absolute left-2.5 top-2.5 text-slate-500" />
          </div>

          <select
            v-model="statusFilter"
            class="bg-slate-950 border border-slate-800 rounded-xl px-3 py-2 text-xs text-slate-200 focus:outline-none focus:border-sky-500"
          >
            <option value="">全部任务状态 ({{ tasksStore.tasks.length }})</option>
            <option value="running">正在扫描 ({{ countByStatus('running') }})</option>
            <option value="completed">扫描完成 ({{ countByStatus('completed') }})</option>
            <option value="pending">待扫描 ({{ countByStatus('pending') }})</option>
            <option value="paused">已暂停 ({{ countByStatus('paused') }})</option>
            <option value="stopped">已停止 ({{ countByStatus('stopped') }})</option>
            <option value="failed">失败 ({{ countByStatus('failed') }})</option>
          </select>
        </div>

        <!-- Right Quick Actions -->
        <div class="flex items-center gap-2">
          <button
            @click="tasksStore.loadTasks"
            class="p-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-300 transition border border-slate-700"
            title="刷新列表"
          >
            <RefreshCw class="w-4 h-4" />
          </button>
        </div>
      </div>

      <!-- Batch Actions Bar (Shown when multiple selected) -->
      <div
        v-if="tasksStore.selectedTaskIds.length > 0"
        class="bg-slate-950 p-2.5 rounded-xl border border-sky-900/50 flex flex-wrap items-center justify-between gap-3 text-xs"
      >
        <div class="flex items-center gap-2 text-slate-300">
          <CheckSquare class="w-4 h-4 text-sky-400" />
          <span>已选中 <strong class="text-sky-400 font-mono">{{ tasksStore.selectedTaskIds.length }}</strong> 个扫描任务</span>
        </div>

        <div class="flex flex-wrap items-center gap-2">
          <button
            @click="batchAction('start')"
            class="px-3 py-1 rounded-lg bg-emerald-950 hover:bg-emerald-900 text-emerald-300 border border-emerald-800/80 transition flex items-center gap-1 font-medium"
          >
            <Play class="w-3 h-3" />
            <span>批量启动</span>
          </button>
          <button
            @click="batchAction('pause')"
            class="px-3 py-1 rounded-lg bg-amber-950 hover:bg-amber-900 text-amber-300 border border-amber-800/80 transition flex items-center gap-1 font-medium"
          >
            <Pause class="w-3 h-3" />
            <span>批量暂停</span>
          </button>
          <button
            @click="batchAction('resume')"
            class="px-3 py-1 rounded-lg bg-sky-950 hover:bg-sky-900 text-sky-300 border border-sky-800/80 transition flex items-center gap-1 font-medium"
          >
            <Play class="w-3 h-3" />
            <span>批量恢复</span>
          </button>
          <button
            @click="batchAction('stop')"
            class="px-3 py-1 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 border border-slate-700 transition flex items-center gap-1 font-medium"
          >
            <Square class="w-3 h-3" />
            <span>批量停止</span>
          </button>
          <button
            @click="batchAction('delete')"
            class="px-3 py-1 rounded-lg bg-rose-950 hover:bg-rose-900 text-rose-300 border border-rose-800/80 transition flex items-center gap-1 font-medium"
          >
            <Trash2 class="w-3 h-3" />
            <span>批量删除</span>
          </button>
          <button
            @click="tasksStore.selectedTaskIds = []"
            class="px-2 py-1 rounded text-slate-400 hover:text-slate-200"
          >
            取消选择
          </button>
        </div>
      </div>
    </div>

    <!-- Task Cards / Table View -->
    <div class="bg-slate-900 border border-slate-800 rounded-2xl overflow-hidden shadow-lg">
      <div class="overflow-x-auto min-h-[350px]">
        <table class="w-full text-left text-xs">
          <thead class="bg-slate-950 text-slate-400 border-b border-slate-800 font-semibold whitespace-nowrap sticky top-0">
            <tr>
              <th class="py-3.5 px-4 w-10 text-center">
                <input
                  type="checkbox"
                  :checked="isAllSelected"
                  @change="toggleSelectAll"
                  class="rounded border-slate-700 bg-slate-900 text-sky-500 focus:ring-sky-500"
                />
              </th>
              <th class="py-3.5 px-3 min-w-[240px]">任务名称与目标站点</th>
              <th class="py-3.5 px-3 whitespace-nowrap">扫描状态</th>
              <th class="py-3.5 px-4 min-w-[180px]">爬取进度</th>
              <th class="py-3.5 px-3 text-center whitespace-nowrap">提取外部域名</th>
              <th class="py-3.5 px-3 text-center whitespace-nowrap">发现子域名</th>
              <th class="py-3.5 px-3 whitespace-nowrap">创建时间</th>
              <th class="py-3.5 px-4 text-right whitespace-nowrap">操作与控制</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-slate-800/60 text-slate-300">
            <tr v-if="tasksStore.loading">
              <td colspan="8" class="py-16 text-center text-slate-500">
                <div class="flex items-center justify-center gap-2">
                  <Loader2 class="w-5 h-5 animate-spin text-sky-400" />
                  <span>正在加载扫描任务列表...</span>
                </div>
              </td>
            </tr>
            <tr v-else-if="filteredTasks.length === 0">
              <td colspan="8" class="py-16 text-center text-slate-500">
                <div class="text-3xl mb-2">📋</div>
                <div class="text-slate-300 font-semibold text-sm">暂无匹配的扫描任务</div>
                <div class="text-xs text-slate-500 mt-1">您可以点击右上角「新建扫描」或「批量导入」开启全站深度爬取</div>
              </td>
            </tr>

            <tr
              v-for="task in paginatedTasks"
              :key="task.id"
              :class="tasksStore.selectedTaskIds.includes(task.id) ? 'bg-sky-950/20' : 'hover:bg-slate-800/40'"
              class="transition group"
            >
              <!-- Checkbox -->
              <td class="py-3.5 px-4 text-center">
                <input
                  type="checkbox"
                  :value="task.id"
                  v-model="tasksStore.selectedTaskIds"
                  class="rounded border-slate-700 bg-slate-900 text-sky-500 focus:ring-sky-500"
                />
              </td>

              <!-- Task Name & Target URL -->
              <td class="py-3.5 px-3">
                <div class="space-y-1">
                  <div
                    @click="$router.push(`/tasks/${task.id}`)"
                    class="font-bold text-slate-100 hover:text-sky-400 cursor-pointer flex items-center gap-1.5 transition"
                  >
                    <span class="font-mono text-slate-500 font-normal">#{{ task.id }}</span>
                    <span>{{ task.name }}</span>
                  </div>
                  <div class="font-mono text-[11px] text-slate-400 truncate max-w-sm flex items-center gap-1">
                    <Globe class="w-3 h-3 text-slate-500 inline" />
                    <span>{{ task.target_url }}</span>
                  </div>
                </div>
              </td>

              <!-- Status -->
              <td class="py-3.5 px-3 whitespace-nowrap">
                <StatusBadge :status="task.status" />
              </td>

              <!-- Crawl Progress Bar -->
              <td class="py-3.5 px-4">
                <div class="space-y-1.5">
                  <div class="flex items-center justify-between text-[11px] font-mono">
                    <span class="text-slate-300">{{ task.pages_crawled ?? task.crawled_pages ?? 0 }} / {{ task.pages_total ? `${task.pages_total} 页` : '不限' }}</span>
                    <span class="text-sky-400 font-bold">{{ typeof getProgressPercent(task) === 'number' ? `${getProgressPercent(task)}%` : getProgressPercent(task) }}</span>
                  </div>
                  <div class="w-full h-1.5 bg-slate-950 rounded-full overflow-hidden border border-slate-800">
                    <div
                      class="h-full bg-gradient-to-r from-sky-500 to-indigo-500 transition-all duration-300"
                      :style="{ width: `${typeof getProgressPercent(task) === 'number' ? getProgressPercent(task) : 100}%` }"
                    ></div>
                  </div>
                </div>
              </td>

              <!-- Ext Domains Count -->
              <td class="py-3.5 px-3 text-center whitespace-nowrap font-mono">
                <span class="text-sky-400 font-bold text-sm bg-sky-950/40 px-2 py-0.5 rounded border border-sky-900/60">
                  {{ task.external_domains_count || 0 }}
                </span>
              </td>

              <!-- Subdomains Count -->
              <td class="py-3.5 px-3 text-center whitespace-nowrap font-mono">
                <span class="text-indigo-400 font-bold text-sm bg-indigo-950/40 px-2 py-0.5 rounded border border-indigo-900/60">
                  {{ task.subdomains_count || 0 }}
                </span>
              </td>

              <!-- Created At -->
              <td class="py-3.5 px-3 whitespace-nowrap font-mono text-slate-400 text-[11px]">
                {{ task.created_at || '-' }}
              </td>

              <!-- Actions Column -->
              <td class="py-3.5 px-4 text-right whitespace-nowrap">
                <div class="flex items-center justify-end gap-1.5">
                  <!-- Start / Resume -->
                  <button
                    v-if="task.status === 'pending' || task.status === 'stopped'"
                    @click="tasksStore.startTask(task.id)"
                    class="p-1.5 rounded-lg bg-emerald-950/80 hover:bg-emerald-900 text-emerald-300 border border-emerald-800/60 transition"
                    title="启动扫描"
                  >
                    <Play class="w-3.5 h-3.5" />
                  </button>

                  <button
                    v-if="task.status === 'paused'"
                    @click="tasksStore.resumeTask(task.id)"
                    class="p-1.5 rounded-lg bg-sky-950/80 hover:bg-sky-900 text-sky-300 border border-sky-800/60 transition"
                    title="恢复扫描"
                  >
                    <Play class="w-3.5 h-3.5" />
                  </button>

                  <!-- Pause -->
                  <button
                    v-if="task.status === 'running'"
                    @click="tasksStore.pauseTask(task.id)"
                    class="p-1.5 rounded-lg bg-amber-950/80 hover:bg-amber-900 text-amber-300 border border-amber-800/60 transition"
                    title="暂停扫描"
                  >
                    <Pause class="w-3.5 h-3.5" />
                  </button>

                  <!-- Stop -->
                  <button
                    v-if="task.status === 'running' || task.status === 'paused'"
                    @click="tasksStore.stopTask(task.id)"
                    class="p-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 border border-slate-700 transition"
                    title="停止扫描"
                  >
                    <Square class="w-3.5 h-3.5" />
                  </button>

                  <!-- Retry (if failed) -->
                  <button
                    v-if="task.status === 'failed' || task.status === 'completed'"
                    @click="tasksStore.retryTask(task.id)"
                    class="p-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 border border-slate-700 transition"
                    title="重新扫描"
                  >
                    <RotateCcw class="w-3.5 h-3.5" />
                  </button>

                  <!-- Enter Details Workspace -->
                  <button
                    @click="$router.push(`/tasks/${task.id}`)"
                    class="px-2.5 py-1 rounded-lg bg-sky-600/20 hover:bg-sky-600/30 text-sky-300 border border-sky-500/30 transition flex items-center gap-1 font-medium"
                    title="进入工作台"
                  >
                    <span>详情</span>
                    <ChevronRight class="w-3.5 h-3.5" />
                  </button>

                  <!-- Delete -->
                  <button
                    @click="tasksStore.deleteTask(task.id)"
                    class="p-1.5 rounded-lg bg-slate-800 hover:bg-rose-950 hover:text-rose-400 text-slate-400 border border-slate-700 transition"
                    title="删除任务"
                  >
                    <Trash2 class="w-3.5 h-3.5" />
                  </button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- Pagination -->
      <Pagination
        v-if="filteredTasks.length > 0"
        :current-page="currentPage"
        :total="filteredTasks.length"
        :page-size="pageSize"
        @page-change="currentPage = $event"
      />
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import {
  Search,
  RefreshCw,
  CheckSquare,
  Play,
  Pause,
  Square,
  Trash2,
  RotateCcw,
  ChevronRight,
  Globe,
  Loader2
} from 'lucide-vue-next'
import StatusBadge from '@/components/common/StatusBadge.vue'
import Pagination from '@/components/common/Pagination.vue'
import { useTasksStore } from '@/stores/tasks'

const tasksStore = useTasksStore()
const searchQuery = ref('')
const statusFilter = ref('')
const currentPage = ref(1)
const pageSize = ref(20)

watch([searchQuery, statusFilter], () => {
  currentPage.value = 1
})

const countByStatus = (status) => {
  return tasksStore.tasks.filter(t => t.status === status).length
}

const filteredTasks = computed(() => {
  return tasksStore.tasks.filter(t => {
    if (statusFilter.value && t.status !== statusFilter.value) return false
    if (searchQuery.value.trim()) {
      const q = searchQuery.value.trim().toLowerCase()
      const matchName = (t.name || '').toLowerCase().includes(q)
      const matchUrl = (t.target_url || '').toLowerCase().includes(q)
      if (!matchName && !matchUrl) return false
    }
    return true
  })
})

const paginatedTasks = computed(() => {
  const start = (currentPage.value - 1) * pageSize.value
  return filteredTasks.value.slice(start, start + pageSize.value)
})

const isAllSelected = computed(() => {
  if (filteredTasks.value.length === 0) return false
  return filteredTasks.value.every(t => tasksStore.selectedTaskIds.includes(t.id))
})

const toggleSelectAll = () => {
  if (isAllSelected.value) {
    tasksStore.selectedTaskIds = []
  } else {
    tasksStore.selectedTaskIds = filteredTasks.value.map(t => t.id)
  }
}

const getProgressPercent = (task) => {
  const crawled = task.pages_crawled ?? task.crawled_pages ?? 0
  const total = task.pages_total || 0
  if (total <= 0) return task.status === 'completed' ? 100 : (crawled > 0 ? 100 : 0)
  return Math.min(100, Math.round((crawled / total) * 100))
}

const batchAction = (action) => {
  tasksStore.executeBatchAction(action, tasksStore.selectedTaskIds)
}

onMounted(async () => {
  await tasksStore.loadTasks()
})
</script>
