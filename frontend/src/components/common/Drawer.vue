<template>
  <Teleport to="body">
    <div
      v-if="modelValue"
      class="fixed inset-0 z-50 overflow-hidden"
    >
      <div
        class="absolute inset-0 bg-slate-950/70 backdrop-blur-sm transition-opacity"
        @click="close"
      />
      <div class="fixed inset-y-0 right-0 pl-10 max-w-full flex">
        <div
          :class="[
            'w-screen bg-slate-900 border-l border-slate-800 shadow-2xl p-6 flex flex-col justify-between transform transition ease-in-out duration-300',
            widthClass
          ]"
        >
          <div class="flex items-center justify-between border-b border-slate-800 pb-4">
            <div class="flex items-center gap-2.5 font-bold text-white text-base">
              <slot name="title">{{ title }}</slot>
            </div>
            <button
              @click="close"
              class="text-slate-400 hover:text-white text-lg p-1 rounded-lg hover:bg-slate-800 transition"
            >
              ✕
            </button>
          </div>

          <div class="flex-1 overflow-y-auto py-4 text-xs">
            <slot />
          </div>

          <div v-if="$slots.footer" class="border-t border-slate-800 pt-4 flex items-center justify-end gap-2.5">
            <slot name="footer" />
          </div>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup>
import { computed, onMounted, onUnmounted } from 'vue'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  title: { type: String, default: '' },
  width: { type: String, default: 'max-w-lg' }
})

const emit = defineEmits(['update:modelValue', 'close'])

const widthClass = computed(() => props.width)

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
