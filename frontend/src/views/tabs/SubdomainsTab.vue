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
            placeholder="搜索发现的本站子域名..."
            class="w-full pl-9 pr-3 py-1.5 bg-slate-950 border border-slate-700 rounded-lg text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:border-indigo-500"
            @keyup.enter="handleSearch"
          />
        </div>

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
          @click="exportTxt"
          class="px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-lg text-sm flex items-center gap-1.5 transition-colors border border-slate-700"
        >
          <Download class="w-4 h-4" />
          导出子域名 TXT
        </button>
      </div>
    </div>

    <!-- Subdomains Table -->
    <div class="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden shadow-sm">
      <div class="overflow-x-auto">
        <table class="w-full text-left text-sm text-slate-300">
          <thead class="bg-slate-950/80 text-xs font-semibold uppercase text-slate-400 border-b border-slate-800">
            <tr>
              <th class="p-4">发现子域名</th>
              <th class="p-4 text-center">出现频次</th>
              <th class="p-4">来源属性</th>
              <th class="p-4 text-right">操作</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-slate-800/60 font-normal">
            <tr v-if="loading" class="text-center py-8">
              <td colspan="4" class="p-8 text-slate-500">
                <div class="flex items-center justify-center gap-2">
                  <Loader2 class="w-5 h-5 animate-spin text-indigo-400" />
                  <span>加载子域名列表中...</span>
                </div>
              </td>
            </tr>
            <tr v-else-if="subdomains.length === 0" class="text-center py-8">
              <td colspan="4" class="p-8 text-slate-500">
                未发现任何本站扩展子域名
              </td>
            </tr>
            <tr
              v-for="item in subdomains"
              :key="item.subdomain"
              class="hover:bg-slate-800/40 transition-colors"
            >
              <td class="p-4 cursor-pointer" @click="viewOccurrences(item.subdomain)" title="点击查看子域名代码证据">
                <div class="font-medium text-slate-100 flex items-center gap-2 hover:text-indigo-400 transition-colors">
                  <Network class="w-4 h-4 text-indigo-400 flex-shrink-0" />
                  <span class="select-all font-mono">{{ item.subdomain }}</span>
                </div>
              </td>
              <td class="p-4 text-center cursor-pointer" @click="viewOccurrences(item.subdomain)" title="点击查看子域名代码证据">
                <span class="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-slate-800 text-indigo-300 border border-slate-700 hover:border-indigo-500/50 hover:bg-slate-700 transition">
                  {{ item.occurrence_count }} 次
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
              <td class="p-4 text-right">
                <button
                  @click="viewOccurrences(item.subdomain)"
                  class="p-1.5 text-slate-400 hover:text-indigo-400 hover:bg-slate-800 rounded-lg transition-colors"
                  title="查看出现页面与代码证据"
                >
                  <FileSearch class="w-4 h-4" />
                </button>
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
      :title="`子域名证据: ${currentSubdomain}`"
      size="xl"
      @update:model-value="drawerOpen = $event"
    >
      <div class="space-y-4">
        <div class="bg-slate-950 p-3 rounded-lg border border-slate-800 text-xs text-slate-400">
          共发现 <strong class="text-indigo-400">{{ occurrences.length }}</strong> 处引用记录
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
              :highlight-term="currentSubdomain"
            />
          </div>
        </div>
      </div>
    </Drawer>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { Search, Download, Network, FileSearch, Loader2 } from 'lucide-vue-next'
import client from '@/api/client'
import { useUiStore } from '@/stores/ui'
import Pagination from '@/components/common/Pagination.vue'
import Drawer from '@/components/common/Drawer.vue'
import CodeSnippet from '@/components/common/CodeSnippet.vue'

const props = defineProps({
  taskId: {
    type: [Number, String],
    required: true
  }
})

const ui = useUiStore()

const subdomains = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(50)
const loading = ref(false)

const filters = ref({
  search: '',
  sourceType: ''
})

const drawerOpen = ref(false)
const currentSubdomain = ref('')
const occurrences = ref([])
const loadingOccurrences = ref(false)

const loadSubdomains = async (p = 1) => {
  page.value = p
  loading.value = true
  try {
    const offset = (p - 1) * pageSize.value
    const params = {
      limit: pageSize.value,
      offset
    }
    if (filters.value.search) params.search = filters.value.search.trim()
    if (filters.value.sourceType === 'link') params.has_link = 1
    if (filters.value.sourceType === 'text') params.has_text = 1

    const res = await client.get(`/tasks/${props.taskId}/subdomains`, { params })
    subdomains.value = res.subdomains || []
    total.value = res.total || 0
  } catch (e) {
    console.error('Failed to load subdomains:', e)
  } finally {
    loading.value = false
  }
}

const handleSearch = () => {
  loadSubdomains(1)
}

const resetFilters = () => {
  filters.value = {
    search: '',
    sourceType: ''
  }
  loadSubdomains(1)
}

const onPageChange = (p) => {
  loadSubdomains(p)
}

const viewOccurrences = async (subdomain) => {
  currentSubdomain.value = subdomain
  drawerOpen.value = true
  loadingOccurrences.value = true
  try {
    const res = await client.get(`/tasks/${props.taskId}/subdomains/${encodeURIComponent(subdomain)}/occurrences`)
    occurrences.value = res.occurrences || []
  } catch (e) {
    ui.showToast('获取子域名证据失败: ' + e.message, 'error')
  } finally {
    loadingOccurrences.value = false
  }
}

const exportTxt = () => {
  window.open(`/api/tasks/${props.taskId}/subdomains/export/txt`, '_blank')
}

onMounted(() => {
  loadSubdomains(1)
})
</script>
