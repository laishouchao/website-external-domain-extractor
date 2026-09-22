<template>
  <div class="space-y-6">
    <!-- Top Back & Breadcrumb -->
    <div class="flex items-center justify-between">
      <div class="flex items-center gap-3">
        <button
          @click="goBack"
          class="p-2 bg-slate-900 border border-slate-800 hover:bg-slate-800 text-slate-300 rounded-xl transition-colors"
          title="返回任务列表"
        >
          <ArrowLeft class="w-4 h-4" />
        </button>
        <div>
          <div class="flex items-center gap-2.5">
            <h1 class="text-xl font-bold text-slate-100 flex items-center gap-2">
              {{ task?.name || '任务工作台' }}
            </h1>
            <StatusBadge v-if="task" :status="task.status" type="task" />
          </div>
          <div class="text-xs text-slate-400 font-mono mt-1 flex items-center gap-2">
            <Globe class="w-3.5 h-3.5 text-slate-500" />
            <a :href="task?.target_url" target="_blank" class="hover:text-indigo-400 hover:underline">
              {{ task?.target_url }}
            </a>
            <span class="text-slate-600">|</span>
            <span>深度: D-{{ task?.max_depth }}</span>
            <span class="text-slate-600">|</span>
            <span>并发: {{ task?.concurrency }}</span>
            <span class="text-slate-600">|</span>
            <span>ID: #{{ taskId }}</span>
          </div>
        </div>
      </div>

      <!-- Action Buttons -->
      <div class="flex items-center gap-2">
        <button
          v-if="task?.status === 'pending' || task?.status === 'stopped' || task?.status === 'failed'"
          @click="start"
          class="px-3 py-1.5 bg-emerald-600 hover:bg-emerald-500 text-white rounded-lg text-xs font-medium flex items-center gap-1.5 transition-colors shadow-sm"
        >
          <Play class="w-3.5 h-3.5 fill-current" />
          启动扫描
        </button>
        <button
          v-if="task?.status === 'running'"
          @click="pause"
          class="px-3 py-1.5 bg-amber-600 hover:bg-amber-500 text-white rounded-lg text-xs font-medium flex items-center gap-1.5 transition-colors shadow-sm"
        >
          <Pause class="w-3.5 h-3.5" />
          暂停
        </button>
        <button
          v-if="task?.status === 'paused'"
          @click="resume"
          class="px-3 py-1.5 bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg text-xs font-medium flex items-center gap-1.5 transition-colors shadow-sm"
        >
          <Play class="w-3.5 h-3.5 fill-current" />
          继续
        </button>
        <button
          v-if="task?.status === 'running' || task?.status === 'paused'"
          @click="stop"
          class="px-3 py-1.5 bg-slate-800 hover:bg-rose-900/40 text-rose-400 border border-slate-700 hover:border-rose-700/50 rounded-lg text-xs font-medium flex items-center gap-1.5 transition-colors"
        >
          <Square class="w-3.5 h-3.5 fill-current" />
          停止
        </button>
        <button
          @click="reloadTask"
          class="p-2 bg-slate-900 hover:bg-slate-800 text-slate-400 hover:text-slate-200 border border-slate-800 rounded-lg transition-colors"
          title="刷新任务数据"
        >
          <RefreshCw class="w-3.5 h-3.5" :class="{ 'animate-spin': loading }" />
        </button>
      </div>
    </div>

    <!-- Progress Ribbon (if running or completed) -->
    <div
      v-if="task"
      class="bg-slate-900 border border-slate-800 rounded-xl p-4 flex flex-wrap items-center justify-between gap-4 shadow-sm"
    >
      <div class="flex items-center gap-6 flex-wrap">
        <div class="space-y-1">
          <div class="text-[11px] text-slate-500">爬取页面进度</div>
          <div class="text-base font-bold font-mono text-slate-200">
            {{ task.pages_crawled ?? task.crawled_pages ?? 0 }} <span class="text-xs text-slate-500">/ {{ task.pages_total ?? ((task.crawled_pages || 0) + (task.pending_pages || 0)) ?? 0 }}</span>
          </div>
        </div>
        <!-- Real-time Speed Metric -->
        <div class="space-y-1 min-w-[120px]">
          <div class="flex items-center gap-1.5 text-[11px] text-slate-500">
            <span>当前扫描速度</span>
            <span
              v-if="task.status === 'running'"
              class="px-1.5 py-0.2 rounded-full text-[10px] bg-emerald-500/20 text-emerald-400 border border-emerald-500/30 animate-pulse font-medium"
            >实时</span>
          </div>
          <div class="text-base font-bold font-mono text-emerald-400 flex items-baseline gap-1">
            <span>{{ task.current_speed ?? task.speed ?? 0 }}</span>
            <span class="text-xs font-normal text-slate-400">{{ task.speed_unit || '页/秒' }}</span>
          </div>
          <div class="text-[10px] font-mono text-slate-500 truncate">
            均速: {{ task.avg_speed || 0 }} {{ task.speed_unit || '页/秒' }}
          </div>
        </div>
        <div class="space-y-1">
          <div class="text-[11px] text-slate-500">提取外部域名</div>
          <div class="text-base font-bold font-mono text-indigo-400">
            {{ task.external_domains_count || 0 }} <span class="text-xs text-slate-500">个</span>
          </div>
        </div>
        <div class="space-y-1">
          <div class="text-[11px] text-slate-500">发现扩展子域名</div>
          <div class="text-base font-bold font-mono text-cyan-400">
            {{ task.subdomains_count || 0 }} <span class="text-xs text-slate-500">个</span>
          </div>
        </div>
        <div class="space-y-1">
          <div class="text-[11px] text-slate-500">爬虫耗时/开始时间</div>
          <div class="text-xs font-mono text-slate-400">
            {{ task.started_at ? (task.started_at.includes('T') ? task.started_at.replace('T', ' ').slice(0, 19) : (task.started_at.split(' ')[1] || task.started_at)) : '尚未开始' }}
          </div>
        </div>
      </div>

      <!-- Linear progress bar -->
      <div class="w-full sm:w-64 space-y-1.5">
        <div class="flex justify-between text-xs font-mono text-slate-400">
          <span>完成度</span>
          <span class="font-bold text-sky-400">{{ progressPercent }}%</span>
        </div>
        <div class="w-full h-2 bg-slate-950 rounded-full overflow-hidden border border-slate-800">
          <div
            class="h-full rounded-full transition-all duration-300"
            :class="task.status === 'running' ? 'bg-gradient-to-r from-sky-500 to-emerald-400 animate-pulse' : 'bg-emerald-500'"
            :style="{ width: progressPercent + '%' }"
          ></div>
        </div>
        <div v-if="task.status === 'running' && task.current_url" class="text-[10px] font-mono text-slate-500 truncate" :title="task.current_url">
          当前: {{ task.current_url }}
        </div>
      </div>
    </div>

    <!-- Sub-tab Navigation Bar -->
    <div class="border-b border-slate-800 flex items-center justify-between">
      <nav class="flex space-x-6 text-sm">
        <button
          v-for="t in tabs"
          :key="t.key"
          @click="activeTab = t.key"
          class="pb-3 relative font-medium transition-colors flex items-center gap-2"
          :class="activeTab === t.key ? 'text-indigo-400' : 'text-slate-400 hover:text-slate-200'"
        >
          <component :is="t.icon" class="w-4 h-4" />
          <span>{{ t.label }}</span>
          <span
            v-if="t.badge !== undefined"
            class="px-1.5 py-0.2 rounded-full text-[11px] font-mono"
            :class="activeTab === t.key ? 'bg-indigo-500/20 text-indigo-300' : 'bg-slate-800 text-slate-400'"
          >
            {{ t.badge }}
          </span>
          <span
            v-if="t.live"
            class="w-2 h-2 rounded-full bg-emerald-400 animate-pulse"
          ></span>

          <!-- Active tab bottom border indicator -->
          <div
            v-if="activeTab === t.key"
            class="absolute bottom-0 left-0 right-0 h-0.5 bg-indigo-500 rounded-t"
          ></div>
        </button>
      </nav>
    </div>

    <!-- Active Tab Component -->
    <div class="pt-2">
      <DomainsTab
        v-if="activeTab === 'domains'"
        :task-id="taskId"
        @updated="reloadTask"
      />
      <SubdomainsTab
        v-else-if="activeTab === 'subdomains'"
        :task-id="taskId"
      />
      <SitemapTab
        v-else-if="activeTab === 'sitemap'"
        :task-id="taskId"
      />
      <LogsTab
        v-else-if="activeTab === 'logs'"
        :task-id="taskId"
      />
      <AnalyticsTab
        v-else-if="activeTab === 'analytics'"
        :task-id="taskId"
      />
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  ArrowLeft, Globe, Play, Pause, Square, RefreshCw,
  Layers, Network, Map, Terminal, BarChart2
} from 'lucide-vue-next'
import { useTasksStore } from '@/stores/tasks'
import client from '@/api/client'
import StatusBadge from '@/components/common/StatusBadge.vue'
import DomainsTab from './tabs/DomainsTab.vue'
import SubdomainsTab from './tabs/SubdomainsTab.vue'
import SitemapTab from './tabs/SitemapTab.vue'
import LogsTab from './tabs/LogsTab.vue'
import AnalyticsTab from './tabs/AnalyticsTab.vue'

