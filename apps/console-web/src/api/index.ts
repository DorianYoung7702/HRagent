import type {
  CandidateItem,
  HRPreferenceMemory,
  JobQaProfile,
  LiepinLoginStatus,
  ReplyJudgmentSummaryReport,
  RuntimeSettings,
  SearchIntentOutput,
  ShortlistItem,
  WorkflowEvent,
  WorkflowInfo,
} from '../types'

const API_BASE = import.meta.env.VITE_API_BASE || ''

function formatApiError(text: string, status: number): string {
  try {
    const json = JSON.parse(text) as {
      detail?: string | { message?: string; reason?: string }
    }
    const detail = json.detail
    if (typeof detail === 'string' && detail) return detail
    if (detail && typeof detail === 'object') {
      return detail.message || detail.reason || text || String(status)
    }
  } catch {
    /* fall through */
  }
  return text || String(status)
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...init?.headers },
    ...init,
  })
  if (!res.ok) {
    const text = await res.text()
    throw new Error(formatApiError(text, res.status))
  }
  return res.json() as Promise<T>
}

export function getLiepinLoginStatus(profile = 'hr_default'): Promise<LiepinLoginStatus> {
  return request(`/browser/login/status?profile=${encodeURIComponent(profile)}`)
}

export function clearAndReloginLiepin(profile = 'hr_default'): Promise<LiepinLoginStatus> {
  return request('/browser/login/relogin', {
    method: 'POST',
    body: JSON.stringify({ profile_name: profile }),
  })
}

export function completeLiepinLogin(): Promise<LiepinLoginStatus> {
  return request('/browser/login/complete', { method: 'POST' })
}

export function cancelLiepinLogin(): Promise<LiepinLoginStatus> {
  return request('/browser/login/cancel', { method: 'POST' })
}

export function verifyLiepinLogin(profile = 'hr_default'): Promise<LiepinLoginStatus> {
  return request('/browser/login/verify', {
    method: 'POST',
    body: JSON.stringify({ profile_name: profile }),
  })
}

export type ParseIntentRequest =
  | {
      unified_requirement: string
      search_requirement?: never
      screening_criteria?: never
      position_name?: string
    }
  | {
      unified_requirement?: never
      search_requirement: string
      screening_criteria: string
      position_name?: string
    }

