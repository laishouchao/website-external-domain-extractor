import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import client from '@/api/client'
import { useUiStore } from './ui'

export const useAuthStore = defineStore('auth', () => {
  const token = ref(localStorage.getItem('access_token') || '')
  
  let savedUser = null
  try {
    const raw = localStorage.getItem('user_info')
    if (raw) savedUser = JSON.parse(raw)
  } catch (e) {
    savedUser = null
  }
  const user = ref(savedUser)
  const loading = ref(false)

  const isAuthenticated = computed(() => !!token.value)
  const isAdmin = computed(() => user.value?.role === 'admin')
  const userDisplayName = computed(() => user.value?.nickname || user.value?.username || '用户')

  const setAuth = (newToken, newUser) => {
    token.value = newToken
    user.value = newUser
    if (newToken) {
      localStorage.setItem('access_token', newToken)
    } else {
      localStorage.removeItem('access_token')
    }
    if (newUser) {
      localStorage.setItem('user_info', JSON.stringify(newUser))
    } else {
      localStorage.removeItem('user_info')
    }
  }

  const login = async (username, password) => {
    loading.value = true
    try {
      const res = await client.post('/auth/login', { username, password })
      setAuth(res.access_token, res.user)
      return res
    } finally {
      loading.value = false
    }
  }

  const fetchCurrentUser = async () => {
    if (!token.value) return null
    try {
      const userData = await client.get('/auth/me')
      user.value = userData
      localStorage.setItem('user_info', JSON.stringify(userData))
      return userData
    } catch (e) {
      // Token expired or invalid
      logout()
      throw e
    }
  }

  const logout = async () => {
    try {
      if (token.value) {
        await client.post('/auth/logout').catch(() => {})
      }
    } finally {
      setAuth('', null)
    }
  }

  const changePassword = async (oldPassword, newPassword) => {
    return await client.post('/auth/change-password', {
      old_password: oldPassword,
      new_password: newPassword
    })
  }

  return {
    token,
    user,
    loading,
    isAuthenticated,
    isAdmin,
    userDisplayName,
    login,
    logout,
    fetchCurrentUser,
    changePassword,
    setAuth
  }
})