const route = useRoute()
const router = useRouter()
const tasksStore = useTasksStore()

const taskId = computed(() => route.params.id)
const activeTab = ref(route.query.tab || 'domains')
const task = ref(null)
const loading = ref(false)

let eventSource = null
let pollTimer = null

const progressPercent = computed(() => {
  if (!task.value) return 0
  const crawled = task.value.pages_crawled ?? task.value.crawled_pages ?? 0
  const total = task.value.pages_total ?? ((task.value.crawled_pages || 0) + (task.value.pending_pages || 0)) ?? 0
  if (total === 0) return task.value.status === 'completed' ? 100 : 0
  return Math.min(100, Math.round((crawled / total) * 100))
})

const tabs = computed(() => [
  { key: 'domains', label: '外部域名', icon: Globe, badge: task.value?.external_domains_count || 0 },
  { key: 'subdomains', label: '发现子域名', icon: Network, badge: task.value?.subdomains_count || 0 },
  { key: 'sitemap', label: '网站地图', icon: Map, badge: (task.value?.pages_crawled ?? task.value?.crawled_pages ?? 0) },
  { key: 'logs', label: '实时日志', icon: Terminal, live: task.value?.status === 'running' },
  { key: 'analytics', label: '统计分析', icon: BarChart2 }
])

