export interface LiepinVerifyResult {
  logged_in: boolean
  page_type: string
  url: string
}

export interface LiepinLoginStatus {
  status: 'idle' | 'waiting' | 'verifying' | 'ready' | 'error'
  profile_name: string
  profile_path: string
  profile_cached: boolean
  logged_in: boolean | null
  can_start_task: boolean
  message: string
  error: string
  verify_result: LiepinVerifyResult | null
  hint: string
}

export interface LptEducationFilters {
  degree?: string
  school_tiers?: string[]
}

export interface LptOtherFilters {
  activity?: string
  job_seeking?: string
  job_hop?: string
  age?: string
  gender?: string
  language?: string
  grad_industry?: string
  current_industry?: string
  expected_industry?: string
}

export interface SearchIntentOutput {
  keywords: string
  city: string
  cities?: string[]
  current_cities?: string[]
  experience: string
  education?: LptEducationFilters
  other_filters?: LptOtherFilters
  target_count: number
  search_requirement?: string
  screening_criteria: string
  job_description: string
  chat_job_title?: string
  name: string
  parse_summary: string
}

export interface HRPreferenceMemory {
  must_have: string[]
  quick_reject_rules: string[]
  nice_to_have: string[]
  reject_rules: string[]
  followup_questions: string[]
  preference_summary: string
  screening_criteria: string
  assistant_message: string
  ready: boolean
  criteria_version: number
}

export interface JobQaProfile {
  responsibilities?: string
  work_location?: string
  salary_range?: string
  work_mode?: string
  interview_process?: string
  company_intro?: string
  team_intro?: string
  start_time?: string
  recruiting_status?: string
  custom_notes?: string
}

export interface WorkflowEvent {
  id: number
  ts: string
  level: 'info' | 'success' | 'warn' | 'error'
  category: string
  message: string
  meta?: Record<string, unknown>
}

export interface WorkflowLogSummary {
  event_count: number
  last_message: string
  last_ts?: string | null
  last_level: string
  persisted: boolean
}

export interface WorkflowInfo {
  id: string
  name: string
  status: string
  platform: string
  config: Record<string, unknown>
  error_message?: string | null
  created_at?: string
  updated_at?: string
  log_summary?: WorkflowLogSummary | null
}

export interface CandidateItem {
  id: string
  platform?: string
  display_name: string | null
  current_title: string | null
  current_company?: string | null
  work_years?: number | null
  education?: string | null
  city: string | null
  captured_at?: string | null
  screening: {
    total_score: number | null
    level: string | null
    matched_points: string[]
    gaps: string[]
    missing_info: { field: string; question: string; importance: string }[]
    resume_summary?: string | null
    reason?: string | null
    criteria_analysis?: string | null
    summary_for_list?: string | null
    score_detail?: Record<string, unknown>
  } | null
  metadata?: Record<string, unknown>
}

export interface ShortlistItem {
  rank: number
  score: number | null
  level: string
  candidate_snapshot_id: string
  display_name: string | null
  matched_points: string[]
  missing_info: { field: string; question: string; importance: string }[]
}

export interface ReplySummaryCandidate {
  candidate_snapshot_id: string
  display_name: string | null
  rank: number
  priority: string
  recommendation: string
  risk_points: string[]
  talking_points: string[]
  followup_passed: boolean
  score?: number | null
}

export interface ReplyJudgmentSummaryReport {
  workflow_id: string
  generated_at: string
  ranked_candidates: ReplySummaryCandidate[]
  summary: string
}

export interface RuntimeSettings {
  deepseek_configured: boolean
  deepseek_api_key_masked: string
  hr_company_name: string
  hr_identity_configured: boolean
  deepseek_model: string
  default_screening_criteria?: string
  default_chat_job_title?: string
  default_collect_parent_group?: string
  default_hr_preference_memory?: HRPreferenceMemory | null
  default_job_qa_profile?: JobQaProfile
}
