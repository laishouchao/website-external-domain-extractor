import { createRouter, createWebHistory } from 'vue-router'
import DashboardView from '@/views/DashboardView.vue'
import TasksView from '@/views/TasksView.vue'
import TaskDetailView from '@/views/TaskDetailView.vue'
import GlobalDomainsView from '@/views/GlobalDomainsView.vue'
import RiskRemediationView from '@/views/RiskRemediationView.vue'
import ThreatIntelView from '@/views/ThreatIntelView.vue'
import SettingsView from '@/views/SettingsView.vue'
import LoginView from '@/views/LoginView.vue'

const routes = [
  {
    path: '/login',
    name: 'Login',
    component: LoginView,
    meta: { title: '用户登录', requiresAuth: false, layout: 'blank' }
  },
  {
    path: '/',
    redirect: '/dashboard'
  },
  {
    path: '/dashboard',
    name: 'Dashboard',
    component: DashboardView,
    meta: { title: '态势大屏' }
  },
  {
    path: '/tasks',
    name: 'Tasks',
    component: TasksView,
    meta: { title: '扫描任务中心' }
  },
  {
    path: '/tasks/:id',
    name: 'TaskDetail',
    component: TaskDetailView,
    meta: { title: '任务工作台' }
  },
  {
    path: '/global-domains',
    name: 'GlobalDomains',
    component: GlobalDomainsView,
    meta: { title: '全网外部域名知识库' }
  },
  {
    path: '/remediation',
    name: 'RiskRemediation',
    component: RiskRemediationView,
    meta: { title: '风险页面待处置' }
  },
  {
    path: '/threat-intel',
    name: 'ThreatIntel',
    component: ThreatIntelView,
    meta: { title: '威胁情报规则' }
  },
  {
    path: '/settings',
    name: 'Settings',
    component: SettingsView,
    meta: { title: '系统设置' }
  },
  {
    path: '/:pathMatch(.*)*',
    redirect: '/dashboard'
  }
]

const router = createRouter({
  history: createWebHistory(),
  routes,
  scrollBehavior() {
    return { top: 0 }
  }
})

// Authentication Navigation Guard
router.beforeEach((to, from, next) => {
  const token = localStorage.getItem('access_token')
  const requiresAuth = to.meta.requiresAuth !== false

  if (requiresAuth && !token) {
    next({
      path: '/login',
      query: { redirect: to.fullPath }
    })
  } else if (to.path === '/login' && token) {
    next('/dashboard')
  } else {
    next()
  }
})

router.afterEach((to) => {
  if (to.meta.title) {
    document.title = `${to.meta.title} - 网站外部域名提取与风险研判系统`
  }
})

export default router
