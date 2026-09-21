<template>
  <div class="space-y-6">
    <!-- Header & Action Ribbon -->
    <div class="flex flex-wrap items-center justify-between gap-4">
      <div>
        <h1 class="text-2xl font-bold text-slate-100 flex items-center gap-2.5">
          <Database class="w-6 h-6 text-indigo-400" />
          全网外部域名知识库
        </h1>
        <p class="text-xs text-slate-400 mt-1">
          汇聚并去重所有扫描任务发现的外部域名资产，支持跨站点关联分析、集中研判与全库整改复测
        </p>
      </div>

      <div class="flex items-center gap-2">
        <button
          @click="exportCsv"
          class="px-3.5 py-2 bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 rounded-xl text-xs font-medium flex items-center gap-1.5 transition-colors shadow-sm"
        >
          <Download class="w-4 h-4 text-emerald-400" />
          导出全库域名 CSV
        </button>
        <button
          @click="refresh"
          class="p-2 bg-slate-900 hover:bg-slate-800 text-slate-400 hover:text-slate-200 border border-slate-800 rounded-xl transition-colors"
          title="刷新数据"
        >
          <RefreshCw class="w-4 h-4" :class="{ 'animate-spin': store.loading }" />
        </button>
      </div>
    </div>

    <!-- 4 Key Metric Cards -->
    <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
      <MetricCard
        title="全库去重域名"
        :value="store.stats.total_unique_domains || 0"
        subtitle="独立非本站外部域名总数"
        icon="Globe"
        color="indigo"
      />
      <MetricCard
        title="全网引用频次"
        :value="store.stats.total_domain_occurrences || 0"
        subtitle="跨页面代码被引用总次数"
        icon="Layers"
        color="cyan"
      />
      <MetricCard
        title="关联分析任务"
        :value="store.stats.active_tasks_count || 0"
        subtitle="贡献域名数据的扫描任务"
        icon="Briefcase"
        color="amber"
      />
      <MetricCard
        title="涉险违规域名"
        :value="store.stats.risk_domains_count || 0"
        subtitle="中高危及严重风险级别"
        icon="ShieldAlert"
        color="rose"
      />
    </div>

    <!-- Filter and Search Bar -->
    <div class="bg-slate-900 border border-slate-800 rounded-xl p-4 flex flex-wrap items-center justify-between gap-4">
      <div class="flex flex-wrap items-center gap-3">
        <!-- Search Input -->
        <div class="relative w-64">
          <Search class="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
          <input
            v-model="store.filters.search"
            type="text"
            placeholder="搜索域名或主根域名..."
            class="w-full pl-9 pr-3 py-1.5 bg-slate-950 border border-slate-700 rounded-lg text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:border-indigo-500"
            @keyup.enter="handleSearch"
          />
        </div>

        <!-- Risk Level Select -->
        <select
          v-model="store.filters.riskLevel"
          class="bg-slate-950 border border-slate-700 text-slate-300 text-sm rounded-lg px-3 py-1.5 focus:outline-none focus:border-indigo-500"
          @change="handleSearch"
        >
          <option value="">全部风险等级</option>
          <option value="risk_only">所有风险项 (高危/中危/严重)</option>
          <option value="critical">严重风险 (Critical)</option>
          <option value="high">高危风险 (High)</option>
          <option value="medium">中危风险 (Medium)</option>
          <option value="low">低危风险 (Low)</option>
          <option value="safe">安全可信 (Safe)</option>
          <option value="pending">待研判 (Pending)</option>
        </select>

        <!-- Source Type Select -->
        <select
          v-model="store.filters.sourceType"
          class="bg-slate-950 border border-slate-700 text-slate-300 text-sm rounded-lg px-3 py-1.5 focus:outline-none focus:border-indigo-500"
          @change="handleSearch"
        >
          <option value="all">全部来源属性</option>
          <option value="link">包含超链接 (Link)</option>
          <option value="text">包含文本/代码 (Text)</option>
        </select>

        <!-- Verify Status Select -->
        <select
          v-model="store.filters.verifyStatus"
          class="bg-slate-950 border border-slate-700 text-slate-300 text-sm rounded-lg px-3 py-1.5 focus:outline-none focus:border-indigo-500"
          @change="handleSearch"
        >
          <option value="">全部复测状态</option>
          <option value="unverified">未复测</option>
          <option value="verified_clean">已彻底清除</option>
          <option value="verified_failed">仍有残留</option>
          <option value="error">复测异常</option>
        </select>

        <!-- Sort Select -->
        <select
          v-model="store.filters.sortBy"
          class="bg-slate-950 border border-slate-700 text-slate-300 text-sm rounded-lg px-3 py-1.5 focus:outline-none focus:border-indigo-500"
          @change="handleSearch"
        >
          <option value="total_occurrences">按总频次排序</option>
          <option value="task_count">按关联任务数排序</option>
          <option value="domain">按域名首字母排序</option>
          <option value="risk_level">按风险等级排序</option>
        </select>

        <button
          @click="handleSearch"
          class="px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-200 text-sm font-medium rounded-lg transition-colors"
        >
          筛选
        </button>
        <button
          @click="resetFilters"
          class="px-2.5 py-1.5 text-slate-400 hover:text-slate-200 text-sm transition-colors"
        >
          重置
        </button>
      </div>
    </div>

    <!-- Domains Table -->
    <div class="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden shadow-sm">
      <div class="overflow-x-auto">
        <table class="w-full text-left text-sm text-slate-300">
          <thead class="bg-slate-950/80 text-xs font-semibold uppercase text-slate-400 border-b border-slate-800">
            <tr>
              <th class="p-4">外部域名</th>
              <th class="p-4">所属主根域名</th>
              <th class="p-4 text-center">关联任务数</th>
              <th class="p-4 text-center">累计引用频次</th>
              <th class="p-4">来源类型</th>
              <th class="p-4">风险等级</th>
              <th class="p-4">复测状态</th>
              <th class="p-4 text-right">操作</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-slate-800/60 font-normal">
            <tr v-if="store.loading" class="text-center py-8">
              <td colspan="8" class="p-8 text-slate-500">
                <div class="flex items-center justify-center gap-2">
                  <Loader2 class="w-5 h-5 animate-spin text-indigo-400" />
                  <span>正在汇总全网外部域名数据...</span>
                </div>
              </td>
            </tr>
            <tr v-else-if="store.domains.length === 0" class="text-center py-8">
              <td colspan="8" class="p-8 text-slate-500">
                暂无符合条件的全局外部域名
              </td>
            </tr>
            <tr
              v-for="item in store.domains"
              :key="item.domain"
              class="hover:bg-slate-800/40 transition-colors"
            >
              <td class="p-4 cursor-pointer" @click="openAssociatedDrawer(item.domain, item)" title="点击查看跨任务关联溯源及代码证据">
                <div class="font-medium text-slate-100 flex items-center gap-2 hover:text-indigo-400 transition-colors">
                  <Globe class="w-4 h-4 text-slate-400 flex-shrink-0" />
                  <span class="select-all">{{ item.domain }}</span>
                </div>
              </td>
              <td class="p-4 font-mono text-xs text-slate-400">
                {{ item.root_domain || '-' }}
              </td>
              <td class="p-4 text-center">
                <button
                  @click="openAssociatedDrawer(item.domain, item)"
                  class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-mono font-medium bg-indigo-500/10 text-indigo-300 border border-indigo-500/20 hover:bg-indigo-500/20 transition-colors cursor-pointer"
                  title="点击查看所有关联任务及代码"
                >
                  <Briefcase class="w-3 h-3" />
                  {{ item.task_count || 1 }} 个任务
                </button>
              </td>
              <td class="p-4 text-center">
                <span class="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-mono font-medium bg-slate-800 text-slate-200 border border-slate-700">
                  {{ item.total_occurrences }} 次
                </span>
              </td>
              <td class="p-4">
                <div class="flex items-center gap-1.5">
                  <span
                    v-if="item.has_link"
                    class="px-1.5 py-0.5 rounded text-[11px] font-medium bg-blue-500/10 text-blue-400 border border-blue-500/20"
                  >
                    超链接
                  </span>
                  <span
                    v-if="item.has_text"
                    class="px-1.5 py-0.5 rounded text-[11px] font-medium bg-purple-500/10 text-purple-400 border border-purple-500/20"
                  >
                    文本/脚本
                  </span>
                </div>
              </td>
              <td class="p-4">
                <div class="flex items-center gap-1.5">
                  <RiskBadge :level="item.risk_level" />
                  <button
                    @click="openAssessModal(item)"
                    class="text-slate-500 hover:text-amber-400 transition-colors p-0.5 cursor-pointer"
                    title="快捷研判"
                  >
                    <ShieldAlert class="w-3.5 h-3.5" />
                  </button>
                </div>
                <div v-if="item.risk_tags && item.risk_tags.length" class="flex flex-wrap gap-1 mt-1">
                  <span
                    v-for="tag in (Array.isArray(item.risk_tags) ? item.risk_tags : [item.risk_tags]).slice(0, 3)"
                    :key="tag"
                    class="text-[10px] px-1.5 py-0.2 rounded bg-slate-800 text-slate-400 font-mono"
                  >
                    {{ tag }}
                  </span>
                </div>
              </td>
              <td class="p-4">
                <StatusBadge :status="item.verify_status || 'unverified'" type="verify" />
              </td>
              <td class="p-4 text-right">
                <div class="flex items-center justify-end gap-1.5">
                  <button
                    @click="openAssessModal(item)"
                    class="p-1.5 text-slate-400 hover:text-amber-400 hover:bg-slate-800 rounded-lg transition-colors cursor-pointer"
                    title="快捷研判与全局情报"
                  >
                    <ShieldAlert class="w-4 h-4" />
                  </button>
                  <button
                    @click="openAssociatedDrawer(item.domain, item)"
                    class="p-1.5 text-slate-400 hover:text-indigo-400 hover:bg-slate-800 rounded-lg transition-colors cursor-pointer"
                    title="关联任务溯源"
                  >
                    <FileSearch class="w-4 h-4" />
                  </button>
                  <button
                    @click="verifyGlobal(item.domain)"
                    class="p-1.5 text-slate-400 hover:text-emerald-400 hover:bg-slate-800 rounded-lg transition-colors cursor-pointer"
                    :disabled="verifying === item.domain"
                    title="全库跨任务一键复测"
                  >
                    <RefreshCw class="w-4 h-4" :class="{ 'animate-spin': verifying === item.domain }" />
                  </button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- Pagination -->
      <Pagination
        :current-page="store.page"
        :total="store.total"
        :page-size="store.pageSize"
        @page-change="onPageChange"
      />
    </div>

    <!-- Associated Tasks Drawer -->
    <Drawer
      :model-value="drawerOpen"
      size="xl"
      @update:model-value="drawerOpen = $event"
    >
      <template #title>
        <div class="flex items-center gap-2.5 flex-wrap">
          <Globe class="w-5 h-5 text-indigo-400 flex-shrink-0" />
          <span class="font-mono text-base font-bold">跨任务关联溯源: {{ currentDomain }}</span>
          <RiskBadge v-if="currentDomainItem?.risk_level" :level="currentDomainItem.risk_level" />
          <StatusBadge v-if="currentDomainItem?.verify_status" :status="currentDomainItem.verify_status" type="verify" />
        </div>
      </template>

      <div class="space-y-4">
        <!-- Risk Domain Verification & Remediation Banner -->
        <div
          v-if="isRiskDomain || currentDomainItem?.verify_status"
          class="bg-slate-950 border border-slate-800 rounded-xl p-4 flex flex-col sm:flex-row sm:items-center justify-between gap-3 shadow-sm"
        >
          <div class="space-y-1">
            <div class="flex items-center gap-2 flex-wrap">
              <ShieldAlert v-if="isRiskDomain" class="w-4 h-4 text-rose-400 flex-shrink-0" />
              <ShieldCheck v-else class="w-4 h-4 text-emerald-400 flex-shrink-0" />
              <span class="text-xs font-bold text-slate-200">
                {{ isRiskDomain ? '风险域名处置与闭环复测' : '外部域名跨任务复测' }}
              </span>
              <RiskBadge v-if="currentDomainItem?.risk_level" :level="currentDomainItem.risk_level" />
              <StatusBadge :status="currentDomainItem?.verify_status || 'unverified'" type="verify" />
            </div>
            <p class="text-[11px] text-slate-400">
              {{
                currentDomainItem?.verify_status === 'verified_clean'
                  ? '全系统跨任务复测结论：已完全清除修复，所有关联页面的违规外链均已下线移除。'
                  : (currentDomainItem?.verify_status === 'verified_failed'
                    ? '全系统跨任务复测结论：仍存在未清除代码，请参考下方各任务开展专项修复整改。'
                    : '全量扫描该风险域名在所有任务中的历史涉险页面代码，自动检测是否已彻底修复移除。')
              }}
            </p>
          </div>

          <div class="flex items-center gap-2 flex-shrink-0">
            <button
              @click="verifyGlobal(currentDomain)"
              :disabled="verifying === currentDomain"
              class="px-3.5 py-1.5 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white rounded-lg text-xs font-semibold flex items-center gap-1.5 shadow-md shadow-indigo-600/20 transition cursor-pointer"
              title="一键并发复测所有关联任务下的全部页面代码"
            >
              <RefreshCw class="w-3.5 h-3.5" :class="{ 'animate-spin': verifying === currentDomain }" />
              <span>{{ verifying === currentDomain ? '全库检测中...' : '跨任务一键复测' }}</span>
            </button>
            <button
              @click="openAssessModal(currentDomainItem || { domain: currentDomain })"
              class="px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-amber-300 border border-slate-700 rounded-lg text-xs font-medium flex items-center gap-1 transition cursor-pointer"
              title="修改研判风险等级与情报规则"
            >
              <ShieldAlert class="w-3.5 h-3.5" />
              <span>快捷研判</span>
            </button>
          </div>
        </div>

        <!-- Task Count and Export Toolbar -->
        <div class="flex items-center justify-between bg-slate-950 p-3 rounded-lg border border-slate-800 text-xs text-slate-400">
          <span>共在 <strong class="text-indigo-400">{{ store.associatedTasks.length }}</strong> 个扫描任务中检测到该外部域名</span>
          <div class="flex items-center gap-2">
            <button
              @click="exportAssociatedCsv"
              class="px-2.5 py-1 bg-slate-800 hover:bg-slate-700 text-slate-200 rounded text-xs flex items-center gap-1 border border-slate-700 cursor-pointer"
            >
              <Download class="w-3.5 h-3.5" /> 导出关联 CSV
            </button>
            <button
              @click="exportAssociatedJson"
              class="px-2.5 py-1 bg-slate-800 hover:bg-slate-700 text-slate-200 rounded text-xs flex items-center gap-1 border border-slate-700 cursor-pointer"
            >
              <Download class="w-3.5 h-3.5" /> 导出关联 JSON
            </button>
          </div>
        </div>

        <div v-if="store.loadingTasks" class="flex items-center justify-center py-12 text-slate-500 gap-2">
          <Loader2 class="w-5 h-5 animate-spin text-indigo-400" />
          <span>正在检索跨任务关联记录...</span>
        </div>

        <div v-else-if="store.associatedTasks.length === 0" class="text-center py-12 text-slate-500">
          暂无关联任务详情
        </div>

        <div v-else class="space-y-4">
          <div
            v-for="t in store.associatedTasks"
            :key="t.task_id"
            class="bg-slate-950 border border-slate-800 rounded-xl p-4 space-y-3"
          >
            <!-- Task Header -->
            <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-2.5">
              <div>
                <div class="font-medium text-slate-200 text-sm flex items-center gap-2">
                  <span>{{ t.task_name || `任务 #${t.task_id}` }}</span>
                  <StatusBadge :status="t.task_status" type="task" />
                </div>
                <div class="text-xs text-slate-400 font-mono mt-0.5 flex items-center gap-1.5">
                  <span>目标站点:</span>
                  <a :href="t.target_url" target="_blank" class="text-slate-300 hover:text-indigo-400 hover:underline truncate max-w-sm font-mono" :title="t.target_url">
                    {{ t.target_url }}
                  </a>
                </div>
              </div>

              <div class="flex items-center gap-2 flex-wrap sm:flex-nowrap justify-end">
                <span class="px-2 py-1 rounded text-xs font-mono bg-slate-900 border border-slate-800 text-indigo-400 flex-shrink-0">
                  频次: {{ t.occurrence_count }} 次
                </span>

                <!-- Task Verification Status Badge -->
                <StatusBadge v-if="t.verify_status" :status="t.verify_status" type="verify" class="flex-shrink-0" />

                <!-- 修复检测 Button -->
                <button
                  @click="verifyTask(t.task_id, currentDomain)"
                  :disabled="taskVerifying[t.task_id] || verifying === currentDomain"
                  class="px-2.5 py-1 bg-emerald-600/20 hover:bg-emerald-600/30 text-emerald-300 border border-emerald-500/40 rounded text-xs font-medium flex items-center gap-1 transition-colors disabled:opacity-50 cursor-pointer flex-shrink-0"
                  :title="`全量检测任务 #${t.task_id} 下该域名的全部页面代码是否已彻底移除`"
                >
                  <RefreshCw class="w-3.5 h-3.5" :class="{ 'animate-spin': taskVerifying[t.task_id] }" />
                  <span>{{ taskVerifying[t.task_id] ? '检测中...' : '修复检测' }}</span>
                </button>

                <!-- 进入工作台 -->
                <router-link
                  :to="`/tasks/${t.task_id}`"
                  class="px-2.5 py-1 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded text-xs font-medium flex items-center gap-1 border border-slate-700 flex-shrink-0"
                >
                  工作台
                  <ExternalLink class="w-3 h-3" />
                </router-link>
              </div>
            </div>

            <!-- Task Verification Progress & Summary Details -->
            <div
              v-if="t.verify_status || t.verify_progress || taskVerifying[t.task_id] || verifying === currentDomain"
              class="bg-slate-900/80 border border-slate-800/90 rounded-lg p-3 space-y-2 text-xs"
            >
              <div class="flex items-center justify-between gap-2 flex-wrap">
                <div class="flex items-center gap-2">
                  <span class="text-slate-400 font-medium">任务复测进度:</span>
                  <span v-if="taskVerifying[t.task_id] || verifying === currentDomain" class="text-indigo-400 font-mono flex items-center gap-1.5 font-bold">
                    <Loader2 class="w-3.5 h-3.5 animate-spin" />
                    正在全量并发拉取并复测全部关联页面 (共 {{ t.occurrence_count }} 条记录)...
                  </span>
                  <span v-else-if="t.total_pages > 0" class="font-mono text-xs font-bold"
                    :class="t.verify_status === 'verified_clean' ? 'text-emerald-400' : 'text-amber-400'"
                  >
                    已清除 {{ t.cleared_count || 0 }} / 仍存留 {{ t.still_present_count || 0 }} (共 {{ t.total_pages }} 个页面)
                  </span>
                  <span v-else-if="t.verify_progress" class="font-mono text-slate-300">
                    {{ t.verify_progress }}
                  </span>
                </div>
                <span v-if="t.verify_time && !taskVerifying[t.task_id] && verifying !== currentDomain" class="text-slate-500 font-mono text-[11px]">
                  复测时间: {{ t.verify_time }}
                </span>
              </div>

              <!-- Progress Bar -->
              <div v-if="!taskVerifying[t.task_id] && verifying !== currentDomain && t.total_pages > 0" class="w-full bg-slate-950 rounded-full h-1.5 overflow-hidden flex">
                <div
                  class="bg-emerald-500 h-full transition-all duration-500"
                  :style="{ width: `${Math.round(((t.cleared_count || 0) / t.total_pages) * 100)}%` }"
                ></div>
                <div
                  class="bg-rose-500 h-full transition-all duration-500"
                  :style="{ width: `${Math.round(((t.still_present_count || 0) / t.total_pages) * 100)}%` }"
                ></div>
              </div>

              <div v-if="!taskVerifying[t.task_id] && verifying !== currentDomain && t.verify_summary" class="text-[11px] text-slate-400">
                {{ t.verify_summary }}
              </div>
            </div>

            <!-- Occurrences in this task -->
            <div v-if="t.occurrences && t.occurrences.length" class="space-y-2 pt-2 border-t border-slate-900">
              <div
                v-for="(occ, idx) in t.occurrences"
                :key="idx"
                class="bg-slate-900/60 border border-slate-800/80 rounded-lg p-3 space-y-2 text-xs"
              >
                <div class="flex items-center justify-between gap-3">
                  <div class="flex items-center gap-2 truncate flex-1 min-w-0">
                    <span class="px-1.5 py-0.5 rounded text-[10px] uppercase font-bold flex-shrink-0"
                      :class="occ.source_type === 'link' ? 'bg-blue-500/20 text-blue-400' : 'bg-purple-500/20 text-purple-400'"
                    >
                      {{ occ.source_type }}
                    </span>
                    <a :href="occ.page_url" target="_blank" class="text-indigo-400 hover:underline truncate font-mono" :title="occ.page_url">
                      {{ occ.page_url }}
                    </a>
                  </div>
                  <span class="text-slate-500 font-mono flex-shrink-0 text-[11px]">{{ occ.created_at || '' }}</span>
                </div>

                <CodeSnippet
                  :code="occ.context_snippet || occ.raw_match"
                  :highlight-term="currentDomain"
                />
              </div>
            </div>
            <div v-else class="text-xs text-slate-500 italic">
              示例页面: {{ t.sample_page_url || '未提供' }}
            </div>
          </div>
        </div>
      </div>
    </Drawer>

    <!-- Global Domain Quick Assess Modal (快捷研判与全局情报) -->
    <RiskAssessModal
      v-model="assessModalOpen"
      :item="activeAssessItem"
      @saved="handleAssessSaved"
    />
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import {
  Database, Globe, Layers, Briefcase, ShieldAlert, ShieldCheck, Download,
  RefreshCw, Search, FileSearch, ExternalLink, Loader2
} from 'lucide-vue-next'
import { useGlobalDomainsStore } from '@/stores/globalDomains'
import { useUIStore } from '@/stores/ui'
import client from '@/api/client'
import MetricCard from '@/components/common/MetricCard.vue'
import RiskBadge from '@/components/common/RiskBadge.vue'
import StatusBadge from '@/components/common/StatusBadge.vue'
import Pagination from '@/components/common/Pagination.vue'
import Drawer from '@/components/common/Drawer.vue'
import Modal from '@/components/common/Modal.vue'
import CodeSnippet from '@/components/common/CodeSnippet.vue'
import RiskAssessModal from '@/components/common/RiskAssessModal.vue'

