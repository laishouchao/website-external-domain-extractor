import { defineStore } from 'pinia'
import { ref } from 'vue'

export const useUiStore = defineStore('ui', () => {
  const sidebarCollapsed = ref(localStorage.getItem('sidebar_collapsed') === 'true')
  const theme = ref(localStorage.getItem('app_theme') || 'dark')
  const toasts = ref([])
  let toastId = 0

  const applyTheme = (t) => {
    theme.value = t
    localStorage.setItem('app_theme', t)
    const root = document.documentElement
    if (t === 'light') {
      root.classList.remove('dark')
      root.classList.add('light')
    } else {
      root.classList.remove('light')
      root.classList.add('dark')
    }
  }

  const toggleTheme = () => {
    applyTheme(theme.value === 'dark' ? 'light' : 'dark')
  }

  const setTheme = (t) => {
    applyTheme(t)
  }

  // Initialize theme on store creation
  applyTheme(theme.value)

  const toggleSidebar = () => {
    sidebarCollapsed.value = !sidebarCollapsed.value
    localStorage.setItem('sidebar_collapsed', sidebarCollapsed.value ? 'true' : 'false')
  }

  const showToast = (message, type = 'info', duration = 3500) => {
    const id = ++toastId
    toasts.value.push({ id, message, type })
    if (duration > 0) {
      setTimeout(() => {
        removeToast(id)
      }, duration)
    }
  }

  const removeToast = (id) => {
    const idx = toasts.value.findIndex(t => t.id === id)
    if (idx !== -1) {
      toasts.value.splice(idx, 1)
    }
  }

  return {
    sidebarCollapsed,
    theme,
    toasts,
    toggleSidebar,
    toggleTheme,
    setTheme,
    showToast,
    removeToast
  }
})
