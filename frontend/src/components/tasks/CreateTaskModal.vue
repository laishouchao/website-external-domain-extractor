<template>
  <Modal
    :model-value="modelValue"
    @update:model-value="$emit('update:modelValue', $event)"
    title="新建全深度网站扫描任务"
    max-width="max-w-xl"
  >
    <div class="space-y-4">
      <div>
        <label class="block font-semibold text-slate-300 mb-1">
          任务名称 <span class="text-rose-400">*</span>
        </label>
        <input
          v-model="form.name"
          placeholder="例如：某高校官网外部依赖与全站地图扫描"
          class="w-full bg-slate-950 border border-slate-700 rounded-xl px-3 py-2 text-slate-200 focus:outline-none focus:border-sky-500"
        />
      </div>

      <div>
        <label class="block font-semibold text-slate-300 mb-1">
          目标站点 URL <span class="text-rose-400">*</span>
        </label>
        <input
          v-model="form.target_url"
          placeholder="https://example.com 或 http://school.edu.cn"
          class="w-full bg-slate-950 border border-slate-700 rounded-xl px-3 py-2 text-slate-200 font-mono focus:outline-none focus:border-sky-500"
        />
        <p class="text-slate-500 text-[11px] mt-1">自动识别协议头，爬虫将从此起始页开始进行全深度遍历。</p>
      </div>

      <div class="grid grid-cols-3 gap-3">
        <div>
          <label class="block font-semibold text-slate-300 mb-1">最大深度</label>
          <input
            v-model.number="form.config.max_depth"
            type="number"
            min="0"
            class="w-full bg-slate-950 border border-slate-700 rounded-xl px-3 py-2 text-slate-200 font-mono focus:outline-none focus:border-sky-500"
          />
          <span class="text-slate-500 text-[10px]">0为不限制深度</span>
        </div>
        <div>
          <label class="block font-semibold text-slate-300 mb-1">最大页面上限</label>
          <input
            v-model.number="form.config.max_pages"
            type="number"
            min="0"
            class="w-full bg-slate-950 border border-slate-700 rounded-xl px-3 py-2 text-slate-200 font-mono focus:outline-none focus:border-sky-500"
          />
          <span class="text-slate-500 text-[10px]">0为不限制页数</span>
        </div>
        <div>
          <label class="block font-semibold text-slate-300 mb-1">并发协程数</label>
          <input
            v-model.number="form.config.concurrency"
            type="number"
            min="1"
            max="50"
            class="w-full bg-slate-950 border border-slate-700 rounded-xl px-3 py-2 text-slate-200 font-mono focus:outline-none focus:border-sky-500"
          />
          <span class="text-slate-500 text-[10px]">推荐 10 - 20</span>
        </div>
      </div>

      <!-- Advanced Settings -->
      <div class="pt-2">
        <button
          type="button"
          @click="showAdvanced = !showAdvanced"
          class="text-sky-400 hover:text-sky-300 flex items-center gap-1 font-semibold text-xs"
        >
          <span>{{ showAdvanced ? '▼ 收起高级设置' : '▶ 展开高级参数设置 (探测范围、静态资产内容扫描等)' }}</span>
        </button>

        <div v-if="showAdvanced" class="mt-3 p-3.5 bg-slate-950/80 rounded-xl border border-slate-800 space-y-3">
          <div class="grid grid-cols-2 gap-3">
            <div>
              <label class="block text-slate-400 mb-1">爬取范围模式</label>
              <select
                v-model="form.config.scope_mode"
                class="w-full bg-slate-900 border border-slate-700 rounded-lg px-2.5 py-1.5 text-slate-200"
              >
                <option value="root_domain">全主域名范围 (允许爬取所有子域名)</option>
                <option value="exact_domain">严格同主机名 (仅限当前子域名)</option>
              </select>
            </div>
            <div>
              <label class="block text-slate-400 mb-1">请求间隔 (秒)</label>
              <input
                v-model.number="form.config.request_delay"
                type="number"
                step="0.1"
                min="0"
                class="w-full bg-slate-900 border border-slate-700 rounded-lg px-2.5 py-1.5 text-slate-200 font-mono"
              />
            </div>
          </div>

          <div class="space-y-2 pt-1">
            <label class="flex items-center gap-2 cursor-pointer text-slate-300">
              <input type="checkbox" v-model="form.config.scan_asset_content" class="rounded bg-slate-900 border-slate-700 text-sky-500" />
              <span>深度扫描 JS / CSS 等静态资源内容中的外部域名引用（关键）</span>
            </label>
            <label class="flex items-center gap-2 cursor-pointer text-slate-300">
              <input type="checkbox" v-model="form.config.extract_text" class="rounded bg-slate-900 border-slate-700 text-sky-500" />
              <span>提取网页正文中的纯文本域名（包含无超链接的裸域名）</span>
            </label>
            <label class="flex items-center gap-2 cursor-pointer text-slate-300">
              <input type="checkbox" v-model="form.config.ignore_ssl" class="rounded bg-slate-900 border-slate-700 text-sky-500" />
              <span>忽略 SSL 证书验证（推荐勾选，适应自签名证书环境）</span>
            </label>
          </div>
        </div>
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
        :disabled="submitting"
        class="px-5 py-2 rounded-xl bg-gradient-to-r from-sky-500 to-indigo-600 hover:from-sky-400 hover:to-indigo-500 text-white font-semibold transition shadow-md shadow-sky-500/20 disabled:opacity-50"
      >
        {{ submitting ? '创建中...' : '立即创建任务' }}
      </button>
    </template>
  </Modal>
</template>

<script setup>
import { ref } from 'vue'
import Modal from '@/components/common/Modal.vue'
import { useTasksStore } from '@/stores/tasks'

const props = defineProps({
  modelValue: { type: Boolean, default: false }
})

const emit = defineEmits(['update:modelValue', 'created'])

const tasksStore = useTasksStore()
const showAdvanced = ref(false)
const submitting = ref(false)

const form = ref({
  name: '',
  target_url: '',
  config: {
    max_depth: 10,
    max_pages: 1000,
    concurrency: 15,
    request_delay: 0.0,
    timeout: 10.0,
    scope_mode: 'root_domain',
    detect_sitemap: true,
    ignore_ssl: true,
    extract_assets: true,
    extract_text: true,
    scan_asset_content: true
  }
})

const submit = async () => {
  if (!form.value.name.trim() || !form.value.target_url.trim()) {
    alert('请填写任务名称和目标站点 URL')
    return
  }
  submitting.value = true
  try {
    const res = await tasksStore.createTask(form.value)
    emit('update:modelValue', false)
    emit('created', res)
    form.value.name = ''
    form.value.target_url = ''
  } catch (e) {
    // Handled in store
  } finally {
    submitting.value = false
  }
}
</script>
