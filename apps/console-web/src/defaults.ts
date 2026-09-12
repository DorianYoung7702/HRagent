import type { HRPreferenceMemory, JobQaProfile } from './types'
import type { RequirementWizardState } from './utils/requirementWizard'

export type PresetInputMode = 'wizard' | 'unified' | 'split'
export type PresetPlatformKey = 'liepin' | 'boss'

export interface JobPreset {
  id: string
  label: string
  searchRequirement: string
  screeningCriteria: string
  chatJobTitle?: string
  collectParentGroup?: string
  preferenceMemory?: HRPreferenceMemory | null
  jobQaProfile?: JobQaProfile | null
  unifiedRequirement?: string
  inputMode?: PresetInputMode
  wizardState?: RequirementWizardState | null
  collectOnly?: boolean
  imReviewRequired?: boolean
  platforms?: PresetPlatformKey[]
}

export function presetToUnified(preset: JobPreset): string {
  return `${preset.searchRequirement}\n\n【HR偏好】\n${preset.screeningCriteria}`
}

// Fictional examples for first-time setup; saved user presets are never overwritten.
export const BUILTIN_JOB_PRESETS: JobPreset[] = [
  {
    id: 'example_python_developer',
    label: 'Python 开发工程师（示例）',
    searchRequirement: 'Python 开发工程师，2年以上开发经验，处理20份简历',
    screeningCriteria: `岗位：Python 开发工程师（虚构示例，请按实际岗位修改）

## 必备
1. 有 Python 服务端项目开发经验
2. 能说明自己在项目中的职责与技术方案

## 快速淘汰
1. 明确表示不考虑软件开发岗位

## 加分
1. 有自动化测试、数据库或 API 设计经验

## 追问
1. 项目职责不明确时，确认个人负责的模块和交付成果

## 初筛结论规则
- 证据满足岗位要求：观察
- 信息不足，需要确认：追问
- 有明确不匹配证据：排除`,
    jobQaProfile: null,
    preferenceMemory: null,
    inputMode: 'split',
    platforms: ['liepin'],
    imReviewRequired: true,
  },
  {
    id: 'example_account_manager',
    label: '客户经理（示例）',
    searchRequirement: '客户经理，企业客户销售经验，处理20份简历',
    screeningCriteria: `岗位：客户经理（虚构示例，请按实际岗位修改）

## 必备
1. 有企业客户沟通和销售项目跟进经验

## 加分
1. 能说明客户开发方法与可核实的项目成果

## 追问
1. 客户类型、个人职责或业绩口径不明确时进行确认

## 初筛结论规则
- 证据满足岗位要求：观察
- 信息不足，需要确认：追问
- 有明确不匹配证据：排除`,
    jobQaProfile: null,
    preferenceMemory: null,
    inputMode: 'split',
    platforms: ['liepin'],
    imReviewRequired: true,
  },
]

/** @deprecated Use loadJobPresets() to preserve user configuration. */
export const JOB_PRESETS = BUILTIN_JOB_PRESETS
export const DEFAULT_PRESET_ID = 'example_python_developer'
const defaultPreset = BUILTIN_JOB_PRESETS[0]
export const DEFAULT_SEARCH_REQUIREMENT = defaultPreset.searchRequirement
export const DEFAULT_SCREENING_CRITERIA = defaultPreset.screeningCriteria
