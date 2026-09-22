<template>
  <Modal
    :model-value="modelValue"
    @update:model-value="$emit('update:modelValue', $event)"
    title="批量导入网站扫描任务"
    max-width="max-w-2xl"
  >
    <div class="space-y-4">
      <div>
        <label class="block font-semibold text-slate-300 mb-1">
          目标 URL 列表 (每行一条) <span class="text-rose-400">*</span>
        </label>
        <textarea
          v-model="rawUrls"
          rows="7"
          placeholder="https://example.com&#10;https://target.edu.cn&#10;192.168.1.100:8080&#10;# 支持自动忽略井号开头的注释与重复项"
          class="w-full bg-slate-950 border border-slate-700 rounded-xl p-3 text-slate-200 font-mono text-xs focus:outline-none focus:border-indigo-500 leading-relaxed"
        />
        <div class="flex items-center justify-between text-[11px] text-slate-500 mt-1">
          <span>当前已输入有效 URL: <strong class="text-indigo-400 font-mono">{{ parsedUrls.length }}</strong> 条</span>
          <button @click="loadDemoUrls" class="text-indigo-400 hover:underline">加载示例数据</button>
        </div>
      </div>

      <div class="grid grid-cols-2 gap-3">
        <div>
          <label class="block font-semibold text-slate-300 mb-1">任务命名规则</label>
          <select
            v-model="nameTemplate"
            class="w-full bg-slate-950 border border-slate-700 rounded-xl px-3 py-2 text-slate-200"
          >
            <option value="domain">提取域名作为任务名称 (例如: example.com)</option>
            <option value="prefix_index">前缀 + 序号 (例如: 批量扫描_01)</option>
            <option value="raw">直接使用完整 URL 作为名称</option>
          </select>
        </div>
        <div v-if="nameTemplate === 'prefix_index'">
          <label class="block font-semibold text-slate-300 mb-1">任务前缀</label>
          <input
            v-model="namePrefix"
            placeholder="例如：高校站点专项排查"
            class="w-full bg-slate-950 border border-slate-700 rounded-xl px-3 py-2 text-slate-200"
          />
        </div>
      </div>

      <div class="p-3 bg-indigo-950/20 border border-indigo-900/40 rounded-xl text-[11px] text-slate-300 flex items-center justify-between">
        <span>创建后是否直接排队自动开始扫描？</span>
        <label class="flex items-center gap-2 cursor-pointer font-semibold text-indigo-300">
          <input type="checkbox" v-model="autoStart" class="rounded bg-slate-900 border-slate-700 text-indigo-500" />
          <span>创建后自动并发启动</span>
        </label>
      </div>
    </div>

    <template #footer>
      <button
        @click="$emit('update:modelValue', false)"
        class="px-4 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-300 transition font-medium"
      >
        取消
      </button>
      <button
        @click="submit"
        :disabled="submitting || parsedUrls.length === 0"
        class="px-5 py-2 rounded-xl bg-gradient-to-r from-indigo-600 to-sky-600 hover:from-indigo-500 hover:to-sky-500 text-white font-semibold transition shadow-md shadow-indigo-500/20 disabled:opacity-50"
      >
        {{ submitting ? '正在批量创建中...' : `确认批量导入 (${parsedUrls.length} 个任务)` }}
      </button>
    </template>
  </Modal>
</template>

<script setup>
import { ref, computed } from 'vue'
import Modal from '@/components/common/Modal.vue'
import { useTasksStore } from '@/stores/tasks'

const props = defineProps({
  modelValue: { type: Boolean, default: false }
})

const emit = defineEmits(['update:modelValue', 'created'])

const tasksStore = useTasksStore()
const rawUrls = ref('')
const nameTemplate = ref('domain')
const namePrefix = ref('批量扫描')
const autoStart = ref(false)
const submitting = ref(false)

const parsedUrls = computed(() => {
  return rawUrls.value
    .split('\n')
    .map(line => line.trim())
    .filter(line => line && !line.startsWith('#'))
})

const loadDemoUrls = () => {
  rawUrls.value = `https://www.sdfmu.edu.cn/\nhttps://www.sdnu.edu.cn/\nhttp://zhkt.sdlvtc.cn/\n# 自动去重与过滤注释`
}

const extractDomain = (url) => {
  try {
    const full = url.startsWith('http') ? url : `http://${url}`
    return new URL(full).hostname
  } catch {
    return url.slice(0, 30)
  }
}

const submit = async () => {
  if (parsedUrls.value.length === 0) return
  submitting.value = true

  const tasksData = parsedUrls.value.map((url, idx) => {
    let taskName = ''
    if (nameTemplate.value === 'domain') {
      taskName = `${extractDomain(url)}扫描_${new Date().toTimeString().slice(0, 8)}`
    } else if (nameTemplate.value === 'prefix_index') {
      taskName = `${namePrefix.value || '批量任务'}_${idx + 1}`
    } else {
      taskName = url
    }

    return {
      name: taskName,
      target_url: url,
      config: {
        max_depth: 10,
        max_pages: 1000,
        concurrency: 35,
        request_delay: 0.0,
        timeout: 10.0,
        scope_mode: 'root_domain',
        detect_sitemap: true,
        ignore_ssl: true,
        extract_assets: true,
        extract_text: true,
        scan_asset_content: true
      }
    }
  })

  try {
    const res = await tasksStore.createBatchTasks({
      tasks: tasksData,
      auto_start: autoStart.value
    })
    emit('update:modelValue', false)
    emit('created', res)
    rawUrls.value = ''
  } catch (e) {
    // Handled in store
  } finally {
    submitting.value = false
  }
}
</script>
