<template>
  <header class="h-16 bg-slate-900/90 backdrop-blur border-b border-slate-800 flex items-center justify-between px-4 sm:px-6 sticky top-0 z-20">
    <div class="flex items-center gap-3">
      <button
        v-if="ui.sidebarCollapsed"
        @click="ui.toggleSidebar"
        class="text-slate-400 hover:text-white p-1.5 rounded-lg hover:bg-slate-800 transition md:hidden"
      >
        <Menu class="w-5 h-5" />
      </button>

      <!-- Breadcrumbs / Page Title -->
      <div class="flex items-center gap-2 text-xs">
        <span class="text-slate-500">工作台</span>
        <span class="text-slate-600">/</span>
        <span class="text-white font-semibold">{{ currentTitle }}</span>
      </div>
    </div>

    <!-- Right Controls -->
    <div class="flex items-center gap-3">
      <!-- Active Crawler Running Tag -->
      <div
        v-if="tasksStore.runningTasksCount > 0"
        class="hidden sm:flex items-center gap-2 px-3 py-1 rounded-full bg-emerald-950/70 border border-emerald-800/80 text-emerald-300 text-xs shadow-sm"
      >
        <span class="relative flex h-2 w-2">
          <span class="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
          <span class="relative inline-flex rounded-full h-2 w-2 bg-emerald-500"></span>
        </span>
        <span class="font-medium">正在并发扫描: {{ tasksStore.runningTasksCount }} 个任务</span>
      </div>

      <!-- Theme Switcher -->
      <button
        @click="ui.toggleTheme"
        class="p-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-300 transition border border-slate-700 flex items-center justify-center cursor-pointer"
        :title="ui.theme === 'dark' ? '切换为浅色明亮模式' : '切换为深色暗黑模式'"
      >
        <Sun v-if="ui.theme === 'dark'" class="w-4 h-4 text-amber-400" />
        <Moon v-else class="w-4 h-4 text-indigo-400" />
      </button>

      <!-- Quick Action Buttons -->
      <button
        @click="$emit('open-batch-modal')"
        class="text-xs font-semibold px-3 py-2 rounded-xl bg-indigo-600/20 hover:bg-indigo-600/30 text-indigo-300 border border-indigo-500/30 transition flex items-center gap-1.5 shadow-sm cursor-pointer"
      >
        <Layers class="w-3.5 h-3.5" />
        <span class="hidden md:inline">批量导入任务</span>
      </button>

      <button
        @click="$emit('open-create-modal')"
        class="text-xs font-semibold px-3.5 py-2 rounded-xl bg-gradient-to-r from-sky-500 to-indigo-600 hover:from-sky-400 hover:to-indigo-500 text-white transition flex items-center gap-1.5 shadow-md shadow-sky-500/20 cursor-pointer"
      >
        <Plus class="w-4 h-4" />
        <span>新建扫描</span>
      </button>

      <!-- User Profile & Account Dropdown -->
      <div class="relative" ref="dropdownRef">
        <button
          @click="dropdownOpen = !dropdownOpen"
          class="flex items-center gap-2 pl-2 pr-3 py-1.5 rounded-xl bg-slate-800/80 hover:bg-slate-800 border border-slate-700/80 transition cursor-pointer text-xs text-slate-200"
        >
          <div class="w-7 h-7 rounded-lg bg-indigo-500/20 border border-indigo-500/30 text-indigo-400 flex items-center justify-center font-bold">
            <User class="w-4 h-4" />
          </div>
          <div class="hidden md:flex flex-col text-left">
            <span class="font-medium text-slate-200 leading-tight">{{ authStore.userDisplayName }}</span>
            <span class="text-[10px] text-slate-400 leading-tight">{{ authStore.user?.role === 'admin' ? '系统管理员' : '操作员' }}</span>
          </div>
          <ChevronDown class="w-3.5 h-3.5 text-slate-400" />
        </button>

        <!-- Dropdown Menu -->
        <transition name="fade">
          <div
            v-if="dropdownOpen"
            class="absolute right-0 mt-2 w-52 bg-slate-900 border border-slate-800 rounded-xl shadow-2xl p-1.5 z-50 space-y-1"
          >
            <div class="px-3 py-2 border-b border-slate-800/80">
              <div class="font-semibold text-xs text-slate-200 truncate">{{ authStore.userDisplayName }}</div>
              <div class="text-[10px] text-slate-400 font-mono">账号: {{ authStore.user?.username }}</div>
            </div>

            <button
              @click="openChangePasswordModal"
              class="w-full flex items-center gap-2 px-3 py-2 text-xs text-slate-300 hover:text-white hover:bg-slate-800/80 rounded-lg transition cursor-pointer"
            >
              <KeyRound class="w-4 h-4 text-indigo-400" />
              <span>修改密码</span>
            </button>

            <button
              @click="handleLogout"
              class="w-full flex items-center gap-2 px-3 py-2 text-xs text-rose-400 hover:text-rose-300 hover:bg-rose-500/10 rounded-lg transition cursor-pointer"
            >
              <LogOut class="w-4 h-4" />
              <span>退出登录</span>
            </button>
          </div>
        </transition>
      </div>
    </div>

    <!-- Change Password Modal -->
    <Modal
      :model-value="changePasswordModalOpen"
      title="修改个人密码"
      size="md"
      @update:model-value="changePasswordModalOpen = $event"
    >
      <form @submit.prevent="submitChangePassword" class="space-y-4">
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
            @click="changePasswordModalOpen = false"
            class="px-4 py-2 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-xl text-xs font-medium transition cursor-pointer"
          >
            取消
          </button>
          <button
            type="submit"
            :disabled="isSubmittingPwd"
            class="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white rounded-xl text-xs font-semibold transition cursor-pointer flex items-center gap-1.5 shadow-sm"
          >
            <Loader2 v-if="isSubmittingPwd" class="w-3.5 h-3.5 animate-spin" />
            <span>确认修改</span>
          </button>
        </div>
      </form>
    </Modal>
  </header>
