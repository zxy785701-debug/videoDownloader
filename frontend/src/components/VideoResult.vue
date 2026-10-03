<script setup lang="ts">
import { computed } from 'vue'
import { Check, ChevronDown, Circle, Video } from '@lucide/vue'
import type { DeliveryMode, ModeOption, ParsedVideo } from '../types/video'
import FormatPicker from './FormatPicker.vue'

const props = defineProps<{
  video: ParsedVideo
  formatId: string
  mode: DeliveryMode
  modes: ModeOption[]
  modeLabel: string
  thumbnailFailed: boolean
  busy: boolean
  formatDuration: (seconds: number | null) => string
  formatSize: (bytes: number | null) => string
}>()
const emit = defineEmits<{
  'update:formatId': [value: string]
  'update:mode': [value: DeliveryMode]
  'thumbnail-error': []
  reset: []
}>()
const knownDuration = computed(() => props.video.duration !== null && Number.isFinite(props.video.duration) && props.video.duration >= 0)
const sourceLabel = computed(() => {
  const source = props.video.extractor
  if (!source) return null
  if (/douyin/i.test(source)) return '抖音'
  if (/bilibili|bili/i.test(source)) return '哔哩哔哩'
  if (/youtube/i.test(source)) return 'YouTube'
  return source
})
</script>

<template>
  <section class="relative" aria-labelledby="result-heading">
    <div class="p-4 md:p-8">
      <div class="flex flex-col items-start gap-6 md:flex-row md:gap-8">
        <div class="aspect-video w-full shrink-0 overflow-hidden rounded-control border border-line bg-subtle md:w-thumbnail">
          <img v-if="video.thumbnail && !thumbnailFailed" class="h-full w-full object-contain" :src="video.thumbnail" alt="" @error="emit('thumbnail-error')" />
          <div v-else class="flex h-full flex-col items-center justify-center gap-2 text-muted"><Video class="size-icon" aria-hidden="true" /><span class="text-caption">暂无封面</span></div>
        </div>
        <div class="min-w-0 w-full flex-1 md:py-2">
          <h2 id="result-heading" class="line-clamp-3 break-words text-input font-semibold text-ink md:line-clamp-2" :title="video.title">{{ video.title }}</h2>
          <div class="mt-4 flex flex-wrap items-center justify-between gap-2">
            <p v-if="sourceLabel || knownDuration" class="flex min-w-0 flex-wrap items-center gap-x-2 text-caption text-muted"><span v-if="sourceLabel" class="break-words">{{ sourceLabel }}</span><span v-if="sourceLabel && knownDuration" aria-hidden="true">·</span><span v-if="knownDuration" class="tabular-nums">{{ formatDuration(video.duration) }}</span></p>
            <button class="quiet-button ml-auto shrink-0 px-2 text-caption" type="button" aria-label="清除解析结果并更换链接" :disabled="busy" @click="emit('reset')">换个链接</button>
          </div>
        </div>
      </div>

      <div class="mb-4 mt-8 flex items-center gap-2">
        <h3 class="text-body font-medium">保存格式</h3><span v-if="video.formats.length > 1" class="text-caption tabular-nums text-muted">{{ video.formats.length }} 项可选</span>
      </div>
      <FormatPicker :formats="video.formats" :model-value="formatId" :busy="busy" :format-size="formatSize" @update:model-value="emit('update:formatId', $event)" />

      <details class="group mt-4 border-t border-line">
        <summary class="flex min-h-touch flex-wrap items-center gap-2 rounded-control text-caption text-muted transition-feedback duration-enter ease-enter hover:text-primary">下载选项<span>· {{ modeLabel }}</span><ChevronDown class="ml-auto size-icon transition-feedback duration-enter ease-enter group-open:rotate-180 motion-reduce:transform-none" aria-hidden="true" /></summary>
        <fieldset class="min-w-0 pb-2" :disabled="busy">
          <legend class="sr-only">下载方式，单选</legend>
          <div class="grid gap-2">
            <label v-for="option in modes" :key="option.value" class="flex min-h-touch min-w-0 items-center gap-4 rounded-control border px-4 py-2 transition-feedback duration-enter ease-enter has-focus-visible:outline-focus has-focus-visible:outline-offset-focus has-focus-visible:outline-primary" :class="[mode === option.value ? 'border-primary bg-primary-soft' : 'border-line hover:border-line-strong', busy ? 'cursor-not-allowed' : 'cursor-pointer']">
              <input class="sr-only" type="radio" name="delivery-mode" :value="option.value" :checked="mode === option.value" @change="emit('update:mode', option.value)" />
              <span class="grid size-icon shrink-0 place-items-center" aria-hidden="true"><Check v-if="mode === option.value" class="size-icon text-primary" /><Circle v-else class="size-icon text-line-strong" /></span>
              <span class="min-w-0"><span class="block text-body font-medium">{{ option.label }}</span><span class="block text-caption text-muted">{{ option.hint }}</span></span>
            </label>
          </div>
        </fieldset>
      </details>
    </div>
    <slot name="download" />
  </section>
</template>
