<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { ArrowRight, BookOpen, CirclePlay, Globe, Link2 } from '@lucide/vue'
import RequestError from './components/RequestError.vue'
import LinkComposer from './components/LinkComposer.vue'
import ParseStatus from './components/ParseStatus.vue'
import VideoResult from './components/VideoResult.vue'
import DownloadAction from './components/DownloadAction.vue'
import HelpPanel from './components/HelpPanel.vue'
import StartGuide from './components/StartGuide.vue'
import ResultDialog from './components/ResultDialog.vue'
import { motionDuration } from './ui/motion'

type DeliveryMode = 'auto' | 'server' | 'redirect'
type TaskStatus = 'pending' | 'processing' | 'ready' | 'failed'

interface VideoFormat {
  format_id: string
  label: string
  ext: string | null
  resolution: string | null
  filesize: number | null
  fps: number | null
}

interface ParsedVideo {
  title: string
  extractor: string | null
  thumbnail: string | null
  duration: number | null
  formats: VideoFormat[]
}

interface DownloadTask {
  task_id: string
  status: TaskStatus
  delivery_mode: DeliveryMode
  progress: number | null
  filename: string | null
  error: string | null
  expires_at: string
}

const linkInput = ref<HTMLInputElement | null>(null)
const parsedUrl = ref('')
const url = ref('')
const parsedVideo = ref<ParsedVideo | null>(null)
const thumbnailFailed = ref(false)
const selectedFormat = ref('best')
const deliveryMode = ref<DeliveryMode>('auto')
const task = ref<DownloadTask | null>(null)
const downloadUrl = ref('')
const errorMessage = ref('')
const errorOrigin = ref<'input' | 'download'>('input')
const isParsing = ref(false)
const isStartingDownload = ref(false)
const helpOpen = ref(false)
const wideScreenQuery = window.matchMedia('(min-width: 1024px)')
const isWideScreen = ref(wideScreenQuery.matches)
function updateWideScreen(event: MediaQueryListEvent) {
  isWideScreen.value = event.matches
}
wideScreenQuery.addEventListener('change', updateWideScreen)
const resultOpen = ref(false)
const platformsHighlighted = ref(false)
let platformFeedbackTimer: number | undefined
const selectedFormatLabel = computed(() => parsedVideo.value?.formats.find(format => format.format_id === selectedFormat.value)?.label ?? '最佳画质')
const isTaskRunning = computed(() => task.value?.status === 'pending' || task.value?.status === 'processing')
const progressValue = computed(() => Math.max(0, Math.min(100, task.value?.progress ?? 0)))
let pollTimer: number | undefined

const modeOptions: { value: DeliveryMode; label: string; hint: string }[] = [
  { value: 'auto', label: '自动选择', hint: '根据视频选择可用的保存方式' },
  { value: 'server', label: '先处理再保存', hint: '等待文件准备好后，再保存到设备' },
  { value: 'redirect', label: '打开源文件链接', hint: '打开视频来源提供的文件，仅部分平台可用' },
]

function readableError(error: unknown) {
  return error instanceof Error ? error.message : '请求失败，请稍后重试。'
}

function formatDuration(seconds: number | null) {
  if (seconds === null || !Number.isFinite(seconds)) return '时长未知'
  const minutes = Math.floor(seconds / 60)
  const remainder = Math.floor(seconds % 60)
  return `${minutes}:${String(remainder).padStart(2, '0')}`
}

function formatSize(bytes: number | null) {
  if (!bytes || bytes <= 0) return '大小未知'
  if (bytes < 1024 ** 2) return `${Math.round(bytes / 1024)} KB`
  return `${(bytes / 1024 ** 2).toFixed(1)} MB`
}

async function parseVideo() {
  if (isParsing.value || isStartingDownload.value || isTaskRunning.value) return
  errorOrigin.value = 'input'
  const requestedUrl = url.value.trim()
  errorMessage.value = ''
  parsedVideo.value = null
  thumbnailFailed.value = false
  task.value = null
  downloadUrl.value = ''
  if (!url.value.trim()) {
    errorMessage.value = '先粘贴一个视频链接。'
    return
  }

  isParsing.value = true
  try {
    const response = await fetch('/api/v1/parse', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url: url.value.trim() }),
    })
    const data = await response.json()
    if (!response.ok) throw new Error(data.detail || '暂时无法解析这个链接。')
    parsedUrl.value = requestedUrl
    parsedVideo.value = data as ParsedVideo
    if (/youtube/i.test(data.extractor ?? '') && deliveryMode.value === 'redirect') deliveryMode.value = 'auto'
    selectedFormat.value = data.formats?.[0]?.format_id ?? 'best'
  } catch (error) {
    errorMessage.value = readableError(error)
  } finally {
    isParsing.value = false
  }
}

function wait(milliseconds: number) {
  return new Promise<void>((resolve) => {
    pollTimer = window.setTimeout(resolve, milliseconds)
  })
}

