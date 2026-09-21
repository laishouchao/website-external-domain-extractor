<template>
  <span
    :class="[
      'inline-flex items-center gap-1.5 font-medium rounded-full border px-2.5 py-0.5 text-xs whitespace-nowrap shadow-sm',
      badgeClass
    ]"
  >
    <span :class="['w-1.5 h-1.5 rounded-full', dotClass]"></span>
    <span>{{ label }}</span>
  </span>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  status: {
    type: String,
    required: true
  }
})

const map = {
  // Task status
  pending: { label: '待处理', badge: 'bg-slate-900 text-slate-400 border-slate-800', dot: 'bg-slate-400' },
  running: { label: '正在扫描', badge: 'bg-emerald-950 text-emerald-300 border-emerald-800/80', dot: 'bg-emerald-400 animate-ping' },
  paused: { label: '已暂停', badge: 'bg-amber-950 text-amber-300 border-amber-800/80', dot: 'bg-amber-400' },
  completed: { label: '扫描完成', badge: 'bg-sky-950 text-sky-300 border-sky-800/80', dot: 'bg-sky-400' },
  stopped: { label: '已停止', badge: 'bg-slate-800 text-slate-300 border-slate-700', dot: 'bg-slate-400' },
  failed: { label: '失败', badge: 'bg-rose-950 text-rose-300 border-rose-800/80', dot: 'bg-rose-500' },
  deleting: { label: '清理中', badge: 'bg-red-950 text-red-400 border-red-900', dot: 'bg-red-500 animate-pulse' },

  // Verification status
  unverified: { label: '待复测', badge: 'bg-amber-950 text-amber-300 border-amber-800/80', dot: 'bg-amber-400' },
  verified_failed: { label: '违规仍残留 (未修复)', badge: 'bg-rose-950 text-rose-300 border-rose-800/80 font-bold', dot: 'bg-rose-500 animate-pulse' },
  verified_clean: { label: '已修复清除', badge: 'bg-emerald-950 text-emerald-300 border-emerald-800/80 font-semibold', dot: 'bg-emerald-400' },
  page_removed: { label: '页面已下线 (404)', badge: 'bg-slate-800 text-slate-300 border-slate-700', dot: 'bg-slate-400' },
  error: { label: '访问异常', badge: 'bg-slate-900 text-slate-400 border-slate-800', dot: 'bg-slate-500' },

  // Manual status
  in_progress: { label: '处理中', badge: 'bg-sky-950 text-sky-300 border-sky-800', dot: 'bg-sky-400' },
  resolved: { label: '已解决', badge: 'bg-emerald-950 text-emerald-300 border-emerald-800', dot: 'bg-emerald-400' },
  ignored: { label: '已忽略', badge: 'bg-slate-900 text-slate-500 border-slate-800', dot: 'bg-slate-600' }
}

const current = computed(() => map[props.status] || { label: props.status, badge: 'bg-slate-800 text-slate-400 border-slate-700', dot: 'bg-slate-500' })
const label = computed(() => current.value.label)
const badgeClass = computed(() => current.value.badge)
const dotClass = computed(() => current.value.dot)
</script>
