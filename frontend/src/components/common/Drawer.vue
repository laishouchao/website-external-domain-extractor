<template>
  <Teleport to="body">
    <div
      v-if="modelValue"
      class="fixed inset-0 z-50 overflow-hidden"
    >
      <!-- Backdrop -->
      <div
        class="absolute inset-0 bg-slate-950/70 backdrop-blur-sm transition-opacity"
        @click="close"
      />
      
      <!-- Slide-over Drawer Panel -->
      <div class="fixed inset-y-0 right-0 pl-6 sm:pl-10 max-w-full flex">
        <div
          :class="[
            'w-screen bg-slate-900 border-l border-slate-800 shadow-2xl p-6 flex flex-col justify-between transform transition-all ease-in-out duration-300',
            currentWidthClass
          ]"
        >
          <!-- Header -->
          <div class="flex items-center justify-between border-b border-slate-800 pb-4 flex-shrink-0">
            <div class="flex items-center gap-2.5 font-bold text-white text-base truncate pr-2">
              <slot name="title">{{ title }}</slot>
            </div>
            
            <div class="flex items-center gap-1.5 flex-shrink-0">
              <button
                @click="toggleMaximize"
                class="text-slate-400 hover:text-white p-1.5 rounded-lg hover:bg-slate-800 transition"
                :title="isMaximized ? '还原宽度' : '全屏展开'"
              >
                <Minimize2 v-if="isMaximized" class="w-4 h-4" />
                <Maximize2 v-else class="w-4 h-4" />
              </button>
              <button
                @click="close"
                class="text-slate-400 hover:text-white p-1.5 rounded-lg hover:bg-slate-800 transition"
                title="关闭侧边栏 (Esc)"
              >
                <X class="w-4 h-4" />
              </button>
            </div>
          </div>

          <!-- Body Content Area -->
          <div class="flex-1 overflow-y-auto py-4 text-xs">
            <slot />
          </div>

          <!-- Optional Footer -->
          <div v-if="$slots.footer" class="border-t border-slate-800 pt-4 flex items-center justify-end gap-2.5 flex-shrink-0">
            <slot name="footer" />
          </div>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { X, Maximize2, Minimize2 } from 'lucide-vue-next'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  title: { type: String, default: '' },
  width: { type: String, default: '' },
  size: { type: String, default: 'xl' }
})

const emit = defineEmits(['update:modelValue', 'close'])

const isMaximized = ref(false)

const sizeMap = {
  sm: 'max-w-md',
  md: 'max-w-xl',
  lg: 'max-w-3xl xl:max-w-4xl',
  xl: 'max-w-4xl xl:max-w-5xl 2xl:max-w-6xl',
  '2xl': 'max-w-5xl xl:max-w-6xl 2xl:max-w-7xl',
  full: 'max-w-[96vw]'
}

const currentWidthClass = computed(() => {
  if (isMaximized.value) {
    return 'max-w-[96vw]'
  }
  if (props.width) {
    return props.width
  }
  return sizeMap[props.size] || sizeMap.xl
})

const toggleMaximize = () => {
  isMaximized.value = !isMaximized.value
}

const close = () => {
  emit('update:modelValue', false)
  emit('close')
}

const handleKeydown = (e) => {
  if (e.key === 'Escape' && props.modelValue) {
    close()
  }
}

onMounted(() => window.addEventListener('keydown', handleKeydown))
onUnmounted(() => window.removeEventListener('keydown', handleKeydown))
</script>
