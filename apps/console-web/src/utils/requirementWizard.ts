import type { HRPreferenceMemory } from '../types'

export interface RequirementWizardState {
  jobTitle: string
  jobType: string
  keywords: string
  currentCity: string
  expectedCity: string
  experience: string
  targetCount: number
  degree: string
  schoolTiers: string
  industry: string
  skills: string
  mustHave: string
  quickReject: string
  niceToHave: string
  followup: string
  /** @deprecated 已并入 mustHave，保留仅为兼容旧预设 */
  reject?: string
}

function clean(value: string | number | undefined | null): string {
  return String(value ?? '').trim()
}

function lines(text: string): string[] {
  return clean(text)
    .split(/\r?\n|[；;]/)
    .map((x) => x.trim())
    .filter(Boolean)
}

function numbered(items: string[], fallback: string): string {
  const rows = items.length ? items : [fallback]
  return rows.map((item, idx) => `${idx + 1}. ${item}`).join('\n')
}

export function defaultRequirementWizard(): RequirementWizardState {
  return {
    jobTitle: '',
    jobType: '开发/技术',
    keywords: '',
    currentCity: '',
    expectedCity: '',
    experience: '',
    targetCount: 20,
    degree: '',
    schoolTiers: '',
    industry: '',
    skills: '',
    mustHave: '',
    quickReject: '',
    niceToHave: '',
    followup: '',
  }
}

export function wizardFromPreset(input: {
  label: string
  searchRequirement: string
  screeningCriteria: string
  chatJobTitle?: string
  collectParentGroup?: string
  wizardState?: RequirementWizardState | null
}): RequirementWizardState {
  if (input.wizardState && typeof input.wizardState === 'object') {
    const mergedMust = [input.wizardState.mustHave, input.wizardState.reject]
      .filter(Boolean)
      .join('\n')
    const positionName = input.label.trim()
    return {
      ...defaultRequirementWizard(),
      ...input.wizardState,
      mustHave: mergedMust || input.wizardState.mustHave,
      reject: undefined,
      jobTitle: positionName || input.wizardState.jobTitle?.trim() || '',
      targetCount: Math.max(
        1,
        Math.min(50, Number(input.wizardState.targetCount) || 20),
      ),
    }
  }
  const jobTitle = input.label.trim()
  return {
    ...defaultRequirementWizard(),
    jobTitle,
    keywords: input.searchRequirement,
    mustHave: input.screeningCriteria,
  }
}

export function buildWizardSearchRequirement(input: RequirementWizardState): string {
  const parts = [
    clean(input.jobTitle),
    clean(input.keywords),
    clean(input.industry),
    clean(input.skills),
  ].filter(Boolean)

  const filters = [
    clean(input.currentCity) ? `目前城市=${clean(input.currentCity)}` : '',
    clean(input.expectedCity) ? `期望城市=${clean(input.expectedCity)}` : '',
    clean(input.experience) ? `${clean(input.experience)}经验` : '',
    clean(input.degree) ? clean(input.degree) : '',
    clean(input.schoolTiers) ? `院校要求=${clean(input.schoolTiers)}` : '',
    clean(input.targetCount) ? `处理${Math.max(1, Math.min(50, Number(input.targetCount) || 20))}份简历` : '',
  ].filter(Boolean)

  return [...parts, ...filters].join('，')
}

export function buildWizardScreeningCriteria(input: RequirementWizardState): string {
  const title = clean(input.jobTitle) || '未命名岗位'
  const type = clean(input.jobType) || '通用岗位'
  const skills = lines(input.skills)
  const must = lines([input.mustHave, input.reject].filter(Boolean).join('\n'))
  const quickReject = lines(input.quickReject)
  const nice = lines(input.niceToHave)
  const followup = lines(input.followup)
  const location = [clean(input.currentCity), clean(input.expectedCity)].filter(Boolean).join(' / ')

  const baseMust = [
    clean(input.experience) ? `工作年限符合 ${clean(input.experience)}` : '',
    clean(input.degree) ? `学历达到 ${clean(input.degree)}` : '',
    clean(input.schoolTiers) ? `院校背景满足 ${clean(input.schoolTiers)}` : '',
    clean(input.industry) ? `行业或业务背景匹配：${clean(input.industry)}` : '',
    location ? `城市匹配：${location}` : '',
    ...skills.map((skill) => `具备 ${skill}`),
    ...must,
  ].filter(Boolean)

  return `岗位：${title}
岗位类型：${type}

## 必备
${numbered(baseMust, '请根据岗位描述判断核心能力是否匹配；排除性要求（不要/不得/不考虑）也写在本节。')}

## 快速淘汰
${numbered(quickReject, '命中以下任一明确情形可直接排除；信息不足时转入追问。')}

## 加分
${numbered(nice, '有同类业务经验、稳定履历或更强业务结果可加分，用于简历排序。')}

## 追问
${numbered(followup, '简历未明确但可能满足必备条件时，生成追问问题确认。')}

## 初筛结论规则
- 必备条件大部分明确满足 → 观察
- 必备条件缺失但可通过沟通确认 → 追问
- 命中快速淘汰偏好且简历证据明确 → 排除
- 明确违反必备（含排除性说法）或岗位方向不匹配 → 排除`
}

export function buildWizardPreferenceMemory(input: RequirementWizardState): HRPreferenceMemory {
  const criteria = buildWizardScreeningCriteria(input)
  const location = [clean(input.currentCity), clean(input.expectedCity)].filter(Boolean).join(' / ')
  const mustHave = [
    clean(input.experience) ? `工作年限符合 ${clean(input.experience)}` : '',
    clean(input.degree) ? `学历达到 ${clean(input.degree)}` : '',
    clean(input.schoolTiers) ? `院校背景满足 ${clean(input.schoolTiers)}` : '',
    clean(input.industry) ? `行业或业务背景匹配：${clean(input.industry)}` : '',
    location ? `城市匹配：${location}` : '',
    ...lines(input.skills).map((skill) => `具备 ${skill}`),
    ...lines([input.mustHave, input.reject].filter(Boolean).join('\n')),
  ].filter(Boolean)

  return {
    must_have: mustHave,
    quick_reject_rules: lines(input.quickReject),
    nice_to_have: lines(input.niceToHave),
    reject_rules: [],
    followup_questions: lines(input.followup),
    preference_summary: `按岗位画像生成：${clean(input.jobTitle) || '未命名岗位'}`,
    screening_criteria: criteria,
    assistant_message: '已按当前筛选偏好生成初筛标准。',
    ready: true,
    criteria_version: 1,
  }
}

export function buildWizardUnifiedRequirement(input: RequirementWizardState): string {
  return `${buildWizardSearchRequirement(input)}

【HR偏好】
${buildWizardScreeningCriteria(input)}`
}
