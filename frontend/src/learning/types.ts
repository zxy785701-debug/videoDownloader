export interface Cue { id: string; start: number; end: number; text: string }
export interface Reference { cue_id: string; start: number; end: number; text: string }
export interface Track { language: string; kind: string }
export interface Job { id: string; kind: string; status: string; stage: string; error: string | null; error_code: string | null }
export interface Usage { calls: number; prompt_tokens: number; completion_tokens: number; prompt_cache_hit_tokens: number }
export interface Analysis {
  id: string; url: string; platform: string; requested_language: string
  title: string; duration: number | null; source_id: string | null
  language: string | null; track_kind: string | null; tracks: Track[]; notes: string[]
  subtitle_status: string; subtitle_error: string | null; subtitle_error_code: string | null
  summary_status: string; created_at: string; updated_at: string
  jobs?: Job[]; usage?: Usage
}
export interface Point { text: string; cue_ids: string[]; references: Reference[] }
export interface Chapter { title: string; overview: string; cue_ids: string[]; references: Reference[]; points: Point[] }
export interface SummaryContent { headline: string; overview: string; chapters: Chapter[] }
export interface MapNode { id: string; text: string; cue_ids: string[]; children: MapNode[] }
export interface SummaryVersion { id: string; model: string; prompt_version: string; created_at: string; content: SummaryContent; mindmap: MapNode }
export interface SummaryResponse { status: string; summary: SummaryVersion | null; usage: Usage }
export interface Answer { answer: string; cue_ids: string[]; evidence: 'supported' | 'insufficient'; references: Reference[] }
export interface Message { id: string; question: string; answer: Answer | null; status: string; error: string | null; error_code: string | null }
export interface AIConfig { configured: boolean; model: string; max_duration: number; max_characters: number; firefox_subtitle_session: boolean; summary_stream_version?: number; auto_summary_version?: number }
export interface Page<T> { items: T[]; total: number }
export interface TranscriptPage extends Page<Cue> { offset: number; limit: number }
