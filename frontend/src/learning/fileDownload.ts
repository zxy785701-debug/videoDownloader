export function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.append(link)
  link.click()
  link.remove()
  // Keep the URL alive until the browser has accepted the download.
  setTimeout(() => URL.revokeObjectURL(url), 30_000)
}

export function downloadFilename(disposition: string | null, fallback: string): string {
  const encoded = disposition?.match(/filename\*=UTF-8''([^;]+)/i)?.[1]
  if (encoded) {
    try { return decodeURIComponent(encoded) } catch { /* Use the ASCII fallback below. */ }
  }
  return disposition?.match(/filename="([^"]+)"/i)?.[1] || fallback
}
