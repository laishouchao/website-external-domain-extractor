<template>
  <div class="space-y-6">
    <!-- Header & Action Ribbon -->
    <div class="flex flex-wrap items-center justify-between gap-4">
      <div>
        <h1 class="text-2xl font-bold text-slate-100 flex items-center gap-2.5">
          <ShieldAlert class="w-6 h-6 text-indigo-400" />
          威胁情报与风险研判知识库
        </h1>
        <p class="text-xs text-slate-400 mt-1">
          维护黑灰产、暗链、恶意重定向等已知违规外部域名特征库，扫描任务将自动比对研判并支持存量全库历史回溯
        </p>
      </div>

      <div class="flex items-center gap-2">
        <button
          @click="openAddModal"
          class="px-3.5 py-2 bg-indigo-600 hover:bg-indigo-500 text-white rounded-xl text-xs font-semibold flex items-center gap-1.5 transition-colors shadow-sm"
        >
          <Plus class="w-4 h-4" />
          添加情报规则
        </button>

        <button
          @click="openBatchModal"
          class="px-3.5 py-2 bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 rounded-xl text-xs font-medium flex items-center gap-1.5 transition-colors shadow-sm"
        >
          <Upload class="w-4 h-4 text-cyan-400" />
          批量导入
        </button>

        <button
          @click="syncHistory"
          :disabled="syncing"
          class="px-3.5 py-2 bg-amber-600/20 hover:bg-amber-600/30 text-amber-300 border border-amber-500/30 rounded-xl text-xs font-medium flex items-center gap-1.5 transition-colors"
          title="将当前规则库全量回溯到历史所有扫描任务与域名"
        >
          <RefreshCw class="w-4 h-4 text-amber-400" :class="{ 'animate-spin': syncing }" />
          全库历史回溯
        </button>

        <button
          @click="exportRules"
          class="px-3.5 py-2 bg-slate-800 hover:bg-slate-700 text-slate-300 border border-slate-700 rounded-xl text-xs font-medium flex items-center gap-1.5 transition-colors"
        >
          <Download class="w-4 h-4" />
          导出规则
        </button>
      </div>
    </div>

    <!-- Filter Bar -->
    <div class="bg-slate-900 border border-slate-800 rounded-xl p-4 flex flex-wrap items-center justify-between gap-4">
      <div class="flex flex-wrap items-center gap-3">
        <!-- Search Input -->
        <div class="relative w-64">
          <Search class="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
          <input
            v-model="search"
            type="text"
            placeholder="搜索目标域名、分类或备注..."
            class="w-full pl-9 pr-3 py-1.5 bg-slate-950 border border-slate-700 rounded-lg text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:border-indigo-500"
            @keyup.enter="handleSearch"
          />
        </div>

        <!-- Risk Level Select -->
        <select
          v-model="riskLevel"
          class="bg-slate-950 border border-slate-700 text-slate-300 text-sm rounded-lg px-3 py-1.5 focus:outline-none focus:border-indigo-500"
          @change="handleSearch"
        >
          <option value="">全部风险等级</option>
          <option value="critical">严重风险 (Critical)</option>
          <option value="high">高危风险 (High)</option>
          <option value="medium">中危风险 (Medium)</option>
          <option value="low">低危风险 (Low)</option>
          <option value="safe">安全可信 (Safe)</option>
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

      <div class="text-xs text-slate-400">
        共维护 <strong class="text-indigo-400">{{ store.total }}</strong> 条研判特征规则
      </div>
    </div>

    <!-- Threat Intel Rules Table -->
    <div class="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden shadow-sm">
      <div class="overflow-x-auto">
        <table class="w-full text-left text-sm text-slate-300">
          <thead class="bg-slate-950/80 text-xs font-semibold uppercase text-slate-400 border-b border-slate-800">
            <tr>
              <th class="p-4">目标规则匹配模式</th>
              <th class="p-4 w-28">匹配方式</th>
              <th class="p-4 w-32">风险等级</th>
              <th class="p-4">分类类别</th>
              <th class="p-4">安全标签</th>
              <th class="p-4">研判依据与说明</th>
              <th class="p-4 w-36">录入时间</th>
              <th class="p-4 w-20 text-right">操作</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-slate-800/60 font-normal">
            <tr v-if="store.loading" class="text-center py-8">
              <td colspan="8" class="p-8 text-slate-500">
                <div class="flex items-center justify-center gap-2">
                  <Loader2 class="w-5 h-5 animate-spin text-indigo-400" />
                  <span>加载威胁情报规则库...</span>
                </div>
              </td>
            </tr>
            <tr v-else-if="store.profiles.length === 0" class="text-center py-8">
              <td colspan="8" class="p-8 text-slate-500">
                暂无威胁情报规则记录，可点击右上角添加或批量导入
              </td>
            </tr>
            <tr
              v-for="item in store.profiles"
              :key="item.id"
              class="hover:bg-slate-800/40 transition-colors"
            >
              <td class="p-4 font-mono font-medium text-slate-100 flex items-center gap-2">
                <Globe class="w-4 h-4 text-slate-400 flex-shrink-0" />
                <span class="select-all">{{ item.domain }}</span>
              </td>
              <td class="p-4">
                <span
                  class="px-2 py-0.5 rounded text-xs font-mono font-medium"
                  :class="item.match_type === 'root' ? 'bg-indigo-500/10 text-indigo-300 border border-indigo-500/20' : 'bg-slate-800 text-slate-300 border border-slate-700'"
                >
                  {{ item.match_type === 'root' ? '根域通配 (*.)' : '精确子域' }}
                </span>
              </td>
              <td class="p-4">
                <RiskBadge :level="item.risk_level" />
              </td>
              <td class="p-4 text-slate-300">
                {{ item.category || '-' }}
              </td>
              <td class="p-4">
                <div v-if="item.tags && item.tags.length" class="flex flex-wrap gap-1">
                  <span
                    v-for="tag in item.tags"
                    :key="tag"
                    class="text-[10px] px-1.5 py-0.5 rounded bg-slate-800 text-slate-300 border border-slate-700/60"
                  >
                    {{ tag }}
                  </span>
                </div>
                <span v-else class="text-slate-500 text-xs">-</span>
              </td>
              <td class="p-4 text-xs text-slate-400 max-w-xs truncate">
                {{ item.remark || '-' }}
              </td>
              <td class="p-4 text-xs font-mono text-slate-500">
                {{ item.created_at ? item.created_at.split(' ')[0] : '-' }}
              </td>
              <td class="p-4 text-right">
                <button
                  @click="deleteRule(item.id)"
                  class="p-1.5 text-slate-400 hover:text-rose-400 hover:bg-slate-800 rounded-lg transition-colors"
                  title="删除此规则"
                >
                  <Trash2 class="w-4 h-4" />
                </button>
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

    <!-- Add Rule Modal -->
    <Modal
      :model-value="addModalOpen"
      title="添加威胁情报研判规则"
      @update:model-value="addModalOpen = $event"
    >
      <form @submit.prevent="submitAddRule" class="space-y-4">
        <div>
          <label class="block text-xs font-medium text-slate-400 mb-1">目标域名 / 模式 <span class="text-rose-400">*</span></label>
          <input
            v-model="addForm.domain"
            type="text"
            required
            placeholder="例如: evil.com 或 *.gamble-site.top"
            class="w-full px-3 py-2 bg-slate-950 border border-slate-700 rounded-lg text-sm text-slate-200 focus:outline-none focus:border-indigo-500 font-mono"
          />
        </div>

        <div class="grid grid-cols-2 gap-4">
          <div>
            <label class="block text-xs font-medium text-slate-400 mb-1">匹配类型</label>
            <select
              v-model="addForm.match_type"
              class="w-full px-3 py-2 bg-slate-950 border border-slate-700 rounded-lg text-sm text-slate-200 focus:outline-none focus:border-indigo-500"
            >
              <option value="root">根域通配 (*.domain.com)</option>
              <option value="exact">精确子域 (exact match)</option>
            </select>
          </div>

          <div>
            <label class="block text-xs font-medium text-slate-400 mb-1">风险等级</label>
            <select
              v-model="addForm.risk_level"
              class="w-full px-3 py-2 bg-slate-950 border border-slate-700 rounded-lg text-sm text-slate-200 focus:outline-none focus:border-indigo-500"
            >
              <option value="critical">严重风险 (Critical)</option>
              <option value="high">高危风险 (High)</option>
              <option value="medium">中危风险 (Medium)</option>
              <option value="low">低危风险 (Low)</option>
              <option value="safe">安全可信 (Safe)</option>
            </select>
          </div>
        </div>

        <div>
          <label class="block text-xs font-medium text-slate-400 mb-1">风险分类</label>
          <input
            v-model="addForm.category"
            type="text"
            placeholder="例如: 黑产博彩, 暗链挂马, 纯IP非法外链"
            class="w-full px-3 py-2 bg-slate-950 border border-slate-700 rounded-lg text-sm text-slate-200 focus:outline-none focus:border-indigo-500"
          />
        </div>

        <div>
          <label class="block text-xs font-medium text-slate-400 mb-1">安全标签 (逗号分隔)</label>
          <input
            v-model="addForm.tagsInput"
            type="text"
            placeholder="例如: 赌博, 涉诈, 僵尸外链"
            class="w-full px-3 py-2 bg-slate-950 border border-slate-700 rounded-lg text-sm text-slate-200 focus:outline-none focus:border-indigo-500"
          />
        </div>

        <div>
          <label class="block text-xs font-medium text-slate-400 mb-1">研判说明与依据</label>
          <textarea
            v-model="addForm.remark"
            rows="3"
            placeholder="威胁情报来源、被篡改证据等说明..."
            class="w-full px-3 py-2 bg-slate-950 border border-slate-700 rounded-lg text-sm text-slate-200 focus:outline-none focus:border-indigo-500"
          ></textarea>
        </div>

        <div class="flex items-center gap-2 pt-2 border-t border-slate-800">
          <input
            id="syncToHistory"
            v-model="addForm.sync_to_history"
            type="checkbox"
            class="rounded bg-slate-900 border-slate-700 text-indigo-600 focus:ring-0 cursor-pointer"
          />
          <label for="syncToHistory" class="text-xs text-slate-300 cursor-pointer select-none">
            立即全量回溯到现有历史扫描任务并更新违规标记
          </label>
        </div>

        <div class="flex justify-end gap-2 pt-4 border-t border-slate-800">
          <button
            type="button"
            @click="addModalOpen = false"
            class="px-4 py-2 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-lg text-sm"
          >
            取消
          </button>
          <button
            type="submit"
            class="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg text-sm font-medium"
          >
            确认添加规则
          </button>
        </div>
      </form>
    </Modal>

    <!-- Batch Import Modal -->
    <Modal
      :model-value="batchModalOpen"
      title="批量导入威胁情报规则"
      size="lg"
      @update:model-value="batchModalOpen = $event"
    >
      <form @submit.prevent="submitBatchImport" class="space-y-4">
        <div>
          <label class="block text-xs font-medium text-slate-400 mb-1">
            规则列表 (每行一条规则，以逗号分隔: 域名,风险等级,分类,标签(以/分隔),备注)
          </label>
          <textarea
            v-model="batchInput"
            rows="8"
            required
            placeholder="evil-gambling.com,high,黑产博彩,赌博/外链,恶意博彩跳转
