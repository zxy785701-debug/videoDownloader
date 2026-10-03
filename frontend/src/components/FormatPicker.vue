<script setup lang="ts">
import { computed } from 'vue'
import { Circle, CircleCheck } from '@lucide/vue'
import type { VideoFormat } from '../types/video'

const props = defineProps<{
  formats: VideoFormat[]
  modelValue: string
  busy: boolean
  formatSize: (bytes: number | null) => string
}>()
const emit = defineEmits<{ 'update:modelValue': [value: string] }>()
const unknownSizes = computed(() => props.formats.some(format => !format.filesize || format.filesize <= 0))
const mergesAudio = computed(() => props.formats.some(format => format.format_id.startsWith('video:')))

function quality(format: VideoFormat) {
  if (format.format_id === 'best') return format.resolution?.trim() ? '原始画质' : '最佳画质'
  const resolution = format.resolution?.trim()
  return resolution || format.label.match(/\d+p\b/i)?.[0] || format.label
}
function metadata(format: VideoFormat) {
  return [
    format.format_id === 'best' ? format.resolution?.trim() : null,
    format.ext?.toUpperCase(),
    format.fps && Number.isFinite(format.fps) ? `${Number(format.fps.toFixed(1))} fps` : null,
    format.filesize && format.filesize > 0 ? props.formatSize(format.filesize) : null,
  ].filter(Boolean).join(' · ')
}
function accessibleLabel(format: VideoFormat) {
  return [quality(format), format.format_id === 'best' ? '推荐' : null, metadata(format)].filter(Boolean).join(' ')
}
</script>

<template>
  <fieldset class="min-w-0" :disabled="busy">
    <legend class="sr-only">选择保存格式，单选</legend>
    <div class="grid gap-4" :class="formats.length > 1 ? 'md:grid-cols-formats-two' : 'max-w-format-option'">
      <label v-for="format in formats" :key="format.format_id" class="format-card" :class="{ 'is-selected': modelValue === format.format_id, 'bg-primary-soft': modelValue === format.format_id, 'is-subdued': Boolean(modelValue) && modelValue !== format.format_id, 'is-disabled': busy }">
        <input class="sr-only" type="radio" name="video-format" :value="format.format_id" :aria-label="accessibleLabel(format)" :checked="modelValue === format.format_id" @change="emit('update:modelValue', format.format_id)" />
        <span class="min-w-0">
          <span class="flex flex-wrap items-center gap-x-2 gap-y-2"><span class="break-words text-input font-medium text-ink">{{ quality(format) }}</span><span v-if="format.format_id === 'best'" class="text-caption font-medium text-primary-hover">推荐</span></span>
          <span v-if="metadata(format)" class="mt-2 block break-words text-caption tabular-nums text-muted">{{ metadata(format) }}</span>
        </span>
        <span class="grid size-indicator shrink-0 place-items-center" aria-hidden="true">
          <Circle v-if="modelValue !== format.format_id" class="col-start-1 row-start-1 size-icon text-line-strong" />
          <Transition name="check"><CircleCheck v-if="modelValue === format.format_id" class="col-start-1 row-start-1 size-icon text-primary" /></Transition>
        </span>
      </label>
    </div>
    <p v-if="!formats.length" class="rounded-control border border-line p-4 text-caption text-muted">源站暂未提供可选格式，请尝试其他视频链接。</p>
    <p v-if="formats.length && (unknownSizes || mergesAudio)" class="mt-2 text-caption text-muted"><span v-if="unknownSizes">文件大小以实际下载为准。</span><span v-if="mergesAudio"> 音频会随视频合并，最终格式以文件名为准。</span></p>
  </fieldset>
</template>
