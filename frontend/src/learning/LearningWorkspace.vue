<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { ArrowLeft, BookOpen, CirclePlay, Clock3, FileText, MessageCircle, Network, Plus, Trash2 } from '@lucide/vue'
import ResultDialog from '../components/ResultDialog.vue'
import MindMapView from './MindMapView.vue'
import { clock, learningApi, sourceKind } from './api'
import type { AIConfig, Analysis, Message, Page, Reference, SummaryResponse, SummaryVersion, TranscriptPage } from './types'
import './learning.css'

const props = defineProps<{ initialUrl: string; downloadBusy: boolean }>()
const emit = defineEmits<{ close: []; download: [url: string] }>()
const inputUrl = ref(props.initialUrl)
const linkInput = ref<HTMLInputElement | null>(null)
const config = ref<AIConfig | null>(null)
const history = ref<Analysis[]>([])
const historyTotal = ref(0)
const historyOpen = ref(false)
const record = ref<Analysis | null>(null)
const currentId = ref('')
const summary = ref<SummaryVersion | null>(null)
const messages = ref<Message[]>([])
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
const confirmation = ref<{ kind: 'record' | 'chat'; id: string; title: string } | null>(null)
let controller = new AbortController()
let revision = 0
let pollTimer: number | undefined
let transcriptRevision = 0
let transcriptLoadedFor = ''
let disposed = false
let pendingQuestion: { recordId: string; question: string; requestId: string } | null = null
const busyStates = new Set(['pending', 'fetching', 'queued', 'processing'])
const transcriptReady = computed(() => record.value?.subtitle_status === 'ready')
const summaryBusy = computed(() => busyStates.has(record.value?.summary_status || ''))
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
  const id = currentId.value, expected = revision
  if (!id) return
  try {
    const [detail, result, conversation] = await Promise.all([
      learningApi<Analysis>('/analyses/' + id, {}, controller.signal),
      learningApi<SummaryResponse>('/analyses/' + id + '/summary', {}, controller.signal),
      learningApi<{ items: Message[] }>('/analyses/' + id + '/messages', {}, controller.signal),
    ])
    if (expected !== revision || disposed) return
    const oldSubtitleStatus = record.value?.subtitle_status
    const oldSummaryStatus = record.value?.summary_status
    record.value = detail; summary.value = result.summary; messages.value = conversation.items
    networkError.value = ''
    if (detail.subtitle_status === 'ready' && (transcriptLoadedFor !== id || oldSubtitleStatus !== 'ready')) await loadTranscript()
    if (oldSubtitleStatus !== detail.subtitle_status || oldSummaryStatus !== detail.summary_status) void loadHistory()
    if (expected === revision && (busyStates.has(detail.subtitle_status) || busyStates.has(detail.summary_status) || conversation.items.some(message => busyStates.has(message.status)))) {
      pollTimer = window.setTimeout(() => void refreshCurrent(), 1600)
    }
  } catch (error) {
    if (!cancelled(error) && expected === revision && !disposed) networkError.value = readable(error)
  } finally {
    if (expected === revision) loading.value = false
  }
}
async function selectRecord(id: string) {
  stopPolling(); controller.abort(); controller = new AbortController()
  revision++; transcriptRevision++
  currentId.value = id; record.value = null; summary.value = null; messages.value = []
  transcript.value = { items: [], total: 0, offset: 0, limit: 100 }
  transcriptLoadedFor = ''; search.value = ''; highlightedCue.value = ''
  notice.value = ''; networkError.value = ''; historyOpen.value = false; loading.value = true
  tab.value = 'summary'
  window.history.replaceState(null, '', '#learn/' + encodeURIComponent(id))
  await refreshCurrent()
}
async function createRecord(url = inputUrl.value, language = 'auto') {
  if (creating.value) return
  if (!url.trim()) { notice.value = '先粘贴一个 B 站、抖音或 YouTube 的视频链接。'; linkInput.value?.focus(); return }
  creating.value = true; notice.value = ''
  try {
    const response = await learningApi<{ id: string }>('/analyses', { method: 'POST', body: JSON.stringify({ url: url.trim(), language }) }, controller.signal)
    if (disposed) return
    await selectRecord(response.id)
    await loadHistory()
  } catch (error) {
    if (!cancelled(error) && !disposed) notice.value = readable(error)
  } finally {
    creating.value = false
  }
}
function newRecord() {
  stopPolling(); controller.abort(); controller = new AbortController(); revision++
  currentId.value = ''; record.value = null; summary.value = null; messages.value = []
  inputUrl.value = ''; search.value = ''; notice.value = ''; networkError.value = ''; loading.value = false
  historyOpen.value = false
  window.history.replaceState(null, '', '#learn')
  void nextTick(() => linkInput.value?.focus())
}
async function generate(force = false) {
  const id = currentId.value, expected = revision
  busy.value = true; notice.value = ''
  try {
    await learningApi('/analyses/' + id + '/summary', { method: 'POST', body: JSON.stringify({ force }) }, controller.signal)
    if (expected === revision && !disposed) await refreshCurrent()
  } catch (error) {
    if (!cancelled(error) && expected === revision && !disposed) notice.value = readable(error)
  } finally { busy.value = false }
}
async function sendQuestion() {
  const text = question.value.trim(), id = currentId.value, expected = revision
  if (!text || busy.value || chatBusy.value) return
  if (!pendingQuestion || pendingQuestion.recordId !== id || pendingQuestion.question !== text) pendingQuestion = { recordId: id, question: text, requestId: crypto.randomUUID() }
  const submission = pendingQuestion
  busy.value = true; notice.value = ''
  try {
    await learningApi('/analyses/' + id + '/chat', { method: 'POST', body: JSON.stringify({ question: text, request_id: submission.requestId }) }, controller.signal)
    if (expected === revision && !disposed) { question.value = ''; pendingQuestion = null; await refreshCurrent() }
  } catch (error) {
    if (!cancelled(error) && expected === revision && !disposed) notice.value = readable(error)
  } finally { busy.value = false }
}
async function confirmAction() {
  const action = confirmation.value
  if (!action) return
  busy.value = true; notice.value = ''
  try {
    await learningApi('/analyses/' + action.id + (action.kind === 'chat' ? '/messages' : ''), { method: 'DELETE' }, controller.signal)
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
  } finally { busy.value = false }
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
function switchLanguage(event: Event) {
  if (record.value) void createRecord(record.value.url, (event.target as HTMLSelectElement).value)
}
function followLearningHash() {
  const match = window.location.hash.match(/^#learn\/([A-Za-z0-9_-]+)$/)
  if (match?.[1] && match[1] !== currentId.value) void selectRecord(match[1])
  else if (window.location.hash === '#learn' && currentId.value) newRecord()
}
onMounted(async () => {
  try { config.value = await learningApi<AIConfig>('/ai/config', {}, controller.signal) }
  catch (error) { if (!cancelled(error)) networkError.value = readable(error) }
  await loadHistory()
  if (disposed) return
  window.addEventListener('hashchange', followLearningHash)
  const match = window.location.hash.match(/^#learn\/([A-Za-z0-9_-]+)$/)
  if (match?.[1]) await selectRecord(match[1])
  else linkInput.value?.focus()
})
onBeforeUnmount(() => {
  disposed = true; stopPolling(); controller.abort(); revision++
  window.removeEventListener('hashchange', followLearningHash)
})
</script>

<template>
  <div class="learning-shell">
    <header class="learning-header">
      <a href="#top" class="learning-brand" @click.prevent="emit('close')"><CirclePlay aria-hidden="true" /><span>SaveAny</span></a>
      <span class="learning-header-label">视频学习</span>
      <button type="button" class="learning-button" @click="emit('close')"><ArrowLeft aria-hidden="true" /><span>返回视频下载</span></button>
    </header>
    <main class="learning-layout">
      <button class="learning-button history-toggle" type="button" :aria-expanded="historyOpen" aria-controls="learning-history" @click="historyOpen = !historyOpen">本机学习记录（{{ historyTotal }}）</button>
      <aside id="learning-history" class="learning-history" :class="{ 'history-is-open': historyOpen }" aria-label="本机学习记录">
        <div class="learning-toolbar"><h2>学习记录</h2><button class="learning-button" type="button" @click="newRecord"><Plus aria-hidden="true" />新建</button></div>
        <p class="learning-muted">保存在本机，重启后仍可查看。</p>
        <p v-if="!history.length" class="learning-empty-small">还没有记录，从一个视频开始。</p>
        <div v-for="item in history" :key="item.id" class="history-item" :class="{ 'history-selected': currentId === item.id }">
          <button class="history-select" type="button" @click="selectRecord(item.id)"><span>{{ item.title }}</span><small>{{ item.platform }} · {{ recordStatus(item) }}</small></button>
          <button class="history-delete" type="button" :aria-label="'删除记录：' + item.title" @click="confirmation = { kind: 'record', id: item.id, title: item.title }"><Trash2 aria-hidden="true" /></button>
        </div>
        <button v-if="history.length < historyTotal" class="learning-button" type="button" @click="loadHistory(true)">加载更多记录</button>
      </aside>
      <section class="learning-main" aria-label="视频学习工作区">
        <form class="learning-link-form" @submit.prevent="createRecord()">
          <label for="learning-url">视频链接</label>
          <div class="learning-link-row"><input id="learning-url" ref="linkInput" v-model="inputUrl" type="url" required maxlength="2048" placeholder="粘贴 B 站、抖音或 YouTube 链接" :disabled="creating" /><button class="learning-button learning-primary" type="submit" :disabled="creating">{{ creating ? '正在创建…' : '获取字幕' }}</button></div>
          <p class="learning-muted">先获取平台字幕，再选择生成总结。无需先下载视频，首版最长 {{ clock(config?.max_duration || 7200) }}。</p>
          <p v-if="config?.firefox_subtitle_session" class="learning-muted">B 站与抖音字幕已启用本机 Firefox 会话。请确认 Firefox 已登录对应平台。</p>
        </form>
        <div v-if="networkError" class="learning-alert" role="alert"><p>{{ networkError }}</p><button class="learning-button" type="button" @click="currentId ? refreshCurrent() : loadHistory()">重试刷新</button></div>
        <div v-if="notice" class="learning-notice" role="status"><span>{{ notice }}</span><button class="learning-button" type="button" aria-label="关闭提示" @click="notice = ''">关闭</button></div>
        <div v-if="loading" class="learning-empty" role="status">正在读取本机记录…</div>
        <template v-else-if="record">
          <div class="learning-video-header">
            <div><p class="learning-eyebrow">{{ record.platform }} <span v-if="record.duration !== null">· {{ clock(record.duration) }}</span></p><h1>{{ record.title }}</h1><p class="learning-muted">{{ record.language || '字幕尚未获取' }} · {{ sourceKind(record.track_kind) }}</p></div>
            <div class="learning-toolbar"><a class="learning-button" :href="record.url" target="_blank" rel="noopener noreferrer">打开原视频</a><button class="learning-button" type="button" :disabled="downloadBusy" :title="downloadBusy ? '现有下载仍在处理中' : '进入原有视频下载流程'" @click="emit('download', record.url)">下载视频</button></div>
          </div>
          <div v-if="busyStates.has(record.subtitle_status)" class="learning-progress" role="status"><Clock3 aria-hidden="true" /><span>{{ subtitleJob?.stage || '等待获取字幕' }}。平台响应可能需要一些时间。</span></div>
          <div v-else-if="record.subtitle_status !== 'ready'" class="learning-alert" role="alert"><p>{{ record.subtitle_error || '字幕获取未完成。' }}</p><p class="learning-muted">没有有效字幕时暂不能总结、生成导图或问答；视频仍可通过下载入口保存。</p><button class="learning-button" type="button" :disabled="creating" @click="createRecord(record!.url, record!.requested_language)">重试获取字幕</button></div>
          <template v-else>
            <div class="learning-source-bar"><span>根据所获字幕整理，未分析视频画面。</span><label v-if="selectedTrack.length > 1">字幕语言 <select aria-label="切换字幕语言" :value="record.language || 'auto'" :disabled="creating || busy" @change="switchLanguage"><option value="auto">自动选择</option><option v-for="track in selectedTrack" :key="track.language" :value="track.language">{{ track.language }} · {{ sourceKind(track.kind) }}</option></select></label></div>
            <p v-for="note in record.notes.filter(n => !n.startsWith('仅根据'))" :key="note" class="learning-muted">{{ note }}</p>
            <div v-if="config && !config.configured" class="learning-config-note"><p>DeepSeek 尚未配置，字幕和视频下载已可使用。</p><details><summary>配置方法</summary><p>在项目根目录的 <code>.env</code> 填写 <code>DEEPSEEK_API_KEY</code>，保存后重启后端。也可使用 <code>.\start-local.ps1 -AskDeepSeekKey</code> 隐藏输入。无需把密钥粘贴到网页或聊天。</p></details></div>
          </template>
          <nav class="learning-tabs" aria-label="学习内容"><button v-for="item in tabs" :id="'tab-' + item.value" :key="item.value" class="learning-tab" :class="{ 'learning-tab-active': tab === item.value }" type="button" :aria-pressed="tab === item.value" @click="tab = item.value"><component :is="item.icon" aria-hidden="true" />{{ item.label }}</button></nav>
          <section class="learning-panel" :aria-labelledby="'tab-' + tab">
            <template v-if="tab === 'summary'">
              <div class="learning-toolbar"><h2>视频摘要</h2><div class="learning-toolbar"><button v-if="summary" class="learning-button" type="button" @click="copySummary">复制</button><a v-if="summary" class="learning-button" :href="'/api/v1/analyses/' + record.id + '/export?format=markdown'" download>导出 Markdown</a><button class="learning-button learning-primary" type="button" :disabled="!transcriptReady || !config?.configured || busy || summaryBusy" @click="generate(summary !== null && record.summary_status === 'ready')">{{ summaryBusy ? '正在总结…' : summary ? (record.summary_status === 'ready' ? '重新生成' : '重试总结') : '生成总结' }}</button></div></div>
              <p class="learning-muted">生成与追问会调用你的 DeepSeek 账户；重新生成也会产生用量。</p>
              <p v-if="summaryBusy" class="learning-progress" role="status">{{ summaryJob?.stage || '等待模型处理' }}</p>
              <div v-if="record.summary_status === 'failed' || record.summary_status === 'interrupted'" class="learning-alert" role="alert">{{ summaryJob?.error || '总结被中断，请手动重试。' }}<p v-if="summary">下方保留上次成功生成的摘要。</p></div>
              <template v-if="summary">
                <article class="summary-overview"><p class="learning-eyebrow">快速总览</p><h3>{{ summary.content.headline }}</h3><p>{{ summary.content.overview }}</p></article>
                <ol class="summary-chapters">
                  <li v-for="(chapter, index) in summary.content.chapters" :key="index"><article><p class="learning-eyebrow">章节 {{ index + 1 }}</p><h3>{{ chapter.title }}</h3><p>{{ chapter.overview }}</p><div class="learning-references"><button v-for="reference in chapter.references" :key="reference.cue_id" class="learning-reference" type="button" :title="reference.text" @click="locate(reference.cue_id)">{{ refLabel(reference) }}</button></div><ul><li v-for="(point, pointIndex) in chapter.points" :key="pointIndex"><p>{{ point.text }}</p><div class="learning-references"><button v-for="reference in point.references" :key="reference.cue_id" class="learning-reference" type="button" :title="reference.text" @click="locate(reference.cue_id)">{{ refLabel(reference) }}</button></div></li></ul></article></li>
                </ol>
                <p class="learning-muted">模型 {{ summary.model }} · {{ new Date(summary.created_at).toLocaleString('zh-CN') }}</p>
              </template>
              <div v-else-if="!summaryBusy" class="learning-empty">获取字幕后点击“生成总结”，查看总览、章节大纲和核心知识要点。</div>
            </template>
            <template v-else-if="tab === 'transcript'">
              <div class="learning-toolbar"><h2>字幕原文</h2><a v-if="transcriptReady" class="learning-button" :href="'/api/v1/analyses/' + record.id + '/export?format=srt'" download>导出 SRT</a></div>
              <form v-if="transcriptReady" class="transcript-search" @submit.prevent="loadTranscript()"><label class="sr-only" for="transcript-search">搜索字幕</label><input id="transcript-search" v-model="search" maxlength="200" type="search" placeholder="搜索原文中的词语" /><button class="learning-button" type="submit">搜索</button><button v-if="search" class="learning-button" type="button" @click="search = ''; loadTranscript()">清除</button></form>
              <p class="learning-muted">字幕保留原语言，平台自动字幕可能存在识别错误。</p>
              <div class="transcript-list"><article v-for="cue in transcript.items" :id="'cue-' + cue.id" :key="cue.id" class="transcript-cue" :class="{ 'cue-highlighted': highlightedCue === cue.id }" tabindex="-1"><span>{{ clock(cue.start) }}–{{ clock(cue.end) }}</span><p>{{ cue.text }}</p></article></div>
              <p v-if="!transcript.items.length" class="learning-empty-small">{{ transcriptReady ? '未找到匹配的字幕片段。' : '暂无有效字幕。' }}</p>
              <div v-if="transcript.total" class="learning-toolbar transcript-pagination"><span>{{ transcript.offset + 1 }}–{{ Math.min(transcript.total, transcript.offset + transcript.limit) }} / {{ transcript.total }} 段</span><div><button class="learning-button" type="button" :disabled="transcript.offset === 0" @click="loadTranscript(Math.max(0, transcript.offset - transcript.limit), '', true)">上一页</button><button class="learning-button" type="button" :disabled="transcript.offset + transcript.limit >= transcript.total" @click="loadTranscript(transcript.offset + transcript.limit, '', true)">下一页</button></div></div>
            </template>
            <template v-else-if="tab === 'mindmap'"><h2>思维导图</h2><MindMapView v-if="summary" :tree="summary.mindmap" @locate="locate" /><div v-else class="learning-empty">生成摘要后，导图会根据同一份章节与要点自动呈现。</div></template>
            <template v-else>
              <div class="learning-toolbar"><h2>针对视频提问</h2><button v-if="messages.length" class="learning-button" type="button" :disabled="busy" @click="confirmation = { kind: 'chat', id: record.id, title: record.title }">清空对话</button></div>
              <p class="learning-muted">回答依据当前字幕；没有信息或需要观看画面时会说明限制。</p>
              <div v-if="!messages.length" class="question-suggestions"><button class="learning-button" type="button" @click="question = '用三个要点概括这个视频的核心知识。'">概括核心知识</button><button class="learning-button" type="button" @click="question = '视频讲了哪些具体方法和适用条件？'">提取方法与条件</button></div>
              <div class="chat-messages" aria-live="polite"><article v-for="message in messages" :key="message.id" class="chat-turn"><div class="chat-question"><p class="learning-eyebrow">我的问题</p><p>{{ message.question }}</p></div><div class="chat-answer"><p class="learning-eyebrow">视频回答</p><template v-if="message.answer"><p>{{ message.answer.answer }}</p><span v-if="message.answer.evidence === 'insufficient'" class="learning-muted">字幕依据不足</span><div class="learning-references"><button v-for="reference in message.answer.references" :key="reference.cue_id" class="learning-reference" type="button" :title="reference.text" @click="locate(reference.cue_id)">{{ refLabel(reference) }}</button></div></template><p v-else-if="busyStates.has(message.status)" role="status">正在根据字幕回答…</p><div v-else class="learning-alert"><p>{{ message.error || '回答未完成，请重试。' }}</p><button class="learning-button" type="button" @click="question = message.question; pendingQuestion = null">重新提问</button></div></div></article></div>
              <form class="chat-form" @submit.prevent="sendQuestion"><label for="video-question">你的问题</label><textarea id="video-question" v-model="question" maxlength="2000" rows="3" placeholder="例如：视频中这个方法有哪些步骤？" :disabled="!transcriptReady || !config?.configured || busy || chatBusy" /><div class="learning-toolbar"><span class="learning-muted">{{ question.length }}/2000 · 将调用 DeepSeek</span><button class="learning-button learning-primary" type="submit" :disabled="!question.trim() || !transcriptReady || !config?.configured || busy || chatBusy">{{ chatBusy ? '等待回答…' : '发送问题' }}</button></div></form>
            </template>
          </section>
          <p v-if="record.usage && record.usage.calls" class="learning-usage">本记录 {{ record.usage.calls }} 次已返回用量的模型请求 · 输入 {{ record.usage.prompt_tokens.toLocaleString() }} / 输出 {{ record.usage.completion_tokens.toLocaleString() }} tokens。费用以 DeepSeek 账单为准。</p>
        </template>
        <div v-else-if="!loading" class="learning-welcome"><BookOpen aria-hidden="true" /><h1>把长视频变成学习笔记</h1><p>从平台字幕开始，生成摘要与思维导图，针对内容继续提问。</p><p class="learning-muted">支持 B 站、抖音和 YouTube。有可提取字幕的视频才能总结；所有学习记录保存在本机。</p></div>
      </section>
    </main>
    <ResultDialog :open="!!confirmation" @close="confirmation = null"><template #title>{{ confirmation?.kind === 'chat' ? '清空视频对话' : '删除学习记录' }}</template><div v-if="confirmation" class="learning-confirm"><p>{{ confirmation.title }}</p><p>{{ confirmation.kind === 'chat' ? '删除该视频的所有本机问答记录，进行中的回答也将停止保存。' : '删除该视频在本机保存的字幕、摘要、导图、问答及中间结果。' }}</p><div class="learning-toolbar"><button class="learning-button" type="button" :disabled="busy" @click="confirmation = null">取消</button><button class="learning-button learning-danger" type="button" :disabled="busy" @click="confirmAction">{{ confirmation.kind === 'chat' ? '确认清空' : '确认删除' }}</button></div></div></ResultDialog>
  </div>
</template>
