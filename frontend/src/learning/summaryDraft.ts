export interface SummaryDraftPart { id: number; text: string; stage: string; phase: string; attempt: number; retry_reason?: string }
export interface SummaryDraft { text: string; stage: string; phase: string; parts: SummaryDraftPart[] }
export interface SummarySnapshot { text?: string; stage?: string; phase?: string; parts?: SummaryDraftPart[] }

function retainedText(previous: string, incoming: string) {
  // Empty or older prefix snapshots can arrive on a reconnect. They must not
  // erase text that the user has already read in this same task and attempt.
  return !incoming || previous.startsWith(incoming) ? previous : incoming
}

export function mergeSummaryDraft(previous: SummaryDraft | null, snapshot: SummarySnapshot, defaultStage: string): SummaryDraft {
  const stage = snapshot.stage || defaultStage, phase = snapshot.phase || 'generating'
  const text = typeof snapshot.text === 'string' ? snapshot.text : ''
  const parts = previous?.parts.map(part => ({ ...part })) || []
  if (snapshot.parts?.length) {
    for (const incoming of snapshot.parts) {
      const index = parts.findIndex(part => part.id === incoming.id)
      if (index < 0) parts.push({ ...incoming })
      else parts[index] = { ...incoming, text: retainedText(parts[index]!.text, incoming.text) }
    }
  } else {
    // A running backend may still use the original current-draft-only SSE
    // protocol. Reconstruct stage/attempt history instead of replacing id=1.
    const last = parts.at(-1)
    const nextId = () => Math.max(0, ...parts.map(part => part.id)) + 1
    if (!last) {
      parts.push({ id: nextId(), text, stage, phase, attempt: 1 })
    } else if (!text && ['waiting', 'queued', 'processing'].includes(phase)) {
      // A transient waiting snapshot is not a request to clear existing notes.
    } else if (last.stage !== stage) {
      if (!last.text) Object.assign(last, { text, stage, phase, attempt: 1 })
      else {
        if (last.phase === 'validating') last.phase = 'validated'
        else if (last.phase === 'generating') last.phase = 'finished'
        parts.push({ id: nextId(), text, stage, phase, attempt: 1 })
      }
    } else if (text && last.text && !text.startsWith(last.text) && !last.text.startsWith(text)) {
      // A reordered JSON field or formatted validation snapshot may change the
      // prefix without any model retry. Retain it, but never invent a repair.
      last.phase = 'retained'
      parts.push({ id: nextId(), text, stage, phase, attempt: last.attempt })
    } else {
      last.text = retainedText(last.text, text)
      last.phase = phase
    }
  }
  return { text: parts.at(-1)?.text || text, stage, phase, parts }
}
