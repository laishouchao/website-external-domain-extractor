<template>
  <aside
    :class="[
      'bg-slate-900 border-r border-slate-800 flex flex-col justify-between transition-all duration-300 z-30 select-none',
      ui.sidebarCollapsed ? 'w-16' : 'w-64'
    ]"
  >
    <!-- Brand / Header -->
    <div class="h-16 border-b border-slate-800 flex items-center justify-between px-3.5">
      <router-link to="/dashboard" class="flex items-center gap-3 overflow-hidden">
        <div class="w-9 h-9 min-w-[36px] rounded-xl bg-gradient-to-tr from-sky-500 to-indigo-600 flex items-center justify-center text-white font-bold shadow-lg shadow-sky-500/20">
          <Globe class="w-5 h-5 text-white" />
        </div>
        <div v-if="!ui.sidebarCollapsed" class="truncate">
          <div class="text-sm font-bold text-white tracking-tight flex items-center gap-1.5">
            <span>外链提取与治理</span>
            <span class="text-[10px] px-1.5 py-0.2 rounded bg-sky-500/20 text-sky-400 border border-sky-500/30">v2.0</span>
          </div>
          <div class="text-[10px] text-slate-500 truncate">全深度爬虫 • 资产测绘</div>
        </div>
      </router-link>

      <button
        v-if="!ui.sidebarCollapsed"
        @click="ui.toggleSidebar"
        class="text-slate-400 hover:text-white p-1 rounded hover:bg-slate-800 transition"
        title="收缩侧边栏"
      >
        <ChevronLeft class="w-4 h-4" />
      </button>
    </div>

    <!-- Navigation List -->
    <div class="flex-1 overflow-y-auto py-4 px-2 space-y-1">
      <router-link
        v-for="item in navItems"
        :key="item.path"
        :to="item.path"
        :class="[
          'flex items-center gap-3 px-3 py-2.5 rounded-xl text-xs font-medium transition group relative',
          $route.path.startsWith(item.path)
            ? 'bg-sky-500/15 text-sky-300 border border-sky-500/30 font-semibold'
            : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/60 border border-transparent'
        ]"
        :title="ui.sidebarCollapsed ? item.label : ''"
      >
        <component :is="item.icon" class="w-4 h-4 min-w-[16px]" />
        <span v-if="!ui.sidebarCollapsed" class="truncate flex-1">{{ item.label }}</span>
        
        <!-- Badge indicator -->
        <span
          v-if="item.badge && (!ui.sidebarCollapsed || item.badgeOnlyDot)"
          :class="[
            'px-1.5 py-0.2 rounded-full font-mono text-[10px] font-bold border',
            item.badgeClass || 'bg-slate-800 text-slate-300 border-slate-700'
          ]"
        >
          {{ !ui.sidebarCollapsed ? item.badge : '' }}
        </span>
      </router-link>
    </div>

    <!-- Footer Toggle (When collapsed) -->
    <div class="p-3 border-t border-slate-800 flex items-center justify-center">
      <button
        v-if="ui.sidebarCollapsed"
        @click="ui.toggleSidebar"
        class="text-slate-400 hover:text-white p-2 rounded-lg hover:bg-slate-800 transition"
        title="展开侧边栏"
      >
        <ChevronRight class="w-4 h-4" />
      </button>
      <div v-else class="w-full flex items-center justify-between text-xs text-slate-400 px-1">
        <div class="flex items-center gap-2 truncate">
          <span class="w-2 h-2 rounded-full bg-emerald-400 shrink-0"></span>
          <span class="truncate font-medium text-slate-300 text-[11px]">{{ authStore.userDisplayName }}</span>
        </div>
        <button
          @click="handleLogout"
          class="p-1 rounded-lg text-slate-500 hover:text-rose-400 hover:bg-slate-800 transition cursor-pointer"
          title="退出登录"
        >
          <LogOut class="w-3.5 h-3.5" />
        </button>
      </div>
    </div>
  </aside>
</template>

<script setup>
import { computed, markRaw } from 'vue'
import { useRouter } from 'vue-router'
import {
  LayoutDashboard,
  ListTodo,
  Globe,
  ShieldAlert,
  FileCode,
  Settings,
  ChevronLeft,
  ChevronRight,
  LogOut
} from 'lucide-vue-next'
import { useUiStore } from '@/stores/ui'
import { useRemediationStore } from '@/stores/remediation'
import { useGlobalDomainsStore } from '@/stores/globalDomains'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const ui = useUiStore()
const remediation = useRemediationStore()
const globalDomains = useGlobalDomainsStore()
const authStore = useAuthStore()

const handleLogout = async () => {
  if (confirm('确认退出系统？')) {
    await authStore.logout()
    router.replace('/login')
  }
}

const navItems = computed(() => [
  {
    label: '态势总览',
    path: '/dashboard',
    icon: markRaw(LayoutDashboard)
  },
  {
    label: '扫描任务中心',
    path: '/tasks',
    icon: markRaw(ListTodo)
  },
  {
    label: '全局外部域名库',
    path: '/global-domains',
    icon: markRaw(Globe),
    badge: globalDomains.stats?.total_unique_domains || null,
    badgeClass: 'bg-indigo-950 text-indigo-300 border-indigo-800/60'
  },
  {
    label: '风险页面待处置',
    path: '/remediation',
    icon: markRaw(ShieldAlert),
    badge: remediation.stats?.pending_count ? (remediation.stats.pending_count > 9999 ? '9999+' : remediation.stats.pending_count) : null,
    badgeClass: 'bg-rose-950 text-rose-300 border-rose-800/80'
  },
  {
    label: '威胁情报研判库',
    path: '/threat-intel',
    icon: markRaw(FileCode)
  },
  {
    label: '系统与引擎配置',
    path: '/settings',
    icon: markRaw(Settings)
  }
])
</script>
