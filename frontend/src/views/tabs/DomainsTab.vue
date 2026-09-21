<template>
  <div class="space-y-4">
    <!-- Filter and Action Bar -->
    <div class="bg-slate-900 border border-slate-800 rounded-xl p-4 flex flex-wrap items-center justify-between gap-4">
      <div class="flex flex-wrap items-center gap-3">
        <!-- Search Input -->
        <div class="relative w-64">
          <Search class="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
          <input
            v-model="filters.search"
            type="text"
            placeholder="搜索外部域名或根域..."
            class="w-full pl-9 pr-3 py-1.5 bg-slate-950 border border-slate-700 rounded-lg text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:border-indigo-500"
            @keyup.enter="handleSearch"
          />
        </div>

        <!-- Risk Level Select -->
        <select
          v-model="filters.riskLevel"
          class="bg-slate-950 border border-slate-700 text-slate-300 text-sm rounded-lg px-3 py-1.5 focus:outline-none focus:border-indigo-500"
          @change="handleSearch"
        >
          <option value="">全部风险等级</option>
          <option value="critical">严重风险 (Critical)</option>
          <option value="high">高危风险 (High)</option>
          <option value="medium">中危风险 (Medium)</option>
          <option value="low">低危风险 (Low)</option>
          <option value="safe">安全可信 (Safe)</option>
          <option value="pending">待研判 (Pending)</option>
        </select>

        <!-- Source Type Select -->
        <select
          v-model="filters.sourceType"
          class="bg-slate-950 border border-slate-700 text-slate-300 text-sm rounded-lg px-3 py-1.5 focus:outline-none focus:border-indigo-500"
          @change="handleSearch"
        >
          <option value="">全部来源类型</option>
          <option value="link">仅超链接 (Link)</option>
          <option value="text">仅文本/脚本代码 (Text)</option>
        </select>

        <!-- Verify Status Select -->
        <select
          v-model="filters.verifyStatus"
          class="bg-slate-950 border border-slate-700 text-slate-300 text-sm rounded-lg px-3 py-1.5 focus:outline-none focus:border-indigo-500"
          @change="handleSearch"
        >
          <option value="">全部复测状态</option>
          <option value="unverified">未复测</option>
          <option value="verified_clean">已彻底清除</option>
          <option value="verified_failed">仍有残留</option>
          <option value="error">复测异常</option>
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

      <!-- Right Action Tools -->
      <div class="flex items-center gap-2">
        <button
          v-if="selectedDomains.length > 0"
          @click="openBatchRiskModal"
          class="px-3 py-1.5 bg-amber-600/20 text-amber-300 border border-amber-500/30 hover:bg-amber-600/30 rounded-lg text-sm font-medium flex items-center gap-1.5 transition-colors"
        >
          <ShieldAlert class="w-4 h-4" />
          批量研判 ({{ selectedDomains.length }})
        </button>

        <button
          @click="exportTxt"
          class="px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-lg text-sm flex items-center gap-1.5 transition-colors border border-slate-700"
        >
          <Download class="w-4 h-4" />
          导出TXT
        </button>
      </div>
    </div>

    <!-- Domains Table -->
    <div class="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden shadow-sm">
      <div class="overflow-x-auto">
        <table class="w-full text-left text-sm text-slate-300">
          <thead class="bg-slate-950/80 text-xs font-semibold uppercase text-slate-400 border-b border-slate-800">
            <tr>
              <th class="p-4 w-10">
                <input
                  type="checkbox"
                  class="rounded bg-slate-900 border-slate-700 text-indigo-600 focus:ring-0 focus:ring-offset-0 cursor-pointer"
                  :checked="isAllSelected"
                  @change="toggleSelectAll"
                />
              </th>
              <th class="p-4">外部域名</th>
              <th class="p-4">主根域名</th>
              <th class="p-4 text-center">出现频次</th>
              <th class="p-4">来源属性</th>
              <th class="p-4">风险研判</th>
              <th class="p-4">闭环复测</th>
              <th class="p-4 text-right">操作</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-slate-800/60 font-normal">
            <tr v-if="loading" class="text-center py-8">
              <td colspan="8" class="p-8 text-slate-500">
                <div class="flex items-center justify-center gap-2">
                  <Loader2 class="w-5 h-5 animate-spin text-indigo-400" />
                  <span>加载外部域名列表中...</span>
                </div>
              </td>
            </tr>
            <tr v-else-if="domains.length === 0" class="text-center py-8">
              <td colspan="8" class="p-8 text-slate-500">
                暂无符合条件的外部域名记录
              </td>
            </tr>
            <tr
              v-for="item in domains"
              :key="item.domain"
              class="hover:bg-slate-800/40 transition-colors"
            >
              <td class="p-4">
                <input
                  type="checkbox"
                  class="rounded bg-slate-900 border-slate-700 text-indigo-600 focus:ring-0 focus:ring-offset-0 cursor-pointer"
                  :value="item.domain"
                  v-model="selectedDomains"
                />
              </td>
              <td class="p-4 cursor-pointer" @click="viewOccurrences(item.domain)" title="点击查看代码证据详情">
                <div class="font-medium text-slate-100 flex items-center gap-1.5 hover:text-indigo-400 transition-colors">
                  <Globe class="w-4 h-4 text-slate-400 flex-shrink-0" />
                  <span class="select-all">{{ item.domain }}</span>
                </div>
              </td>
              <td class="p-4 text-slate-400 font-mono text-xs">
                {{ item.root_domain || '-' }}
              </td>
              <td class="p-4 text-center cursor-pointer" @click="viewOccurrences(item.domain)" title="点击查看代码证据详情">
                <span class="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-slate-800 text-indigo-300 border border-slate-700 hover:border-indigo-500/50 hover:bg-slate-700 transition">
                  {{ item.occurrence_count }} 次
                </span>
              </td>
              <td class="p-4">
                <div class="flex items-center gap-1.5">
                  <span
                    v-if="item.has_link"
                    class="px-1.5 py-0.5 rounded text-[11px] font-medium bg-blue-500/10 text-blue-400 border border-blue-500/20"
                    title="包含指向该域名的 HTML 超链接"
                  >
                    超链接
                  </span>
                  <span
                    v-if="item.has_text"
                    class="px-1.5 py-0.5 rounded text-[11px] font-medium bg-purple-500/10 text-purple-400 border border-purple-500/20"
                    title="包含在网页文本、JS脚本或注释中"
                  >
                    文本/脚本
                  </span>
                </div>
              </td>
              <td class="p-4">
                <RiskBadge :level="item.risk_level" />
                <div v-if="item.tags && item.tags.length" class="flex flex-wrap gap-1 mt-1">
                  <span
                    v-for="tag in item.tags.slice(0, 2)"
                    :key="tag"
                    class="text-[10px] px-1 py-0.2 rounded bg-slate-800 text-slate-400"
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
                    @click="viewOccurrences(item.domain)"
                    class="p-1.5 text-slate-400 hover:text-indigo-400 hover:bg-slate-800 rounded-lg transition-colors"
                    title="查看代码上下文证据"
                  >
                    <FileSearch class="w-4 h-4" />
                  </button>
                  <button
                    @click="openRiskModal(item)"
                    class="p-1.5 text-slate-400 hover:text-amber-400 hover:bg-slate-800 rounded-lg transition-colors"
                    title="编辑风险评级"
                  >
                    <ShieldAlert class="w-4 h-4" />
                  </button>
                  <button
                    @click="verifyDomain(item.domain)"
                    class="p-1.5 text-slate-400 hover:text-emerald-400 hover:bg-slate-800 rounded-lg transition-colors"
                    :disabled="verifyingDomain === item.domain"
                    title="一键闭环复测"
                  >
                    <RefreshCw class="w-4 h-4" :class="{ 'animate-spin': verifyingDomain === item.domain }" />
                  </button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- Pagination -->
      <Pagination
        :current-page="page"
        :total="total"
        :page-size="pageSize"
        @page-change="onPageChange"
      />
    </div>

    <!-- Evidence Drawer -->
    <Drawer
      :model-value="drawerOpen"
      :title="`证据详情: ${currentDomain}`"
      size="xl"
      @update:model-value="drawerOpen = $event"
    >
      <div class="space-y-4">
        <div class="flex items-center justify-between bg-slate-950 p-3 rounded-lg border border-slate-800 text-xs text-slate-400">
          <span>共提取到 <strong class="text-indigo-400">{{ occurrences.length }}</strong> 条页面证据代码</span>
          <div class="flex items-center gap-2">
            <button
              @click="exportEvidenceCsv"
              class="px-2.5 py-1 bg-slate-800 hover:bg-slate-700 text-slate-200 rounded text-xs flex items-center gap-1 border border-slate-700"
            >
              <Download class="w-3.5 h-3.5" /> 导出 CSV
            </button>
            <button
              @click="exportEvidenceJson"
              class="px-2.5 py-1 bg-slate-800 hover:bg-slate-700 text-slate-200 rounded text-xs flex items-center gap-1 border border-slate-700"
            >
              <Download class="w-3.5 h-3.5" /> 导出 JSON
            </button>
          </div>
        </div>

        <div v-if="loadingOccurrences" class="flex items-center justify-center py-12 text-slate-500 gap-2">
          <Loader2 class="w-5 h-5 animate-spin text-indigo-400" />
          <span>正在检索上下文证据...</span>
        </div>

        <div v-else-if="occurrences.length === 0" class="text-center py-12 text-slate-500">
          暂无上下文详情
        </div>

        <div v-else class="space-y-3">
          <div
            v-for="(occ, idx) in occurrences"
            :key="idx"
            class="bg-slate-950 border border-slate-800 rounded-lg p-3 space-y-2"
          >
            <div class="flex items-center justify-between text-xs gap-3">
              <div class="flex items-center gap-2 truncate flex-1 min-w-0">
                <span class="px-1.5 py-0.5 rounded font-mono text-[10px] uppercase font-bold flex-shrink-0"
                  :class="occ.source_type === 'link' ? 'bg-blue-500/20 text-blue-400' : 'bg-purple-500/20 text-purple-400'"
                >
                  {{ occ.source_type }}
                </span>
                <a
                  :href="occ.page_url"
                  target="_blank"
                  class="text-indigo-400 hover:underline truncate font-mono"
                  :title="occ.page_url"
                >
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
      </div>
    </Drawer>

    <!-- Risk Assess Modal (统一标准研判弹窗) -->
    <RiskAssessModal
      v-model="riskModalOpen"
      :item="editingDomain"
      @saved="handleAssessSaved"
    />

    <!-- Batch Risk Modal -->
    <Modal
      :model-value="batchModalOpen"
      :title="`批量研判风险 (${selectedDomains.length} 个域名)`"
      @update:model-value="batchModalOpen = $event"
    >
      <form @submit.prevent="submitBatchRisk" class="space-y-4">
        <div>
          <label class="block text-xs font-medium text-slate-400 mb-1">批量设置风险等级</label>
          <select
            v-model="batchRiskForm.risk_level"
            class="w-full px-3 py-2 bg-slate-950 border border-slate-700 rounded-lg text-sm text-slate-200 focus:outline-none focus:border-indigo-500"
          >
            <option value="critical">严重风险 (Critical)</option>
            <option value="high">高危风险 (High)</option>
            <option value="medium">中危风险 (Medium)</option>
            <option value="low">低危风险 (Low)</option>
            <option value="safe">安全可信 (Safe)</option>
            <option value="pending">待研判 (Pending)</option>
          </select>
        </div>

        <div>
          <label class="block text-xs font-medium text-slate-400 mb-1">通用研判备注</label>
          <textarea
            v-model="batchRiskForm.remark"
            rows="3"
            placeholder="批量研判理由..."
            class="w-full px-3 py-2 bg-slate-950 border border-slate-700 rounded-lg text-sm text-slate-200 focus:outline-none focus:border-indigo-500"
          ></textarea>
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
            应用到已选域名
          </button>
        </div>
      </form>
    </Modal>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import {
  Search, ShieldAlert, Download, Globe, FileSearch, RefreshCw, Loader2
} from 'lucide-vue-next'
import client from '@/api/client'
import { useUiStore } from '@/stores/ui'
import RiskBadge from '@/components/common/RiskBadge.vue'
import StatusBadge from '@/components/common/StatusBadge.vue'
import Pagination from '@/components/common/Pagination.vue'
import Drawer from '@/components/common/Drawer.vue'
import Modal from '@/components/common/Modal.vue'
import CodeSnippet from '@/components/common/CodeSnippet.vue'
import RiskAssessModal from '@/components/common/RiskAssessModal.vue'