async function pollDownload(statusUrl: string, fileUrl: string) {
  while (task.value && task.value.status !== 'ready' && task.value.status !== 'failed') {
    await wait(900)
    try {
      const response = await fetch(statusUrl)
      const data = await response.json()
      if (!response.ok) throw new Error(data.detail || '下载任务已过期。')
      task.value = data as DownloadTask
      if (task.value.status === 'ready') downloadUrl.value = fileUrl
      if (task.value.status === 'failed') errorMessage.value = task.value.error || '下载失败。'
    } catch (error) {
      errorMessage.value = readableError(error)
      break
    }
  }
}

async function startDownload() {
  if (!parsedVideo.value) return
  errorOrigin.value = 'download'
  errorMessage.value = ''
  task.value = null
  downloadUrl.value = ''
  isStartingDownload.value = true
  try {
    const response = await fetch('/api/v1/downloads', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        url: parsedUrl.value,
        format_id: selectedFormat.value,
        delivery_mode: deliveryMode.value,
      }),
    })
    const data = await response.json()
    if (!response.ok) throw new Error(data.detail || '无法创建下载任务。')
    task.value = {
      task_id: data.task_id,
      status: data.status,
      delivery_mode: deliveryMode.value,
      progress: null,
      filename: null,
      error: null,
      expires_at: '',
    }
    void pollDownload(data.status_url, data.download_url)
  } catch (error) {
    errorMessage.value = readableError(error)
  } finally {
    isStartingDownload.value = false
  }
}

async function pasteLink() {
  if (isParsing.value || isStartingDownload.value || isTaskRunning.value) return
  errorOrigin.value = 'input'
  try {
    url.value = await navigator.clipboard.readText()
    errorMessage.value = ''
  } catch {
    errorMessage.value = '无法读取剪贴板，请直接粘贴链接。'
  }
}

function resetResult() {
  if (isTaskRunning.value || isStartingDownload.value) return
  parsedVideo.value = null
  thumbnailFailed.value = false
  task.value = null
  downloadUrl.value = ''
  errorMessage.value = ''
}

const availableModes = computed(() => /youtube/i.test(parsedVideo.value?.extractor ?? '') ? modeOptions.filter(m => m.value !== 'redirect') : modeOptions)
const currentModeLabel = computed(() => modeOptions.find(mode => mode.value === deliveryMode.value)?.label ?? '自动选择')

function useExample() {
  if (isParsing.value || isStartingDownload.value || isTaskRunning.value) return
  url.value = 'https://www.youtube.com/watch?v=aqz-KE-bpKQ'
  linkInput.value?.focus()
}

function fillExample() {
  useExample()
  helpOpen.value = false
}

watch(parsedVideo, video => { resultOpen.value = Boolean(video) })

function openHelp() {
  helpOpen.value = !helpOpen.value
}

function highlightPlatforms() {
  window.clearTimeout(platformFeedbackTimer)
  platformsHighlighted.value = true
  platformFeedbackTimer = window.setTimeout(() => {
    platformsHighlighted.value = false
  }, motionDuration('attention'))
}

onBeforeUnmount(() => {
  if (pollTimer) window.clearTimeout(pollTimer)
  window.clearTimeout(platformFeedbackTimer)
  wideScreenQuery.removeEventListener('change', updateWideScreen)
})
</script>

