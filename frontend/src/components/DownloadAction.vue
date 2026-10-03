<script setup lang="ts">
import { computed } from 'vue'
import { ArrowDownToLine, Check, LoaderCircle } from '@lucide/vue'
import type { DownloadTask } from '../types/video'
import RequestError from './RequestError.vue'

const props = defineProps<{
  task: DownloadTask | null
  starting: boolean
  running: boolean
  progress: number
  downloadUrl: string
  errorMessage: string
  selection: string
}>()
const emit = defineEmits<{ start: []; dismiss: [] }>()
const busy = computed(() => props.starting || props.running)
const ready = computed(() => props.task?.status === 'ready' && !!props.downloadUrl)
const hasProgress = computed(() => props.running && props.task?.progress != null && !props.errorMessage)
const phase = computed(() => {
  if (props.errorMessage) return busy.value ? 'interrupted' : 'failed'
  if (ready.value) return 'ready'
  if (props.starting || props.task?.status === 'pending') return 'preparing'
  if (hasProgress.value) return props.progress >= 100 ? 'finalizing' : 'progress'
  return props.running ? 'processing' : 'idle'
})
const title = computed(() => ({
  idle: `已选择 · ${props.selection}`, preparing: '正在准备下载',
  progress: '正在下载视频文件', finalizing: '正在整理文件',
  processing: '正在处理视频', ready: '文件已准备好',
  failed: '这次下载未完成', interrupted: '状态更新已中断',
})[phase.value])
const description = computed(() => ({
  idle: '文件准备好后，再保存到设备。', preparing: '请求已提交，请稍候。',
  progress: '文件准备完成后，即可保存到设备。', finalizing: '下载数据已接收，等待文件准备完成。',
  processing: '暂未收到进度信息，请稍候。', ready: props.task?.filename || '点击按钮，保存到设备。',
  failed: '查看下一步建议后，可以重试下载。', interrupted: '查看错误提示；当前任务尚未返回结束状态。',
})[phase.value])
const buttonLabel = computed(() => {
  if (phase.value === 'failed') return '重试下载'
  if (phase.value === 'interrupted') return '等待状态'
  if (phase.value === 'preparing') return '准备中'
  if (phase.value === 'progress') return `下载中 ${props.progress}%`
  if (phase.value === 'processing' || phase.value === 'finalizing') return '处理中'
  return '下载'
})
</script>

<template>
  <div class="contents">
    <Transition name="rise"><RequestError v-if="errorMessage" class="mx-4 mb-4 md:mx-6" :message="errorMessage" context="download" :busy="busy" @dismiss="emit('dismiss')" @retry="emit('start')" /></Transition>
    <div class="min-h-download-bar rounded-b-panel bg-surface p-4 md:px-8 md:pb-8">
      <div class="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between sm:gap-6">
        <div class="min-w-0 flex-1 sm:order-2" aria-live="polite">
          <div class="grid"><Transition name="fade"><div :key="phase" class="col-start-1 row-start-1 min-w-0">
            <p class="flex min-w-0 items-center gap-2 text-body font-medium"><Check v-if="ready" class="size-icon text-primary" aria-hidden="true" /><span class="truncate">{{ title }}</span></p>
            <p class="mt-2 truncate text-caption text-muted" :title="description">{{ description }}</p>
          </div></Transition></div>
          <button v-if="ready" class="inline-flex min-h-touch items-center rounded-control text-caption text-muted underline underline-offset-link hover:text-primary" type="button" @click="emit('start')">重新准备文件</button>
        </div>
        <div class="w-full shrink-0 sm:order-1 sm:w-download">
          <Transition name="fade" mode="out-in">
            <a v-if="ready" class="primary-button w-full rounded-pill" :href="downloadUrl"><ArrowDownToLine class="size-icon" aria-hidden="true" />保存到设备</a>
            <button v-else class="primary-button relative w-full overflow-hidden rounded-pill" type="button" :disabled="busy" :aria-busy="busy" @click="emit('start')">
              <span v-if="hasProgress" class="progress-fill absolute inset-y-0 left-0 bg-download-fill transition-progress duration-enter ease-enter" :style="{ width: `${progress}%` }" aria-hidden="true"></span>
              <Transition name="fade" mode="out-in"><span :key="phase" class="relative inline-flex items-center justify-center gap-2"><LoaderCircle v-if="busy" class="size-icon" aria-hidden="true" /><ArrowDownToLine v-else class="size-icon" aria-hidden="true" /><span :class="{ 'font-mono text-caption tabular-nums': hasProgress }">{{ buttonLabel }}</span></span></Transition>
            </button>
          </Transition>
        </div>
      </div>
      <Transition name="fade"><div v-if="hasProgress" class="mt-4 h-progress overflow-hidden rounded-control bg-subtle" role="progressbar" aria-label="视频文件准备进度" :aria-valuenow="progress" :aria-valuemin="0" :aria-valuemax="100"><div class="progress-fill h-full bg-primary transition-progress duration-enter ease-enter" :style="{ width: `${progress}%` }"></div></div></Transition>
    </div>
  </div>
</template>
