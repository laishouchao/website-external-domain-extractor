<template>
  <div class="bg-slate-900 border border-slate-800 rounded-2xl p-5 flex items-center justify-between shadow-sm hover:border-slate-700 transition group">
    <div class="space-y-1.5 min-w-0 pr-3">
      <p class="text-xs font-medium text-slate-400 truncate">{{ title }}</p>
      <p :class="['text-2xl font-bold font-mono tracking-tight leading-none', finalValueClass]">
        {{ formattedValue }}
      </p>
      <p v-if="displaySubtext" class="text-[11px] text-slate-500 truncate">{{ displaySubtext }}</p>
    </div>
    <div :class="['w-12 h-12 rounded-xl flex items-center justify-center border flex-shrink-0 transition-transform group-hover:scale-105', finalIconBoxClass]">
      <slot name="icon">
        <component :is="resolvedIcon" class="w-5 h-5" />
      </slot>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import {
  Globe,
  Layers,
  ShieldAlert,
  Briefcase,
  Clock,
  AlertCircle,
  CheckCircle2,
  Activity,
  FileText,
  Network,
  ListTodo,
  Code2,
  Cpu,
  Database,
  Search,
  FileCode
} from 'lucide-vue-next'

const iconMap = {
  Globe,
  Layers,
  ShieldAlert,
  Briefcase,
  Clock,
  AlertCircle,
  CheckCircle2,
  Activity,
  FileText,
  Network,
  ListTodo,
  Code2,
  Cpu,
  Database,
  Search,
  FileCode
}

const props = defineProps({
  title: { type: String, required: true },
  value: { type: [Number, String], default: 0 },
  subtitle: { type: String, default: '' },
  subtext: { type: String, default: '' },
  icon: { type: String, default: '' },
  color: { type: String, default: '' },
  valueClass: { type: String, default: '' },
  iconBoxClass: { type: String, default: '' }
})

const displaySubtext = computed(() => props.subtitle || props.subtext)

const formattedValue = computed(() => {
  if (typeof props.value === 'number') {
    return props.value.toLocaleString()
  }
  return props.value ?? 0
})

const resolvedIcon = computed(() => {
  if (props.icon && iconMap[props.icon]) {
    return iconMap[props.icon]
  }
  return Globe
})

const colorTheme = computed(() => {
  switch (props.color) {
    case 'emerald':
      return {
        value: 'text-emerald-400',
        box: 'bg-emerald-500/10 border-emerald-500/20 text-emerald-400'
      }
    case 'rose':
      return {
        value: 'text-rose-400',
        box: 'bg-rose-500/10 border-rose-500/20 text-rose-400'
      }
    case 'amber':
      return {
        value: 'text-amber-400',
        box: 'bg-amber-500/10 border-amber-500/20 text-amber-400'
      }
    case 'cyan':
      return {
        value: 'text-cyan-400',
        box: 'bg-cyan-500/10 border-cyan-500/20 text-cyan-400'
      }
    case 'sky':
      return {
        value: 'text-sky-400',
        box: 'bg-sky-500/10 border-sky-500/20 text-sky-400'
      }
    case 'indigo':
    default:
      return {
        value: 'text-indigo-400',
        box: 'bg-indigo-500/10 border-indigo-500/20 text-indigo-400'
      }
  }
})

const finalValueClass = computed(() => {
  if (props.valueClass) return props.valueClass
  if (props.color) return colorTheme.value.value
  return 'text-slate-100'
})

const finalIconBoxClass = computed(() => {
  if (props.iconBoxClass) return props.iconBoxClass
  if (props.color) return colorTheme.value.box
  return 'bg-slate-800/60 border-slate-700 text-slate-300'
})
</script>
