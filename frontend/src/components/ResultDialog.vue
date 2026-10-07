<script setup lang="ts">
import { nextTick, onBeforeUnmount, ref, useId, watch } from 'vue'
import { X } from '@lucide/vue'

const props = defineProps<{ open: boolean }>()
const emit = defineEmits<{ close: [] }>()
const dialog = ref<HTMLDialogElement | null>(null)
const heading = ref<HTMLHeadingElement | null>(null)
const headingId = useId()
let returnFocus: HTMLElement | null = null
let backdropPressed = false

watch(() => props.open, async open => {
  if (!open) {
    // Release the native modal immediately. A fading, hidden dialog must not
    // keep the rest of the page inert or steal focus from a new input.
    dialog.value?.close()
    restoreFocus()
    return
  }
  await nextTick()
  const panel = dialog.value
  if (props.open && panel && !panel.open) {
    const active = panel.ownerDocument.activeElement
    returnFocus = active instanceof HTMLElement ? active : null
    panel.showModal()
    heading.value?.focus({ preventScroll: true })
  }
}, { immediate: true, flush: 'post' })

function restoreFocus() {
  if (dialog.value?.open) return
  const previous = returnFocus
  returnFocus = null
  backdropPressed = false
  if (previous?.isConnected && !previous.matches(':disabled') && !previous.ownerDocument.querySelector('dialog:modal')) {
    previous.focus({ preventScroll: true })
  }
}
function afterLeave() {
  if (!props.open) {
    dialog.value?.close()
    restoreFocus()
  }
}
function isOutside(event: MouseEvent | PointerEvent) {
  const panel = dialog.value
  if (!panel || event.target !== panel) return false
  const bounds = panel.getBoundingClientRect()
  return event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom
}
function startBackdropPress(event: PointerEvent) {
  backdropPressed = isOutside(event)
}
function dismissOutside(event: MouseEvent) {
  if (backdropPressed && isOutside(event)) emit('close')
  backdropPressed = false
}
function keepFocus(event: KeyboardEvent) {
  const panel = dialog.value
  if (!panel || event.key !== 'Tab') return
  const controls = [...panel.querySelectorAll<HTMLElement>('button:not(:disabled), a[href], input:not(:disabled), select:not(:disabled), textarea:not(:disabled), summary, [tabindex]:not([tabindex="-1"])')].filter(control => control.tabIndex >= 0 && control.getClientRects().length)
  const first = controls[0]
  const last = controls.at(-1)
  const active = panel.ownerDocument.activeElement
  if (!first || !last) {
    event.preventDefault()
    heading.value?.focus({ preventScroll: true })
  } else if (event.shiftKey && (active === first || active === heading.value || active === panel || !panel.contains(active))) {
    event.preventDefault()
    last.focus()
  } else if (!event.shiftKey && (active === last || active === panel || !panel.contains(active))) {
    event.preventDefault()
    first.focus()
  }
}
onBeforeUnmount(() => {
  dialog.value?.close()
  restoreFocus()
})
</script>

<template>
  <Transition name="fade" @after-leave="afterLeave">
    <dialog v-show="open" ref="dialog" class="result-dialog m-auto max-h-result-height w-result-frame max-w-result-panel overflow-hidden rounded-panel border border-line bg-surface p-0 text-ink backdrop:bg-overlay" :aria-labelledby="headingId" @cancel.prevent="emit('close')" @pointerdown="startBackdropPress" @click="dismissOutside" @keydown="keepFocus" @close="restoreFocus">
      <div class="flex max-h-result-height flex-col">
        <div class="sticky top-0 z-dialog-header flex min-h-touch shrink-0 items-center justify-between gap-4 border-b border-line bg-surface px-4 md:px-6">
          <h2 :id="headingId" ref="heading" tabindex="-1" class="text-body font-medium"><slot name="title">解析结果</slot></h2>
          <button class="quiet-button size-touch shrink-0 px-0" type="button" aria-label="关闭弹窗" @click="emit('close')"><X class="size-icon" aria-hidden="true" /></button>
        </div>
        <div class="min-h-0 overflow-y-auto overscroll-contain"><slot /></div>
      </div>
    </dialog>
  </Transition>
</template>
