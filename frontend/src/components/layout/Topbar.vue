<template>
  <header class="h-16 bg-slate-900/90 backdrop-blur border-b border-slate-800 flex items-center justify-between px-4 sm:px-6 sticky top-0 z-20">
    <div class="flex items-center gap-3">
      <button
        v-if="ui.sidebarCollapsed"
        @click="ui.toggleSidebar"
        class="text-slate-400 hover:text-white p-1.5 rounded-lg hover:bg-slate-800 transition md:hidden"
      >
        <Menu class="w-5 h-5" />
      </button>

      <!-- Breadcrumbs / Page Title -->
      <div class="flex items-center gap-2 text-xs">
        <span class="text-slate-500">工作台</span>
        <span class="text-slate-600">/</span>
        <span class="text-white font-semibold">{{ currentTitle }}</span>
      </div>
    </div>

    <!-- Right Controls -->
    <div class="flex items-center gap-3">
      <!-- Active Crawler Running Tag -->
      <div
        v-if="tasksStore.runningTasksCount > 0"
        class="hidden sm:flex items-center gap-2 px-3 py-1 rounded-full bg-emerald-950/70 border border-emerald-800/80 text-emerald-300 text-xs shadow-sm"
      >
        <span class="relative flex h-2 w-2">
          <span class="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
          <span class="relative inline-flex rounded-full h-2 w-2 bg-emerald-500"></span>
        </span>
        <span class="font-medium">正在并发扫描: {{ tasksStore.runningTasksCount }} 个任务</span>
      </div>

      <!-- Theme Switcher -->
      <button
        @click="ui.toggleTheme"
        class="p-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-300 transition border border-slate-700 flex items-center justify-center cursor-pointer"
        :title="ui.theme === 'dark' ? '切换为浅色明亮模式' : '切换为深色暗黑模式'"
      >
        <Sun v-if="ui.theme === 'dark'" class="w-4 h-4 text-amber-400" />
        <Moon v-else class="w-4 h-4 text-indigo-400" />
      </button>

      <!-- Quick Action Buttons -->
      <button
        @click="$emit('open-batch-modal')"
        class="text-xs font-semibold px-3 py-2 rounded-xl bg-indigo-600/20 hover:bg-indigo-600/30 text-indigo-300 border border-indigo-500/30 transition flex items-center gap-1.5 shadow-sm"
      >
        <Layers class="w-3.5 h-3.5" />
        <span class="hidden md:inline">批量导入任务</span>
      </button>

      <button
        @click="$emit('open-create-modal')"
        class="text-xs font-semibold px-3.5 py-2 rounded-xl bg-gradient-to-r from-sky-500 to-indigo-600 hover:from-sky-400 hover:to-indigo-500 text-white transition flex items-center gap-1.5 shadow-md shadow-sky-500/20"
      >
        <Plus class="w-4 h-4" />
        <span>新建扫描</span>
      </button>
    </div>
  </header>
</template>

<script setup>
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { Menu, Plus, Layers, Sun, Moon } from 'lucide-vue-next'
import { useUiStore } from '@/stores/ui'
import { useTasksStore } from '@/stores/tasks'

defineEmits(['open-create-modal', 'open-batch-modal'])

const route = useRoute()
const ui = useUiStore()
const tasksStore = useTasksStore()

const currentTitle = computed(() => {
  return route.meta.title || '系统总览'
})
</script>
