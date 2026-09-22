<template>
  <div class="space-y-6">
    <!-- Welcome / Summary Banner -->
    <div class="bg-gradient-to-r from-sky-950/50 via-slate-900 to-slate-900 border border-sky-900/40 rounded-2xl p-6 shadow-xl flex flex-col md:flex-row md:items-center justify-between gap-4">
      <div class="space-y-1.5">
        <div class="flex items-center gap-2">
          <ShieldAlert class="w-6 h-6 text-sky-400" />
          <h2 class="text-xl font-bold text-white tracking-tight">网络资产测绘与违规外链治理态势</h2>
        </div>
        <p class="text-xs text-slate-400 max-w-2xl leading-relaxed">
          全自动递归遍历目标站点全部深度页面，深度提取 HTML/JavaScript 代码、正文中的所有非本站外部域名，结合威胁情报规则进行自动化定级研判与 3 小时闭环复测。
        </p>
      </div>
      <div class="flex items-center gap-3">
        <router-link
          to="/remediation"
          class="px-4 py-2.5 rounded-xl bg-rose-600/20 hover:bg-rose-600/30 text-rose-300 border border-rose-500/40 text-xs font-semibold flex items-center gap-2 transition shadow-sm"
        >
          <span class="w-2 h-2 rounded-full bg-rose-500 animate-ping"></span>
          <span>待处置工单: {{ remediationStore.stats?.pending_count || 0 }} 项</span>
        </router-link>
        <router-link
          to="/tasks"
          class="px-4 py-2.5 rounded-xl bg-sky-500 hover:bg-sky-400 text-white text-xs font-semibold flex items-center gap-1.5 transition shadow-lg shadow-sky-500/20"
        >
          <span>进入任务中心</span>
          <span>→</span>
        </router-link>
      </div>
    </div>

    <!-- Core Metrics Grid -->
    <div class="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3.5">
      <MetricCard
        title="扫描任务总数"
        :value="tasksStore.tasks.length"
        value-class="text-white"
        icon-box-class="bg-sky-950/60 border-sky-800/40 text-sky-400"
      >
        <template #icon><ListTodo class="w-5 h-5" /></template>
      </MetricCard>

      <MetricCard
        title="正在扫描"
        :value="tasksStore.runningTasksCount"
        value-class="text-emerald-400"
        icon-box-class="bg-emerald-950/60 border-emerald-800/40 text-emerald-400"
      >
        <template #icon><Activity class="w-5 h-5" /></template>
      </MetricCard>

      <MetricCard
        title="累计爬取页面"
        :value="tasksStore.totalPagesCrawled"
        value-class="text-amber-400"
        icon-box-class="bg-amber-950/60 border-amber-800/40 text-amber-400"
      >
        <template #icon><FileText class="w-5 h-5" /></template>
      </MetricCard>

      <MetricCard
        title="提取唯一外部域名"
        :value="globalDomainsStore.stats?.total_unique_domains || tasksStore.totalExtDomainsFound"
        value-class="text-indigo-400"
        icon-box-class="bg-indigo-950/60 border-indigo-800/40 text-indigo-400"
      >
        <template #icon><Globe class="w-5 h-5" /></template>
      </MetricCard>

      <MetricCard
        title="发现本站子域名"
        :value="tasksStore.totalSubdomainsFound"
        value-class="text-cyan-400"
        icon-box-class="bg-cyan-950/60 border-cyan-800/40 text-cyan-400"
      >
        <template #icon><Network class="w-5 h-5" /></template>
      </MetricCard>

      <MetricCard
        title="风险外链待处置"
        :value="remediationStore.stats?.pending_count || 0"
        value-class="text-rose-400 font-bold"
        icon-box-class="bg-rose-950/60 border-rose-800/40 text-rose-400"
      >
        <template #icon><ShieldAlert class="w-5 h-5" /></template>
      </MetricCard>
    </div>

    <!-- Overview Split Section -->
    <div class="grid grid-cols-1 lg:grid-cols-3 gap-6">
      <!-- Recent Active Tasks (2 Cols) -->
      <div class="lg:col-span-2 bg-slate-900 border border-slate-800 rounded-2xl p-5 space-y-4 shadow-lg">
        <div class="flex items-center justify-between">
          <div class="flex items-center gap-2">
            <ListTodo class="w-4 h-4 text-sky-400" />
            <h3 class="text-sm font-bold text-white">近期重点扫描任务</h3>
          </div>
          <router-link to="/tasks" class="text-xs text-sky-400 hover:text-sky-300 flex items-center gap-1">
            <span>查看全部任务</span>
            <span>→</span>
          </router-link>
        </div>

        <div v-if="tasksStore.loading && tasksStore.tasks.length === 0" class="py-12 text-center text-slate-500">
          <Loader2 class="w-6 h-6 animate-spin mx-auto text-sky-400 mb-2" />
          <span class="text-xs">正在汇总重点扫描任务...</span>
        </div>
        <div v-else-if="recentTasks.length === 0" class="py-12 text-center text-slate-500">
          <div class="text-2xl mb-1">📋</div>
          <div class="text-xs">暂无扫描任务，点击右上角新建任务</div>
        </div>
        <div v-else class="divide-y divide-slate-800/60">
          <div
            v-for="task in recentTasks"
            :key="task.id"
            class="py-3 flex items-center justify-between gap-4 hover:bg-slate-800/30 px-2 rounded-xl transition cursor-pointer"
            @click="$router.push(`/tasks/${task.id}`)"
          >
            <div class="space-y-1 min-w-0">
              <div class="flex items-center gap-2">
                <span class="font-mono text-xs text-slate-500 font-semibold">#{{ task.id }}</span>
                <span class="font-bold text-xs text-white truncate max-w-sm">{{ task.name }}</span>
                <StatusBadge :status="task.status" />
              </div>
              <div class="text-[11px] text-slate-400 font-mono truncate">
                {{ task.target_url }}
              </div>
            </div>

            <div class="flex items-center gap-6 text-xs text-right whitespace-nowrap">
              <div>
                <span class="text-slate-500 block text-[10px]">爬取页面</span>
                <span class="font-mono font-bold text-amber-400">{{ task.pages_crawled ?? task.crawled_pages ?? 0 }}</span>
              </div>
              <div>
                <span class="text-slate-500 block text-[10px]">外部域名</span>
                <span class="font-mono font-bold text-sky-400">{{ task.external_domains_count || 0 }}</span>
              </div>
              <div>
                <span class="text-slate-500 block text-[10px]">子域名</span>
                <span class="font-mono font-bold text-indigo-400">{{ task.subdomains_count || 0 }}</span>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- Quick Action & Intelligence Status (1 Col) -->
      <div class="space-y-6">
        <!-- 3-Hour Verifier Status Card -->
        <div class="bg-slate-900 border border-slate-800 rounded-2xl p-5 space-y-3.5 shadow-lg">
          <div class="flex items-center justify-between">
            <div class="flex items-center gap-2">
              <Clock class="w-4 h-4 text-rose-400" />
              <h3 class="text-sm font-bold text-white">自动闭环复测引擎</h3>
            </div>
            <span class="w-2 h-2 rounded-full bg-emerald-500 animate-pulse"></span>
          </div>

          <div class="p-3.5 bg-slate-950/80 rounded-xl border border-slate-800/80 space-y-2 text-xs">
            <div class="flex items-center justify-between text-slate-400">
              <span>轮询状态:</span>
              <span class="text-emerald-400 font-semibold">3小时并发多协程轮询</span>
            </div>
            <div class="flex items-center justify-between text-slate-400 font-mono">
              <span>下次复测倒计时:</span>
              <span class="text-sky-400 font-bold bg-slate-900 px-2 py-0.5 rounded border border-slate-800">
                {{ Math.floor((remediationStore.timer?.remaining_seconds || 0) / 3600) > 0 ? Math.floor((remediationStore.timer?.remaining_seconds || 0) / 3600) + '时' : '' }}{{ Math.floor(((remediationStore.timer?.remaining_seconds || 0) % 3600) / 60) }}分{{ (remediationStore.timer?.remaining_seconds || 0) % 60 }}秒
              </span>
            </div>
            <div v-if="remediationStore.timer?.last_run_stats?.finished_at" class="text-[11px] text-slate-500 pt-1 border-t border-slate-800">
              上次核验: 已确认修复 {{ remediationStore.timer.last_run_stats.cleaned_count || 0 }} 处，残留 {{ remediationStore.timer.last_run_stats.failed_count || 0 }} 处
            </div>
          </div>

          <router-link
            to="/remediation"
            class="w-full py-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-semibold flex items-center justify-center gap-1.5 transition border border-slate-700"
          >
            <span>进入风险工单处置专区</span>
            <span>→</span>
          </router-link>
        </div>

        <!-- Threat Intel Quick Card -->
        <div class="bg-slate-900 border border-slate-800 rounded-2xl p-5 space-y-3.5 shadow-lg">
          <div class="flex items-center justify-between">
            <div class="flex items-center gap-2">
              <FileCode class="w-4 h-4 text-indigo-400" />
              <h3 class="text-sm font-bold text-white">威胁情报研判库</h3>
            </div>
          </div>

          <p class="text-xs text-slate-400 leading-relaxed">
            支持基于主域名与正则表达式配置涉赌、涉黄、暗链、废弃劫持等威胁情报规则，支持针对历史 5900 万级数据库执行毫秒级精准回溯标记。
          </p>

          <router-link
            to="/threat-intel"
            class="w-full py-2 rounded-xl bg-indigo-950/60 hover:bg-indigo-900/60 text-indigo-300 text-xs font-semibold flex items-center justify-center gap-1.5 transition border border-indigo-800/60"
          >
            <span>管理情报规则与历史回溯</span>
            <span>→</span>
          </router-link>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted } from 'vue'
import {
  ListTodo,
  Activity,
  FileText,
  Globe,
  Network,
  ShieldAlert,
  Clock,
  FileCode,
  Loader2
} from 'lucide-vue-next'
import MetricCard from '@/components/common/MetricCard.vue'
import StatusBadge from '@/components/common/StatusBadge.vue'
import { useTasksStore } from '@/stores/tasks'
import { useGlobalDomainsStore } from '@/stores/globalDomains'
import { useRemediationStore } from '@/stores/remediation'

const tasksStore = useTasksStore()
const globalDomainsStore = useGlobalDomainsStore()
const remediationStore = useRemediationStore()

const recentTasks = computed(() => {
  return [...tasksStore.tasks].slice(0, 6)
})

onMounted(async () => {
  await tasksStore.loadTasks()
  await globalDomainsStore.loadStats()
  await remediationStore.loadStats()
  await remediationStore.loadTimerStatus()
})
</script>
