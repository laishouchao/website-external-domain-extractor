<template>
  <div class="relative group font-mono text-xs bg-slate-950/80 border border-slate-800 rounded-xl p-3.5 overflow-hidden shadow-inner">
    <div
      :class="[
        'overflow-x-auto text-slate-300 leading-relaxed break-words select-all whitespace-pre-wrap',
        maxHeightClass
      ]"
    >
      <template v-if="displayHighlight">
        <span v-html="highlightedContent"></span>
      </template>
      <template v-else>
        {{ displayCode }}
      </template>
    </div>
    
    <!-- Copy Button -->
    <button
      @click="copyContent"
      class="absolute top-2.5 right-2.5 opacity-0 group-hover:opacity-100 transition px-2 py-1 rounded bg-slate-800 hover:bg-slate-700 text-slate-300 text-[11px] border border-slate-700 flex items-center gap-1 shadow cursor-pointer"
      :title="copied ? '已复制' : '复制内容'"
    >
      <Check v-if="copied" class="w-3 h-3 text-emerald-400" />
      <Copy v-else class="w-3 h-3 text-slate-400" />
      <span :class="copied ? 'text-emerald-400' : ''">{{ copied ? '已复制' : '复制' }}</span>
    </button>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { Copy, Check } from 'lucide-vue-next'

const props = defineProps({
  code: { type: String, default: '' },
  content: { type: String, default: '' },
  highlightTerm: { type: String, default: '' },
  highlight: { type: String, default: '' },
  maxHeight: { type: String, default: 'max-h-56' }
})

const copied = ref(false)

const displayCode = computed(() => props.code || props.content || '')
const displayHighlight = computed(() => props.highlightTerm || props.highlight || '')
const maxHeightClass = computed(() => props.maxHeight)

const highlightedContent = computed(() => {
  if (!displayCode.value) return ''
  if (!displayHighlight.value) return displayCode.value
  const escaped = displayHighlight.value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  const regex = new RegExp(`(${escaped})`, 'gi')
  return displayCode.value.replace(regex, '<mark class="bg-rose-500/30 text-rose-300 font-bold px-1 rounded border border-rose-500/40">$1</mark>')
})

const copyContent = async () => {
  if (!displayCode.value) return
  try {
    await navigator.clipboard.writeText(displayCode.value)
    copied.value = true
    setTimeout(() => { copied.value = false }, 2000)
  } catch (e) {
    console.error('Failed to copy', e)
  }
}
</script>
