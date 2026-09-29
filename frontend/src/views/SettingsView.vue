<template>
  <div class="max-w-5xl mx-auto space-y-6">
    <!-- Header -->
    <div>
      <h1 class="text-2xl font-bold text-slate-100 flex items-center gap-2.5">
        <Settings class="w-6 h-6 text-indigo-400" />
        系统设置与运行环境
      </h1>
      <p class="text-xs text-slate-400 mt-1">
        查看网络爬虫引擎运行状态、PostgreSQL 数据库连接与整改巡检调度器健康指标
      </p>
    </div>

    <!-- Cards Grid -->
    <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
      <!-- Database Connection Status Card -->
      <div class="bg-slate-900 border border-slate-800 rounded-xl p-6 space-y-4">
        <div class="flex items-center justify-between">
          <h3 class="text-sm font-semibold text-slate-200 flex items-center gap-2">
            <Database class="w-4 h-4 text-emerald-400" />
            PostgreSQL 数据库存储引擎
          </h3>
          <span class="px-2 py-0.5 rounded-full text-xs font-medium bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 flex items-center gap-1">
            <span class="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse"></span>
            已连接就绪
          </span>
        </div>

        <div class="space-y-3 text-xs">
          <div class="flex justify-between py-2 border-b border-slate-800/80">
            <span class="text-slate-400">数据库驱动</span>
            <span class="font-mono text-slate-200">psycopg2-binary / asyncpg</span>
          </div>
          <div class="flex justify-between py-2 border-b border-slate-800/80">
            <span class="text-slate-400">存储引擎类型</span>
            <span class="font-mono text-indigo-400 font-medium">PostgreSQL 14+</span>
          </div>
          <div class="flex justify-between py-2 border-b border-slate-800/80">
            <span class="text-slate-400">数据库名称</span>
            <span class="font-mono text-slate-200">crawler_domain_extractor</span>
          </div>
          <div class="flex justify-between py-2">
            <span class="text-slate-400">连接池管理</span>
            <span class="text-emerald-400 font-mono">ThreadedConnectionPool (Min 5 / Max 30)</span>
          </div>
        </div>
      </div>

      <!-- Crawler Engine Settings Card -->
      <div class="bg-slate-900 border border-slate-800 rounded-xl p-6 space-y-4">
        <div class="flex items-center justify-between">
          <h3 class="text-sm font-semibold text-slate-200 flex items-center gap-2">
            <Cpu class="w-4 h-4 text-indigo-400" />
            异步网络爬虫与提取引擎
          </h3>
          <span class="px-2 py-0.5 rounded-full text-xs font-medium bg-indigo-500/10 text-indigo-300 border border-indigo-500/20">
            Active
          </span>
        </div>

        <div class="space-y-3 text-xs">
          <div class="flex justify-between py-2 border-b border-slate-800/80">
            <span class="text-slate-400">网络底层技术</span>
            <span class="font-mono text-slate-200">httpx (Async Client, HTTP/2 Ready)</span>
          </div>
          <div class="flex justify-between py-2 border-b border-slate-800/80">
            <span class="text-slate-400">页面解析引擎</span>
            <span class="font-mono text-slate-200">BeautifulSoup4 (lxml parser) + Regex</span>
          </div>
          <div class="flex justify-between py-2 border-b border-slate-800/80">
            <span class="text-slate-400">默认并发协程限制</span>
            <span class="font-mono text-indigo-400">10 协程 / 单任务</span>
          </div>
          <div class="flex justify-between py-2">
            <span class="text-slate-400">请求超时时间</span>
            <span class="font-mono text-slate-200">15.0 秒</span>
          </div>
        </div>
      </div>

      <!-- Periodic Verifier Card -->
      <div class="bg-slate-900 border border-slate-800 rounded-xl p-6 space-y-4">
        <div class="flex items-center justify-between">
          <h3 class="text-sm font-semibold text-slate-200 flex items-center gap-2">
            <Clock class="w-4 h-4 text-amber-400" />
            3 小时整改闭环巡检调度器
          </h3>
          <span class="px-2 py-0.5 rounded-full text-xs font-medium bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
            Running
          </span>
        </div>

        <div class="space-y-3 text-xs">
          <div class="flex justify-between py-2 border-b border-slate-800/80">
            <span class="text-slate-400">调度周期</span>
            <span class="font-mono text-amber-300">每 3 小时 (10800 秒) 自动轮询</span>
          </div>
          <div class="flex justify-between py-2 border-b border-slate-800/80">
            <span class="text-slate-400">校验对象范围</span>
            <span class="text-slate-200">未复测或复测仍残留的涉险页面</span>
          </div>
          <div class="flex justify-between py-2">
            <span class="text-slate-400">判定算法</span>
            <span class="text-slate-200">异步并发 HTTP 抓取 + DOM 属性精准搜索 + 代码切片匹配</span>
          </div>
        </div>
      </div>

      <!-- System Architecture & Version Card -->
      <div class="bg-slate-900 border border-slate-800 rounded-xl p-6 space-y-4">
        <div class="flex items-center justify-between">
          <h3 class="text-sm font-semibold text-slate-200 flex items-center gap-2">
            <ShieldCheck class="w-4 h-4 text-cyan-400" />
            前端现代工程化架构
          </h3>
          <span class="px-2 py-0.5 rounded-full text-xs font-medium bg-cyan-500/10 text-cyan-300 border border-cyan-500/20">
            Vite 5 + Vue 3
          </span>
        </div>

        <div class="space-y-3 text-xs">
          <div class="flex justify-between py-2 border-b border-slate-800/80">
            <span class="text-slate-400">前端框架</span>
            <span class="font-mono text-slate-200">Vue 3.4 (Composition API &lt;script setup&gt;)</span>
          </div>
          <div class="flex justify-between py-2 border-b border-slate-800/80">
            <span class="text-slate-400">构建工具</span>
            <span class="font-mono text-slate-200">Vite 5 (Rollup Bundled SPA)</span>
          </div>
          <div class="flex justify-between py-2 border-b border-slate-800/80">
            <span class="text-slate-400">状态管理</span>
            <span class="font-mono text-slate-200">Pinia 2.1</span>
          </div>
          <div class="flex justify-between py-2">
            <span class="text-slate-400">图标库与样式</span>
            <span class="font-mono text-indigo-400">Lucide SVG + Tailwind CSS</span>
          </div>
        </div>
      </div>

      <!-- Appearance & Theme Setting Card -->
      <div class="bg-slate-900 border border-slate-800 rounded-xl p-6 space-y-4 md:col-span-2">
        <div class="flex items-center justify-between">
          <h3 class="text-sm font-semibold text-slate-200 flex items-center gap-2">
            <Palette class="w-4 h-4 text-amber-400" />
            界面外观与主题偏好
          </h3>
          <span class="text-xs text-slate-400">
            当前模式: <strong class="text-indigo-400">{{ ui.theme === 'dark' ? '深色暗黑模式' : '浅色明亮模式' }}</strong>
          </span>
        </div>

        <p class="text-xs text-slate-400">
          系统支持根据环境光线与使用习惯一键切换深浅色风格，您也可在顶部导航栏右上角随时快速切换。
        </p>

        <div class="grid grid-cols-1 sm:grid-cols-2 gap-4 pt-2">
          <!-- Dark Theme Option -->
          <div
            @click="ui.setTheme('dark')"
            class="p-4 rounded-xl border cursor-pointer transition flex items-center justify-between"
            :class="ui.theme === 'dark' ? 'bg-indigo-950/30 border-indigo-500 shadow-md ring-1 ring-indigo-500/50' : 'bg-slate-950 border-slate-800 hover:border-slate-700'"
          >
            <div class="flex items-center gap-3">
              <div class="p-2.5 rounded-lg bg-slate-900 border border-slate-800 text-indigo-400">
                <Moon class="w-5 h-5" />
              </div>
              <div>
                <div class="text-sm font-semibold text-slate-200">深色暗黑模式 (Dark Mode)</div>
                <div class="text-xs text-slate-500 mt-0.5">专业网络安全监控大屏风格，夜间更护眼</div>
              </div>
            </div>
            <div v-if="ui.theme === 'dark'" class="w-2.5 h-2.5 rounded-full bg-indigo-500 shadow-sm shadow-indigo-500"></div>
          </div>

          <!-- Light Theme Option -->
          <div
            @click="ui.setTheme('light')"
            class="p-4 rounded-xl border cursor-pointer transition flex items-center justify-between"
            :class="ui.theme === 'light' ? 'bg-amber-950/20 border-amber-500 shadow-md ring-1 ring-amber-500/50' : 'bg-slate-950 border-slate-800 hover:border-slate-700'"
          >
            <div class="flex items-center gap-3">
              <div class="p-2.5 rounded-lg bg-slate-800 text-amber-400">
                <Sun class="w-5 h-5" />
              </div>
              <div>
                <div class="text-sm font-semibold text-slate-200">浅色明亮模式 (Light Mode)</div>
                <div class="text-xs text-slate-500 mt-0.5">高对比度清爽企业报表风格，白天更清晰</div>
              </div>
            </div>
            <div v-if="ui.theme === 'light'" class="w-2.5 h-2.5 rounded-full bg-amber-500 shadow-sm shadow-amber-500"></div>
          </div>
        </div>
      </div>

      <!-- Account & Auth Security Card -->
      <div class="bg-slate-900 border border-slate-800 rounded-xl p-6 space-y-4 md:col-span-2">
        <div class="flex items-center justify-between">
          <h3 class="text-sm font-semibold text-slate-200 flex items-center gap-2">
            <UserCheck class="w-4 h-4 text-sky-400" />
            用户鉴权与账号安全
          </h3>
          <span class="px-2 py-0.5 rounded-full text-xs font-medium bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 flex items-center gap-1">
            <span class="w-1.5 h-1.5 rounded-full bg-emerald-400"></span>
            当前会话已认证
          </span>
        </div>

        <div class="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-4 gap-4 text-xs">
          <div class="p-3.5 bg-slate-950/60 border border-slate-800 rounded-xl space-y-1">
            <span class="text-slate-500">当前账号</span>
            <div class="font-mono text-sm font-semibold text-slate-200">{{ authStore.user?.username || 'admin' }}</div>
          </div>

          <div class="p-3.5 bg-slate-950/60 border border-slate-800 rounded-xl space-y-1">
            <span class="text-slate-500">用户昵称 / 角色</span>
            <div class="text-sm font-semibold text-slate-200">{{ authStore.userDisplayName }} ({{ authStore.user?.role === 'admin' ? '超级管理员' : '操作员' }})</div>
          </div>

          <div class="p-3.5 bg-slate-950/60 border border-slate-800 rounded-xl space-y-1">
            <span class="text-slate-500">加密算法与令牌</span>
            <div class="font-mono text-sm font-semibold text-indigo-400">JWT (HS256) + Bcrypt</div>
          </div>

          <div class="p-3.5 bg-slate-950/60 border border-slate-800 rounded-xl flex items-center justify-between">
            <div class="space-y-1">
              <span class="text-slate-500">密码安全</span>
              <div class="text-xs text-slate-300">已设置加密哈希</div>
            </div>
            <button
              @click="openChangePwdModal"
              class="px-3 py-1.5 rounded-lg bg-indigo-600/20 hover:bg-indigo-600/30 text-indigo-300 border border-indigo-500/30 text-xs font-medium flex items-center gap-1.5 transition cursor-pointer"
            >
              <KeyRound class="w-3.5 h-3.5" />
              <span>修改密码</span>
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- Password Modal -->
    <Modal
      :model-value="changePwdModalOpen"
      title="修改管理员密码"
      size="md"
      @update:model-value="changePwdModalOpen = $event"
    >
      <form @submit.prevent="submitChangePwd" class="space-y-4">
        <div class="space-y-1.5">
          <label class="block text-xs font-medium text-slate-300">当前旧密码</label>
          <input
            v-model="pwdForm.oldPassword"
            type="password"
            required
            placeholder="请输入当前旧密码"
            class="w-full px-3.5 py-2 bg-slate-950 border border-slate-800 rounded-xl text-xs text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-indigo-500"
          />
        </div>

        <div class="space-y-1.5">
          <label class="block text-xs font-medium text-slate-300">新密码（至少6位）</label>
          <input
            v-model="pwdForm.newPassword"
            type="password"
            required
            minlength="6"
            placeholder="请输入新密码"
            class="w-full px-3.5 py-2 bg-slate-950 border border-slate-800 rounded-xl text-xs text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-indigo-500"
          />
        </div>

        <div class="space-y-1.5">
          <label class="block text-xs font-medium text-slate-300">确认新密码</label>
          <input
            v-model="pwdForm.confirmPassword"
            type="password"
            required
            minlength="6"
            placeholder="请再次输入新密码"
            class="w-full px-3.5 py-2 bg-slate-950 border border-slate-800 rounded-xl text-xs text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-indigo-500"
          />
        </div>

        <div v-if="pwdError" class="p-2.5 rounded-lg bg-rose-500/10 border border-rose-500/30 text-rose-300 text-xs">
          {{ pwdError }}
        </div>

        <div class="flex items-center justify-end gap-3 pt-3 border-t border-slate-800">
          <button
            type="button"
            @click="changePwdModalOpen = false"
            class="px-4 py-2 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-xl text-xs font-medium transition cursor-pointer"
          >
            取消
          </button>
          <button
            type="submit"
            :disabled="isSubmitting"
            class="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white rounded-xl text-xs font-semibold transition cursor-pointer flex items-center gap-1.5 shadow-sm"
          >
            <Loader2 v-if="isSubmitting" class="w-3.5 h-3.5 animate-spin" />
            <span>确认修改</span>
          </button>
        </div>
      </form>
    </Modal>
  </div>
