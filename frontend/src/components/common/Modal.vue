<template>
  <Teleport to="body">
    <div
      v-if="modelValue"
      class="fixed inset-0 z-50 flex items-center justify-center p-4 modal-backdrop"
      @click.self="closeOnBackdrop && close()"
    >
      <div
        :class="[
          'bg-slate-900 border border-slate-800 rounded-2xl w-full shadow-2xl space-y-5 p-6 transform transition-all',
          maxWidthClass
        ]"
      >
        <div class="flex items-center justify-between border-b border-slate-800 pb-3">
          <div class="flex items-center gap-2.5 font-bold text-white text-base">
            <slot name="title">{{ title }}</slot>
          </div>
          <button
            @click="close"
            class="text-slate-400 hover:text-white text-lg px-1 rounded hover:bg-slate-800 transition"
          >
            ✕
          </button>
        </div>

        <div class="max-h-[75vh] overflow-y-auto pr-1 text-xs">
          <slot />
        </div>

        <div v-if="$slots.footer" class="border-t border-slate-800 pt-3.5 flex items-center justify-end gap-2.5">
          <slot name="footer" />
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
  maxWidth: { type: String, default: 'max-w-xl' },
  closeOnBackdrop: { type: Boolean, default: true }
})

const emit = defineEmits(['update:modelValue', 'close'])

const maxWidthClass = computed(() => props.maxWidth)

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
