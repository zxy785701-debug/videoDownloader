export async function learningApi<T>(path: string, options: RequestInit = {}, signal?: AbortSignal): Promise<T> {
  const response = await fetch('/api/v1' + path, {
    ...options, signal,
    headers: { ...(options.body ? { 'Content-Type': 'application/json' } : {}), ...options.headers },
  })
  if (response.status === 204) return undefined as T
  const result = await response.json()
  if (!response.ok) {
    const detail = result.detail
    throw new Error(typeof detail === 'string' ? detail : detail?.message || '请求未完成，请检查输入或稍后重试。')
  }
  return result as T
}

export function clock(seconds: number) {
  const total = Math.max(0, Math.floor(seconds))
  const hours = Math.floor(total / 3600)
  const minutes = Math.floor(total % 3600 / 60)
  const remaining = total % 60
  return (hours ? String(hours).padStart(2, '0') + ':' : '') + String(minutes).padStart(2, '0') + ':' + String(remaining).padStart(2, '0')
}

export function sourceKind(kind: string | null) {
  return ({ manual: '人工字幕', automatic: '自动字幕', unknown: '平台字幕（类型未标明）' } as Record<string, string>)[kind || ''] || '尚未获取'
}
