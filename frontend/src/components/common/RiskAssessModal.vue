<template>
  <Modal
    :model-value="modelValue"
    :title="computedTitle"
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
              class="mt-0.5 text-purple-500 focus:ring-0 cursor-pointer"
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
              class="mt-0.5 text-purple-500 focus:ring-0 cursor-pointer"
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
            <span class="font-mono text-purple-400 font-semibold">
              {{ assessForm.match_type === 'root' ? `*.${cleanPreviewDomain}` : cleanPreviewDomain }}
            </span>
          </div>
          <input
            v-model="assessForm.target_domain"
            type="text"
            class="w-full px-3 py-2 bg-slate-900 border border-slate-700 rounded-lg text-sm text-slate-100 font-mono focus:outline-none focus:border-purple-500"
            placeholder="例如: evil-domain.com 或 *.gamble-site.top"
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
        <div class="flex flex-wrap items-center justify-between gap-1.5">
          <label class="block text-xs font-semibold text-slate-300">
            研判属性标签 (点击快速选择 / 联动风险)
          </label>
          <!-- Category Filter Pills -->
          <div class="flex items-center gap-1">
            <button
              type="button"
              v-for="cat in tagCategories"
              :key="cat.key"
              @click="activeTagCategory = cat.key"
              :class="[
                'px-2 py-0.5 rounded text-[11px] transition border cursor-pointer',
                activeTagCategory === cat.key
                  ? 'bg-purple-600 text-white border-purple-500 font-medium shadow-sm'
                  : 'bg-slate-900 text-slate-400 border-slate-800 hover:text-slate-200 hover:border-slate-700'
              ]"
            >
              {{ cat.name }}
            </button>
          </div>
        </div>

        <!-- Tag Pills Container -->
        <div class="p-2 bg-slate-950 rounded-xl border border-slate-800 space-y-2">
          <!-- Tag Category Groups or Filtered Tags -->
          <div class="flex flex-wrap gap-1.5 max-h-40 overflow-y-auto pr-1">
            <button
              type="button"
              v-for="tagObj in filteredTags"
              :key="tagObj.name"
              @click="toggleTag(tagObj)"
              :class="[
                'px-2.5 py-1 rounded-lg text-xs transition border flex items-center gap-1 cursor-pointer select-none',
                assessForm.tags.includes(tagObj.name)
                  ? 'bg-purple-950 text-purple-200 border-purple-500 font-semibold shadow-sm'
                  : 'bg-slate-900 text-slate-400 border-slate-800 hover:border-slate-700 hover:text-slate-200'
              ]"
            >
              <span class="text-[10px]">{{ assessForm.tags.includes(tagObj.name) ? '✓' : '+' }}</span>
              <span>{{ tagObj.name }}</span>
            </button>
          </div>

          <!-- Active custom tags and input -->
          <div class="flex items-center gap-2 pt-1 border-t border-slate-800/80">
            <input
              v-model="customTagInput"
              @keydown.enter.prevent="addCustomTag"
              type="text"
              placeholder="输入自定义标签 (按回车快速添加)..."
              class="flex-1 px-3 py-1.5 bg-slate-900 border border-slate-700 rounded-lg text-xs text-slate-200 focus:outline-none focus:border-purple-500"
            />
            <button
              type="button"
              @click="addCustomTag"
              class="px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs rounded-lg border border-slate-700 cursor-pointer transition"
            >
              添加标签
            </button>
          </div>
        </div>

        <!-- Selected Tags Bar -->
        <div v-if="assessForm.tags.length" class="flex flex-wrap items-center gap-1.5 pt-0.5">
          <span class="text-xs text-slate-500 self-center">已选属性标签 ({{ assessForm.tags.length }}):</span>
          <span
            v-for="tag in assessForm.tags"
            :key="tag"
            class="px-2 py-0.5 rounded text-xs bg-indigo-500/10 text-indigo-300 border border-indigo-500/30 flex items-center gap-1 font-medium"
          >
            {{ tag }}
            <button type="button" @click="removeTag(tag)" class="hover:text-rose-400 cursor-pointer">✕</button>
          </span>
          <button
            type="button"
            @click="assessForm.tags = []"
            class="text-[11px] text-slate-500 hover:text-slate-400 underline ml-1 cursor-pointer"
          >
            清空已选
          </button>
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
          class="px-4 py-2 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-lg text-xs transition cursor-pointer"
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
          {{ item ? '保存研判并同步' : '保存情报规则并同步' }}
        </button>
      </div>
    </form>
  </Modal>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
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
  },
  title: {
    type: String,
    default: ''
  }
})

const emit = defineEmits(['update:modelValue', 'saved'])
const ui = useUiStore()

const savingAssess = ref(false)
const customTagInput = ref('')
const activeTagCategory = ref('all')

