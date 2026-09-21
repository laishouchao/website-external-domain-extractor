<template>
  <div class="px-4 py-3 bg-slate-950/60 border-t border-slate-800/80 flex flex-wrap items-center justify-between gap-3 text-xs select-none">
    <!-- Total Summary -->
    <div class="text-slate-400">
      共 <span class="font-bold text-slate-100 font-mono">{{ total.toLocaleString() }}</span> 条数据
      <span v-if="actualPageSize" class="ml-1">• 每页 {{ actualPageSize }} 条</span>
    </div>

    <!-- Navigation Buttons -->
    <div class="flex items-center gap-1.5">
      <!-- First Page -->
      <button
        :disabled="activePage <= 1"
        @click="goToPage(1)"
        class="px-2.5 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 disabled:opacity-40 disabled:hover:bg-slate-800 disabled:cursor-not-allowed text-slate-300 transition font-medium border border-slate-700 cursor-pointer flex items-center justify-center"
        title="前往第一页"
      >
        <ChevronsLeft class="w-3.5 h-3.5" />
      </button>

      <!-- Previous Page -->
      <button
        :disabled="activePage <= 1"
        @click="goToPage(activePage - 1)"
        class="px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 disabled:opacity-40 disabled:hover:bg-slate-800 disabled:cursor-not-allowed text-slate-300 transition font-medium border border-slate-700 cursor-pointer flex items-center gap-1"
        title="上一页"
      >
        <ChevronLeft class="w-3.5 h-3.5" />
        <span>上一页</span>
      </button>

      <!-- Current / Total Page Display -->
      <div class="flex items-center gap-1 px-2 font-mono text-slate-300">
        <span>第</span>
        <span class="font-bold text-sky-400 px-1.5 py-0.5 rounded bg-slate-900 border border-slate-800 min-w-[28px] text-center">
          {{ activePage }}
        </span>
        <span>/ {{ totalPages }} 页</span>
      </div>

      <!-- Next Page -->
      <button
        :disabled="activePage >= totalPages"
        @click="goToPage(activePage + 1)"
        class="px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 disabled:opacity-40 disabled:hover:bg-slate-800 disabled:cursor-not-allowed text-slate-300 transition font-medium border border-slate-700 cursor-pointer flex items-center gap-1"
        title="下一页"
      >
        <span>下一页</span>
        <ChevronRight class="w-3.5 h-3.5" />
      </button>

      <!-- Last Page -->
      <button
        :disabled="activePage >= totalPages"
        @click="goToPage(totalPages)"
        class="px-2.5 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 disabled:opacity-40 disabled:hover:bg-slate-800 disabled:cursor-not-allowed text-slate-300 transition font-medium border border-slate-700 cursor-pointer flex items-center justify-center"
        title="前往最后一页"
      >
        <ChevronsRight class="w-3.5 h-3.5" />
      </button>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { ChevronLeft, ChevronRight, ChevronsLeft, ChevronsRight } from 'lucide-vue-next'

const props = defineProps({
  page: { type: Number, default: undefined },
  currentPage: { type: Number, default: undefined },
  modelValue: { type: Number, default: undefined },
  total: { type: Number, default: 0 },
  pageSize: { type: Number, default: 50 }
})

const emit = defineEmits([
  'update:page',
  'update:currentPage',
  'update:modelValue',
  'page-change',
  'change'
])

const activePage = computed(() => {
  return props.currentPage ?? props.page ?? props.modelValue ?? 1
})

const actualPageSize = computed(() => {
  return props.pageSize || 50
})

const totalPages = computed(() => {
  return Math.max(1, Math.ceil(props.total / actualPageSize.value))
})

const goToPage = (p) => {
  const targetPage = Number(p)
  if (isNaN(targetPage) || targetPage < 1 || targetPage > totalPages.value || targetPage === activePage.value) return
  emit('page-change', targetPage)
  emit('change', targetPage)
  emit('update:page', targetPage)
  emit('update:currentPage', targetPage)
  emit('update:modelValue', targetPage)
}
</script>
