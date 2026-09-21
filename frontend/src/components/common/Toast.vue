<template>
  <div class="fixed top-4 right-4 z-50 flex flex-col gap-2.5 max-w-sm w-full pointer-events-none">
    <TransitionGroup
      enter-active-class="transition duration-200 ease-out"
      enter-from-class="transform translate-y-2 opacity-0 scale-95"
      enter-to-class="transform translate-y-0 opacity-100 scale-100"
      leave-active-class="transition duration-150 ease-in"
      leave-from-class="opacity-100"
      leave-to-class="opacity-0 scale-95"
    >
      <div
        v-for="t in ui.toasts"
        :key="t.id"
        :class="[
          'pointer-events-auto p-3.5 rounded-xl border shadow-xl flex items-start gap-3 text-xs',
          getToastClass(t.type)
        ]"
      >
        <span class="text-base leading-none mt-0.5">{{ getIcon(t.type) }}</span>
        <div class="flex-1 text-slate-200 font-medium leading-relaxed">
          {{ t.message }}
        </div>
        <button
          @click="ui.removeToast(t.id)"
          class="text-slate-400 hover:text-slate-200 text-xs px-1"
        >
          ✕
        </button>
      </div>
    </TransitionGroup>
  </div>
</template>

<script setup>
import { useUiStore } from '@/stores/ui'

const ui = useUiStore()

const getToastClass = (type) => {
  switch (type) {
    case 'success':
      return 'bg-slate-900 border-emerald-700/60 shadow-emerald-950/30 text-emerald-300'
    case 'warn':
      return 'bg-slate-900 border-amber-700/60 shadow-amber-950/30 text-amber-300'
    case 'error':
      return 'bg-slate-900 border-rose-700/60 shadow-rose-950/30 text-rose-300'
    default:
      return 'bg-slate-900 border-sky-700/60 shadow-sky-950/30 text-sky-300'
  }
}

const getIcon = (type) => {
  switch (type) {
    case 'success': return '✓'
    case 'warn': return '⚠️'
    case 'error': return '✕'
    default: return 'ℹ'
  }
}
</script>
