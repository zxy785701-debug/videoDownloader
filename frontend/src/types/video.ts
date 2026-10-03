export type DeliveryMode = 'auto' | 'server' | 'redirect'
export type TaskStatus = 'pending' | 'processing' | 'ready' | 'failed'

export interface VideoFormat {
  format_id: string
  label: string
  ext: string | null
  resolution: string | null
  filesize: number | null
  fps: number | null
}

export interface ParsedVideo {
  title: string
  extractor: string | null
  thumbnail: string | null
  duration: number | null
  formats: VideoFormat[]
}

export interface DownloadTask {
  task_id: string
  status: TaskStatus
  delivery_mode: DeliveryMode
  progress: number | null
  filename: string | null
  error: string | null
  expires_at: string
}

export interface ModeOption { value: DeliveryMode; label: string; hint: string }