const props = defineProps({
  taskId: {
    type: [Number, String],
    required: true
  }
})

const emit = defineEmits(['updated'])
const ui = useUiStore()

const domains = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(50)
const loading = ref(false)

const filters = ref({
  search: '',
  riskLevel: '',
  sourceType: '',
  verifyStatus: ''
})

const selectedDomains = ref([])
const isAllSelected = computed(() => {
  return domains.value.length > 0 && selectedDomains.value.length === domains.value.length
})

const toggleSelectAll = (e) => {
  if (e.target.checked) {
    selectedDomains.value = domains.value.map(d => d.domain)
  } else {
    selectedDomains.value = []
  }
}

// Drawer state
const drawerOpen = ref(false)
const currentDomain = ref('')
const occurrences = ref([])
const loadingOccurrences = ref(false)

// Risk Modal state
const riskModalOpen = ref(false)
const editingDomain = ref(null)

// Batch Risk Modal state
const batchModalOpen = ref(false)
const batchRiskForm = ref({
  risk_level: 'high',
  remark: ''
})

// Verifying domain
const verifyingDomain = ref(null)

const loadDomains = async (p = 1) => {
  page.value = p
  loading.value = true
  try {
    const offset = (p - 1) * pageSize.value
    const params = {
      limit: pageSize.value,
      offset
    }
    if (filters.value.search) params.search = filters.value.search.trim()
    if (filters.value.riskLevel) params.risk_level = filters.value.riskLevel
    if (filters.value.verifyStatus) params.verify_status = filters.value.verifyStatus
    if (filters.value.sourceType === 'link') params.has_link = 1
    if (filters.value.sourceType === 'text') params.has_text = 1

    const res = await client.get(`/tasks/${props.taskId}/domains`, { params })
    domains.value = res.domains || []
    total.value = res.total || 0
  } catch (e) {
    console.error('Failed to load domains:', e)
  } finally {
    loading.value = false
  }
}