const store = useGlobalDomainsStore()
const ui = useUIStore()

const drawerOpen = ref(false)
const currentDomain = ref('')
const currentDomainItem = ref(null)
const verifying = ref(null)
const taskVerifying = ref({})

const isRiskDomain = computed(() => {
  const level = currentDomainItem.value?.risk_level
  return ['critical', 'high', 'medium', 'low'].includes(level)
})

// Assess modal state
const assessModalOpen = ref(false)
const activeAssessItem = ref(null)

const openAssessModal = (item) => {
  activeAssessItem.value = item
  assessModalOpen.value = true
}

const handleAssessSaved = async (payload) => {
  if (currentDomainItem.value && (currentDomainItem.value.domain === payload.domain || currentDomainItem.value.root_domain === payload.domain)) {
    currentDomainItem.value.risk_level = payload.risk_level
    currentDomainItem.value.risk_tags = payload.tags
  }
  await Promise.all([
    store.loadDomains(store.page),
    store.loadStats()
  ])
}

const handleSearch = () => {
  store.loadDomains(1)
}

const resetFilters = () => {
  store.filters.search = ''
  store.filters.riskLevel = ''
  store.filters.sourceType = 'all'
  store.filters.verifyStatus = ''
  store.filters.sortBy = 'total_occurrences'
  store.loadDomains(1)
}

