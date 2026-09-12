import type { LptOtherFilters, SearchIntentOutput, WorkflowInfo } from '../types'

type WorkflowConfig = WorkflowInfo['config'] & {
  search_intent?: Partial<SearchIntentOutput>
  requirement_preset?: {
    id?: string
    label?: string
    search_requirement?: string
    screening_criteria?: string
  }
  fetch?: {
    target_count?: number
    collect_parent_group?: string
    search?: Partial<SearchIntentOutput> & {
      keywords?: string
      city?: string
      cities?: string[]
      current_cities?: string[]
      experience?: string
    }
  }
  job?: {
    description?: string
    title?: string
    screening_criteria?: string
  }
}

const OTHER_FILTER_LABELS: Record<keyof LptOtherFilters, string> = {
  activity: '活跃',
  job_seeking: '求职',
  job_hop: '跳槽',
  age: '年龄',
  gender: '性别',
  language: '语言',
  grad_industry: '毕业行业',
  current_industry: '当前行业',
  expected_industry: '期望行业',
}

function otherFilterChips(other?: LptOtherFilters): string[] {
  if (!other) return []
  return (Object.keys(OTHER_FILTER_LABELS) as (keyof LptOtherFilters)[])
    .map((key) => {
      const value = other[key]?.trim()
      if (!value || value === '不限') return ''
      return `${OTHER_FILTER_LABELS[key]}:${value}`
    })
    .filter(Boolean)
}

export function workflowPositionName(wf: WorkflowInfo): string {
  const cfg = wf.config as WorkflowConfig
  return (
    cfg.requirement_preset?.label?.trim() ||
    cfg.job?.title?.trim() ||
    cfg.search_intent?.chat_job_title?.trim() ||
    cfg.fetch?.collect_parent_group?.trim() ||
    wf.name?.trim() ||
    wf.id.slice(0, 8)
  )
}

export function parsedFromWorkflow(wf: WorkflowInfo): SearchIntentOutput | null {
  const cfg = wf.config as WorkflowConfig
  const intent = cfg.search_intent
  const search = cfg.fetch?.search

  const keywords = intent?.keywords || search?.keywords
  if (!keywords && !intent?.parse_summary) {
    return null
  }

  const cities = intent?.cities?.length ? intent.cities : search?.cities?.length ? search.cities : undefined
  const current_cities = intent?.current_cities?.length
    ? intent.current_cities
    : search?.current_cities?.length
      ? search.current_cities
      : []
  const city = cities?.length ? cities.join('、') : intent?.city || search?.city || '深圳'
  const experience = intent?.experience || search?.experience || '3-5年'
  const education = intent?.education || search?.education
  const other_filters = intent?.other_filters || search?.other_filters
  const target_count = intent?.target_count ?? cfg.fetch?.target_count ?? 20
  const name = intent?.name || wf.name || 'AI 筛选任务'
  const screening_criteria =
    intent?.screening_criteria ||
    cfg.requirement_preset?.screening_criteria ||
    cfg.job?.screening_criteria ||
    ''
  const job_description = intent?.job_description || cfg.job?.description || ''
  const chat_job_title =
    cfg.requirement_preset?.label ||
    cfg.job?.title ||
    intent?.chat_job_title ||
    ''
  const search_requirement =
    intent?.search_requirement ||
    cfg.requirement_preset?.search_requirement ||
    ''
  const parse_summary =
    intent?.parse_summary ||
    `已配置猎聘搜索：关键词「${keywords || '—'}」，期望 ${city}，经验 ${experience}，目标 ${target_count} 份简历。`

  return {
    keywords: keywords || '',
    city,
    cities: cities?.length ? cities : city ? [city] : [],
    current_cities,
    experience,
    education,
    other_filters,
    target_count,
    search_requirement,
    screening_criteria,
    job_description,
    chat_job_title,
    name,
    parse_summary,
  }
}

export function formatOtherFilters(other?: LptOtherFilters): string {
  return otherFilterChips(other).join('、')
}

export function saveParsedToStorage(workflowId: string, parsed: SearchIntentOutput) {
  try {
    localStorage.setItem(`hr_agent_parse_${workflowId}`, JSON.stringify(parsed))
  } catch {
    /* ignore */
  }
}

export function loadParsedFromStorage(workflowId: string): SearchIntentOutput | null {
  try {
    const raw = localStorage.getItem(`hr_agent_parse_${workflowId}`)
    if (!raw) return null
    return JSON.parse(raw) as SearchIntentOutput
  } catch {
    return null
  }
}

export function clearParsedFromStorage(workflowId: string) {
  try {
    localStorage.removeItem(`hr_agent_parse_${workflowId}`)
  } catch {
    /* ignore */
  }
}