*.malware-cdn.net,critical,暗链挂马,挂马/脚本,JS注入恶意脚本
gov-phish.xyz,critical,仿冒钓鱼,仿冒/欺诈,仿冒政府网站"
            class="w-full px-3 py-2 bg-slate-950 border border-slate-700 rounded-lg text-xs font-mono text-slate-200 focus:outline-none focus:border-indigo-500"
          ></textarea>
        </div>

        <div class="flex items-center gap-2 pt-2 border-t border-slate-800">
          <input
            id="batchSyncToHistory"
            v-model="batchSyncToHistory"
            type="checkbox"
            class="rounded bg-slate-900 border-slate-700 text-indigo-600 focus:ring-0 cursor-pointer"
          />
          <label for="batchSyncToHistory" class="text-xs text-slate-300 cursor-pointer select-none">
            导入后立即对全库所有历史任务执行自动化智能回溯标记
          </label>
        </div>

        <div class="flex justify-end gap-2 pt-4 border-t border-slate-800">
          <button
            type="button"
            @click="batchModalOpen = false"
            class="px-4 py-2 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-lg text-sm"
          >
            取消
          </button>
          <button
            type="submit"
            class="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg text-sm font-medium"
          >
            解析并导入
          </button>
        </div>
      </form>
    </Modal>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { ShieldAlert, Plus, Upload, RefreshCw, Download, Search, Globe, Trash2, Loader2 } from 'lucide-vue-next'