export function parseSearchIntent(body: ParseIntentRequest): Promise<SearchIntentOutput> {
  return request('/workflows/parse-search-intent', {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export interface PlatformStartResult {
  platform: string
  platform_label: string
  workflow_id: string
  status: string
  console_url: string
  message: string
}

export async function parseSearchIntentStream(
  body: ParseIntentRequest,
  handlers: {
    onStatus?: (text: string) => void
    onDelta?: (text: string) => void
  } = {},
): Promise<SearchIntentOutput> {
  const res = await fetch(`${API_BASE}/workflows/parse-search-intent/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) {
    const text = await res.text()
    throw new Error(text || res.statusText)
  }
  if (!res.body) {
    throw new Error('解析流不可用')
  }

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let eventType = ''
  let result: SearchIntentOutput | null = null

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })

    let boundary = buffer.indexOf('\n\n')
    while (boundary !== -1) {
      const block = buffer.slice(0, boundary)
      buffer = buffer.slice(boundary + 2)
      boundary = buffer.indexOf('\n\n')

      eventType = ''
      let dataLine = ''
      for (const line of block.split('\n')) {
        if (line.startsWith('event:')) eventType = line.slice(6).trim()
        else if (line.startsWith('data:')) dataLine = line.slice(5).trim()
      }
      if (!dataLine) continue

      const data = JSON.parse(dataLine) as Record<string, unknown>
      if (eventType === 'status' && typeof data.text === 'string') {
        handlers.onStatus?.(data.text)
      } else if (eventType === 'delta' && typeof data.text === 'string') {
        handlers.onDelta?.(data.text)
      } else if (eventType === 'result') {
        result = data as unknown as SearchIntentOutput
      } else if (eventType === 'error') {
        throw new Error(String(data.message || '解析失败'))
      }
    }
  }

  if (!result) {
    throw new Error('解析未完成')
  }
  return result
}

export function startDemo(body: Record<string, unknown>): Promise<{
  workflow_id: string
  status: string
  console_url: string
  message: string
  platform_results?: PlatformStartResult[]
}> {
  return request('/workflows/demo/liepin-lpt/start', {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export async function startPdfImport(
  body: Record<string, unknown>,
  files: File[],
): Promise<{ workflow_id: string; status: string; console_url: string; message: string }> {
  const form = new FormData()
  form.append('config', JSON.stringify(body))
  for (const file of files) form.append('files', file)
  const res = await fetch(`${API_BASE}/workflows/pdf-import`, { method: 'POST', body: form })
  if (!res.ok) {
    const text = await res.text()
    throw new Error(formatApiError(text, res.status))
  }
  return res.json() as Promise<{ workflow_id: string; status: string; console_url: string; message: string }>
}

export function getPdfImportStatus(id: string): Promise<{
  workflow_id: string
  status: string
  progress: {
    total: number
    processing: number
    completed: number
    duplicate: number
    failed: number
    state: string
    ranking_state: string
    ranking_error: string
  }
}> {
  return request(`/workflows/${id}/pdf-import/status`)
}

export function getPdfImportReport(id: string): Promise<{
  workflow_id: string
  ready: boolean
  report: ReplyJudgmentSummaryReport | null
}> {
  return request(`/workflows/${id}/pdf-import/report`)
}

export function regeneratePdfImportReport(id: string): Promise<{ workflow_id: string; status: string; message: string }> {
  return request(`/workflows/${id}/pdf-import/report/regenerate`, { method: 'POST' })
}

export function initPreferenceMemory(body: {
  current_requirement: string
  parsed_intent?: Record<string, unknown>
  screening_criteria: string
  preset_memory?: HRPreferenceMemory | null
  messages?: Array<{ role: string; content: string }>
}): Promise<HRPreferenceMemory> {
  return request('/workflows/preference-memory/init', {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export function chatPreferenceMemory(body: {
  current_requirement: string
  parsed_intent?: Record<string, unknown>
  screening_criteria: string
  preset_memory?: HRPreferenceMemory | null
  messages: Array<{ role: string; content: string }>
}): Promise<HRPreferenceMemory> {
  return request('/workflows/preference-memory/chat', {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export function getWorkflowPreferenceMemory(id: string): Promise<{
  workflow_id: string
  memory: HRPreferenceMemory
}> {
  return request(`/workflows/${id}/preference-memory`)
}

export function getWorkflow(id: string): Promise<WorkflowInfo> {
  return request(`/workflows/${id}`)
}

export function updateWorkflowRuntimeOptions(
  id: string,
  body: { collect_only?: boolean; im_auto_reply?: boolean },
): Promise<{ workflow_id: string; collect_only: boolean; im_auto_reply: boolean }> {
  return request(`/workflows/${id}/runtime-options`, {
    method: 'PATCH',
    body: JSON.stringify(body),
  })
}

export function pauseWorkflow(id: string): Promise<{ workflow_id: string; paused: boolean }> {
  return request(`/workflows/${id}/pause`, { method: 'POST' })
}

export function resumeWorkflow(id: string): Promise<{ workflow_id: string; paused: boolean }> {
  return request(`/workflows/${id}/resume`, { method: 'POST' })
}

export function getExecutionControl(id: string): Promise<{
  workflow_id: string
  paused: boolean
  global_paused: boolean
  can_pause: boolean
}> {
  return request(`/workflows/${id}/execution-control`)
}

export function pauseExecution(id: string): Promise<{
  workflow_id: string
  paused: boolean
  global_paused: boolean
}> {
  return request(`/workflows/${id}/execution/pause`, { method: 'POST' })
}

export function resumeExecution(id: string): Promise<{
  workflow_id: string
  paused: boolean
  global_paused: boolean
}> {
  return request(`/workflows/${id}/execution/resume`, { method: 'POST' })
}

export function cancelWorkflow(id: string): Promise<{
  workflow_id: string
  cancelled: boolean
  already_stopped?: boolean
  tasks_cancelled?: number
}> {
  return request(`/workflows/${id}/cancel`, { method: 'POST' })
}

export function deleteWorkflow(id: string): Promise<{
  workflow_id: string
  deleted: boolean
  tasks_cancelled?: number
}> {
  return request(`/workflows/${id}`, { method: 'DELETE' })
}

export function listWorkflows(): Promise<WorkflowInfo[]> {
  return request('/workflows')
}

export function listRunningWorkflows(): Promise<WorkflowInfo[]> {
  return request('/workflows/active')
}

/** @deprecated use listRunningWorkflows */
export function listStartingWorkflows(): Promise<WorkflowInfo[]> {
  return listRunningWorkflows()
}

export function getCandidates(id: string): Promise<CandidateItem[]> {
  return request(`/workflows/${id}/candidates`)
}

export function openResumeLibrary(
  workflowId: string,
  snapshotId: string,
): Promise<{
  ok: boolean
  message: string
  matched_name?: string
  folder?: string
  url?: string
}> {
  return request(`/workflows/${workflowId}/candidates/${snapshotId}/resume-library`, {
    method: 'POST',
  })
}

export function getShortlist(id: string): Promise<{
  shortlist_id: string
  selected_count: number
  candidates: ShortlistItem[]
}> {
  return request(`/workflows/${id}/shortlist`)
}

export function getEvents(id: string, since = 0): Promise<{ events: WorkflowEvent[] }> {
  return request(`/workflows/${id}/events?since=${since}`)
}

export function prepareFollowupIm(id: string): Promise<{
  workflow_id: string
  drafts: Array<{
    conversation_id: string
    display_name: string | null
    message_text: string
    reason: string
    round: number
    reused_existing?: boolean
  }>
  count: number
  new_count?: number
  reused_count?: number
}> {
  return request(`/workflows/${id}/followup/im-prepare`, { method: 'POST' })
}

export function sendFollowupIm(id: string, confirmed: boolean): Promise<{ status: string; message?: string }> {
  return request(`/workflows/${id}/followup/im-send`, {
    method: 'POST',
    body: JSON.stringify({ confirmed }),
  })
}

export function updateOutreachMessage(
  messageId: string,
  messageText: string,
): Promise<{ id: string; message_text: string; status: string }> {
  return request(`/outreach_messages/${messageId}`, {
    method: 'PATCH',
    body: JSON.stringify({ message_text: messageText }),
  })
}

export function sendOutreachMessage(messageId: string): Promise<{
  status: string
  message_id: string
  platform_result?: Record<string, unknown>
}> {
  return request(`/outreach_messages/${messageId}/send`, { method: 'POST' })
}

export function startImAutopilot(id: string): Promise<{
  workflow_id: string
  status: string
  message: string
}> {
  return request(`/workflows/${id}/followup/im-autopilot-start`, { method: 'POST' })
}

export function stopImAutopilot(id: string): Promise<{
  workflow_id: string
  status: string
  message: string
}> {
  return request(`/workflows/${id}/followup/im-autopilot-stop`, { method: 'POST' })
}

export function getImAutopilotStatus(id: string): Promise<{
  workflow_id: string
  running: boolean
  stopped: boolean
}> {
  return request(`/workflows/${id}/followup/im-autopilot-status`)
}

export function scanFollowupUnread(id: string): Promise<{ status: string }> {
  return request(`/workflows/${id}/followup/scan-unread`, { method: 'POST' })
}

export function continueFollowup(id: string): Promise<{ status: string }> {
  return request(`/workflows/${id}/followup/continue`, { method: 'POST' })
}

export function requestObserveResume(id: string, confirmed: boolean): Promise<{ status: string }> {
  return request(`/workflows/${id}/observe/im-request-resume`, {
    method: 'POST',
    body: JSON.stringify({ confirmed }),
  })
}

export function listConversations(id: string): Promise<{
  workflow_id: string
  conversations: Array<{
    id: string
    display_name: string | null
    subtitle: string | null
    conversation_type: string
    status: string
    need_resume_request: boolean
    last_agent_reason: string | null
    latest_outbound: string | null
    latest_inbound: string | null
    messages: Array<{
      id?: string
      direction: string
      message_text: string
      status: string
      round: number | null
      extracted_fields?: Record<string, unknown>
    }>
  }>
}> {
  return request(`/workflows/${id}/conversations`)
}

export function syncAndReplyDialogue(id: string): Promise<{
  workflow_id: string
  processed: number
  auto_reply_sent: number
  needs_hr: number
  drafted: number
  skipped_duplicate: number
  failed: number
}> {
  return request(`/workflows/${id}/dialogue/sync-and-reply`, { method: 'POST' })
}

export function draftDialogueReply(conversationId: string): Promise<{
  conversation_id: string
  message_id: string | null
  output: Record<string, unknown>
}> {
  return request(`/conversations/${conversationId}/dialogue/draft`, { method: 'POST' })
}

export function sendDialogueDraft(conversationId: string): Promise<{
  conversation_id: string
  message_id: string
  send: Record<string, unknown>
}> {
  return request(`/conversations/${conversationId}/dialogue/send`, { method: 'POST' })
}

export function getJobQaProfile(id: string): Promise<{
  workflow_id: string
  profile: JobQaProfile
}> {
  return request(`/workflows/${id}/job-qa-profile`)
}

export function updateJobQaProfile(id: string, profile: JobQaProfile): Promise<{
  workflow_id: string
  profile: JobQaProfile
}> {
  return request(`/workflows/${id}/job-qa-profile`, {
    method: 'PUT',
    body: JSON.stringify({ profile }),
  })
}

export function getReplyJudgmentQueue(id: string): Promise<{
  workflow_id: string
  queue: Array<{
    conversation_id: string
    candidate_snapshot_id: string
    display_name: string | null
    status: string
    conversation_type: string
  }>
  count: number
}> {
  return request(`/workflows/${id}/reply-judgment/queue`)
}

export function getReplyJudgmentStatus(id: string): Promise<{
  workflow_id: string
  running: boolean
  phase: string
  total: number
  current_index: number
  current_name: string | null
  processed: number
  enriched: number
  passed: number
  still_followup: number
  excluded: number
  skipped: number
  failed: number
  results: Array<{
    candidate_snapshot_id?: string
    display_name?: string | null
    ok?: boolean
    skipped?: boolean
    updated_level?: string
    followup_passed?: boolean
    summary_for_list?: string
    error?: string
  }>
  report_ready?: boolean
  summary_report?: ReplyJudgmentSummaryReport | null
  report_error?: string | null
  message: string
}> {
  return request(`/workflows/${id}/reply-judgment/status`)
}

export function getReplyJudgmentReport(id: string): Promise<{
  workflow_id: string
  ready: boolean
  report: ReplyJudgmentSummaryReport | null
}> {
  return request(`/workflows/${id}/reply-judgment/report`)
}

export function startReplyJudgment(id: string): Promise<{
  workflow_id: string
  status: string
  message: string
}> {
  return request(`/workflows/${id}/reply-judgment/start`, { method: 'POST' })
}

export function stopReplyJudgment(id: string): Promise<{
  workflow_id: string
  status: string
  message: string
  stopped?: boolean
  was_running?: boolean
}> {
  return request(`/workflows/${id}/reply-judgment/stop`, { method: 'POST' })
}

export function subscribeEvents(
  workflowId: string,
  onEvent: (event: WorkflowEvent) => void,
  onError?: (err: Event) => void,
): EventSource {
  const es = new EventSource(`${API_BASE}/workflows/${workflowId}/events/stream`)
  es.onmessage = (ev) => {
    try {
      const data = JSON.parse(ev.data) as WorkflowEvent
      onEvent(data)
    } catch {
      /* ignore parse errors */
    }
  }
  es.onerror = (err) => onError?.(err)
  return es
}

export function getRuntimeSettings(): Promise<RuntimeSettings> {
  return request('/settings/runtime')
}

export function updateRuntimeSettings(body: {
  deepseek_api_key?: string
  hr_company_name?: string
  deepseek_model?: string
  default_screening_criteria?: string
  default_chat_job_title?: string
  default_collect_parent_group?: string
  default_hr_preference_memory?: HRPreferenceMemory | null
  default_job_qa_profile?: JobQaProfile
}): Promise<RuntimeSettings> {
  return request('/settings/runtime', {
    method: 'PUT',
    body: JSON.stringify(body),
  })
}
