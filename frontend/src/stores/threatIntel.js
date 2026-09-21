import { defineStore } from 'pinia'
import { ref } from 'vue'
import client from '@/api/client'
import { useUiStore } from './ui'

export const useThreatIntelStore = defineStore('threatIntel', () => {
  const ui = useUiStore()

  const profiles = ref([])
  const total = ref(0)
  const page = ref(1)
  const pageSize = ref(50)
  const loading = ref(false)

  const loadProfiles = async (p = 1, search = '', level = '') => {
    page.value = p
    loading.value = true
    try {
      const offset = (p - 1) * pageSize.value
      const params = {
        limit: pageSize.value,
        offset
      }
      if (search && search.trim()) params.search = search.trim()
      if (level) params.risk_level = level

      const res = await client.get('/risk-profiles', { params })
      profiles.value = res.profiles || res.items || []
      total.value = res.total || 0
    } catch (e) {
      console.error('Failed to load risk profiles:', e)
    } finally {
      loading.value = false
    }
  }

  const addProfile = async (payload) => {
    try {
      const res = await client.post('/risk-profiles', payload)
      ui.showToast('风险情报规则已添加', 'success')
      await loadProfiles(page.value)
      return res
    } catch (e) {
      ui.showToast('添加规则失败: ' + e.message, 'error')
      throw e
    }
  }

  const deleteProfile = async (id) => {
    try {
      await client.delete(`/risk-profiles/${id}`)
      ui.showToast('情报规则已删除', 'info')
      await loadProfiles(page.value)
    } catch (e) {
      ui.showToast('删除规则失败: ' + e.message, 'error')
    }
  }

  const batchImport = async (items, syncToHistory = true) => {
    try {
      const res = await client.post('/risk-profiles/batch', { items, sync_to_history: syncToHistory })
      ui.showToast(`成功导入 ${res.imported_count || 0} 条规则并完成回溯标记`, 'success')
      await loadProfiles(1)
      return res
    } catch (e) {
      ui.showToast('批量导入失败: ' + e.message, 'error')
      throw e
    }
  }

  const syncAllToHistory = async () => {
    try {
      const res = await client.post('/risk-profiles/sync-history')
      ui.showToast(`全库历史回溯完成！比对 ${res.result?.profile_count || 0} 条规则，更新标记 ${res.result?.updated_domains || 0} 条域名`, 'success')
      return res
    } catch (e) {
      ui.showToast('全量回溯失败: ' + e.message, 'error')
      throw e
    }
  }

  return {
    profiles,
    total,
    page,
    pageSize,
    loading,
    loadProfiles,
    addProfile,
    deleteProfile,
    batchImport,
    syncAllToHistory
  }
})
