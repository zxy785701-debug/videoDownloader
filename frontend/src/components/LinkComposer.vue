<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { Clipboard, Link2, LoaderCircle, Search } from '@lucide/vue'
import { motionDuration, reducedMotion } from '../ui/motion'

const props = defineProps<{ modelValue: string; busy: boolean; parsing: boolean; invalid: boolean }>()
const emit = defineEmits<{
  'update:modelValue': [value: string]
  ready: [input: HTMLInputElement]
  parse: []
  paste: []
}>()
const input = ref<HTMLInputElement | null>(null)
const pulsing = ref(false)
let pasteArmed = false
let feedbackTimer: number | undefined

function validLink(value: string) {
  try { return ['http:', 'https:'].includes(new URL(value.trim()).protocol) } catch { return false }
}
function pulse() {
  if (reducedMotion()) return
  window.clearTimeout(feedbackTimer)
  pulsing.value = true
  feedbackTimer = window.setTimeout(() => { pulsing.value = false }, motionDuration('elastic'))
}
function update(event: Event) {
  const value = (event.target as HTMLInputElement).value
  emit('update:modelValue', value)
  if (pasteArmed) {
    pasteArmed = false
    if (validLink(value)) pulse()
  }
}
function paste() {
  pasteArmed = true
  emit('paste')
}
function armPaste() { pasteArmed = true }
watch(() => props.modelValue, value => {
  if (pasteArmed && validLink(value)) { pasteArmed = false; pulse() }
})
onMounted(() => { if (input.value) emit('ready', input.value) })
onBeforeUnmount(() => window.clearTimeout(feedbackTimer))
</script>

<template>
  <form class="grid w-full grid-cols-composer-mobile gap-2 rounded-panel border bg-surface p-2 shadow-input transition-feedback duration-enter ease-enter focus-within:border-primary focus-within:shadow-focus sm:flex sm:h-composer sm:items-center sm:gap-0 sm:overflow-hidden sm:rounded-pill sm:p-0" :class="invalid ? 'border-error' : 'border-line'" :aria-busy="parsing" @submit.prevent="emit('parse')">
    <div class="col-span-2 flex h-touch min-w-0 items-center gap-2 px-2 sm:h-full sm:flex-1 sm:px-4">
      <label class="sr-only" for="video-link">视频页面链接</label>
      <Link2 class="size-icon text-muted" aria-hidden="true" />
      <input id="video-link" ref="input" :value="modelValue" class="h-full min-w-0 flex-1 border-0 bg-transparent text-input text-ink placeholder:text-muted focus-visible:outline-none disabled:text-muted" type="url" required autocomplete="off" spellcheck="false" placeholder="粘贴视频链接" :disabled="busy" :aria-invalid="invalid" :aria-describedby="invalid ? 'supported-platforms input-error' : 'supported-platforms'" @input="update" @paste="armPaste" />
    </div>
    <button class="quiet-button h-touch w-full border border-line bg-subtle px-2 text-body sm:h-full sm:w-paste sm:rounded-none sm:border-0 sm:bg-transparent" type="button" aria-label="粘贴视频链接" title="粘贴链接" :disabled="busy" @click="paste"><Clipboard class="size-icon" aria-hidden="true" /><span class="sm:sr-only">粘贴</span></button>
    <button class="primary-button button-feedback h-touch w-full sm:h-full sm:w-parse sm:rounded-none" :class="{ 'is-pulsing': pulsing }" type="submit" :disabled="busy" :aria-busy="parsing">
      <Transition name="fade" mode="out-in"><span :key="String(parsing)" class="inline-flex items-center justify-center gap-2"><LoaderCircle v-if="parsing" class="size-icon" aria-hidden="true" /><Search v-else class="size-icon" aria-hidden="true" /><span>{{ parsing ? '解析中' : '解析视频' }}</span></span></Transition>
    </button>
  </form>
</template>