import { useThreatIntelStore } from '@/stores/threatIntel'
import RiskBadge from '@/components/common/RiskBadge.vue'
import Pagination from '@/components/common/Pagination.vue'
import Modal from '@/components/common/Modal.vue'

const store = useThreatIntelStore()

const search = ref('')
const riskLevel = ref('')
const syncing = ref(false)

// Add Modal
const addModalOpen = ref(false)
const addForm = ref({
  domain: '',
  match_type: 'root',
  risk_level: 'high',
  category: '',
  tagsInput: '',
  remark: '',
  sync_to_history: true
})

// Batch Modal
const batchModalOpen = ref(false)
const batchInput = ref('')
const batchSyncToHistory = ref(true)

const handleSearch = () => {
  store.loadProfiles(1, search.value, riskLevel.value)
}

const resetFilters = () => {
  search.value = ''
  riskLevel.value = ''
  store.loadProfiles(1)
}

const onPageChange = (p) => {
  store.loadProfiles(p, search.value, riskLevel.value)
}

const syncHistory = async () => {
  syncing.value = true
  try {
    await store.syncAllToHistory()
  } finally {
    syncing.value = false
  }
}

const deleteRule = async (id) => {
  if (confirm('确认删除该威胁情报规则？')) {
    await store.deleteProfile(id)
  }
}

