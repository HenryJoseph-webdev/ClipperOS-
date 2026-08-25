export type Platform = 'youtube' | 'twitch' | 'kick' | 'unknown'

export type Job = {
  id: string
  type: string
  status: 'running' | 'done' | 'error' | string
  message: string
  progress: number
  result?: Record<string, unknown> | null
  error?: string | null
  error_kind?: string | null
  error_status?: number | null
  detail?: string | null
  created_at?: string
}

export type HistoryEntry = {
  time: string
  kind: string
  platform: string
  name: string
  url: string
  raw: string
}

export type TranscriptResult = {
  video_id: string
  platform: string
  word_count: number
  file_path?: string
  title?: string
  preview?: string
  cached?: boolean
}

export type ClipResult = {
  rank: number
  start: string
  end: string
  title: string
  reason: string
  score: number
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, init)
  const body = await response.json().catch(() => ({})) as { error?: string; message?: string }
  if (!response.ok) throw new Error(body.error || body.message || `Request failed (${response.status})`)
  return body as T
}

const json = (body: unknown): RequestInit => ({
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
})

export function detectPlatform(url: string) {
  return request<{ platform: Platform }>('/api/detect', json({ url }))
}

export function startFullDownload(body: { url: string; filename: string; quality: string }) {
  return request<{ job_id: string }>('/api/download/full', json(body))
}

export function startClipDownload(body: { url: string; filename: string; quality: string; start: string; end: string }) {
  return request<{ job_id: string }>('/api/download/clip', json(body))
}

export function startAudioDownload(body: { url: string; filename: string; format: string }) {
  return request<{ job_id: string }>('/api/download/audio', json(body))
}

export function getJob(id: string) {
  return request<Job>(`/api/job/${encodeURIComponent(id)}`)
}

export function getJobs() {
  return request<Job[]>('/api/jobs')
}

export function getHistory() {
  return request<HistoryEntry[]>('/api/history')
}

export function openFolder(path: string) {
  return request<{ ok: boolean }>('/api/open-folder', json({ path }))
}

// Triggers a real browser download for a finished job. The browser (not the
// server) decides where the file lands — normally the user's own default
// Downloads folder — which is what we want for testers on other machines.
export async function downloadJobFile(jobId: string) {
  const response = await fetch(`/api/download/file/${encodeURIComponent(jobId)}`)
  if (!response.ok) {
    const body = await response.json().catch(() => ({})) as { error?: string; message?: string }
    throw new Error(body.error || body.message || `Download failed (${response.status})`)
  }

  const blob = await response.blob()
  const disposition = response.headers.get('Content-Disposition') || ''
  const encodedName = disposition.match(/filename\*=UTF-8''([^;]+)/i)?.[1]
  const plainName = disposition.match(/filename="?([^";]+)"?/i)?.[1]
  let filename = encodedName || plainName || `clipperos-${jobId}.mp4`
  try { filename = decodeURIComponent(filename) } catch { /* Keep the header value. */ }
  filename = filename.split(/[\\/]/).pop() || `clipperos-${jobId}.mp4`

  const objectUrl = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = objectUrl
  link.download = filename
  link.rel = 'noopener'
  document.body.appendChild(link)
  link.click()
  link.remove()
  window.setTimeout(() => URL.revokeObjectURL(objectUrl), 1000)
}

export function startTranscript(url: string) {
  return request<{ job_id: string }>('/api/transcript', json({ url }))
}

export function startAnalysis(url: string, category: string) {
  return request<{ job_id: string }>('/api/analyze', json({ url, category }))
}

export async function pollJob(id: string, onUpdate?: (job: Job) => void): Promise<Job> {
  while (true) {
    const job = await getJob(id)
    onUpdate?.(job)
    if (job.status === 'done' || job.status === 'error') return job
    await new Promise(resolve => window.setTimeout(resolve, 800))
  }
}
