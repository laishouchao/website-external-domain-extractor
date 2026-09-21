import { defineStore } from 'pinia'
import { ref } from 'vue'
import client from '@/api/client'
import { useUiStore } from './ui'

export const useGlobalDomainsStore = defineStore('globalDomains', () => {
  const ui = useUiStore()

  const domains = ref([])
  const total = ref(0)
  const page = ref(1)
  const pageSize = ref(50)
  const loading = ref(false)

  const stats = ref({
    total_unique_domains: 0,
    total_domain_occurrences: 0,
    active_tasks_count: 0,
    risk_domains_count: 0
  })

  const filters = ref({
    search: '',
    sourceType: 'all',
    riskLevel: '',
    verifyStatus: '',
    sortBy: 'total_occurrences',
    order: 'DESC'
  })

  const associatedTasks = ref([])
  const loadingTasks = ref(false)

  const loadDomains = async (p = 1) => {
    page.value = p
    loading.value = true
    try {
      const offset = (p - 1) * pageSize.value
      const params = {
        limit: pageSize.value,
        offset,
        sort_by: filters.value.sortBy || 'total_occurrences',
        order: filters.value.order || 'DESC'
      }
      if (filters.value.search && filters.value.search.trim()) params.search = filters.value.search.trim()
      if (filters.value.sourceType === 'link') params.has_link = 1
      if (filters.value.sourceType === 'text') params.has_text = 1
      if (filters.value.riskLevel) params.risk_level = filters.value.riskLevel
      if (filters.value.verifyStatus) params.verify_status = filters.value.verifyStatus

      const res = await client.get('/global-domains', { params })
      domains.value = res.domains || []
      total.value = res.total || 0
    } catch (e) {
      console.error('Failed to load global domains:', e)
    } finally {
      loading.value = false
    }
  }

  const loadStats = async () => {
    try {
      const res = await client.get('/global-domains/stats')
      stats.value = res || {}
    } catch (e) {
      console.error('Failed to load global domain stats:', e)
    }
  }

  const loadAssociatedTasks = async (domain) => {
    loadingTasks.value = true
    try {
      const res = await client.get(`/global-domains/${encodeURIComponent(domain)}/tasks`)
      associatedTasks.value = res.tasks || []
      return associatedTasks.value
    } catch (e) {
      ui.showToast('加载关联任务失败: ' + e.message, 'error')
      return []
    } finally {
      loadingTasks.value = false
    }
  }

  const verifyDomainAcrossTasks = async (domain) => {
    try {
      const res = await client.post(`/global-domains/${encodeURIComponent(domain)}/verify`)
      const isClean = res.overall_status === 'verified_clean'
      ui.showToast(
        `全库复测完成！已全量复测 ${res.task_count || 0} 个任务中的所有页面，状态: ${isClean ? '全部已清除修复' : '仍存在存留代码'}`,
        isClean ? 'success' : 'warning'
      )
      // Sync local task states in associatedTasks if open
      if (res.tasks && Array.isArray(res.tasks)) {
        for (const r of res.tasks) {
          const found = associatedTasks.value.find(t => t.task_id === r.task_id)
          if (found) {
            found.verify_status = r.verify_status
            found.verify_time = r.verify_time
            found.verify_progress = r.progress_text
            found.total_pages = r.total_pages
            found.cleared_count = r.cleared_count
            found.still_present_count = r.still_present_count
            found.verify_summary = r.summary
          }
        }
      }
      await loadDomains(page.value)
      await loadStats()
      return res
    } catch (e) {
      ui.showToast('全库复测失败: ' + e.message, 'error')
      throw e
    }
  }

  const verifyDomainInTask = async (domain, taskId) => {
    try {
      const res = await client.post(`/global-domains/${encodeURIComponent(domain)}/tasks/${taskId}/verify`)
      const isClean = res.verify_status === 'verified_clean'
      ui.showToast(
        `任务 #${taskId} 复测完成: ${res.summary || res.verify_status}`,
        isClean ? 'success' : 'warning'
      )
      // Sync this specific task state
      const found = associatedTasks.value.find(t => t.task_id === taskId)
      if (found) {
        found.verify_status = res.verify_status
        found.verify_time = res.verify_time
        found.verify_progress = res.progress_text
        found.total_pages = res.total_pages
        found.cleared_count = res.cleared_count
        found.still_present_count = res.still_present_count
        found.verify_summary = res.summary
      }
      await loadDomains(page.value)
      await loadStats()
      return res
    } catch (e) {
      ui.showToast(`任务 #${taskId} 复测失败: ` + e.message, 'error')
      throw e
    }
  }

  return {
    domains,
    total,
    page,
    pageSize,
    loading,
    stats,
    filters,
    associatedTasks,
    loadingTasks,
    loadDomains,
    loadStats,
    loadAssociatedTasks,
    verifyDomainAcrossTasks,
    verifyDomainInTask
  }
})