const handleSearch = () => {
  loadDomains(1)
}

const resetFilters = () => {
  filters.value = {
    search: '',
    riskLevel: '',
    sourceType: '',
    verifyStatus: ''
  }
  loadDomains(1)
}

const onPageChange = (p) => {
  loadDomains(p)
}

const viewOccurrences = async (domain) => {
  currentDomain.value = domain
  drawerOpen.value = true
  loadingOccurrences.value = true
  try {
    const res = await client.get(`/tasks/${props.taskId}/domains/${encodeURIComponent(domain)}/occurrences`)
    occurrences.value = res.occurrences || []
  } catch (e) {
    ui.showToast('获取证据失败: ' + e.message, 'error')
  } finally {
    loadingOccurrences.value = false
  }
}

const openRiskModal = (item) => {
  editingDomain.value = item
  riskModalOpen.value = true
}

const handleAssessSaved = async (payload) => {
  if (editingDomain.value) {
    editingDomain.value.risk_level = payload.risk_level
    editingDomain.value.risk_tags = payload.tags
    editingDomain.value.risk_remark = payload.remark
  }
  await loadDomains(page.value)
  emit('updated')
}

const openBatchRiskModal = () => {
  batchRiskForm.value = {
    risk_level: 'high',
    remark: ''
  }
  batchModalOpen.value = true
}