const onPageChange = (p) => {
  store.loadDomains(p)
}

const refresh = async () => {
  await Promise.all([
    store.loadStats(),
    store.loadDomains(store.page)
  ])
}

const openAssociatedDrawer = async (domain, item = null) => {
  currentDomain.value = domain
  currentDomainItem.value = item || store.domains.find(d => d.domain === domain) || null
  drawerOpen.value = true
  await store.loadAssociatedTasks(domain)
}

const verifyGlobal = async (domain) => {
  verifying.value = domain
  try {
    const res = await store.verifyDomainAcrossTasks(domain)
    if (res?.overall_status && currentDomainItem.value) {
      currentDomainItem.value.verify_status = res.overall_status
    }
  } catch (e) {
    // handled by store toast
  } finally {
    verifying.value = null
  }
}

const verifyTask = async (taskId, domain) => {
  taskVerifying.value[taskId] = true
  try {
    const res = await store.verifyDomainInTask(domain, taskId)
    if (res?.verify_status && currentDomainItem.value) {
      const allClean = store.associatedTasks.every(t => t.verify_status === 'verified_clean')
      if (allClean) {
        currentDomainItem.value.verify_status = 'verified_clean'
      } else if (res.verify_status === 'verified_failed') {
        currentDomainItem.value.verify_status = 'verified_failed'
      }
    }
  } catch (e) {
    // handled in store
  } finally {
    taskVerifying.value[taskId] = false
  }
}

const exportCsv = () => {
  window.open('/api/global-domains/export/csv', '_blank')
}

const exportAssociatedCsv = () => {
  window.open(`/api/global-domains/${encodeURIComponent(currentDomain.value)}/tasks/export/csv`, '_blank')
}

const exportAssociatedJson = () => {
  window.open(`/api/global-domains/${encodeURIComponent(currentDomain.value)}/tasks/export/json`, '_blank')
}

onMounted(() => {
  refresh()
})
</script>
