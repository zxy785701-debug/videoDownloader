<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ArrowRight, BookOpen, CirclePlay, Clock3, Copyright, FileText, MessageCircle, Network, Plus, Sparkles, Trash2 } from '@lucide/vue'
import LinkComposer from '../components/LinkComposer.vue'
import CompactVideoResult from '../components/CompactVideoResult.vue'
import DownloadAction from '../components/DownloadAction.vue'
import CopyrightNotice from '../components/CopyrightNotice.vue'
import HomeTutorial from './HomeTutorial.vue'
import { useVideoDownload } from './useVideoDownload'
import ResultDialog from '../components/ResultDialog.vue'
import MemberPanel from '../membership/MemberPanel.vue'
import MembershipPlans from '../membership/MembershipPlans.vue'
import MindMapView from './MindMapView.vue'
import { downloadBlob, downloadFilename } from './fileDownload'
import { clock, LearningApiError, learningApi, sourceKind } from './api'
import { readChatStream, readLearningStream } from './chatStream'
import { mergeSummaryDraft, type SummaryDraft, type SummarySnapshot } from './summaryDraft'
import type { AIConfig, Analysis, Message, Page, Reference, SummaryResponse, SummaryVersion, TranscriptPage } from './types'
import './learning.css'
import './workspace-design.css'

const inputUrl = ref('')
const download = useVideoDownload()
const { video, url: parsedUrl, format: selectedFormat, mode: deliveryMode, task: downloadTask, fileUrl: downloadUrl, parseError, downloadError, parsing, starting, thumbnailFailed, running, locked: downloadBusy, availableModes, selection, progress } = download
const rightsOpen = ref(false)
const memberPanel = ref<InstanceType<typeof MemberPanel> | null>(null)
const membershipState = ref({ enabled: false, signedIn: false, isMember: false, busy: false })
function focusComposer() { linkInput.value?.scrollIntoView({ block: 'center' }); linkInput.value?.focus({ preventScroll: true }) }
const learningUnavailable = ref('')
let savedPreference = true
try { savedPreference = localStorage.getItem('saveany.auto-summary') !== 'off' } catch { /* Private browser storage can be unavailable. */ }
const autoSummary = ref(savedPreference)
watch(autoSummary, value => { try { localStorage.setItem('saveany.auto-summary', value ? 'on' : 'off') } catch { /* Preference is still usable for this visit. */ } })
const workspaceActive = computed(() => !!video.value || parsing.value || !!parseError.value || !!currentId.value || !!learningUnavailable.value)
const composerBusy = computed(() => parsing.value || creating.value || restoring.value || downloadBusy.value)
const linkInput = ref<HTMLInputElement | null>(null)
const config = ref<AIConfig | null>(null)
const history = ref<Analysis[]>([])
const historyTotal = ref(0)
const historyOpen = ref(false)
const record = ref<Analysis | null>(null)
const currentId = ref('')
const summary = ref<SummaryVersion | null>(null)
const summaryDraft = ref<SummaryDraft | null>(null)
const summaryStreamNote = ref('')
const messages = ref<Message[]>([])
const chatDrafts = ref<Record<string, { text: string; stage: string }>>({})
const chatStreamNote = ref('')
const transcript = ref<TranscriptPage>({ items: [], total: 0, offset: 0, limit: 100 })
const search = ref('')
const highlightedCue = ref('')
const question = ref('')
const tab = ref<'summary' | 'transcript' | 'mindmap' | 'chat'>('summary')
const notice = ref('')
const networkError = ref('')
const busy = ref(false)
const creating = ref(false)
const loading = ref(false)
const restoring = ref(false)
const subtitleFormat = ref<'srt' | 'txt'>('srt')
const subtitleExporting = ref(false)
const confirmation = ref<{ kind: 'record' | 'chat'; id: string; title: string } | null>(null)
let controller = new AbortController()
let revision = 0
let refreshRevision = 0
let pollTimer: number | undefined
let transcriptRevision = 0
let transcriptLoadedFor = ''
let disposed = false
let chatController: AbortController | null = null
let chatStreamId = ''
let chatConnected = false
let nextChatReconnect = 0
let summaryController: AbortController | null = null
let summaryStreamId = ''
let summaryConnected = false
let nextSummaryReconnect = 0
let summaryDraftJob = ''
let pendingQuestion: { recordId: string; question: string; requestId: string } | null = null
let autoSummaryPromptFor = ''
const busyStates = new Set(['pending', 'fetching', 'queued', 'processing'])
const transcriptReady = computed(() => record.value?.subtitle_status === 'ready')
const autoSummaryJob = computed(() => record.value?.jobs?.find(job => job.kind === 'auto_summary'))
const summaryBusy = computed(() => busyStates.has(record.value?.summary_status || '') || busyStates.has(autoSummaryJob.value?.status || ''))
const summaryCompatible = computed(() => config.value?.summary_stream_version === 2)
const chatBusy = computed(() => messages.value.some(message => busyStates.has(message.status)))
const summaryJob = computed(() => record.value?.jobs?.find(job => job.kind === 'summary'))
const subtitleJob = computed(() => record.value?.jobs?.find(job => job.kind === 'subtitle'))
const selectedTrack = computed(() => {
  const unique = new Map<string, { language: string; kind: string }>()
  const priority: Record<string, number> = { manual: 0, unknown: 1, automatic: 2 }
  for (const track of record.value?.tracks || []) {
    const previous = unique.get(track.language)
    if (!previous || (priority[track.kind] ?? 3) < (priority[previous.kind] ?? 3)) unique.set(track.language, track)
  }
  return Array.from(unique.values())
})
const tabs = [
  { value: 'summary' as const, label: '摘要', icon: BookOpen },
  { value: 'transcript' as const, label: '字幕原文', icon: FileText },
  { value: 'mindmap' as const, label: '思维导图', icon: Network },
  { value: 'chat' as const, label: '视频问答', icon: MessageCircle },
]

