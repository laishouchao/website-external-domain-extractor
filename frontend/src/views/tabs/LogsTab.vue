<template>
  <div class="space-y-4">
    <!-- Log Controls Bar -->
    <div class="bg-slate-900 border border-slate-800 rounded-xl p-4 flex flex-wrap items-center justify-between gap-4">
      <div class="flex items-center gap-3">
        <!-- Live Connection Status -->
        <div class="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-slate-950 border border-slate-800 text-xs">
          <span
            class="w-2 h-2 rounded-full"
            :class="connected ? 'bg-emerald-400 animate-pulse' : 'bg-slate-500'"
          ></span>
          <span :class="connected ? 'text-emerald-300 font-medium' : 'text-slate-400'">
            {{ connected ? 'SSE 实时推送中' : '日志连接已断开/就绪' }}
          </span>
        </div>

        <!-- Level Filter -->
        <select
          v-model="selectedLevel"
          class="bg-slate-950 border border-slate-700 text-slate-300 text-xs rounded-lg px-3 py-1.5 focus:outline-none focus:border-indigo-500"
        >
          <option value="">全部日志级别 (ALL)</option>
          <option value="INFO">INFO (信息)</option>
          <option value="WARN">WARN (警告)</option>
          <option value="ERROR">ERROR (错误)</option>
          <option value="PROGRESS">PROGRESS (进度)</option>
        </select>
      </div>

      <div class="flex items-center gap-3">
        <!-- Auto-scroll checkbox -->
        <label class="flex items-center gap-2 text-xs text-slate-300 cursor-pointer select-none">
          <input
            v-model="autoScroll"
            type="checkbox"
            class="rounded bg-slate-950 border-slate-700 text-indigo-600 focus:ring-0 cursor-pointer"
          />
          <span>自动滚动到底部</span>
        </label>

        <!-- Reconnect button -->
        <button
          v-if="!connected"
          @click="startStream"
          class="px-3 py-1.5 bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg text-xs flex items-center gap-1.5 font-medium transition-colors"
        >
          <Radio class="w-3.5 h-3.5" />
          重新连接
        </button>

        <!-- Clear Logs -->
        <button
          @click="clearLogs"
          class="px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-lg text-xs flex items-center gap-1.5 transition-colors border border-slate-700"
        >
          <Trash2 class="w-3.5 h-3.5" />
          清屏
        </button>
      </div>
    </div>

    <!-- Terminal Container -->
    <div
      ref="terminalRef"
      class="bg-slate-950 border border-slate-800 rounded-xl p-4 font-mono text-xs text-slate-300 h-[600px] overflow-y-auto space-y-1.5 select-text shadow-inner"
    >
      <div v-if="filteredLogs.length === 0" class="text-slate-500 py-12 text-center">
        暂无运行日志输出...
      </div>
      <div
        v-for="(log, idx) in filteredLogs"
        :key="idx"
        class="leading-relaxed flex items-start gap-2.5 hover:bg-slate-900/60 px-2 py-0.5 rounded transition-colors"
      >
        <span class="text-slate-500 text-[11px] flex-shrink-0 select-none">
          {{ log.time }}
        </span>
        <span
          class="px-1 py-0.2 rounded text-[10px] uppercase font-bold flex-shrink-0 select-none"
          :class="getLevelBadgeClass(log.level)"
        >
          {{ log.level }}
        </span>
        <span class="text-slate-200 break-all whitespace-pre-wrap">
          {{ log.message }}
        </span>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, nextTick } from 'vue'
import { Radio, Trash2 } from 'lucide-vue-next'
import client from '@/api/client'

const props = defineProps({
  taskId: {
    type: [Number, String],
    required: true
  }
})

const logs = ref([])
const connected = ref(false)
const autoScroll = ref(true)
const selectedLevel = ref('')
const terminalRef = ref(null)

let eventSource = null

const filteredLogs = computed(() => {
  if (!selectedLevel.value) return logs.value
  return logs.value.filter(l => (l.level || '').toUpperCase() === selectedLevel.value)
})

const getLevelBadgeClass = (level) => {
  switch ((level || '').toUpperCase()) {
    case 'ERROR':
      return 'bg-rose-500/20 text-rose-400 border border-rose-500/30'
    case 'WARN':
      return 'bg-amber-500/20 text-amber-400 border border-amber-500/30'
    case 'PROGRESS':
      return 'bg-indigo-500/20 text-indigo-400 border border-indigo-500/30'
    default:
      return 'bg-slate-800 text-slate-300 border border-slate-700'
  }
}

const scrollToBottom = () => {
  if (!autoScroll.value || !terminalRef.value) return
  nextTick(() => {
    terminalRef.value.scrollTop = terminalRef.value.scrollHeight
  })
}

const addLog = (level, message, timestamp) => {
  const timeStr = timestamp || new Date().toLocaleTimeString()
  logs.value.push({
    level: level.toUpperCase(),
    message: typeof message === 'object' ? JSON.stringify(message) : String(message),
    time: timeStr
  })
  if (logs.value.length > 2000) {
    logs.value.splice(0, logs.value.length - 2000)
  }
  scrollToBottom()
}

const loadHistoricalLogs = async () => {
  try {
    const res = await client.get(`/tasks/${props.taskId}/logs?limit=100`)
    if (res.logs && Array.isArray(res.logs)) {
      res.logs.forEach(l => {
        addLog(l.level || 'INFO', l.message || '', l.created_at || '')
      })
    }
  } catch (e) {
    console.error('Failed to load historical logs:', e)
  }
}

const startStream = () => {
  if (eventSource) {
    eventSource.close()
    eventSource = null
  }

  const url = `/api/tasks/${props.taskId}/events`
  eventSource = new EventSource(url)

  eventSource.onopen = () => {
    connected.value = true
    addLog('INFO', 'SSE 实时事件流通道已建立成功')
  }

  eventSource.onmessage = (event) => {
    try {
      const parsed = JSON.parse(event.data)
      if (parsed.type === 'log') {
        const item = parsed.data || {}
        addLog(item.level || 'INFO', item.message || JSON.stringify(item), item.created_at)
      } else if (parsed.type === 'progress') {
        const p = parsed.data || {}
        addLog('PROGRESS', `爬取进度更新: 已爬取 ${p.crawled_pages || 0} 页, 待爬取 ${p.pending_pages || 0} 页, 提取外部域名 ${p.external_domains_count || 0} 个`)
      } else if (parsed.type === 'complete') {
        addLog('INFO', '任务扫描已执行完成！')
        connected.value = false
        eventSource.close()
      } else if (parsed.type === 'error') {
        addLog('ERROR', `任务异常: ${parsed.data?.error || '未知错误'}`)
      }
    } catch (e) {
      addLog('INFO', event.data)
    }
  }

  eventSource.onerror = () => {
    connected.value = false
    if (eventSource) {
      eventSource.close()
      eventSource = null
    }
  }
}

const clearLogs = () => {
  logs.value = []
}

onMounted(async () => {
  await loadHistoricalLogs()
  startStream()
})

onUnmounted(() => {
  if (eventSource) {
    eventSource.close()
    eventSource = null
  }
})
</script>
