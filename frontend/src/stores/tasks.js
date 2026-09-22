import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import client from '@/api/client'
import { useUiStore } from './ui'

export const useTasksStore = defineStore('tasks', () => {
  const ui = useUiStore()
  const tasks = ref([])
  const activeTask = ref(null)
  const loading = ref(false)
  const refreshing = ref(false)
  const selectedTaskIds = ref([])
  const deletingTaskIds = ref([])

  const runningTasksCount = computed(() => tasks.value.filter(t => t.status === 'running').length)
  const totalPagesCrawled = computed(() => tasks.value.reduce((acc, t) => acc + (t.pages_crawled || t.crawled_pages || 0), 0))
  const totalExtDomainsFound = computed(() => tasks.value.reduce((acc, t) => acc + (t.external_domains_count || 0), 0))
  const totalSubdomainsFound = computed(() => tasks.value.reduce((acc, t) => acc + (t.subdomains_count || 0), 0))

  const loadTasks = async (silent = false) => {
    // Only set full-screen/table skeleton loading on first load if no data exists
    if (!silent && tasks.value.length === 0) {
      loading.value = true
    }
    refreshing.value = true
    try {
      const data = await client.get('/tasks', { params: { limit: 500 } })
      const items = Array.isArray(data) ? data : (data?.tasks || [])
      const newItems = items.filter(t => t && t.status !== 'deleting')

      if (tasks.value.length === 0) {
        tasks.value = newItems
      } else {
        // In-place reconciliation to prevent DOM destruction and screen flickering
        const existingMap = new Map(tasks.value.map(t => [t.id, t]))
        const reconciled = []
        for (const item of newItems) {
          const existing = existingMap.get(item.id)
          if (existing) {
            Object.assign(existing, item)
            reconciled.push(existing)
          } else {
            reconciled.push(item)
          }
        }
        tasks.value = reconciled
      }

      if (activeTask.value) {
        const found = tasks.value.find(t => t.id === activeTask.value.id)
        if (found) Object.assign(activeTask.value, found)
      }
    } catch (e) {
      console.error('Failed to load tasks:', e)
    } finally {
      loading.value = false
      refreshing.value = false
    }
  }

  const getTask = async (id) => {
    try {
      const data = await client.get(`/tasks/${id}`)
      activeTask.value = data
      return data
    } catch (e) {
      ui.showToast('获取任务详情失败: ' + e.message, 'error')
      throw e
    }
  }

  const fetchTask = getTask

  const createTask = async (payload) => {
    try {
      const res = await client.post('/tasks', payload)
      ui.showToast('扫描任务创建成功', 'success')
      await loadTasks()
      return res
    } catch (e) {
      ui.showToast('创建任务失败: ' + e.message, 'error')
      throw e
    }
  }

  const createBatchTasks = async (payload) => {
    try {
      const res = await client.post('/tasks/batch', payload)
      ui.showToast(`成功批量创建 ${res.created_count || 0} 个任务`, 'success')
      await loadTasks()
      return res
    } catch (e) {
      ui.showToast('批量创建失败: ' + e.message, 'error')
      throw e
    }
  }

  const startTask = async (id) => {
    try {
      await client.post(`/tasks/${id}/start`)
      ui.showToast(`任务 #${id} 已启动`, 'success')
      await loadTasks()
    } catch (e) {
      ui.showToast('启动任务失败: ' + e.message, 'error')
    }
  }

  const pauseTask = async (id) => {
    try {
      await client.post(`/tasks/${id}/pause`)
      ui.showToast(`任务 #${id} 已暂停`, 'info')
      await loadTasks()
    } catch (e) {
      ui.showToast('暂停任务失败: ' + e.message, 'error')
    }
  }

  const resumeTask = async (id) => {
    try {
      await client.post(`/tasks/${id}/resume`)
      ui.showToast(`任务 #${id} 已恢复`, 'success')
      await loadTasks()
    } catch (e) {
      ui.showToast('恢复任务失败: ' + e.message, 'error')
    }
  }

  const stopTask = async (id) => {
    try {
      await client.post(`/tasks/${id}/stop`)
      ui.showToast(`任务 #${id} 已停止`, 'warn')
      await loadTasks()
    } catch (e) {
      ui.showToast('停止任务失败: ' + e.message, 'error')
    }
  }

  const retryTask = async (id) => {
    try {
      await client.post(`/tasks/${id}/retry`)
      ui.showToast(`任务 #${id} 已重置并重试`, 'success')
      await loadTasks()
    } catch (e) {
      ui.showToast('重试任务失败: ' + e.message, 'error')
    }
  }

  const deleteTask = async (id) => {
    try {
      deletingTaskIds.value.push(id)
      tasks.value = tasks.value.filter(t => t.id !== id)
      await client.delete(`/tasks/${id}`)
      ui.showToast(`任务 #${id} 已删除并在后台平滑清理`, 'success')
    } catch (e) {
      ui.showToast('删除任务失败: ' + e.message, 'error')
      await loadTasks()
    } finally {
      deletingTaskIds.value = deletingTaskIds.value.filter(item => item !== id)
    }
  }

  const executeBatchAction = async (action, ids) => {
    if (!ids || ids.length === 0) return
    try {
      if (action === 'delete') {
        deletingTaskIds.value.push(...ids)
        tasks.value = tasks.value.filter(t => !ids.includes(t.id))
      }
      const res = await client.post('/tasks/batch-action', { action, task_ids: ids })
      ui.showToast(`批量操作成功: ${res.affected_count || ids.length} 个任务`, 'success')
      selectedTaskIds.value = []
      await loadTasks()
    } catch (e) {
      ui.showToast('批量操作失败: ' + e.message, 'error')
      await loadTasks()
    } finally {
      if (action === 'delete') {
        deletingTaskIds.value = deletingTaskIds.value.filter(item => !ids.includes(item))
      }
    }
  }

  return {
    tasks,
    activeTask,
    loading,
    refreshing,
    selectedTaskIds,
    deletingTaskIds,
    runningTasksCount,
    totalPagesCrawled,
    totalExtDomainsFound,
    totalSubdomainsFound,
    loadTasks,
    getTask,
    fetchTask,
    createTask,
    createBatchTasks,
    startTask,
    pauseTask,
    resumeTask,
    stopTask,
    retryTask,
    deleteTask,
    executeBatchAction
  }
})