</template>

<script setup>
import { ref, reactive, computed, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  Menu,
  Plus,
  Layers,
  Sun,
  Moon,
  User,
  KeyRound,
  LogOut,
  ChevronDown,
  Loader2
} from 'lucide-vue-next'
import { useUiStore } from '@/stores/ui'
import { useTasksStore } from '@/stores/tasks'
import { useAuthStore } from '@/stores/auth'
import Modal from '@/components/common/Modal.vue'

defineEmits(['open-create-modal', 'open-batch-modal'])

const route = useRoute()
const router = useRouter()
const ui = useUiStore()
const tasksStore = useTasksStore()
const authStore = useAuthStore()

const dropdownOpen = ref(false)
const dropdownRef = ref(null)

const changePasswordModalOpen = ref(false)
const isSubmittingPwd = ref(false)
const pwdError = ref('')
const pwdForm = reactive({
  oldPassword: '',
  newPassword: '',
  confirmPassword: ''
})

const currentTitle = computed(() => {
  return route.meta.title || '系统总览'
})

// Close dropdown when clicking outside
const handleClickOutside = (e) => {
  if (dropdownRef.value && !dropdownRef.value.contains(e.target)) {
    dropdownOpen.value = false
  }
}

onMounted(() => {
  document.addEventListener('click', handleClickOutside)
})

onUnmounted(() => {
  document.removeEventListener('click', handleClickOutside)
})

const openChangePasswordModal = () => {
  dropdownOpen.value = false
  pwdForm.oldPassword = ''
  pwdForm.newPassword = ''
  pwdForm.confirmPassword = ''
  pwdError.value = ''
  changePasswordModalOpen.value = true
}

const submitChangePassword = async () => {
  pwdError.value = ''
  if (pwdForm.newPassword !== pwdForm.confirmPassword) {
    pwdError.value = '两次输入的新密码不一致'
    return
  }
  if (pwdForm.newPassword.length < 6) {
    pwdError.value = '新密码长度至少需要6位'
    return
  }

  isSubmittingPwd.value = true
  try {
    await authStore.changePassword(pwdForm.oldPassword, pwdForm.newPassword)
    ui.showToast('密码修改成功！', 'success')
    changePasswordModalOpen.value = false
  } catch (err) {
    pwdError.value = err.message || '密码修改失败，请检查旧密码'
  } finally {
    isSubmittingPwd.value = false
  }
}

const handleLogout = async () => {
  dropdownOpen.value = false
  if (confirm('确认退出登录当前账号？')) {
    await authStore.logout()
    ui.showToast('已退出登录', 'info')
    router.replace('/login')
  }
}
</script>
