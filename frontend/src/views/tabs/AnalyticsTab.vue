<template>
  <div class="space-y-6">
    <div v-if="loading" class="flex items-center justify-center py-16 text-slate-500 gap-2">
      <Loader2 class="w-6 h-6 animate-spin text-indigo-400" />
      <span>正在计算统计指标与数据全景...</span>
    </div>

    <template v-else>
      <!-- Top 4 Summary Cards -->
      <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <MetricCard
          title="外部域名总数"
          :value="stats.total_unique_domains || 0"
          subtitle="任务去重发现的独立域名"
          icon="Globe"
          color="indigo"
        />
        <MetricCard
          title="涉及根域名数"
          :value="stats.unique_root_domains || 0"
          subtitle="独立主一级组织域名"
          icon="Layers"
          color="cyan"
        />
        <MetricCard
          title="高危涉险域名"
          :value="(stats.risk_stats?.critical || 0) + (stats.risk_stats?.high || 0)"
          subtitle="严重 + 高危等级域名数"
          icon="ShieldAlert"
          color="rose"
        />
        <MetricCard
          title="彻底清除闭环"
          :value="stats.verify_stats?.verified_clean || 0"
          subtitle="复测确认已无代码残留"
          icon="CheckCircle2"
          color="emerald"
        />
      </div>

      <!-- Charts & Visual Breakdown Grid -->
      <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <!-- Risk Distribution Card -->
        <div class="bg-slate-900 border border-slate-800 rounded-xl p-5 space-y-4">
          <div class="flex items-center justify-between">
            <h3 class="text-sm font-semibold text-slate-200 flex items-center gap-2">
              <ShieldAlert class="w-4 h-4 text-amber-400" />
              风险等级全景分布
            </h3>
            <span class="text-xs text-slate-500">共 {{ stats.total_unique_domains || 0 }} 个域名</span>
          </div>

          <div class="space-y-3 pt-2">
            <!-- Critical -->
            <div class="space-y-1">
              <div class="flex justify-between text-xs">
                <span class="text-rose-400 font-medium">严重 (Critical)</span>
                <span class="text-slate-300 font-mono">{{ stats.risk_stats?.critical || 0 }} ({{ getPercentage(stats.risk_stats?.critical) }}%)</span>
              </div>
              <div class="w-full h-2 bg-slate-950 rounded-full overflow-hidden">
                <div class="h-full bg-rose-500 rounded-full transition-all duration-500" :style="{ width: getPercentage(stats.risk_stats?.critical) + '%' }"></div>
              </div>
            </div>

            <!-- High -->
            <div class="space-y-1">
              <div class="flex justify-between text-xs">
                <span class="text-orange-400 font-medium">高危 (High)</span>
                <span class="text-slate-300 font-mono">{{ stats.risk_stats?.high || 0 }} ({{ getPercentage(stats.risk_stats?.high) }}%)</span>
              </div>
              <div class="w-full h-2 bg-slate-950 rounded-full overflow-hidden">
                <div class="h-full bg-orange-500 rounded-full transition-all duration-500" :style="{ width: getPercentage(stats.risk_stats?.high) + '%' }"></div>
              </div>
            </div>

            <!-- Medium -->
            <div class="space-y-1">
              <div class="flex justify-between text-xs">
                <span class="text-amber-400 font-medium">中危 (Medium)</span>
                <span class="text-slate-300 font-mono">{{ stats.risk_stats?.medium || 0 }} ({{ getPercentage(stats.risk_stats?.medium) }}%)</span>
              </div>
              <div class="w-full h-2 bg-slate-950 rounded-full overflow-hidden">
                <div class="h-full bg-amber-500 rounded-full transition-all duration-500" :style="{ width: getPercentage(stats.risk_stats?.medium) + '%' }"></div>
              </div>
            </div>

            <!-- Low -->
            <div class="space-y-1">
              <div class="flex justify-between text-xs">
                <span class="text-yellow-400 font-medium">低危 (Low)</span>
                <span class="text-slate-300 font-mono">{{ stats.risk_stats?.low || 0 }} ({{ getPercentage(stats.risk_stats?.low) }}%)</span>
              </div>
              <div class="w-full h-2 bg-slate-950 rounded-full overflow-hidden">
                <div class="h-full bg-yellow-500 rounded-full transition-all duration-500" :style="{ width: getPercentage(stats.risk_stats?.low) + '%' }"></div>
              </div>
            </div>

            <!-- Safe -->
            <div class="space-y-1">
              <div class="flex justify-between text-xs">
                <span class="text-emerald-400 font-medium">安全可信 (Safe)</span>
                <span class="text-slate-300 font-mono">{{ stats.risk_stats?.safe || 0 }} ({{ getPercentage(stats.risk_stats?.safe) }}%)</span>
              </div>
              <div class="w-full h-2 bg-slate-950 rounded-full overflow-hidden">
                <div class="h-full bg-emerald-500 rounded-full transition-all duration-500" :style="{ width: getPercentage(stats.risk_stats?.safe) + '%' }"></div>
              </div>
            </div>

            <!-- Pending -->
            <div class="space-y-1">
              <div class="flex justify-between text-xs">
                <span class="text-slate-400 font-medium">待研判 (Pending)</span>
                <span class="text-slate-300 font-mono">{{ stats.risk_stats?.pending || 0 }} ({{ getPercentage(stats.risk_stats?.pending) }}%)</span>
              </div>
              <div class="w-full h-2 bg-slate-950 rounded-full overflow-hidden">
                <div class="h-full bg-slate-600 rounded-full transition-all duration-500" :style="{ width: getPercentage(stats.risk_stats?.pending) + '%' }"></div>
              </div>
            </div>
          </div>
        </div>

        <!-- Source Comparison Card -->
        <div class="bg-slate-900 border border-slate-800 rounded-xl p-5 space-y-4">
          <div class="flex items-center justify-between">
            <h3 class="text-sm font-semibold text-slate-200 flex items-center gap-2">
              <Code2 class="w-4 h-4 text-indigo-400" />
              来源载体与复测闭环情况
            </h3>
          </div>

          <div class="grid grid-cols-2 gap-4 pt-2">
            <!-- Link Domains -->
            <div class="bg-slate-950 p-4 rounded-xl border border-slate-800 space-y-1">
              <span class="text-xs text-slate-400">超链接引用域名 (Link)</span>
              <div class="text-2xl font-bold font-mono text-blue-400">{{ stats.link_domains || 0 }}</div>
              <p class="text-[11px] text-slate-500">页面中存在可点击跳转的超链接</p>
            </div>

            <!-- Text Domains -->
            <div class="bg-slate-950 p-4 rounded-xl border border-slate-800 space-y-1">
              <span class="text-xs text-slate-400">文本/脚本引用域名 (Text)</span>
              <div class="text-2xl font-bold font-mono text-purple-400">{{ stats.text_domains || 0 }}</div>
              <p class="text-[11px] text-slate-500">隐藏在网页正文、JS脚本或注释中</p>
            </div>
          </div>

          <!-- Verify Status Breakdown -->
          <div class="pt-2 border-t border-slate-800 space-y-2">
            <div class="text-xs font-medium text-slate-400">整改复测闭环状态统计</div>
            <div class="grid grid-cols-3 gap-2 text-center">
              <div class="bg-slate-950/80 p-2.5 rounded-lg border border-slate-800">
                <div class="text-xs text-slate-500">未复测</div>
                <div class="text-base font-bold font-mono text-slate-300">{{ stats.verify_stats?.unverified || 0 }}</div>
              </div>
              <div class="bg-emerald-500/10 p-2.5 rounded-lg border border-emerald-500/20">
                <div class="text-xs text-emerald-400">已清除</div>
                <div class="text-base font-bold font-mono text-emerald-300">{{ stats.verify_stats?.verified_clean || 0 }}</div>
              </div>
              <div class="bg-rose-500/10 p-2.5 rounded-lg border border-rose-500/20">
                <div class="text-xs text-rose-400">仍残留</div>
                <div class="text-base font-bold font-mono text-rose-300">{{ stats.verify_stats?.verified_failed || 0 }}</div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- Top 10 Root Domains Ranking -->
      <div class="bg-slate-900 border border-slate-800 rounded-xl p-5 space-y-4">
        <h3 class="text-sm font-semibold text-slate-200 flex items-center gap-2">
          <Layers class="w-4 h-4 text-cyan-400" />
          Top 10 主根域名外链频次排行
        </h3>

        <div class="overflow-x-auto">
          <table class="w-full text-left text-sm text-slate-300">
            <thead class="bg-slate-950 text-xs font-semibold uppercase text-slate-400 border-b border-slate-800">
              <tr>
                <th class="p-3 w-12 text-center">排名</th>
                <th class="p-3">根域名</th>
                <th class="p-3 text-center">包含子域名数</th>
                <th class="p-3 text-center">总引用频次</th>
                <th class="p-3 w-64">占比</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-slate-800/60 font-normal">
              <tr v-if="!stats.top_root_domains || stats.top_root_domains.length === 0">
                <td colspan="5" class="p-6 text-center text-slate-500">暂无排行数据</td>
              </tr>
              <tr
                v-for="(root, idx) in stats.top_root_domains"
                :key="root.root_domain"
                class="hover:bg-slate-800/40 transition-colors"
              >
                <td class="p-3 text-center font-bold font-mono" :class="idx < 3 ? 'text-amber-400' : 'text-slate-500'">
                  #{{ idx + 1 }}
                </td>
                <td class="p-3 font-medium font-mono text-slate-200">
                  {{ root.root_domain }}
                </td>
                <td class="p-3 text-center font-mono text-indigo-400">
                  {{ root.domain_count }} 个
                </td>
                <td class="p-3 text-center font-mono font-bold text-slate-200">
                  {{ root.total_occurrences }} 次
                </td>
                <td class="p-3">
                  <div class="w-full h-2 bg-slate-950 rounded-full overflow-hidden">
                    <div
                      class="h-full bg-indigo-500 rounded-full"
                      :style="{ width: getRootPercentage(root.total_occurrences) + '%' }"
                    ></div>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </template>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { ShieldAlert, Globe, Layers, CheckCircle2, Code2, Loader2 } from 'lucide-vue-next'
import client from '@/api/client'
import MetricCard from '@/components/common/MetricCard.vue'

const props = defineProps({
  taskId: {
    type: [Number, String],
    required: true
  }
})

const stats = ref({})
const loading = ref(false)

const loadStats = async () => {
  loading.value = true
  try {
    const res = await client.get(`/tasks/${props.taskId}/domains/stats`)
    stats.value = res || {}
  } catch (e) {
    console.error('Failed to load task analytics:', e)
  } finally {
    loading.value = false
  }
}

const getPercentage = (count) => {
  if (!stats.value.total_unique_domains || !count) return 0
  return ((count / stats.value.total_unique_domains) * 100).toFixed(1)
}

const getRootPercentage = (count) => {
  const top1 = stats.value.top_root_domains?.[0]?.total_occurrences || 1
  return Math.min(100, Math.round((count / top1) * 100))
}

onMounted(() => {
  loadStats()
})
</script>