// Comprehensive structured preset tags
const tagCategories = [
  {
    name: '全部',
    key: 'all'
  },
  {
    name: '黑灰产威胁',
    key: 'malicious',
    tags: [
      { name: '黑产博彩', defaultRisk: 'critical' },
      { name: '暗链挂马', defaultRisk: 'critical' },
      { name: '低俗色情', defaultRisk: 'critical' },
      { name: '恶意欺诈', defaultRisk: 'critical' },
      { name: '钓鱼盗号', defaultRisk: 'critical' },
      { name: '仿冒涉诈', defaultRisk: 'critical' },
      { name: '恶意C2', defaultRisk: 'critical' },
      { name: '挖矿脚本', defaultRisk: 'critical' }
    ]
  },
  {
    name: '违规引流',
    key: 'traffic',
    tags: [
      { name: '广告引流', defaultRisk: 'high' },
      { name: '纯IP外链', defaultRisk: 'medium' },
      { name: '短链跳转', defaultRisk: 'medium' },
      { name: '恶意重定向', defaultRisk: 'high' },
      { name: '未备案外链', defaultRisk: 'medium' },
      { name: '快照镜像', defaultRisk: 'medium' }
    ]
  },
  {
    name: '失效异常',
    key: 'lifecycle',
    tags: [
      { name: '失效废弃', defaultRisk: 'medium' },
      { name: '死链404', defaultRisk: 'low' },
      { name: '域名抢注劫持', defaultRisk: 'high' },
      { name: 'DNS解析失败', defaultRisk: 'low' }
    ]
  },
  {
    name: '官方安全',
    key: 'trusted',
    tags: [
      { name: '官方合作', defaultRisk: 'safe' },
      { name: '政务站群', defaultRisk: 'safe' },
      { name: '公共静态CDN', defaultRisk: 'safe' },
      { name: '云存储服务', defaultRisk: 'safe' },
      { name: '社交分享', defaultRisk: 'safe' },
      { name: '统计分析', defaultRisk: 'safe' },
      { name: '地图与字体', defaultRisk: 'safe' },
      { name: '支付结算', defaultRisk: 'safe' }
    ]
  }
]

// Flattened tags list
const allPresetTags = tagCategories
  .filter(cat => cat.key !== 'all')
  .flatMap(cat => cat.tags)

const filteredTags = computed(() => {
  if (activeTagCategory.value === 'all') {
    return allPresetTags
  }
  const category = tagCategories.find(c => c.key === activeTagCategory.value)
  return category ? category.tags : allPresetTags
})

const assessForm = ref({
  match_type: 'root',
  target_domain: '',
  risk_level: 'high',
  tags: [],
  remark: '',
  sync_to_history: true
})

const computedTitle = computed(() => {
  if (props.title) return props.title
  if (props.item) {
    return '外部域名快捷研判与全局情报沉淀'
  }
  return '添加威胁情报研判规则'
})

const cleanPreviewDomain = computed(() => {
  let dom = (assessForm.value.target_domain || '').trim()
  if (dom.startsWith('*.')) {
    dom = dom.substring(2)
  } else if (dom.startsWith('.')) {
    dom = dom.substring(1)
  }
  return dom || 'domain.com'
})

const initForm = (item) => {
  if (!item) {
    assessForm.value = {
      match_type: 'root',
      target_domain: '',
      risk_level: 'high',
      tags: [],
      remark: '',
      sync_to_history: true
    }
    customTagInput.value = ''
    activeTagCategory.value = 'all'
    return
  }

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
    match_type: item.match_type || (item.root_domain ? 'root' : 'exact'),
    target_domain: item.domain || item.root_domain || '',
    risk_level: item.risk_level && item.risk_level !== 'pending' ? item.risk_level : 'high',
    tags: parsedTags,
    remark: item.risk_remark || item.remark || '',
    sync_to_history: true
  }
  customTagInput.value = ''
  activeTagCategory.value = 'all'
}

watch(
  () => props.modelValue,
  (val) => {
    if (val) {
      initForm(props.item)
    }
  }
)

watch(
  () => props.item,
  (val) => {
    if (props.modelValue) {
      initForm(val)
    }
  }
)

const onMatchTypeChange = () => {
  if (props.item) {
    if (assessForm.value.match_type === 'root') {
      assessForm.value.target_domain = props.item.root_domain || props.item.domain || ''
    } else {
      assessForm.value.target_domain = props.item.domain || ''
    }
  } else {
    let dom = assessForm.value.target_domain.trim()
    if (dom.startsWith('*.')) {
      assessForm.value.target_domain = dom.substring(2)
    }
  }
}

const toggleTag = (tagObj) => {
  const tagName = typeof tagObj === 'string' ? tagObj : tagObj.name
  const idx = assessForm.value.tags.indexOf(tagName)
  if (idx > -1) {
    assessForm.value.tags.splice(idx, 1)
  } else {
    assessForm.value.tags.push(tagName)
    // Intelligent risk level suggestion
    if (tagObj && tagObj.defaultRisk) {
      if (tagObj.defaultRisk === 'critical') {
        assessForm.value.risk_level = 'critical'
      } else if (tagObj.defaultRisk === 'safe' && (assessForm.value.tags.length <= 1 || assessForm.value.risk_level === 'pending')) {
        assessForm.value.risk_level = 'safe'
      }
    }
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
  let domain = assessForm.value.target_domain.trim()
  if (!domain) {
    ui.showToast('目标域名不能为空', 'error')
    return
  }

  // Auto clean leading *. or .
  let matchType = assessForm.value.match_type
  if (domain.startsWith('*.')) {
    domain = domain.substring(2)
    matchType = 'root'
  } else if (domain.startsWith('.')) {
    domain = domain.substring(1)
  }

  savingAssess.value = true
  try {
    const payload = {
      domain,
      match_type: matchType,
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
    ui.showToast('保存研判失败: ' + (e.response?.data?.detail || e.message), 'error')
  } finally {
    savingAssess.value = false
  }
}
</script>
