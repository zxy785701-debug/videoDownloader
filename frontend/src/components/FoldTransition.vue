<script setup lang="ts">
import { reducedMotion } from '../ui/motion'
defineProps<{ mode?: 'out-in' | 'in-out' }>()

function beforeEnter(element: Element) {
  if (!reducedMotion()) (element as HTMLElement).style.height = '0px'
}
function enter(element: Element) {
  if (reducedMotion()) return
  const panel = element as HTMLElement
  // Commit the collapsed size before transitioning to the measured content height.
  void panel.offsetHeight
  panel.style.height = `${panel.scrollHeight}px`
}
function clearHeight(element: Element) {
  (element as HTMLElement).style.height = ''
}
function beforeLeave(element: Element) {
  if (reducedMotion()) return
  const panel = element as HTMLElement
  panel.style.height = `${panel.getBoundingClientRect().height}px`
}
function leave(element: Element) {
  if (reducedMotion()) return
  const panel = element as HTMLElement
  void panel.offsetHeight
  panel.style.height = '0px'
}
</script>

<template>
  <Transition name="expand" :mode="mode" @before-enter="beforeEnter" @enter="enter" @after-enter="clearHeight" @before-leave="beforeLeave" @leave="leave" @after-leave="clearHeight" @enter-cancelled="clearHeight" @leave-cancelled="clearHeight">
    <slot />
  </Transition>
</template>