</template>

<script setup>
import { ref, reactive } from 'vue'
import {
  Settings,
  Database,
  Cpu,
  Clock,
  ShieldCheck,
  Palette,
  Sun,
  Moon,
  UserCheck,
  KeyRound,
  Loader2
} from 'lucide-vue-next'
import { useUiStore } from '@/stores/ui'
import { useAuthStore } from '@/stores/auth'
import Modal from '@/components/common/Modal.vue'

const ui = useUiStore()
const authStore = useAuthStore()

const changePwdModalOpen = ref(false)
const isSubmitting = ref(false)
const pwdError = ref('')
const pwdForm = reactive({
  oldPassword: '',
  newPassword: '',
  confirmPassword: ''
})

const openChangePwdModal = () => {
  pwdForm.oldPassword = ''
  pwdForm.newPassword = ''
  pwdForm.confirmPassword = ''
  pwdError.value = ''
  changePwdModalOpen.value = true
}

const submitChangePwd = async () => {
  pwdError.value = ''
  if (pwdForm.newPassword !== pwdForm.confirmPassword) {
    pwdError.value = '两次输入的新密码不一致'
    return
  }
  if (pwdForm.newPassword.length < 6) {
    pwdError.value = '新密码长度至少需要6位'
    return
  }

  isSubmitting.value = true
  try {
    await authStore.changePassword(pwdForm.oldPassword, pwdForm.newPassword)
    ui.showToast('密码修改成功！', 'success')
    changePwdModalOpen.value = false
  } catch (err) {
    pwdError.value = err.message || '密码修改失败，请检查旧密码'
  } finally {
    isSubmitting.value = false
  }
}
</script>
