<template>
  <div class="min-h-screen bg-slate-950 flex items-center justify-center p-4 relative overflow-hidden selection:bg-indigo-500 selection:text-white">
    <!-- Ambient Background Lighting & Cyber Grid Effects -->
    <div class="absolute inset-0 pointer-events-none">
      <div class="absolute -top-40 -left-40 w-96 h-96 bg-indigo-600/20 rounded-full blur-3xl"></div>
      <div class="absolute -bottom-40 -right-40 w-96 h-96 bg-sky-600/20 rounded-full blur-3xl"></div>
      <div class="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[600px] h-[600px] bg-emerald-600/10 rounded-full blur-[120px]"></div>
      <!-- Subtle Grid Lines -->
      <div class="absolute inset-0 bg-[linear-gradient(to_right,#1e293b15_1px,transparent_1px),linear-gradient(to_bottom,#1e293b15_1px,transparent_1px)] bg-[size:4rem_4rem]"></div>
    </div>

    <!-- Login Center Card -->
    <div class="w-full max-w-md relative z-10">
      <div class="bg-slate-900/80 backdrop-blur-xl border border-slate-800 rounded-2xl p-8 shadow-2xl shadow-black/60 space-y-7">
        <!-- Logo & Header -->
        <div class="text-center space-y-3">
          <div class="inline-flex items-center justify-center p-3 rounded-2xl bg-gradient-to-tr from-indigo-500/20 to-sky-500/20 border border-indigo-500/30 shadow-lg shadow-indigo-500/10">
            <Globe class="w-9 h-9 text-indigo-400 animate-pulse" />
          </div>
          <div>
            <h1 class="text-xl font-bold text-white tracking-tight">
              网站外部域名提取系统
            </h1>
            <p class="text-xs text-slate-400 mt-1">
              全深度站点地图扫描 · 外部域名资产识别 · 威胁情报研判
            </p>
          </div>
        </div>

        <!-- Error Notification -->
        <transition name="fade">
          <div
            v-if="errorMessage"
            class="p-3.5 rounded-xl bg-rose-500/10 border border-rose-500/30 text-rose-300 text-xs flex items-start gap-2.5 animate-shake"
          >
            <AlertCircle class="w-4 h-4 text-rose-400 shrink-0 mt-0.5" />
            <div class="flex-1">{{ errorMessage }}</div>
          </div>
        </transition>

        <!-- Form -->
        <form @submit.prevent="handleLogin" class="space-y-4">
          <!-- Username Input -->
          <div class="space-y-1.5">
            <label class="block text-xs font-medium text-slate-300">
              账号名称
            </label>
            <div class="relative">
              <div class="absolute inset-y-0 left-0 pl-3.5 flex items-center pointer-events-none text-slate-500">
                <User class="w-4 h-4" />
              </div>
              <input
                v-model="username"
                type="text"
                required
                autocomplete="username"
                placeholder="请输入登录用户名"
                class="w-full pl-10 pr-4 py-2.5 bg-slate-950/70 border border-slate-800 rounded-xl text-sm text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent transition"
              />
            </div>
          </div>

          <!-- Password Input -->
          <div class="space-y-1.5">
            <div class="flex items-center justify-between">
              <label class="block text-xs font-medium text-slate-300">
                登录密码
              </label>
            </div>
            <div class="relative">
              <div class="absolute inset-y-0 left-0 pl-3.5 flex items-center pointer-events-none text-slate-500">
                <Lock class="w-4 h-4" />
              </div>
              <input
                v-model="password"
                :type="showPassword ? 'text' : 'password'"
                required
                autocomplete="current-password"
                placeholder="请输入密码"
                class="w-full pl-10 pr-11 py-2.5 bg-slate-950/70 border border-slate-800 rounded-xl text-sm text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent transition"
              />
              <button
                type="button"
                @click="showPassword = !showPassword"
                class="absolute inset-y-0 right-0 pr-3.5 flex items-center text-slate-500 hover:text-slate-300 transition"
              >
                <EyeOff v-if="showPassword" class="w-4 h-4" />
                <Eye v-else class="w-4 h-4" />
              </button>
            </div>
          </div>

          <!-- Remember / Auto Login Option -->
          <div class="flex items-center justify-between text-xs text-slate-400 pt-1">
            <label class="flex items-center gap-2 cursor-pointer select-none">
              <input
                type="checkbox"
                v-model="rememberMe"
                class="rounded bg-slate-950 border-slate-700 text-indigo-600 focus:ring-indigo-500 focus:ring-offset-slate-900"
              />
              <span>保持登录状态 (7天免登)</span>
            </label>
            <span class="text-slate-500">系统内部鉴权</span>
          </div>

          <!-- Submit Button -->
          <button
            type="submit"
            :disabled="authStore.loading"
            class="w-full py-2.5 px-4 bg-gradient-to-r from-sky-500 via-indigo-600 to-indigo-700 hover:from-sky-400 hover:to-indigo-600 text-white font-medium rounded-xl text-sm shadow-lg shadow-indigo-600/30 hover:shadow-indigo-600/50 transition-all flex items-center justify-center gap-2 cursor-pointer disabled:opacity-60 disabled:cursor-not-allowed mt-2"
          >
            <Loader2 v-if="authStore.loading" class="w-4 h-4 animate-spin" />
            <ShieldCheck v-else class="w-4 h-4" />
            <span>{{ authStore.loading ? '正在验证身份...' : '立即登录' }}</span>
          </button>
        </form>

        <!-- Initial Credentials Helper -->
        <div class="pt-4 border-t border-slate-800/80">
          <div class="p-3 rounded-xl bg-slate-950/60 border border-slate-800 flex items-center justify-between text-xs text-slate-400">
            <div class="space-y-0.5">
              <div class="text-[11px] text-slate-500 font-medium">默认初始管理员账号</div>
              <div class="font-mono text-slate-300 font-medium">admin / admin123</div>
            </div>
            <button
              type="button"
              @click="fillDefaultCredentials"
              class="px-2.5 py-1 text-xs rounded-lg bg-indigo-500/10 hover:bg-indigo-500/20 text-indigo-400 border border-indigo-500/30 transition cursor-pointer"
            >
              一键填入
            </button>
          </div>
        </div>
      </div>

      <!-- Footer Info -->
      <div class="text-center mt-6 text-xs text-slate-600">
        网站全深度爬取与外部域名分析管控平台 &copy; 2026
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { useUiStore } from '@/stores/ui'
import {
  Globe,
  User,
  Lock,
  Eye,
  EyeOff,
  AlertCircle,
  Loader2,
  ShieldCheck
} from 'lucide-vue-next'

const router = useRouter()
const route = useRoute()
const authStore = useAuthStore()
const uiStore = useUiStore()

const username = ref('')
const password = ref('')
const showPassword = ref(false)
const rememberMe = ref(true)
const errorMessage = ref('')

const fillDefaultCredentials = () => {
  username.value = 'admin'
  password.value = 'admin123'
  errorMessage.value = ''
}

const handleLogin = async () => {
  errorMessage.value = ''
  if (!username.value.trim() || !password.value) {
    errorMessage.value = '请输入用户名和密码'
    return
  }

  try {
    await authStore.login(username.value.trim(), password.value)
    uiStore.showToast(`欢迎回来，${authStore.userDisplayName}！`, 'success')

    // Redirect to requested page or dashboard
    const redirect = route.query.redirect || '/dashboard'
    router.replace(redirect)
  } catch (err) {
    errorMessage.value = err.message || '登录失败，请检查账号密码'
  }
}
</script>

<style scoped>
@keyframes shake {
  0%, 100% { transform: translateX(0); }
  20%, 60% { transform: translateX(-4px); }
  40%, 80% { transform: translateX(4px); }
}
.animate-shake {
  animation: shake 0.4s ease-in-out;
}
</style>