const openAddModal = () => {
  addForm.value = {
    domain: '',
    match_type: 'root',
    risk_level: 'high',
    category: '',
    tagsInput: '',
    remark: '',
    sync_to_history: true
  }
  addModalOpen.value = true
}

const submitAddRule = async () => {
  const tags = addForm.value.tagsInput
    .split(/[,，]/)
    .map(t => t.trim())
    .filter(Boolean)

  await store.addProfile({
    domain: addForm.value.domain.trim(),
    match_type: addForm.value.match_type,
    risk_level: addForm.value.risk_level,
    category: addForm.value.category.trim(),
    tags,
    remark: addForm.value.remark.trim(),
    sync_to_history: addForm.value.sync_to_history
  })

  addModalOpen.value = false
}

const openBatchModal = () => {
  batchInput.value = ''
  batchSyncToHistory.value = true
  batchModalOpen.value = true
}

const submitBatchImport = async () => {
  const lines = batchInput.value.split('\n').map(l => l.trim()).filter(Boolean)
  const items = []

  for (const line of lines) {
    const parts = line.split(',').map(p => p.trim())
    if (parts.length >= 1 && parts[0]) {
      const domain = parts[0]
      const level = parts[1] || 'high'
      const category = parts[2] || ''
      const tags = (parts[3] || '').split('/').map(t => t.trim()).filter(Boolean)
      const remark = parts[4] || ''

      items.push({
        domain,
        match_type: domain.startsWith('*.') ? 'root' : 'root',
        risk_level: level,
        category,
        tags,
        remark
      })
    }
  }

  if (items.length === 0) return

  await store.batchImport(items, batchSyncToHistory.value)
  batchModalOpen.value = false
}

const exportRules = () => {
  window.open('/api/risk-profiles/export', '_blank')
}

onMounted(() => {
  store.loadProfiles(1)
})
</script>
