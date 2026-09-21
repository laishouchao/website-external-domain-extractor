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
            placeholder="搜索页面URL或标题..."
            class="w-full pl-9 pr-3 py-1.5 bg-slate-950 border border-slate-700 rounded-lg text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:border-indigo-500"
            @keyup.enter="handleSearch"
          />
        </div>

        <!-- Depth Select -->
        <select
          v-model="filters.depth"
          class="bg-slate-950 border border-slate-700 text-slate-300 text-sm rounded-lg px-3 py-1.5 focus:outline-none focus:border-indigo-500"
          @change="handleSearch"
        >
          <option value="">全部爬取深度</option>
          <option value="0">深度 0 (起始首页)</option>
          <option value="1">深度 1 (一级链接)</option>
          <option value="2">深度 2 (二级链接)</option>
          <option value="3">深度 3 (三级链接)</option>
          <option value="4">深度 4 及以上</option>
        </select>

        <!-- Status Code Select -->
        <select
          v-model="filters.statusCode"
          class="bg-slate-950 border border-slate-700 text-slate-300 text-sm rounded-lg px-3 py-1.5 focus:outline-none focus:border-indigo-500"
          @change="handleSearch"
        >
          <option value="">全部状态码</option>
          <option value="200">200 (正常返回)</option>
          <option value="301">301/302 (重定向)</option>
          <option value="403">403 (禁止访问)</option>
          <option value="404">404 (页面未找到)</option>
          <option value="500">500 (服务器错误)</option>
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
          @click="exportXml"
          class="px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-lg text-sm flex items-center gap-1.5 transition-colors border border-slate-700"
        >
          <FileCode2 class="w-4 h-4 text-amber-400" />
          导出 sitemap.xml
        </button>
        <button
          @click="exportCsv"
          class="px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-lg text-sm flex items-center gap-1.5 transition-colors border border-slate-700"
        >
          <Download class="w-4 h-4 text-emerald-400" />
          导出 CSV
        </button>
      </div>
    </div>

    <!-- Sitemap Table -->
    <div class="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden shadow-sm">
      <div class="overflow-x-auto">
        <table class="w-full text-left text-sm text-slate-300">
          <thead class="bg-slate-950/80 text-xs font-semibold uppercase text-slate-400 border-b border-slate-800">
            <tr>
              <th class="p-4 w-16 text-center">深度</th>
              <th class="p-4">网页 URL 及标题</th>
              <th class="p-4 w-28 text-center">HTTP 状态</th>
              <th class="p-4 w-44 text-right">爬取时间</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-slate-800/60 font-normal">
            <tr v-if="loading" class="text-center py-8">
              <td colspan="4" class="p-8 text-slate-500">
                <div class="flex items-center justify-center gap-2">
                  <Loader2 class="w-5 h-5 animate-spin text-indigo-400" />
                  <span>加载网页地图中...</span>
                </div>
              </td>
            </tr>
            <tr v-else-if="pages.length === 0" class="text-center py-8">
              <td colspan="4" class="p-8 text-slate-500">
                暂无爬取页面记录
              </td>
            </tr>
            <tr
              v-for="pageItem in pages"
              :key="pageItem.id"
              class="hover:bg-slate-800/40 transition-colors"
            >
              <td class="p-4 text-center">
                <span class="inline-flex items-center px-2 py-0.5 rounded text-xs font-mono font-medium bg-slate-800 text-indigo-300 border border-slate-700">
                  D-{{ pageItem.depth }}
                </span>
              </td>
              <td class="p-4">
                <div class="space-y-1">
                  <div class="font-medium text-slate-100 flex items-center gap-2">
                    <FileText class="w-4 h-4 text-slate-400 flex-shrink-0" />
                    <a
                      :href="pageItem.url"
                      target="_blank"
                      class="text-indigo-400 hover:underline truncate max-w-2xl font-mono text-xs"
                    >
                      {{ pageItem.url }}
                    </a>
                  </div>
                  <div v-if="pageItem.title" class="text-xs text-slate-400 pl-6 truncate max-w-2xl">
                    {{ pageItem.title }}
                  </div>
                </div>
              </td>
              <td class="p-4 text-center">
                <span
                  class="inline-flex items-center px-2 py-0.5 rounded text-xs font-mono font-bold"
                  :class="getStatusCodeClass(pageItem.status_code)"
                >
                  {{ pageItem.status_code || '---' }}
                </span>
              </td>
              <td class="p-4 text-right text-xs text-slate-400 font-mono">
                {{ pageItem.crawled_at || '-' }}
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
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { Search, Download, FileCode2, FileText, Loader2 } from 'lucide-vue-next'
import client from '@/api/client'
import Pagination from '@/components/common/Pagination.vue'

const props = defineProps({
  taskId: {
    type: [Number, String],
    required: true
  }
})

const pages = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(50)
const loading = ref(false)

const filters = ref({
  search: '',
  depth: '',
  statusCode: ''
})

const loadPages = async (p = 1) => {
  page.value = p
  loading.value = true
  try {
    const offset = (p - 1) * pageSize.value
    const params = {
      limit: pageSize.value,
      offset
    }
    if (filters.value.search) params.search = filters.value.search.trim()
    if (filters.value.depth !== '') params.depth = filters.value.depth
    if (filters.value.statusCode) params.status_code = filters.value.statusCode

    const res = await client.get(`/tasks/${props.taskId}/pages`, { params })
    pages.value = res.pages || []
    total.value = res.total || 0
  } catch (e) {
    console.error('Failed to load sitemap pages:', e)
  } finally {
    loading.value = false
  }
}

const handleSearch = () => {
  loadPages(1)
}

const resetFilters = () => {
  filters.value = {
    search: '',
    depth: '',
    statusCode: ''
  }
  loadPages(1)
}

const onPageChange = (p) => {
  loadPages(p)
}

const getStatusCodeClass = (code) => {
  if (!code) return 'bg-slate-800 text-slate-400 border border-slate-700'
  if (code >= 200 && code < 300) return 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20'
  if (code >= 300 && code < 400) return 'bg-blue-500/10 text-blue-400 border border-blue-500/20'
  if (code >= 400 && code < 500) return 'bg-amber-500/10 text-amber-400 border border-amber-500/20'
  return 'bg-rose-500/10 text-rose-400 border border-rose-500/20'
}

const exportXml = () => {
  window.open(`/api/tasks/${props.taskId}/pages/export/xml`, '_blank')
}

const exportCsv = () => {
  window.open(`/api/tasks/${props.taskId}/pages/export/csv`, '_blank')
}

onMounted(() => {
  loadPages(1)
})
</script>
