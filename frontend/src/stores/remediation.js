import { defineStore } from 'pinia'
import { ref } from 'vue'
import client from '@/api/client'
import { useUiStore } from './ui'

export const useRemediationStore = defineStore('remediation', () => {
  const ui = useUiStore()

  const pages = ref([])
  const total = ref(0)
  const page = ref(1)
  const pageSize = ref(50)
  const loading = ref(false)

  const stats = ref({
    total_items: 0,
    pending_count: 0,
    failed_count: 0,
    unverified_count: 0,
    clean_count: 0,
    tasks_affected: 0,
    unique_risk_domains: 0,
    unique_pages: 0,
    level_counts: { critical: 0, high: 0, medium: 0, low: 0 },
    task_summary: []
  })

  const timer = ref({
    is_running: true,
    is_checking: false,
    interval_seconds: 600,
    remaining_seconds: 600,
    last_run_time: null,
    next_run_time: null,
    last_run_stats: {}
  })

  const filters = ref({
    taskId: '',
    riskLevel: '',
    verifyStatus: 'pending_only',
    manualStatus: '',
    search: ''
  })

  const selectedIds = ref([])
  const verifyingId = ref(null)
  const isTriggeringBatch = ref(false)
  const isSyncing = ref(false)

  const loadPages = async (p = 1) => {
    page.value = p
    loading.value = true
    try {
      const params = {
        page: p,
        page_size: pageSize.value
      }
      if (filters.value.taskId) params.task_id = filters.value.taskId
      if (filters.value.riskLevel) params.risk_level = filters.value.riskLevel
      if (filters.value.verifyStatus) params.verify_status = filters.value.verifyStatus
      if (filters.value.manualStatus) params.manual_status = filters.value.manualStatus
      if (filters.value.search && filters.value.search.trim()) params.search = filters.value.search.trim()

      const res = await client.get('/risk-remediation/pages', { params })
      pages.value = res.items || []
      total.value = res.total || 0
    } catch (e) {
      console.error('Failed to load remediation pages:', e)
    } finally {
      loading.value = false
    }
  }

  const loadStats = async () => {
    try {
      const res = await client.get('/risk-remediation/stats')
      stats.value = res || {}
    } catch (e) {
      console.error('Failed to load remediation stats:', e)
    }
  }

  const loadTimerStatus = async () => {
    try {
      const res = await client.get('/risk-remediation/timer-status')
      timer.value = res || {}
    } catch (e) {
      console.error('Failed to load timer status:', e)
    }
  }

  const verifySingle = async (id) => {
    if (verifyingId.value !== null) return
    verifyingId.value = id
    try {
      const res = await client.post(`/risk-remediation/${id}/verify`)
      const item = pages.value.find(p => p.id === id)
      if (item) {
        item.verify_status = res.verify_status
        item.last_verified_at = res.verify_time
        item.last_verify_detail = res.verify_detail
      }
      ui.showToast('页面复测完成: ' + res.verify_detail, res.verify_status === 'verified_clean' || res.verify_status === 'page_removed' ? 'success' : 'warn')
      await loadStats()
    } catch (e) {
      ui.showToast('即时复测失败: ' + e.message, 'error')
    } finally {
      verifyingId.value = null
    }
  }

  const triggerBatchVerify = async () => {
    if (isTriggeringBatch.value) return
    isTriggeringBatch.value = true
    try {
      const res = await client.post('/risk-remediation/trigger-verify')
      ui.showToast(res.message || '已触发全量待复测风险页面校验', 'success')
      await loadTimerStatus()
      setTimeout(() => {
        loadPages(page.value)
        loadStats()
      }, 2000)
    } catch (e) {
      ui.showToast('触发复测失败: ' + e.message, 'error')
    } finally {
      isTriggeringBatch.value = false
    }
  }

  const syncOccurrences = async () => {
    if (isSyncing.value) return
    isSyncing.value = true
    try {
      const res = await client.post('/risk-remediation/sync')
      ui.showToast(`同步完成！对齐了 ${res.synced_count || 0} 条涉险页面存证`, 'success')
      await loadPages(1)
      await loadStats()
    } catch (e) {
      ui.showToast('同步存证失败: ' + e.message, 'error')
    } finally {
      isSyncing.value = false
    }
  }

  const batchUpdateStatus = async (status) => {
    if (!selectedIds.value.length) return
    try {
      const res = await client.post('/risk-remediation/batch-status', {
        ids: selectedIds.value,
        manual_status: status
      })
      ui.showToast(`已批量更新 ${res.updated_count || selectedIds.value.length} 个工单状态`, 'success')
      selectedIds.value = []
      await loadPages(page.value)
      await loadStats()
    } catch (e) {
      ui.showToast('批量更新状态失败: ' + e.message, 'error')
    }
  }

  return {
    pages,
    total,
    page,
    pageSize,
    loading,
    stats,
    timer,
    filters,
    selectedIds,
    verifyingId,
    isTriggeringBatch,
    isSyncing,
    loadPages,
    loadStats,
    loadTimerStatus,
    verifySingle,
    triggerBatchVerify,
    syncOccurrences,
    batchUpdateStatus
  }
})
