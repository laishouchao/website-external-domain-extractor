<template>
  <span
    :class="[
      'inline-flex items-center gap-1 font-medium rounded border px-2 py-0.5 text-xs',
      badgeClass
    ]"
  >
    <span v-if="dot" :class="['w-1.5 h-1.5 rounded-full', dotClass]"></span>
    <span>{{ label }}</span>
  </span>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  level: {
    type: String,
    default: 'safe'
  },
  dot: {
    type: Boolean,
    default: true
  }
})

const config = {
  critical: {
    label: '严重极危',
    badge: 'bg-rose-950/80 text-rose-300 border-rose-800/80 font-bold',
    dot: 'bg-rose-500 animate-pulse'
  },
  high: {
    label: '高危违规',
    badge: 'bg-red-950/80 text-red-300 border-red-800/80 font-semibold',
    dot: 'bg-red-500'
  },
  medium: {
    label: '中危嫌疑',
    badge: 'bg-amber-950/80 text-amber-300 border-amber-800/80 font-semibold',
    dot: 'bg-amber-500'
  },
  low: {
    label: '低危提示',
    badge: 'bg-sky-950/80 text-sky-300 border-sky-800/80',
    dot: 'bg-sky-500'
  },
  safe: {
    label: '合规安全',
    badge: 'bg-emerald-950/80 text-emerald-300 border-emerald-800/80',
    dot: 'bg-emerald-500'
  },
  pending: {
    label: '未定级',
    badge: 'bg-slate-800/80 text-slate-400 border-slate-700',
    dot: 'bg-slate-500'
  }
}

const itemConfig = computed(() => config[props.level] || config.pending)
const label = computed(() => itemConfig.value.label)
const badgeClass = computed(() => itemConfig.value.badge)
const dotClass = computed(() => itemConfig.value.dot)
</script>
