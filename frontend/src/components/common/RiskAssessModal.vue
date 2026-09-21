<template>
  <Modal
    :model-value="modelValue"
    title="外部域名快捷研判与全局情报沉淀"
    max-width="max-w-2xl"
    @update:model-value="$emit('update:modelValue', $event)"
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
          @click="$emit('update:modelValue', false)"
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
</template>

<script setup>
import { ref, watch } from 'vue'
import { ShieldAlert, Loader2 } from 'lucide-vue-next'
import Modal from '@/components/common/Modal.vue'
import client from '@/api/client'
import { useUiStore } from '@/stores/ui'

const props = defineProps({
  modelValue: {
    type: Boolean,
    default: false
  },
  item: {
    type: Object,
    default: null
  }
})

const emit = defineEmits(['update:modelValue', 'saved'])
const ui = useUiStore()

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

const initForm = (item) => {
  if (!item) return
  const rawTags = item.risk_tags || item.tags
  let parsedTags = []
  if (Array.isArray(rawTags)) {
    parsedTags = [...rawTags]
  } else if (typeof rawTags === 'string') {
    try {
      const p = JSON.parse(rawTags)
      parsedTags = Array.isArray(p) ? p : [rawTags]
    } catch {
      parsedTags = rawTags.split(/[,，]/).map(t => t.trim()).filter(Boolean)
    }
  }

  assessForm.value = {
    match_type: item.root_domain ? 'root' : 'exact',
    target_domain: item.root_domain || item.domain || '',
    risk_level: item.risk_level && item.risk_level !== 'pending' ? item.risk_level : 'high',
    tags: parsedTags,
    remark: item.risk_remark || item.remark || '',
    sync_to_history: true
  }
  customTagInput.value = ''
}

watch(
  () => props.modelValue,
  (val) => {
    if (val && props.item) {
      initForm(props.item)
    }
  }
)

watch(
  () => props.item,
  (val) => {
    if (props.modelValue && val) {
      initForm(val)
    }
  }
)

const onMatchTypeChange = () => {
  if (!props.item) return
  if (assessForm.value.match_type === 'root') {
    assessForm.value.target_domain = props.item.root_domain || props.item.domain || ''
  } else {
    assessForm.value.target_domain = props.item.domain || ''
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
    emit('update:modelValue', false)
    emit('saved', payload)
  } catch (e) {
    ui.showToast('保存研判失败: ' + e.message, 'error')
  } finally {
    savingAssess.value = false
  }
}
</script>
