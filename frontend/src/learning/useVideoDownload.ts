import { computed, ref } from 'vue'
import type { DeliveryMode, DownloadTask, ModeOption, ParsedVideo } from '../types/video'

const modes: ModeOption[] = [
  { value: 'auto', label: '自动选择', hint: '根据视频选择可用的保存方式' },
  { value: 'server', label: '先处理再保存', hint: '文件准备好后保存到设备' },
  { value: 'redirect', label: '打开源文件链接', hint: '仅部分平台支持' },
]
function message(error: unknown) { return error instanceof Error ? error.message : '请求失败，请稍后重试。' }
async function request(path: string, signal: AbortSignal, body?: object) {
  const response = await fetch(path, { signal, ...(body ? { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) } : {}) })
  const data = await response.json()
  if (!response.ok) throw Object.assign(new Error(typeof data.detail === 'string' ? data.detail : data.detail?.message || '请求未完成，请重试。'), { status: response.status })
  return data
}
export function useVideoDownload() {
  const video = ref<ParsedVideo | null>(null), url = ref(''), format = ref('best'), mode = ref<DeliveryMode>('auto')
  const task = ref<DownloadTask | null>(null), fileUrl = ref(''), parseError = ref(''), downloadError = ref('')
  const parsing = ref(false), starting = ref(false), thumbnailFailed = ref(false)
  let controller = new AbortController(), revision = 0, timer: number | undefined
  const running = computed(() => ['pending', 'processing'].includes(task.value?.status || ''))
  const locked = computed(() => starting.value || running.value)
  const availableModes = computed(() => /youtube|bilibili|douyin|mgtv|mango/i.test(video.value?.extractor || '') || /(?:youtube\.com|youtu\.be|bilibili\.com|b23\.tv|douyin\.com|iesdouyin\.com|mgtv\.com)/i.test(new URL(url.value || 'https://localhost').hostname) ? modes.filter(m => m.value !== 'redirect') : modes)
  const selection = computed(() => video.value?.formats.find(f => f.format_id === format.value)?.label || '最佳画质')
  const progress = computed(() => Math.round(Math.max(0, Math.min(100, task.value?.progress || 0))))
  function reset() {
    if (locked.value) return false
    controller.abort(); controller = new AbortController(); revision++; window.clearTimeout(timer)
    video.value = null; url.value = ''; task.value = null; fileUrl.value = ''; parseError.value = ''; downloadError.value = ''; parsing.value = false; thumbnailFailed.value = false
    return true
  }
  async function parse(source: string) {
    if (locked.value || parsing.value || !reset()) return false
    const expected = revision, submitted = source.trim()
    if (!submitted) { parseError.value = '先粘贴一个视频链接。'; return false }
    parsing.value = true
    try {
      const data = await request('/api/v1/parse', controller.signal, { url: submitted }) as ParsedVideo
      if (expected !== revision) return false
      video.value = data; url.value = submitted; format.value = data.formats[0]?.format_id || 'best'
      if (!availableModes.value.some(m => m.value === mode.value)) mode.value = 'auto'
      return true
    } catch (error) { if (expected === revision && !controller.signal.aborted) parseError.value = message(error); return false }
    finally { if (expected === revision) parsing.value = false }
  }
  async function poll(statusUrl: string, downloadUrl: string, expected: number) {
    if (expected !== revision || !running.value) return
    try {
      const data = await request(statusUrl, controller.signal) as DownloadTask
      if (expected !== revision) return
      task.value = data; downloadError.value = ''
      if (data.status === 'ready') fileUrl.value = downloadUrl
      if (data.status === 'failed') downloadError.value = data.error || '下载未完成。'
    } catch (error) {
      if (expected !== revision || controller.signal.aborted) return
      if ([404, 410].includes((error as { status?: number }).status || 0)) {
        if (task.value) task.value = { ...task.value, status: 'failed' }
        downloadError.value = message(error)
        return
      }
      downloadError.value = message(error) + ' 正在自动恢复状态更新。'
    }
    if (expected === revision && running.value) timer = window.setTimeout(() => void poll(statusUrl, downloadUrl, expected), downloadError.value ? 2500 : 900)
  }
  async function start() {
    if (!video.value || locked.value) return
    const expected = revision, submitted = { url: url.value, format_id: format.value, delivery_mode: mode.value }
    starting.value = true; task.value = null; fileUrl.value = ''; downloadError.value = ''
    try {
      const data = await request('/api/v1/downloads', controller.signal, submitted)
      if (expected !== revision) return
      task.value = { task_id: data.task_id, status: data.status, delivery_mode: submitted.delivery_mode, progress: null, filename: null, error: null, expires_at: '' }
      void poll(data.status_url, data.download_url, expected)
    } catch (error) { if (expected === revision && !controller.signal.aborted) downloadError.value = message(error) }
    finally { if (expected === revision) starting.value = false }
  }
  function dispose() { controller.abort(); revision++; window.clearTimeout(timer) }
  return { video, url, format, mode, task, fileUrl, parseError, downloadError, parsing, starting, thumbnailFailed, running, locked, availableModes, selection, progress, reset, parse, start, dispose }
}