const submitBatchRisk = async () => {
  try {
    await client.post(`/tasks/${props.taskId}/domains/batch-risk`, {
      domains: selectedDomains.value,
      risk_level: batchRiskForm.value.risk_level,
      remark: batchRiskForm.value.remark
    })
    ui.showToast(`成功批量更新 ${selectedDomains.value.length} 个域名的研判结果`, 'success')
    batchModalOpen.value = false
    selectedDomains.value = []
    loadDomains(page.value)
    emit('updated')
  } catch (e) {
    ui.showToast('批量更新失败: ' + e.message, 'error')
  }
}

const verifyDomain = async (domain) => {
  verifyingDomain.value = domain
  try {
    const res = await client.post(`/tasks/${props.taskId}/domains/${encodeURIComponent(domain)}/verify`)
    if (res.verify_status === 'verified_clean') {
      ui.showToast(`【复测通过】域名 ${domain} 已彻底清除！`, 'success')
    } else {
      ui.showToast(`【复测警报】域名 ${domain} 仍存在代码残留！`, 'error')
    }
    loadDomains(page.value)
    emit('updated')
  } catch (e) {
    ui.showToast('闭环复测执行失败: ' + e.message, 'error')
  } finally {
    verifyingDomain.value = null
  }
}

const exportTxt = () => {
  window.open(`/api/tasks/${props.taskId}/domains/export/txt`, '_blank')
}

const exportEvidenceCsv = () => {
  window.open(`/api/tasks/${props.taskId}/domains/${encodeURIComponent(currentDomain.value)}/occurrences/export/csv`, '_blank')
}

const exportEvidenceJson = () => {
  window.open(`/api/tasks/${props.taskId}/domains/${encodeURIComponent(currentDomain.value)}/occurrences/export/json`, '_blank')
}

onMounted(() => {
  loadDomains(1)
})
</script>
