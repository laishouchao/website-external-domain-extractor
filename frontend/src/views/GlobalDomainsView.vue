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
              <td class="p-4">
                <div class="font-medium text-slate-100 flex items-center gap-2">
                  <Globe class="w-4 h-4 text-slate-400 flex-shrink-0" />
                  <span class="select-all">{{ item.domain }}</span>
                </div>
              </td>
              <td class="p-4 font-mono text-xs text-slate-400">
                {{ item.root_domain || '-' }}
              </td>
              <td class="p-4 text-center">
                <button
                  @click="openAssociatedDrawer(item.domain)"
                  class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-mono font-medium bg-indigo-500/10 text-indigo-300 border border-indigo-500/20 hover:bg-indigo-500/20 transition-colors"
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
                    class="text-slate-500 hover:text-amber-400 transition-colors p-0.5"
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
                    class="p-1.5 text-slate-400 hover:text-amber-400 hover:bg-slate-800 rounded-lg transition-colors"
                    title="快捷研判与全局情报"
                  >
                    <ShieldAlert class="w-4 h-4" />
                  </button>
                  <button
                    @click="openAssociatedDrawer(item.domain)"
                    class="p-1.5 text-slate-400 hover:text-indigo-400 hover:bg-slate-800 rounded-lg transition-colors"
                    title="关联任务溯源"
                  >
                    <FileSearch class="w-4 h-4" />
                  </button>
                  <button
                    @click="verifyGlobal(item.domain)"
                    class="p-1.5 text-slate-400 hover:text-emerald-400 hover:bg-slate-800 rounded-lg transition-colors"
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
      :title="`跨任务关联溯源: ${currentDomain}`"
      size="xl"
      @update:model-value="drawerOpen = $event"
    >
      <div class="space-y-4">
        <div class="flex items-center justify-between bg-slate-950 p-3 rounded-lg border border-slate-800 text-xs text-slate-400">
          <span>共在 <strong class="text-indigo-400">{{ store.associatedTasks.length }}</strong> 个扫描任务中检测到该外部域名</span>
          <div class="flex items-center gap-2">
            <button
              @click="exportAssociatedCsv"
              class="px-2.5 py-1 bg-slate-800 hover:bg-slate-700 text-slate-200 rounded text-xs flex items-center gap-1 border border-slate-700"
            >
              <Download class="w-3.5 h-3.5" /> 导出关联 CSV
            </button>
            <button
              @click="exportAssociatedJson"
              class="px-2.5 py-1 bg-slate-800 hover:bg-slate-700 text-slate-200 rounded text-xs flex items-center gap-1 border border-slate-700"
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
            <div class="flex items-center justify-between">
              <div>
                <div class="font-medium text-slate-200 text-sm flex items-center gap-2">
                  <span>{{ t.task_name || `任务 #${t.task_id}` }}</span>
                  <StatusBadge :status="t.task_status" type="task" />
                </div>
                <div class="text-xs text-slate-400 font-mono mt-0.5">
                  目标站点: {{ t.target_url }}
                </div>
              </div>

              <div class="flex items-center gap-2">
                <span class="px-2 py-0.5 rounded text-xs font-mono bg-slate-900 border border-slate-800 text-indigo-400">
                  发现频次: {{ t.occurrence_count }} 次
                </span>
                <router-link
                  :to="`/tasks/${t.task_id}`"
                  class="px-2.5 py-1 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded text-xs font-medium flex items-center gap-1 border border-slate-700"
                >
                  进入工作台
                  <ExternalLink class="w-3 h-3" />
                </router-link>
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
    <Modal
      :model-value="assessModalOpen"
      title="外部域名快捷研判与全局情报沉淀"
      max-width="max-w-2xl"
      @update:model-value="assessModalOpen = $event"
    >
      <form @submit.prevent="submitAssess" class="space-y-4">
        <!-- Target & Match Mode -->
        <div class="bg-slate-950 p-3.5 rounded-xl border border-slate-800 space-y-3">
          <label class="block text-xs font-semibold text-slate-300">规则通配类型与目标域名</label>
          <div class="grid grid-cols-2 gap-3">
            <label
              :class="[
                'flex items-start gap-2.5 p-3 rounded-lg border cursor-pointer transition text-xs',
                assessForm.match_type === 'root'
                  ? 'bg-purple-950/40 border-purple-500/60 text-purple-200'
                  : 'bg-slate-900 border-slate-800 text-slate-400 hover:border-slate-700'
              ]"
            >
              <input
                type="radio"
                value="root"
                v-model="assessForm.match_type"
                @change="onMatchTypeChange"
                class="mt-0.5 text-purple-500 focus:ring-0"
              />
              <div>
                <div class="font-bold flex items-center gap-1">
                  <span>根域通配 (*.root)</span>
                  <span class="text-[10px] px-1 rounded bg-purple-500/20 text-purple-300">推荐</span>
                </div>
                <div class="text-[11px] text-slate-400 mt-0.5">
                  通配管控主根下所有子域名及泛二级域
                </div>
              </div>
            </label>

            <label
              :class="[
                'flex items-start gap-2.5 p-3 rounded-lg border cursor-pointer transition text-xs',
                assessForm.match_type === 'exact'
                  ? 'bg-purple-950/40 border-purple-500/60 text-purple-200'
                  : 'bg-slate-900 border-slate-800 text-slate-400 hover:border-slate-700'
              ]"
            >
              <input
                type="radio"
                value="exact"
                v-model="assessForm.match_type"
                @change="onMatchTypeChange"
                class="mt-0.5 text-purple-500 focus:ring-0"
              />
              <div>
                <div class="font-bold">精确匹配 (Exact)</div>
                <div class="text-[11px] text-slate-400 mt-0.5">
                  仅针对当前完整 FQDN 域名生效
                </div>
              </div>
            </label>
          </div>

          <div>
            <div class="flex items-center justify-between text-xs text-slate-400 mb-1">
              <span>生效规则目标:</span>
              <span class="font-mono text-purple-400 font-semibold">{{ assessForm.match_type === 'root' ? `*.${assessForm.target_domain}` : assessForm.target_domain }}</span>
            </div>
            <input
              v-model="assessForm.target_domain"
              type="text"
              class="w-full px-3 py-2 bg-slate-900 border border-slate-700 rounded-lg text-sm text-slate-100 font-mono focus:outline-none focus:border-purple-500"
              placeholder="例如: evil-domain.com"
              required
            />
          </div>
        </div>

        <!-- Risk Level -->
        <div>
          <label class="block text-xs font-semibold text-slate-300 mb-2">研判风险等级</label>
          <div class="grid grid-cols-3 sm:grid-cols-6 gap-2 text-xs">
            <label
              :class="[
                'flex flex-col items-center justify-center p-2.5 rounded-lg border cursor-pointer transition text-center font-medium',
                assessForm.risk_level === 'critical'
                  ? 'bg-rose-950/80 border-rose-500 text-rose-200 font-bold shadow-sm'
                  : 'bg-slate-950 border-slate-800 text-slate-400 hover:border-slate-700'
              ]"
            >
              <input type="radio" value="critical" v-model="assessForm.risk_level" class="sr-only" />
              <span>严重</span>
              <span class="text-[10px] opacity-75 font-mono">Critical</span>
            </label>

            <label
              :class="[
                'flex flex-col items-center justify-center p-2.5 rounded-lg border cursor-pointer transition text-center font-medium',
                assessForm.risk_level === 'high'
                  ? 'bg-red-950/80 border-red-500 text-red-200 font-bold shadow-sm'
                  : 'bg-slate-950 border-slate-800 text-slate-400 hover:border-slate-700'
              ]"
            >
              <input type="radio" value="high" v-model="assessForm.risk_level" class="sr-only" />
              <span>高危</span>
              <span class="text-[10px] opacity-75 font-mono">High</span>
            </label>

            <label
              :class="[
                'flex flex-col items-center justify-center p-2.5 rounded-lg border cursor-pointer transition text-center font-medium',
                assessForm.risk_level === 'medium'
                  ? 'bg-amber-950/80 border-amber-500 text-amber-200 font-bold shadow-sm'
                  : 'bg-slate-950 border-slate-800 text-slate-400 hover:border-slate-700'
              ]"
            >
              <input type="radio" value="medium" v-model="assessForm.risk_level" class="sr-only" />
              <span>中危</span>
              <span class="text-[10px] opacity-75 font-mono">Medium</span>
            </label>

            <label
              :class="[
                'flex flex-col items-center justify-center p-2.5 rounded-lg border cursor-pointer transition text-center font-medium',
                assessForm.risk_level === 'low'
                  ? 'bg-blue-950/80 border-blue-500 text-blue-200 font-bold shadow-sm'
                  : 'bg-slate-950 border-slate-800 text-slate-400 hover:border-slate-700'
              ]"
            >
              <input type="radio" value="low" v-model="assessForm.risk_level" class="sr-only" />
              <span>低危</span>
              <span class="text-[10px] opacity-75 font-mono">Low</span>
            </label>

            <label
              :class="[
                'flex flex-col items-center justify-center p-2.5 rounded-lg border cursor-pointer transition text-center font-medium',
                assessForm.risk_level === 'safe'
                  ? 'bg-emerald-950/80 border-emerald-500 text-emerald-200 font-bold shadow-sm'
                  : 'bg-slate-950 border-slate-800 text-slate-400 hover:border-slate-700'
              ]"
            >
              <input type="radio" value="safe" v-model="assessForm.risk_level" class="sr-only" />
              <span>官方安全</span>
              <span class="text-[10px] opacity-75 font-mono">Safe</span>
            </label>

            <label
              :class="[
                'flex flex-col items-center justify-center p-2.5 rounded-lg border cursor-pointer transition text-center font-medium',
                assessForm.risk_level === 'pending'
                  ? 'bg-slate-800 border-slate-500 text-slate-200 font-bold shadow-sm'
                  : 'bg-slate-950 border-slate-800 text-slate-400 hover:border-slate-700'
              ]"
            >
              <input type="radio" value="pending" v-model="assessForm.risk_level" class="sr-only" />
              <span>待研判</span>
              <span class="text-[10px] opacity-75 font-mono">Pending</span>
            </label>
          </div>
        </div>

        <!-- Tags Selection -->
        <div class="space-y-2">
          <label class="block text-xs font-semibold text-slate-300">研判属性标签 (点击快速添加/移除)</label>
          <div class="flex flex-wrap gap-1.5">
            <button
              type="button"
              v-for="tag in presetTags"
              :key="tag"
              @click="toggleTag(tag)"
              :class="[
                'px-2.5 py-1 rounded-lg text-xs transition border flex items-center gap-1',
                assessForm.tags.includes(tag)
                  ? 'bg-purple-950 text-purple-200 border-purple-500 font-semibold'
                  : 'bg-slate-950 text-slate-400 border-slate-800 hover:border-slate-700 hover:text-slate-200'
              ]"
            >
              <span>{{ assessForm.tags.includes(tag) ? '✓' : '+' }}</span>
              <span>{{ tag }}</span>
            </button>
          </div>

          <!-- Active custom tags and input -->
          <div class="flex items-center gap-2 pt-1">
            <input
              v-model="customTagInput"
              @keydown.enter.prevent="addCustomTag"
              type="text"
              placeholder="添加自定义标签 (按回车添加)..."
              class="flex-1 px-3 py-1.5 bg-slate-950 border border-slate-700 rounded-lg text-xs text-slate-200 focus:outline-none focus:border-purple-500"
            />
            <button
              type="button"
              @click="addCustomTag"
              class="px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs rounded-lg border border-slate-700 cursor-pointer"
            >
              添加标签
            </button>
          </div>

          <div v-if="assessForm.tags.length" class="flex flex-wrap gap-1.5 pt-1">
            <span class="text-xs text-slate-500 self-center">已选标签:</span>
            <span
              v-for="tag in assessForm.tags"
              :key="tag"
              class="px-2 py-0.5 rounded text-xs bg-indigo-500/10 text-indigo-300 border border-indigo-500/30 flex items-center gap-1 font-medium"
            >
              {{ tag }}
              <button type="button" @click="removeTag(tag)" class="hover:text-rose-400 cursor-pointer">✕</button>
            </span>
          </div>
        </div>

        <!-- Remark -->
        <div>
          <label class="block text-xs font-semibold text-slate-300 mb-1">研判说明与处置依据</label>
          <textarea
            v-model="assessForm.remark"
            rows="2"
            placeholder="说明研判依据，例如：属于跨任务公共CDN服务，或恶意赌博暗链引流域名..."
            class="w-full px-3 py-2 bg-slate-950 border border-slate-700 rounded-lg text-xs text-slate-200 focus:outline-none focus:border-purple-500"
          ></textarea>
        </div>

        <!-- Sync to History Checkbox -->
        <div class="flex items-start gap-2 pt-2 border-t border-slate-800">
          <input
            id="syncHistory"
            v-model="assessForm.sync_to_history"
            type="checkbox"
            class="mt-0.5 rounded bg-slate-900 border-slate-700 text-purple-600 focus:ring-0 cursor-pointer"
          />
          <div>
            <label for="syncHistory" class="text-xs text-slate-300 font-medium cursor-pointer select-none">
              立即回溯同步全系统历史任务与待整改工单
            </label>
            <p class="text-[11px] text-slate-500">
              自动更新数据库中所有包含该外部域名的历史扫描记录，并联动刷新风险页面待处置清单
            </p>
          </div>
        </div>

        <!-- Actions -->
        <div class="flex justify-end gap-2.5 pt-4 border-t border-slate-800">
          <button
            type="button"
            @click="assessModalOpen = false"
            class="px-4 py-2 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-lg text-xs transition"
          >
            取消
          </button>
          <button
            type="submit"
            :disabled="savingAssess"
            class="px-5 py-2 bg-purple-600 hover:bg-purple-500 disabled:opacity-50 text-white rounded-lg text-xs font-semibold flex items-center gap-1.5 shadow-lg shadow-purple-600/20 transition cursor-pointer"
          >
            <Loader2 v-if="savingAssess" class="w-3.5 h-3.5 animate-spin" />
            <ShieldAlert v-else class="w-3.5 h-3.5" />
            保存研判并同步
          </button>
        </div>
      </form>
    </Modal>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import {
  Database, Globe, Layers, Briefcase, ShieldAlert, Download,
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

const store = useGlobalDomainsStore()
const ui = useUIStore()

const drawerOpen = ref(false)
const currentDomain = ref('')
const verifying = ref(null)

// Assess modal state
const assessModalOpen = ref(false)
const activeAssessItem = ref(null)
const savingAssess = ref(false)
const customTagInput = ref('')
const presetTags = [
  '黑产博彩', '暗链挂马', '低俗色情', '恶意欺诈',
  '钓鱼盗号', '广告引流', '公共静态CDN', '官方合作',
  '纯IP外链', '失效废弃'
]

const assessForm = ref({
  match_type: 'root',
  target_domain: '',
  risk_level: 'high',
  tags: [],
  remark: '',
  sync_to_history: true
})

const openAssessModal = (item) => {
  activeAssessItem.value = item
  assessForm.value = {
    match_type: item.root_domain ? 'root' : 'exact',
    target_domain: item.root_domain || item.domain,
    risk_level: item.risk_level && item.risk_level !== 'pending' ? item.risk_level : 'high',
    tags: Array.isArray(item.risk_tags) ? [...item.risk_tags] : (item.risk_tags ? [item.risk_tags] : []),
    remark: item.risk_remark || '',
    sync_to_history: true
  }
  customTagInput.value = ''
  assessModalOpen.value = true
}

const onMatchTypeChange = () => {
  if (!activeAssessItem.value) return
  if (assessForm.value.match_type === 'root') {
    assessForm.value.target_domain = activeAssessItem.value.root_domain || activeAssessItem.value.domain
  } else {
    assessForm.value.target_domain = activeAssessItem.value.domain
  }
}

const toggleTag = (tagName) => {
  const idx = assessForm.value.tags.indexOf(tagName)
  if (idx > -1) {
    assessForm.value.tags.splice(idx, 1)
  } else {
    assessForm.value.tags.push(tagName)
  }
}

const addCustomTag = () => {
  const t = customTagInput.value.trim()
  if (t && !assessForm.value.tags.includes(t)) {
    assessForm.value.tags.push(t)
    customTagInput.value = ''
  }
}

const removeTag = (tag) => {
  const idx = assessForm.value.tags.indexOf(tag)
  if (idx > -1) {
    assessForm.value.tags.splice(idx, 1)
  }
}

const submitAssess = async () => {
  if (!assessForm.value.target_domain.trim()) {
    ui.showToast('目标域名不能为空', 'error')
    return
  }
  savingAssess.value = true
  try {
    const payload = {
      domain: assessForm.value.target_domain.trim(),
      match_type: assessForm.value.match_type,
      risk_level: assessForm.value.risk_level,
      category: assessForm.value.tags[0] || '',
      tags: assessForm.value.tags,
      remark: assessForm.value.remark.trim(),
      sync_to_history: Boolean(assessForm.value.sync_to_history)
    }
    await client.post('/risk-profiles', payload)
    ui.showToast(`研判规则已生效！目标: ${payload.match_type === 'root' ? '*.' : ''}${payload.domain}`, 'success')
    assessModalOpen.value = false
    await Promise.all([
      store.loadDomains(store.page),
      store.loadStats()
    ])
  } catch (e) {
    ui.showToast('保存研判失败: ' + e.message, 'error')
  } finally {
    savingAssess.value = false
  }
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

const openAssociatedDrawer = async (domain) => {
  currentDomain.value = domain
  drawerOpen.value = true
  await store.loadAssociatedTasks(domain)
}

const verifyGlobal = async (domain) => {
  verifying.value = domain
  try {
    await store.verifyDomainAcrossTasks(domain)
  } catch (e) {
    // handled by store toast
  } finally {
    verifying.value = null
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
