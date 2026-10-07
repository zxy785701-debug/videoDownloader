<script setup lang="ts">
import { computed } from 'vue'
import { CirclePlay } from '@lucide/vue'
import type { DeliveryMode, ModeOption, ParsedVideo } from '../types/video'
import { clock } from '../learning/api'
const props = defineProps<{ video: ParsedVideo; url: string; format: string; mode: DeliveryMode; modes: ModeOption[]; busy: boolean; thumbnailFailed: boolean }>()
const emit = defineEmits<{ 'update:format': [value: string]; 'update:mode': [value: DeliveryMode]; 'thumbnail-error': [] }>()
const selected = computed(() => props.video.formats.find(f => f.format_id === props.format))
function size(bytes: number | null | undefined) { return bytes ? (bytes / 1024 ** 2).toFixed(1) + ' MB' : '大小由源站提供' }
</script>
<template>
  <div class="compact-video">
    <div class="compact-cover"><img v-if="video.thumbnail && !thumbnailFailed" :src="video.thumbnail" alt="视频封面" @error="emit('thumbnail-error')" /><CirclePlay v-else aria-hidden="true" /></div>
    <p class="learning-eyebrow">{{ video.extractor || '视频' }} · {{ video.duration === null ? '时长未知' : clock(video.duration) }}</p>
    <h2>{{ video.title }}</h2>
    <a class="compact-source" :href="url" target="_blank" rel="noopener noreferrer">打开原视频 ↗</a>
    <label class="compact-format">清晰度与格式<select aria-label="视频清晰度与格式" :value="format" :disabled="busy" @change="emit('update:format', ($event.target as HTMLSelectElement).value)"><option v-for="item in video.formats" :key="item.format_id" :value="item.format_id">{{ item.label }}</option></select></label>
    <p class="learning-muted">{{ selected?.ext?.toUpperCase() || '视频' }} · {{ size(selected?.filesize) }}</p>
    <details class="compact-delivery"><summary>保存方式 · {{ modes.find(m => m.value === mode)?.label }}</summary><label v-for="item in modes" :key="item.value"><input type="radio" name="delivery-mode" :value="item.value" :checked="item.value === mode" :disabled="busy" @change="emit('update:mode', item.value)" /><span>{{ item.label }}<small>{{ item.hint }}</small></span></label></details>
    <slot />
  </div>
</template>
