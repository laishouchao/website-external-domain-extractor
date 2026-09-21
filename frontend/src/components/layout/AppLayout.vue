<template>
  <div class="flex h-screen bg-slate-950 text-slate-100 overflow-hidden">
    <!-- Collapsible Sidebar -->
    <Sidebar />

    <!-- Main Content Area -->
    <div class="flex-1 flex flex-col min-w-0 overflow-hidden">
      <!-- Topbar Header -->
      <Topbar
        @open-create-modal="showCreateModal = true"
        @open-batch-modal="showBatchModal = true"
      />

      <!-- Content Scrollable Body -->
      <main class="flex-1 overflow-y-auto px-4 sm:px-6 lg:px-8 py-6">
        <slot>
          <router-view />
        </slot>
      </main>
    </div>

    <!-- Modals -->
    <CreateTaskModal v-model="showCreateModal" />
    <BatchTaskModal v-model="showBatchModal" />

    <!-- Global Toast Notifications -->
    <Toast />
  </div>
</template>

<script setup>
import { ref } from 'vue'
import Sidebar from './Sidebar.vue'
import Topbar from './Topbar.vue'
import Toast from '@/components/common/Toast.vue'
import CreateTaskModal from '@/components/tasks/CreateTaskModal.vue'
import BatchTaskModal from '@/components/tasks/BatchTaskModal.vue'

const showCreateModal = ref(false)
const showBatchModal = ref(false)
</script>