<template>
  <div class="flex h-dvh flex-col overflow-hidden">
    <header class="shrink-0 border-b border-line bg-surface px-4 md:px-8">
      <div class="home-header mx-auto flex h-header w-full max-w-topbar items-center justify-between gap-2 md:grid md:grid-cols-navigation md:gap-4">
        <a href="#top" class="flex min-h-touch items-center gap-2 justify-self-start whitespace-nowrap rounded-control text-input font-semibold text-ink" aria-label="SaveAny 首页"><span class="grid size-logo place-items-center rounded-control bg-primary text-on-primary"><CirclePlay class="size-indicator" aria-hidden="true" /></span><span>SaveAny</span><span class="hidden rounded-pill bg-subtle px-2 text-caption font-normal text-muted lg:inline">视频下载工具</span></a>
        <nav class="flex items-center gap-0 whitespace-nowrap md:gap-2" aria-label="页面导航"><button class="nav-link" type="button" :aria-expanded="helpOpen" aria-controls="guide" @click="openHelp"><BookOpen class="hidden size-icon md:block" aria-hidden="true" /><span>{{ helpOpen ? '收起帮助' : '使用方法' }}</span></button><button class="nav-link" type="button" aria-controls="supported-platforms" @click="highlightPlatforms"><Globe class="hidden size-icon md:block" aria-hidden="true" />支持平台</button></nav>
        <button class="quiet-button hidden justify-self-end whitespace-nowrap rounded-pill bg-primary-soft px-4 text-primary-hover md:inline-flex" type="button" :aria-expanded="helpOpen" aria-controls="guide" @click="openHelp">{{ helpOpen ? '收起帮助' : '使用帮助' }}</button>
      </div>
    </header>

    <main id="top" class="home-main flex min-h-0 w-full flex-1 flex-col overflow-hidden px-4 py-page-block md:px-8" :class="[{ 'pc-home-main': isWideScreen }, helpOpen ? 'help-expanded justify-center gap-4' : 'gap-6']">
      <div class="home-hero mx-auto flex min-h-0 w-full max-w-workspace flex-col justify-center" :class="helpOpen && !isWideScreen ? 'shrink-0' : 'flex-1'">
        <div class="mx-auto w-full max-w-input-area text-center">
          <p class="hero-note mx-auto inline-flex min-h-badge items-center gap-2 rounded-pill border border-line bg-surface px-4 text-caption text-muted"><Link2 class="size-icon text-primary" aria-hidden="true" /><span>从视频链接，保存到你的设备</span></p>
          <h1 class="hero-heading mt-4 text-hero-mobile font-semibold tracking-headline text-ink sm:text-hero">粘贴链接，<span class="block text-primary sm:inline">保存视频</span></h1>
          <p class="hero-description mt-2 text-body text-muted">选择清晰度和格式，等文件准备好后保存。</p>
          <div class="hero-composer mt-6"><LinkComposer v-model="url" :busy="isParsing || isStartingDownload || isTaskRunning" :parsing="isParsing" :invalid="!!errorMessage && errorOrigin === 'input'" @ready="linkInput = $event" @parse="parseVideo" @paste="pasteLink" /></div>
          <div id="supported-platforms" class="mt-4 flex flex-wrap items-center justify-center gap-2 text-caption text-muted" :class="{ 'platforms-highlighted': platformsHighlighted }" aria-label="支持站点"><span>支持：</span><span class="platform-chip">YouTube</span><span class="platform-chip">哔哩哔哩</span><span class="platform-chip">抖音</span><span class="sr-only" role="status">{{ platformsHighlighted ? '支持 YouTube、哔哩哔哩和抖音视频链接。' : '' }}</span></div>
          <div v-if="!isWideScreen && isParsing" class="mt-4"><ParseStatus /></div>
          <button v-else-if="!isWideScreen && parsedVideo && !resultOpen" class="quiet-button mt-4 border border-line text-primary-hover" type="button" @click="resultOpen = true">查看解析结果</button>
        </div>
      </div>
      <div v-if="isWideScreen" class="home-feedback mx-auto flex w-full max-w-workspace shrink-0 items-center justify-center">
        <ParseStatus v-if="isParsing" class="home-parse-status text-left" />
        <button v-else-if="parsedVideo" class="result-reopen-button" type="button" @click="resultOpen = true"><span>查看解析结果</span><ArrowRight class="size-icon" aria-hidden="true" /></button>
      </div>
      <div class="home-details contents lg:mx-auto lg:block lg:min-h-home-details lg:w-full lg:max-w-workspace lg:shrink-0">
        <Transition name="fade" :css="!isWideScreen" :mode="isWideScreen ? undefined : 'out-in'">
          <HelpPanel v-if="helpOpen" key="help" class="home-help mx-auto w-full max-w-workspace shrink-0" :busy="isParsing || isStartingDownload || isTaskRunning" @close="helpOpen = false" @example="fillExample" @keydown.esc.stop="helpOpen = false" />
          <section v-else-if="isWideScreen || (!parsedVideo && !isParsing)" key="steps" class="home-guide mx-auto w-full max-w-workspace shrink-0 rounded-panel border border-line bg-subtle p-4 md:p-6" aria-label="下载流程说明"><StartGuide /></section>
        </Transition>
      </div>
    </main>

    <ResultDialog :open="resultOpen && !!parsedVideo" @close="resultOpen = false">
      <VideoResult v-if="parsedVideo" :video="parsedVideo" v-model:format-id="selectedFormat" v-model:mode="deliveryMode" :modes="availableModes" :mode-label="currentModeLabel" :thumbnail-failed="thumbnailFailed" :busy="isStartingDownload || isTaskRunning" :format-duration="formatDuration" :format-size="formatSize" @thumbnail-error="thumbnailFailed = true" @reset="resetResult">
        <template #download><DownloadAction :task="task" :starting="isStartingDownload" :running="isTaskRunning" :progress="progressValue" :download-url="downloadUrl" :error-message="errorOrigin === 'download' ? errorMessage : ''" :selection="selectedFormatLabel" @start="startDownload" @dismiss="errorMessage = ''" /></template>
      </VideoResult>
    </ResultDialog>
    <ResultDialog :open="!!errorMessage && errorOrigin === 'input'" @close="errorMessage = ''"><template #title>解析未完成</template><div class="p-4 md:p-6"><RequestError v-if="errorMessage && errorOrigin === 'input'" id="input-error" :message="errorMessage" context="input" :busy="isParsing || isStartingDownload || isTaskRunning" @dismiss="errorMessage = ''" @retry="parseVideo" /></div></ResultDialog>

    <footer class="w-full shrink-0 px-4 md:px-8">
      <div class="home-footer mx-auto flex min-h-footer w-full max-w-workspace items-center justify-center border-t border-line text-center text-caption text-muted"><p>仅保存你拥有版权或已获授权的内容。</p></div>
    </footer>
  </div>
</template>