function readable(error: unknown) {
  return error instanceof Error ? error.message : '请求失败，请稍后重试。'
}
function cancelled(error: unknown) {
  return error instanceof DOMException && error.name === 'AbortError'
}
function showSummaryGate(code: string | null, message: string | null) {
  if (code === 'LOGIN_REQUIRED') memberPanel.value?.showLogin(message || '请先登录，再生成新的 AI 总结。')
  else if (code === 'QUOTA_EXCEEDED') memberPanel.value?.showPlans(message || '今日 AI 总结额度已用完，请明天再试或查看会员。')
}
function recordStatus(item: Analysis) {
  if (item.summary_status === 'ready') return '摘要已保存'
  if (busyStates.has(item.summary_status)) return '正在总结'
  if (item.subtitle_status === 'ready') return '字幕已保存'
  if (busyStates.has(item.subtitle_status)) return '正在获取字幕'
  return item.subtitle_status === 'unavailable' ? '暂无可用字幕' : '获取未完成'
}
function stopPolling() {
  window.clearTimeout(pollTimer)
  pollTimer = undefined
}
function stopChatStream(clear = false) {
  chatController?.abort(); chatController = null; chatStreamId = ''; chatConnected = false
  if (clear) { chatDrafts.value = {}; chatStreamNote.value = ''; nextChatReconnect = 0 }
}
function stopSummaryStream(clear = false) {
  summaryController?.abort(); summaryController = null; summaryStreamId = ''; summaryConnected = false
  if (clear) { summaryDraft.value = null; summaryDraftJob = ''; summaryStreamNote.value = ''; nextSummaryReconnect = 0 }
}
function syncSummaryStream() {
  const active = summaryJob.value
  if (!active || !busyStates.has(active.status)) {
    stopSummaryStream(); summaryStreamNote.value = ''
    if (record.value?.summary_status === 'ready') { summaryDraft.value = null; summaryDraftJob = '' }
    return
  }
  if (summaryStreamId === active.id || Date.now() < nextSummaryReconnect) return
  stopSummaryStream()
  const id = currentId.value, expected = revision, jobId = active.id
  if (summaryDraftJob !== jobId) { summaryDraft.value = null; summaryDraftJob = jobId }
  const connection = new AbortController()
  summaryController = connection; summaryStreamId = jobId
  void readLearningStream('/analyses/' + id + '/summary/' + jobId + '/stream', event => {
    if (disposed || expected !== revision || connection.signal.aborted) return
    const payload = event.data as SummarySnapshot & { job_id: string; summary?: SummaryVersion }
    if (payload.job_id !== jobId) return
    summaryConnected = true; summaryStreamNote.value = ''
    if (event.event === 'snapshot') {
      if (typeof payload.text === 'string') {
        summaryDraft.value = mergeSummaryDraft(summaryDraft.value, payload, active.stage)
      }
    } else if (['complete', 'failed', 'removed'].includes(event.event)) {
      if (event.event === 'complete' && payload.summary) {
        summary.value = payload.summary
        if (record.value) record.value = { ...record.value, summary_status: 'ready' }
      }
      if (event.event !== 'failed') { summaryDraft.value = null; summaryDraftJob = '' }
      void refreshCurrent()
    }
  }, connection.signal).catch(error => {
    if (cancelled(error) || disposed || expected !== revision || connection.signal.aborted) return
    summaryStreamNote.value = '摘要流式连接暂时中断，后台任务仍在继续；会自动重连并读取已保存的结果。'
    nextSummaryReconnect = Date.now() + 3000
    stopPolling()
    pollTimer = window.setTimeout(() => void refreshCurrent(), 1600)
  }).finally(() => {
    if (summaryController === connection) { summaryController = null; summaryStreamId = ''; summaryConnected = false }
  })
}
function syncChatStream() {
  const active = messages.value.find(message => busyStates.has(message.status))
  if (!active) { stopChatStream(); chatStreamNote.value = ''; return }
  if (chatStreamId === active.id || Date.now() < nextChatReconnect) return
  stopChatStream()
  const id = currentId.value, expected = revision, messageId = active.id
  const connection = new AbortController()
  chatController = connection; chatStreamId = messageId
  void readChatStream('/analyses/' + id + '/messages/' + messageId + '/stream', event => {
    if (disposed || expected !== revision || connection.signal.aborted) return
    const payload = event.data as { message_id: string; text?: string; stage?: string; message?: Message }
    if (payload.message_id !== messageId) return
    chatConnected = true; chatStreamNote.value = ''
    if (event.event === 'snapshot') {
      if (typeof payload.text === 'string') chatDrafts.value[messageId] = { text: payload.text, stage: payload.stage || 'generating' }
    } else if (event.event === 'complete' || event.event === 'failed') {
      if (payload.message?.id === messageId) messages.value = messages.value.map(message => message.id === messageId ? payload.message! : message)
      if (event.event === 'complete') delete chatDrafts.value[messageId]
      void refreshCurrent()
    } else if (event.event === 'removed') {
      delete chatDrafts.value[messageId]
      messages.value = messages.value.filter(message => message.id !== messageId)
      void refreshCurrent()
    }
  }, connection.signal).catch(error => {
    if (cancelled(error) || disposed || expected !== revision || connection.signal.aborted) return
    chatStreamNote.value = '流式连接暂时中断，后台任务仍在继续；会自动重连并读取已保存的回答。'
    nextChatReconnect = Date.now() + 3000
    stopPolling()
    pollTimer = window.setTimeout(() => void refreshCurrent(), 1600)
  }).finally(() => {
    if (chatController === connection) { chatController = null; chatStreamId = ''; chatConnected = false }
  })
}
async function loadHistory(append = false) {
  try {
    const response = await learningApi<Page<Analysis>>('/analyses?offset=' + (append ? history.value.length : 0) + '&limit=30', {}, controller.signal)
    if (disposed) return
    history.value = append ? [...history.value, ...response.items] : response.items
    historyTotal.value = response.total
  } catch (error) {
    if (!cancelled(error) && !disposed) networkError.value = readable(error)
  }
}
async function loadTranscript(offset = 0, anchor = '', jumpToFirst = false) {
  const id = currentId.value, expected = revision, pageRevision = ++transcriptRevision
  if (!id) return
  const query = new URLSearchParams({ offset: String(offset), limit: '100', q: search.value })
  if (anchor) query.set('anchor', anchor)
  try {
    const page = await learningApi<TranscriptPage>('/analyses/' + id + '/transcript?' + query, {}, controller.signal)
    if (expected !== revision || pageRevision !== transcriptRevision || disposed) return
    transcript.value = page
    transcriptLoadedFor = id
    if (anchor) {
      await nextTick()
      document.getElementById('cue-' + anchor)?.scrollIntoView({ block: 'center', behavior: 'instant' })
      document.getElementById('cue-' + anchor)?.focus({ preventScroll: true })
    } else if (jumpToFirst && page.items[0]) {
      await nextTick()
      document.getElementById('cue-' + page.items[0].id)?.scrollIntoView({ block: 'start', behavior: 'instant' })
    }
  } catch (error) {
    if (!cancelled(error) && expected === revision && !disposed) networkError.value = readable(error)
  }
}
async function refreshCurrent() {
  stopPolling()
  const id = currentId.value, expected = revision, requestRevision = ++refreshRevision
  if (!id) return
  try {
    const [detail, received, conversation] = await Promise.all([
      learningApi<Analysis>('/analyses/' + id, {}, controller.signal),
      learningApi<SummaryResponse>('/analyses/' + id + '/summary', {}, controller.signal),
      learningApi<{ items: Message[] }>('/analyses/' + id + '/messages', {}, controller.signal),
    ])
    let result = received
    // Parallel reads may straddle the final SQLite save. Do not publish a ready
    // record with a stale, empty summary and then permanently stop polling.
    if (detail.summary_status === 'ready' && result.status !== 'ready') {
      result = await learningApi<SummaryResponse>('/analyses/' + id + '/summary', {}, controller.signal)
    }
    if (expected !== revision || requestRevision !== refreshRevision || disposed) return
    const oldSubtitleStatus = record.value?.subtitle_status
    const oldSummaryStatus = record.value?.summary_status
    record.value = detail; summary.value = result.summary; messages.value = conversation.items
    if (autoSummaryPromptFor === id) {
      const automatic = detail.jobs?.find(job => job.kind === 'auto_summary')
      if (automatic && !busyStates.has(automatic.status)) {
        // Only the current opt-in attempt may prompt, once. History and polling
        // retain the error text without reopening a dismissed account dialog.
        autoSummaryPromptFor = ''
        if (automatic.status === 'failed') showSummaryGate(automatic.error_code, automatic.error)
      }
    }
    for (const messageId of Object.keys(chatDrafts.value)) {
      const current = messages.value.find(message => message.id === messageId)
      if (!current || current.status === 'ready') delete chatDrafts.value[messageId]
    }
    syncChatStream()
    syncSummaryStream()
    networkError.value = ''
    if (detail.subtitle_status === 'ready' && (transcriptLoadedFor !== id || oldSubtitleStatus !== 'ready')) await loadTranscript()
    if (oldSubtitleStatus !== detail.subtitle_status || oldSummaryStatus !== detail.summary_status) void loadHistory()
    if (expected === revision && (busyStates.has(detail.subtitle_status) || (!summaryConnected && summaryBusy.value) || (!chatConnected && conversation.items.some(message => busyStates.has(message.status))))) {
      pollTimer = window.setTimeout(() => void refreshCurrent(), 1600)
    }
  } catch (error) {
    if (!cancelled(error) && expected === revision && requestRevision === refreshRevision && !disposed) {
      networkError.value = readable(error)
      if (record.value && (busyStates.has(record.value.subtitle_status) || summaryBusy.value || chatBusy.value)) {
        stopPolling()
        pollTimer = window.setTimeout(() => void refreshCurrent(), 1600)
      }
    }
  } finally {
    if (expected === revision && requestRevision === refreshRevision) loading.value = false
  }
}
function clearSelection() {
  stopPolling(); stopChatStream(true); stopSummaryStream(true); controller.abort(); controller = new AbortController()
  revision++; transcriptRevision++; refreshRevision++
  currentId.value = ''; record.value = null; summary.value = null; messages.value = []
  autoSummaryPromptFor = ''
  transcript.value = { items: [], total: 0, offset: 0, limit: 100 }
  transcriptLoadedFor = ''; search.value = ''; highlightedCue.value = ''; question.value = ''; pendingQuestion = null
  notice.value = ''; networkError.value = ''; historyOpen.value = false; loading.value = false
  creating.value = false; busy.value = false; subtitleExporting.value = false; confirmation.value = null
  restoring.value = false
  learningUnavailable.value = ''; tab.value = 'summary'
}
async function selectRecord(id: string, keepVideo = false, automatic = false) {
  if (!keepVideo && id === currentId.value) { historyOpen.value = false; return }
  if (downloadBusy.value && !keepVideo) { notice.value = '当前下载仍在处理中，完成后可切换视频。'; return }
  if (!keepVideo) download.reset()
  clearSelection()
  const expected = revision
  currentId.value = id; loading.value = true; restoring.value = true
  if (automatic) autoSummaryPromptFor = id
  window.history.replaceState(null, '', '#learn/' + encodeURIComponent(id))
  try {
    await refreshCurrent()
    if (expected !== revision || disposed || !record.value) return
    if (!keepVideo) {
      inputUrl.value = record.value.url
      // Restoring a local record only parses download metadata; it never creates a model request.
      void download.parse(record.value.url)
    }
  } finally { if (expected === revision) restoring.value = false }
}
async function createRecord(url = inputUrl.value, language = 'auto', automatic = false) {
  if (creating.value) return
  const submitted = url.trim(), expected = revision
  if (!submitted) { notice.value = '先粘贴一个视频链接。'; linkInput.value?.focus(); return }
  creating.value = true; notice.value = ''
  try {
    const response = await learningApi<{ id: string }>('/analyses', { method: 'POST', body: JSON.stringify({ url: submitted, language, auto_summary: automatic }) }, controller.signal)
    if (disposed || expected !== revision) return
    creating.value = false
    await selectRecord(response.id, true, automatic)
    await loadHistory()
  } catch (error) {
    if (!cancelled(error) && !disposed && expected === revision) {
      notice.value = readable(error)
      if (automatic && error instanceof LearningApiError) showSummaryGate(error.code, error.message)
    }
  } finally {
    if (expected === revision) creating.value = false
  }
}
const configController = new AbortController()
let configRequest: Promise<void> | null = null
function loadConfig() {
  if (!configRequest) configRequest = learningApi<AIConfig>('/ai/config', {}, configController.signal).then(value => { if (!disposed) config.value = value }).catch(error => { if (!cancelled(error) && !disposed) { networkError.value = readable(error); configRequest = null } })
  return configRequest
}
function supportsLearning(url: string) {
  try { const host = new URL(url).hostname.toLowerCase(); return ['bilibili.com', 'b23.tv', 'douyin.com', 'iesdouyin.com', 'youtube.com', 'youtu.be'].some(domain => host === domain || host.endsWith('.' + domain)) }
  catch { return false }
}
async function parseVideo() {
  if (composerBusy.value) return
  const submitted = inputUrl.value.trim(), automatic = autoSummary.value
  clearSelection()
  const expected = revision
  window.history.replaceState(null, '', '#top')
  if (!await download.parse(submitted) || expected !== revision || disposed) return
  if (!supportsLearning(submitted)) { learningUnavailable.value = '该平台可下载视频，暂不支持 AI 总结。目前支持 B 站、抖音和 YouTube；没有可用字幕时，可使用服务端开启的语音转录。'; return }
  await loadConfig()
  if (expected !== revision || disposed) return
  await createRecord(submitted, 'auto', automatic && !!config.value?.configured && config.value?.auto_summary_version === 1 && summaryCompatible.value)
  if (!config.value || (automatic && config.value.configured && config.value.auto_summary_version !== 1)) notice.value = '自动总结暂不可用，请重启后端或检查服务连接；已获取的字幕可继续查看。'
}
async function pasteLink() {
  if (composerBusy.value) return
  try { inputUrl.value = await navigator.clipboard.readText() }
  catch { notice.value = '无法读取剪贴板，请直接粘贴链接。' }
}
function newRecord() {
  if (downloadBusy.value) { notice.value = '当前下载仍在处理中，完成后可切换视频。'; return }
  download.reset(); clearSelection(); inputUrl.value = ''
  window.history.replaceState(null, '', '#learn')
  void nextTick(() => linkInput.value?.focus())
}
async function generate(force = false) {
  if (!summaryCompatible.value) { notice.value = '后端仍在运行旧版摘要代码，请重启后端后再生成。'; return }
  const id = currentId.value, expected = revision
  autoSummaryPromptFor = ''
  busy.value = true; notice.value = ''
  try {
    await learningApi('/analyses/' + id + '/summary', { method: 'POST', body: JSON.stringify({ force, stream: true }) }, controller.signal)
    if (expected === revision && !disposed) await refreshCurrent()
  } catch (error) {
    if (!cancelled(error) && expected === revision && !disposed) {
      notice.value = readable(error)
      if (error instanceof LearningApiError) showSummaryGate(error.code, error.message)
    }
  } finally { if (expected === revision) busy.value = false }
}
async function sendQuestion() {
  const text = question.value.trim(), id = currentId.value, expected = revision
  if (!text || busy.value || chatBusy.value) return
  if (!pendingQuestion || pendingQuestion.recordId !== id || pendingQuestion.question !== text) pendingQuestion = { recordId: id, question: text, requestId: crypto.randomUUID() }
  const submission = pendingQuestion
  busy.value = true; notice.value = ''
  try {
    await learningApi('/analyses/' + id + '/chat', { method: 'POST', body: JSON.stringify({ question: text, request_id: submission.requestId, stream: true }) }, controller.signal)
    if (expected === revision && !disposed) { question.value = ''; pendingQuestion = null; await refreshCurrent() }
  } catch (error) {
    if (!cancelled(error) && expected === revision && !disposed) notice.value = readable(error)
  } finally { if (expected === revision) busy.value = false }
}
async function confirmAction() {
  const action = confirmation.value, expected = revision
  if (!action || (action.kind === 'record' && currentId.value === action.id && downloadBusy.value)) return
  busy.value = true; notice.value = ''
  try {
    await learningApi('/analyses/' + action.id + (action.kind === 'chat' ? '/messages' : ''), { method: 'DELETE' }, controller.signal)
    if (currentId.value === action.id) stopChatStream(true)
    if (currentId.value === action.id && action.kind === 'record') stopSummaryStream(true)
    confirmation.value = null
    if (action.kind === 'chat') {
      if (currentId.value === action.id) { pendingQuestion = null; await refreshCurrent() }
    } else {
      await loadHistory()
      if (currentId.value === action.id) {
        if (history.value[0]) await selectRecord(history.value[0].id)
        else newRecord()
      }
    }
  } catch (error) {
    if (!cancelled(error) && !disposed) notice.value = readable(error)
  } finally { if (expected === revision) busy.value = false }
}
async function locate(id: string) {
  tab.value = 'transcript'; search.value = ''; highlightedCue.value = id
  await loadTranscript(0, id)
}
function refLabel(reference: Reference) { return clock(reference.start) + ' 原文' }
function markdown() {
  if (!summary.value || !record.value) return ''
  const content = summary.value.content
  return ['# ' + record.value.title, record.value.url, '## ' + content.headline, content.overview,
    ...content.chapters.flatMap(chapter => ['## ' + chapter.title, chapter.overview,
      ...chapter.points.map(point => '- ' + point.text + '（' + point.references.map(r => clock(r.start)).join('、') + '）')])].join('\n\n')
}
async function copySummary() {
  try { await navigator.clipboard.writeText(markdown()); notice.value = '摘要已复制。' }
  catch { notice.value = '无法访问剪贴板，请使用导出 Markdown。' }
}
async function downloadSubtitle() {
  if (!record.value || !transcriptReady.value || subtitleExporting.value) return
  const id = record.value.id, expected = revision, format = subtitleFormat.value
  subtitleExporting.value = true; notice.value = ''
  try {
    const response = await fetch('/api/v1/analyses/' + id + '/export?format=' + format, { signal: controller.signal })
    if (!response.ok) {
      const body = await response.json().catch(() => null)
      throw new Error(typeof body?.detail === 'string' ? body.detail : body?.detail?.message || '字幕下载未完成，请重试。')
    }
    const blob = await response.blob()
    if (disposed || expected !== revision) return
    downloadBlob(blob, downloadFilename(response.headers.get('Content-Disposition'), 'video-subtitles.' + format))
    notice.value = '已生成完整 ' + format.toUpperCase() + ' 字幕文件，包含当前语言的全部原文和时间戳。'
  } catch (error) {
    if (!cancelled(error) && !disposed && expected === revision) notice.value = readable(error)
  } finally { if (expected === revision) subtitleExporting.value = false }
}
function switchLanguage(event: Event) {
  if (record.value) void createRecord(record.value.url, (event.target as HTMLSelectElement).value)
}
function followLearningHash() {
  if (downloadBusy.value) {
    window.history.replaceState(null, '', currentId.value ? '#learn/' + currentId.value : '#top')
    notice.value = '当前下载仍在处理中，完成后可切换视频。'
    return
  }
  const match = window.location.hash.match(/^#learn\/([A-Za-z0-9_-]+)$/)
  if (match?.[1] && match[1] !== currentId.value) void selectRecord(match[1])
  else if (['#learn', '#top', ''].includes(window.location.hash) && workspaceActive.value) newRecord()
}
onMounted(() => {
  window.addEventListener('hashchange', followLearningHash)
  const match = window.location.hash.match(/^#learn\/([A-Za-z0-9_-]+)$/)
  if (match?.[1]) void selectRecord(match[1])
  else linkInput.value?.focus()
  void loadConfig(); void loadHistory()
})
onBeforeUnmount(() => {
  disposed = true; download.dispose(); configController.abort(); stopPolling(); stopChatStream(true); stopSummaryStream(true); controller.abort(); revision++
  window.removeEventListener('hashchange', followLearningHash)
})
</script>

<template>
  <div class="learning-shell unified-shell">
    <header class="learning-header">
      <a href="#top" class="learning-brand" @click.prevent="newRecord"><span class="learning-brand-icon"><CirclePlay aria-hidden="true" /></span><span>SaveAny</span></a>
      <span class="learning-header-label">万能视频下载总结器</span>
      <nav v-if="!workspaceActive" class="home-navigation" aria-label="产品导航"><a href="#features">功能特性</a><a href="#tutorial">使用教程</a><a v-if="membershipState.enabled" href="#pricing">套餐价格</a></nav>
      <nav class="workspace-navigation" aria-label="页面导航"><button class="learning-button workspace-history-trigger" type="button" @click="historyOpen = true"><Clock3 aria-hidden="true" /><span>本机学习记录（{{ historyTotal }}）</span></button><button class="learning-button workspace-rights-trigger" type="button" aria-label="版权与使用声明" title="版权与使用声明" @click="rightsOpen = true"><Copyright aria-hidden="true" /></button><MemberPanel ref="memberPanel" @state="membershipState = $event" /></nav>
    </header>
    <main class="unified-main" :class="{ 'workspace-is-active': workspaceActive }">
      <section class="workspace-composer" aria-label="解析视频">
        <div v-if="!workspaceActive" class="workspace-intro"><p class="hero-badge"><Sparkles aria-hidden="true" />下载不限量 · 学习更轻松</p><h1>视频下载与 AI 总结，<span>一站完成</span></h1><p class="hero-description">粘贴视频链接，选择画质并保存。让 AI 整理摘要、生成思维导图，<br class="hero-line-break" />视频信息与学习内容，一屏查看。</p></div>
        <LinkComposer v-model="inputUrl" :busy="composerBusy" :parsing="parsing || creating" :invalid="!!parseError" @ready="linkInput = $event" @parse="parseVideo" @paste="pasteLink" />
        <div class="workspace-preferences"><label><input v-model="autoSummary" type="checkbox" />解析后自动总结</label><span>{{ autoSummary ? '有可用字幕时调用 DeepSeek；已保存的摘要会直接复用' : '仅获取视频信息与字幕，可手动生成总结' }}</span><button v-if="workspaceActive" class="workspace-reset" type="button" :disabled="downloadBusy" @click="newRecord">换个链接</button></div>
        <p v-if="downloadBusy" class="learning-muted" role="status">下载处理中，完成后可切换视频；仍可查看摘要、字幕、导图和问答。</p>
        <div v-if="!workspaceActive" class="hero-platforms" aria-label="常见视频平台"><span>支持平台</span><span>YouTube</span><span>Bilibili</span><span>抖音</span></div>
        <p id="supported-platforms" class="workspace-platforms">视频下载：支持多个平台 · AI 总结：B 站、抖音、YouTube · 字幕优先，无字幕时使用语音转录（需服务端开启）</p>
        <p v-if="parseError" id="input-error" class="learning-alert" role="alert">{{ parseError }}</p>
        <p v-if="notice && !workspaceActive" class="learning-notice" role="status">{{ notice }}</p>
      </section>
      <div v-if="workspaceActive" class="unified-grid">
        <aside class="workspace-video" aria-label="视频信息与下载">
          <p v-if="parsing" class="learning-progress" role="status">正在解析视频信息…</p>
          <CompactVideoResult v-if="video" :video="video" :url="parsedUrl" v-model:format="selectedFormat" v-model:mode="deliveryMode" :modes="availableModes" :busy="downloadBusy" :thumbnail-failed="thumbnailFailed" @thumbnail-error="thumbnailFailed = true" />
          <div v-if="video" class="compact-download"><DownloadAction :task="downloadTask" :starting="starting" :running="running" :progress="progress" :download-url="downloadUrl" :error-message="downloadError" :selection="selection" @start="download.start" @dismiss="downloadError = ''" /></div>
          <div v-else-if="record" class="compact-video"><p class="learning-eyebrow">{{ record.platform }} · {{ record.duration === null ? '时长未知' : clock(record.duration) }}</p><h2>{{ record.title }}</h2><a class="compact-source" :href="record.url" target="_blank" rel="noopener noreferrer">打开原视频 ↗</a><p class="learning-muted">本机记录不保存下载地址，正在重新获取视频信息。</p><button v-if="parseError" class="learning-button" type="button" @click="download.parse(record!.url)">重试解析下载信息</button></div>
          <p v-else-if="!parsing" class="learning-empty">视频解析成功后，这里显示封面、清晰度与下载。</p>
        </aside>
        <section class="learning-main workspace-learning" aria-label="视频学习工作区">
        <div v-if="networkError" class="learning-alert" role="alert"><p>{{ networkError }}</p><button class="learning-button" type="button" @click="currentId ? refreshCurrent() : loadHistory()">重试刷新</button></div>
        <div v-if="notice" class="learning-notice" role="status"><span>{{ notice }}</span><button class="learning-button" type="button" aria-label="关闭提示" @click="notice = ''">关闭</button></div>
        <div v-if="loading" class="learning-empty" role="status">正在读取本机记录…</div>
        <template v-else-if="record">
          <div v-if="busyStates.has(record.subtitle_status)" class="learning-progress" role="status"><Clock3 aria-hidden="true" /><span>{{ subtitleJob?.stage || '等待获取字幕' }}。平台响应可能需要一些时间。</span></div>
          <div v-else-if="record.subtitle_status !== 'ready'" class="learning-alert" role="alert"><p>{{ record.subtitle_error || '字幕获取未完成。' }}</p><p class="learning-muted">没有有效字幕时暂不能总结、生成导图或问答；左侧视频下载仍可使用。</p><button class="learning-button" type="button" :disabled="creating" @click="createRecord(record!.url, record!.requested_language)">重试获取字幕</button></div>
          <template v-else>
            <div class="learning-source-bar"><p class="learning-muted" title="根据所获字幕整理，未分析视频画面。">{{ record.language }} · {{ sourceKind(record.track_kind) }}</p><label v-if="selectedTrack.length > 1">字幕语言 <select aria-label="切换字幕语言" :value="record.language || 'auto'" :disabled="creating || busy" @change="switchLanguage"><option value="auto">自动选择</option><option v-for="track in selectedTrack" :key="track.language" :value="track.language">{{ track.language }} · {{ sourceKind(track.kind) }}</option></select></label></div>
            <details v-if="record.notes.length" class="workspace-notes"><summary>字幕来源与说明</summary><p v-for="note in record.notes" :key="note" class="learning-muted">{{ note }}</p></details>
            <div v-if="config && !config.configured" class="learning-config-note"><p>DeepSeek 尚未配置，字幕和视频下载已可使用。</p><details><summary>配置方法</summary><p>在项目根目录的 <code>.env</code> 填写 <code>DEEPSEEK_API_KEY</code>，保存后重启后端。也可使用 <code>.\start-local.ps1 -AskDeepSeekKey</code> 隐藏输入。无需把密钥粘贴到网页或聊天。</p></details></div>
          </template>
          <nav class="learning-tabs" aria-label="学习内容"><button v-for="item in tabs" :id="'tab-' + item.value" :key="item.value" class="learning-tab" :class="{ 'learning-tab-active': tab === item.value }" type="button" :aria-pressed="tab === item.value" @click="tab = item.value"><component :is="item.icon" aria-hidden="true" />{{ item.label }}</button></nav>
          <section class="learning-panel" :aria-labelledby="'tab-' + tab">
            <template v-if="tab === 'summary'">
              <div class="learning-toolbar"><h2>视频摘要</h2><div class="learning-toolbar"><button v-if="summary" class="learning-button" type="button" @click="copySummary">复制</button><a v-if="summary" class="learning-button" :href="'/api/v1/analyses/' + record.id + '/export?format=markdown'" download>导出 Markdown</a><button class="learning-button learning-primary" type="button" :disabled="!transcriptReady || !config?.configured || !summaryCompatible || busy || summaryBusy" @click="generate(summary !== null && record.summary_status === 'ready')">{{ summaryBusy ? '正在总结…' : summary ? (record.summary_status === 'ready' ? '重新生成' : '重试总结') : (['failed', 'interrupted'].includes(record.summary_status) ? '重试总结' : '生成总结') }}</button></div></div>
              <p class="learning-muted">生成与追问会调用你的 DeepSeek 账户；重新生成也会产生用量。</p>
              <p v-if="config && !summaryCompatible" class="learning-alert" role="alert">后端仍在运行旧版摘要代码，请重启后端后再生成。</p>
              <p v-if="summaryBusy" class="learning-progress" role="status">{{ summaryDraft?.stage || summaryJob?.stage || autoSummaryJob?.stage || '等待模型处理' }}</p>
              <p v-if="summaryStreamNote" class="learning-muted" role="status">{{ summaryStreamNote }}</p>
              <div v-if="record.summary_status === 'failed' || record.summary_status === 'interrupted' || (record.summary_status === 'idle' && autoSummaryJob?.status === 'interrupted')" class="learning-alert" role="alert">{{ summaryJob?.error || autoSummaryJob?.error || '总结被中断，请手动重试。' }}<p v-if="summary">下方保留上次成功生成的摘要。</p></div>
              <div v-if="summaryDraft && summaryDraft.parts.some(part => part.text)" class="summary-stream-preview" :aria-busy="summaryBusy">
                <p class="learning-eyebrow">摘要生成过程</p>
                <p class="learning-muted" role="status">{{ !summaryBusy ? '未完成草稿，尚未保存为正式摘要。' : summaryDraft.phase === 'retrying' ? '正在修正当前分段，保留上一版草稿供查看。' : summaryDraft.phase === 'validating' ? '正在校验摘要结构与字幕引用…' : summaryDraft.phase === 'cached' ? '当前分段已复用，等待完整汇总。' : '正在生成，引用尚未校验；完整摘要将在全部处理完成后保存。' }}</p>
                <article v-for="part in summaryDraft.parts.filter(part => part.text)" :key="part.id" class="summary-draft-part" :data-phase="part.phase" :data-part-id="part.id">
                  <p class="learning-eyebrow">{{ part.stage }}{{ part.attempt > 1 ? ' · 修正第 ' + (part.attempt - 1) + ' 次' : '' }}</p>
                  <p v-if="part.phase === 'superseded'" class="learning-muted">上一版草稿未通过校验，正在修正；此版本不会作为正式摘要保存。</p>
                  <p v-else-if="part.phase === 'retained'" class="learning-muted">此前过程文本已保留供查看；请以最终校验完成的摘要为准。</p>
                  <p v-else-if="part.phase === 'validated' || part.phase === 'cached'" class="learning-muted">当前阶段已校验，等待完整汇总。</p>
                  <p v-if="part.retry_reason" class="learning-muted">自动修复原因：{{ part.retry_reason }}</p>
                  <p :class="part.id === summaryDraft.parts.at(-1)?.id ? 'summary-stream-text' : 'summary-stage-text'">{{ part.text }}</p>
                </article>
              </div>
              <p v-if="summary && summaryBusy" class="learning-muted">下方为上次保存的摘要；生成完成后更新。</p>
              <template v-if="summary">
                <article class="summary-overview"><p class="learning-eyebrow">快速总览</p><h3>{{ summary.content.headline }}</h3><p>{{ summary.content.overview }}</p></article>
                <ol class="summary-chapters">
                  <li v-for="(chapter, index) in summary.content.chapters" :key="index"><article><p class="learning-eyebrow">章节 {{ index + 1 }}</p><h3>{{ chapter.title }}</h3><p>{{ chapter.overview }}</p><div class="learning-references"><button v-for="reference in chapter.references" :key="reference.cue_id" class="learning-reference" type="button" :title="reference.text" @click="locate(reference.cue_id)">{{ refLabel(reference) }}</button></div><ul><li v-for="(point, pointIndex) in chapter.points" :key="pointIndex"><p>{{ point.text }}</p><div class="learning-references"><button v-for="reference in point.references" :key="reference.cue_id" class="learning-reference" type="button" :title="reference.text" @click="locate(reference.cue_id)">{{ refLabel(reference) }}</button></div></li></ul></article></li>
                </ol>
                <p class="learning-muted">模型 {{ summary.model }} · {{ new Date(summary.created_at).toLocaleString('zh-CN') }}</p>
              </template>
              <div v-else-if="!summaryBusy" class="learning-empty">字幕准备好后，可手动生成总结。自动接续失败或中断时，请手动重试。</div>
            </template>
            <template v-else-if="tab === 'transcript'">
              <div class="learning-toolbar"><h2>字幕原文</h2><div v-if="transcriptReady" class="subtitle-downloads"><label>格式 <select v-model="subtitleFormat" aria-label="字幕下载格式" :disabled="subtitleExporting"><option value="srt">SRT · 播放器字幕</option><option value="txt">TXT · 带时间戳原文</option></select></label><button class="learning-button" type="button" :disabled="subtitleExporting" @click="downloadSubtitle">{{ subtitleExporting ? '正在准备字幕…' : '下载字幕' }}</button></div></div>
              <form v-if="transcriptReady" class="transcript-search" @submit.prevent="loadTranscript()"><label class="sr-only" for="transcript-search">搜索字幕</label><input id="transcript-search" v-model="search" maxlength="200" type="search" placeholder="搜索原文中的词语" /><button class="learning-button" type="submit">搜索</button><button v-if="search" class="learning-button" type="button" @click="search = ''; loadTranscript()">清除</button></form>
              <p class="learning-muted">字幕保留原语言，平台自动字幕可能存在识别错误。</p>
              <p v-if="transcriptReady" class="learning-muted">下载包含当前语言的全部字幕，不受搜索或分页影响；无需生成 AI 总结。</p>
              <div class="transcript-list"><article v-for="cue in transcript.items" :id="'cue-' + cue.id" :key="cue.id" class="transcript-cue" :class="{ 'cue-highlighted': highlightedCue === cue.id }" tabindex="-1"><span>{{ clock(cue.start) }}–{{ clock(cue.end) }}</span><p>{{ cue.text }}</p></article></div>
              <p v-if="!transcript.items.length" class="learning-empty-small">{{ transcriptReady ? '未找到匹配的字幕片段。' : '暂无有效字幕。' }}</p>
              <div v-if="transcript.total" class="learning-toolbar transcript-pagination"><span>{{ transcript.offset + 1 }}–{{ Math.min(transcript.total, transcript.offset + transcript.limit) }} / {{ transcript.total }} 段</span><div><button class="learning-button" type="button" :disabled="transcript.offset === 0" @click="loadTranscript(Math.max(0, transcript.offset - transcript.limit), '', true)">上一页</button><button class="learning-button" type="button" :disabled="transcript.offset + transcript.limit >= transcript.total" @click="loadTranscript(transcript.offset + transcript.limit, '', true)">下一页</button></div></div>
            </template>
            <template v-else-if="tab === 'mindmap'"><h2>思维导图</h2><MindMapView v-if="summary" :tree="summary.mindmap" :title="record.title" :summary-id="summary.id" @locate="locate" /><div v-else class="learning-empty">生成摘要后，导图会根据同一份章节与要点自动呈现。</div></template>
            <template v-else>
              <div class="learning-toolbar"><h2>针对视频提问</h2><button v-if="messages.length" class="learning-button" type="button" :disabled="busy" @click="confirmation = { kind: 'chat', id: record.id, title: record.title }">清空对话</button></div>
              <p class="learning-muted">回答依据当前字幕；没有信息或需要观看画面时会说明限制。</p>
              <div v-if="!messages.length" class="question-suggestions"><button class="learning-button" type="button" @click="question = '用三个要点概括这个视频的核心知识。'">概括核心知识</button><button class="learning-button" type="button" @click="question = '视频讲了哪些具体方法和适用条件？'">提取方法与条件</button></div>
              <p v-if="chatStreamNote" class="learning-muted" role="status">{{ chatStreamNote }}</p>
              <div class="chat-messages" aria-live="polite">
                <article v-for="message in messages" :key="message.id" class="chat-turn">
                  <div class="chat-question"><p class="learning-eyebrow">我的问题</p><p>{{ message.question }}</p></div>
                  <div class="chat-answer" :aria-busy="busyStates.has(message.status)">
                    <p class="learning-eyebrow">视频回答</p>
                    <template v-if="message.answer">
                      <p>{{ message.answer.answer }}</p><span v-if="message.answer.evidence === 'insufficient'" class="learning-muted">字幕依据不足</span>
                      <div class="learning-references"><button v-for="reference in message.answer.references" :key="reference.cue_id" class="learning-reference" type="button" :title="reference.text" @click="locate(reference.cue_id)">{{ refLabel(reference) }}</button></div>
                    </template>
                    <template v-else>
                      <p v-if="chatDrafts[message.id]?.text" class="chat-stream-text">{{ chatDrafts[message.id]?.text }}</p>
                      <p v-if="busyStates.has(message.status)" class="learning-muted" role="status">{{ chatDrafts[message.id]?.stage === 'validating' ? '正在校验回答与字幕引用…' : chatDrafts[message.id]?.text ? '正在生成，引用尚未校验…' : '正在根据字幕回答…' }}</p>
                      <div v-else class="learning-alert">
                        <p v-if="chatDrafts[message.id]?.text" class="learning-muted">上方内容为未完成草稿，尚未校验或保存为正式回答。</p>
                        <p>{{ message.error || '回答未完成，请重试。' }}</p><button class="learning-button" type="button" @click="question = message.question; pendingQuestion = null">重新提问</button>
                      </div>
                    </template>
                  </div>
                </article>
              </div>
              <form class="chat-form" @submit.prevent="sendQuestion"><label for="video-question">你的问题</label><textarea id="video-question" v-model="question" maxlength="2000" rows="3" placeholder="例如：视频中这个方法有哪些步骤？" :disabled="!transcriptReady || !config?.configured || busy || chatBusy" /><div class="learning-toolbar"><span class="learning-muted">{{ question.length }}/2000 · 将调用 DeepSeek</span><button class="learning-button learning-primary" type="submit" :disabled="!question.trim() || !transcriptReady || !config?.configured || busy || chatBusy">{{ chatBusy ? '等待回答…' : '发送问题' }}</button></div></form>
            </template>
          </section>
          <p v-if="record.usage && record.usage.calls" class="learning-usage">本记录 {{ record.usage.calls }} 次已返回用量的模型请求 · 输入 {{ record.usage.prompt_tokens.toLocaleString() }} / 输出 {{ record.usage.completion_tokens.toLocaleString() }} tokens。费用以 DeepSeek 账单为准。</p>
        </template>
        <div v-else-if="!loading" class="learning-welcome"><BookOpen aria-hidden="true" /><h2>{{ learningUnavailable ? '暂不能总结这个视频' : '准备视频学习内容' }}</h2><p>{{ learningUnavailable || (parsing ? '解析成功后自动获取字幕，并按你的选择生成总结。' : notice ? '字幕请求未完成，可重新解析或稍后重试。' : '正在获取字幕记录…') }}</p></div>
        </section>
      </div>
      <template v-if="!workspaceActive">
        <section id="features" class="home-section home-features" aria-labelledby="features-heading"><div class="home-section-heading"><p class="learning-eyebrow">不止于保存</p><h2 id="features-heading">把视频，变成随时可用的知识</h2><p>下载与学习放在一起，少一点切换，多一点收获。</p></div><div class="workspace-start"><div><span class="home-feature-icon"><FileText aria-hidden="true" /></span><h3>清晰保存</h3><p>解析真实清晰度与格式，按需保存视频和字幕。</p><span class="home-feature-caption">多画质选择 <ArrowRight aria-hidden="true" /></span></div><div><span class="home-feature-icon"><BookOpen aria-hidden="true" /></span><h3>快速读懂</h3><p>AI 自动整理总览、章节和知识要点，保留字幕引用。</p><span class="home-feature-caption">流式摘要与原文定位 <ArrowRight aria-hidden="true" /></span></div><div><span class="home-feature-icon"><MessageCircle aria-hidden="true" /></span><h3>深入学习</h3><p>查看思维导图，针对视频字幕提问，随时导出笔记。</p><span class="home-feature-caption">问答与学习记录 <ArrowRight aria-hidden="true" /></span></div></div></section>
        <HomeTutorial @start="focusComposer" @rights="rightsOpen = true" />
        <section v-if="membershipState.enabled" id="pricing" class="home-section home-pricing" aria-labelledby="pricing-heading"><div class="home-section-heading"><p class="learning-eyebrow">按你的节奏选择</p><h2 id="pricing-heading">下载免费，会员让学习更从容</h2><p>日常使用选免费版，经常总结选 VIP。一次购买，不自动续费。</p></div><MembershipPlans :signed-in="membershipState.signedIn" :is-member="membershipState.isMember" :busy="membershipState.busy" preview @start="focusComposer" @buy="memberPanel?.showPlans()" /></section>
        <footer class="workspace-home-footer"><a class="footer-brand" href="#top" @click.prevent="focusComposer">SaveAny<span>保存视频，也保存知识。</span></a><nav class="workspace-public-guides" aria-label="产品介绍、教程与声明"><a href="/zh/">产品介绍与中文教程</a><a href="/en/" lang="en">English guides</a><button type="button" @click="rightsOpen = true">版权与使用声明</button></nav></footer>
      </template>
    </main>
    <ResultDialog :open="historyOpen" @close="historyOpen = false"><template #title>本机学习记录</template><aside id="learning-history" class="workspace-history" aria-label="本机学习记录"><div class="learning-toolbar"><p class="learning-muted">保存在本机，重启后仍可查看。</p><button class="learning-button" type="button" :disabled="downloadBusy" @click="newRecord"><Plus aria-hidden="true" />新建</button></div><p v-if="!history.length" class="learning-empty-small">还没有记录，从一个视频开始。</p><div v-for="item in history" :key="item.id" class="history-item" :class="{ 'history-selected': currentId === item.id }"><button class="history-select" type="button" :disabled="downloadBusy && currentId !== item.id" @click="selectRecord(item.id)"><span>{{ item.title }}</span><small>{{ item.platform }} · {{ recordStatus(item) }}</small></button><button class="history-delete" type="button" :disabled="downloadBusy && currentId === item.id" :aria-label="'删除记录：' + item.title" @click="historyOpen = false; confirmation = { kind: 'record', id: item.id, title: item.title }"><Trash2 aria-hidden="true" /></button></div><button v-if="history.length < historyTotal" class="learning-button" type="button" @click="loadHistory(true)">加载更多记录</button></aside></ResultDialog>
    <ResultDialog :open="rightsOpen" variant="notice" @close="rightsOpen = false"><template #title>版权与使用声明</template><template #description>尊重创作者，按授权使用内容。</template><CopyrightNotice @close="rightsOpen = false" /></ResultDialog>
    <ResultDialog :open="!!confirmation" @close="confirmation = null"><template #title>{{ confirmation?.kind === 'chat' ? '清空视频对话' : '删除学习记录' }}</template><div v-if="confirmation" class="learning-confirm"><p>{{ confirmation.title }}</p><p>{{ confirmation.kind === 'chat' ? '删除该视频的所有本机问答记录，进行中的回答也将停止保存。' : '删除该视频在本机保存的字幕、摘要、导图、问答及中间结果。' }}</p><div class="learning-toolbar"><button class="learning-button" type="button" :disabled="busy" @click="confirmation = null">取消</button><button class="learning-button learning-danger" type="button" :disabled="busy" @click="confirmAction">{{ confirmation.kind === 'chat' ? '确认清空' : '确认删除' }}</button></div></div></ResultDialog>
  </div>
</template>
