export interface LearningEvent { event: string; data: unknown }

// Decode UTF-8 and SSE independently of network packet boundaries. The API
// sends complete snapshots so reconnecting replaces rather than repeats text.
export async function readLearningStream(path: string, onEvent: (event: LearningEvent) => void, signal: AbortSignal) {
  const response = await fetch('/api/v1' + path, { signal, headers: { Accept: 'text/event-stream' } })
  if (!response.ok) {
    const body = await response.json().catch(() => null)
    throw new Error(typeof body?.detail === 'string' ? body.detail : body?.detail?.message || '流式连接暂不可用。')
  }
  if (!response.headers.get('Content-Type')?.startsWith('text/event-stream') || !response.body) throw new Error('后端未返回流式结果。')
  const reader = response.body.getReader(), decoder = new TextDecoder()
  let buffer = '', event = 'message', data: string[] = [], terminal = false
  function line(text: string) {
    if (!text) {
      if (data.length) {
        const payload = JSON.parse(data.join('\n'))
        onEvent({ event, data: payload })
        if (['complete', 'failed', 'removed'].includes(event)) terminal = true
      }
      event = 'message'; data = []
    } else if (text.startsWith('event:')) event = text.slice(6).trim()
    else if (text.startsWith('data:')) data.push(text.slice(5).replace(/^ /, ''))
  }
  try {
    while (!terminal) {
      const part = await reader.read()
      buffer += decoder.decode(part.value, { stream: !part.done })
      if (buffer.length + data.reduce((n, item) => n + item.length, 0) > 2 * 1024 * 1024) throw new Error('流式消息过大，请刷新查看已保存结果。')
      let end: number
      while ((end = buffer.indexOf('\n')) >= 0) {
        line(buffer.slice(0, end).replace(/\r$/, ''))
        buffer = buffer.slice(end + 1)
        if (terminal) return
      }
      if (part.done) break
    }
    if (!terminal) throw new Error('流式连接已中断。')
  } finally {
    await reader.cancel().catch(() => {})
    reader.releaseLock()
  }
}

// Keep the existing question stream entry point for callers and regression tests.
export const readChatStream = readLearningStream