const setupRealtimeUpdates = () => {
  cleanupRealtimeUpdates()
  if (!taskId.value) return

  try {
    const url = `/api/tasks/${taskId.value}/events`
    eventSource = new EventSource(url)

    eventSource.onmessage = (event) => {
      try {
        const parsed = JSON.parse(event.data)
        handleStreamEvent(parsed)
      } catch (err) {
        // Comment frames / ping keep-alive
      }
    }

    eventSource.onerror = () => {
      // EventSource reconnects automatically
    }
  } catch (err) {
    console.warn('Failed to initialize SSE EventSource:', err)
  }

  startPolling()
}

const cleanupRealtimeUpdates = () => {
  if (eventSource) {
    eventSource.close()
    eventSource = null
  }
  stopPolling()
}

const startPolling = () => {
  if (pollTimer) return
  pollTimer = setInterval(async () => {
    if (!taskId.value) return
    if (!task.value || task.value.status === 'running') {
      try {
        const updated = await client.get(`/tasks/${taskId.value}`)
        if (task.value) {
          Object.assign(task.value, updated)
        } else {
          task.value = updated
        }
      } catch (e) {
        // Silent fail during background polling
      }
    } else {
      stopPolling()
    }
  }, 2500)
}

const stopPolling = () => {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

const handleStreamEvent = (msg) => {
  const { type, data } = msg || {}
  if (!data) return

  if (type === 'init') {
    if (!task.value) {
      task.value = data
    } else {
      Object.assign(task.value, data)
    }
  } else if (type === 'progress') {
    if (task.value) {
      if (data.pages_crawled !== undefined) task.value.pages_crawled = data.pages_crawled
      if (data.pages_total !== undefined) task.value.pages_total = data.pages_total
      if (data.external_domains_count !== undefined) task.value.external_domains_count = data.external_domains_count
      if (data.subdomains_count !== undefined) task.value.subdomains_count = data.subdomains_count
      if (data.current_url !== undefined) task.value.current_url = data.current_url

      const curSpeed = data.speed !== undefined ? data.speed : (data.current_speed !== undefined ? data.current_speed : 0)
      task.value.current_speed = curSpeed
      task.value.speed = curSpeed
      if (data.avg_speed !== undefined) task.value.avg_speed = data.avg_speed
      if (data.speed_unit) task.value.speed_unit = data.speed_unit
    }
  } else if (type === 'status') {
    if (task.value) {
      task.value.status = data.status
      if (data.status !== 'running') {
        task.value.current_speed = 0
        task.value.speed = 0
      } else {
        startPolling()
      }
    }
  } else if (type === 'complete') {
    if (task.value) {
      task.value.status = data.status || 'completed'
      task.value.current_speed = 0
      task.value.speed = 0
      if (data.avg_speed !== undefined) task.value.avg_speed = data.avg_speed
      if (data.pages_crawled !== undefined) task.value.pages_crawled = data.pages_crawled
      if (data.external_domains_count !== undefined) task.value.external_domains_count = data.external_domains_count
      if (data.subdomains_count !== undefined) task.value.subdomains_count = data.subdomains_count
    }
    cleanupRealtimeUpdates()
  }
}

const reloadTask = async () => {
  loading.value = true
  try {
    task.value = await tasksStore.fetchTask(taskId.value)
    if (task.value?.status === 'running') {
      setupRealtimeUpdates()
    }
  } catch (e) {
    console.error('Failed to load task details:', e)
  } finally {
    loading.value = false
  }
}

const goBack = () => {
  router.push('/tasks')
}

const start = async () => {
  await tasksStore.startTask(taskId.value)
  await reloadTask()
  setupRealtimeUpdates()
}

const pause = async () => {
  await tasksStore.pauseTask(taskId.value)
  await reloadTask()
}

const resume = async () => {
  await tasksStore.resumeTask(taskId.value)
  await reloadTask()
  setupRealtimeUpdates()
}

const stop = async () => {
  await tasksStore.stopTask(taskId.value)
  await reloadTask()
  cleanupRealtimeUpdates()
}

watch(activeTab, (newTab) => {
  router.replace({ query: { ...route.query, tab: newTab } })
})

watch(taskId, (newId) => {
  if (newId) {
    reloadTask()
    setupRealtimeUpdates()
  }
})

onMounted(async () => {
  await reloadTask()
  setupRealtimeUpdates()
})

onUnmounted(() => {
  cleanupRealtimeUpdates()
})
</script>
