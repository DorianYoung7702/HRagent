import { BUILTIN_JOB_PRESETS, type JobPreset, presetToUnified } from '../defaults'
import type { HRPreferenceMemory } from '../types'

export type PresetInputMode = 'wizard' | 'unified' | 'split'
export type PresetPlatformKey = 'liepin' | 'boss'

export type SavedJobPreset = JobPreset & {
  createdAt?: string
  updatedAt?: string
  preferenceMemory?: HRPreferenceMemory | null
}

export type PresetPersistPayload = Partial<
  Omit<JobPreset, 'id' | 'label'>
> & {
  preferenceMemory?: HRPreferenceMemory | null
}

const STORAGE_KEY = 'hr_agent_job_presets_v1'
const ACTIVE_KEY = 'hr_agent_active_preset_id'

function newId(): string {
  return `preset_${Date.now()}_${Math.random().toString(36).slice(2, 9)}`
}

/** 主页筛选需求卡片名称 = 开聊选岗名（收藏文件夹单独填写） */
export function resolvePresetPositionName(
  preset: Pick<JobPreset, 'label'> | null | undefined,
): string {
  return preset?.label?.trim() || ''
}

function normalizePreset(preset: SavedJobPreset): SavedJobPreset {
  const position = resolvePresetPositionName(preset)
  return {
    ...preset,
    chatJobTitle: preset.chatJobTitle?.trim() || position,
    collectParentGroup: preset.collectParentGroup?.trim() || '',
  }
}

/** 把新增内置预设合并进已有 localStorage，避免老用户看不到新 JD 预设 */
function mergeBuiltinPresets(existing: SavedJobPreset[]): SavedJobPreset[] {
  const byId = new Map(existing.map((p) => [p.id, normalizePreset(p)]))
  const now = new Date().toISOString()
  let changed = false
  for (const builtin of BUILTIN_JOB_PRESETS) {
    const current = byId.get(builtin.id)
    if (!current) {
      byId.set(builtin.id, { ...builtin, createdAt: now, updatedAt: now })
      changed = true
      continue
    }
    // 已存在的岗位预设属于用户数据。内置预设仅补充缺失项，不能覆盖 HR 已保存的筛选偏好。
  }
  const merged = Array.from(byId.values())
  if (changed) saveJobPresets(merged)
  return merged
}

export function loadJobPresets(): SavedJobPreset[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (raw) {
      const parsed = JSON.parse(raw) as SavedJobPreset[]
      if (Array.isArray(parsed)) {
        return mergeBuiltinPresets(parsed.map(normalizePreset))
      }
    }
  } catch {
    /* ignore */
  }
  const seeded = BUILTIN_JOB_PRESETS.map((p) => ({
    ...p,
    createdAt: new Date().toISOString(),
  }))
  saveJobPresets(seeded)
  return seeded
}

export function saveJobPresets(presets: SavedJobPreset[]): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(presets))
  } catch {
    /* ignore */
  }
}

export function loadActivePresetId(): string | null {
  try {
    return localStorage.getItem(ACTIVE_KEY)
  } catch {
    return null
  }
}

export function saveActivePresetId(id: string | null): void {
  try {
    if (id) localStorage.setItem(ACTIVE_KEY, id)
    else localStorage.removeItem(ACTIVE_KEY)
  } catch {
    /* ignore */
  }
}

export function addJobPreset(input: Omit<JobPreset, 'id'>): SavedJobPreset {
  const now = new Date().toISOString()
  const preset: SavedJobPreset = {
    id: newId(),
    ...input,
    createdAt: now,
    updatedAt: now,
  }
  const presets = loadJobPresets()
  presets.push(preset)
  saveJobPresets(presets)
  return preset
}

export function updateJobPreset(
  id: string,
  patch: Partial<Omit<JobPreset, 'id'>>,
): SavedJobPreset | null {
  const presets = loadJobPresets()
  const idx = presets.findIndex((p) => p.id === id)
  if (idx < 0) return null
  presets[idx] = {
    ...presets[idx],
    ...patch,
    updatedAt: new Date().toISOString(),
  }
  saveJobPresets(presets)
  return presets[idx]
}

export function deleteJobPreset(id: string): SavedJobPreset[] {
  const presets = loadJobPresets().filter((p) => p.id !== id)
  saveJobPresets(presets)
  return presets
}

export function persistJobPreset(id: string, patch: PresetPersistPayload): SavedJobPreset | null {
  return updateJobPreset(id, patch)
}

export function emptyFormDefaults() {
  return {
    unifiedRequirement: '',
    searchRequirement: '',
    screeningCriteria: '',
  }
}

export function formFromPreset(preset: JobPreset) {
  const unified =
    preset.unifiedRequirement?.trim() ||
    presetToUnified(preset)
  return {
    unifiedRequirement: unified,
    searchRequirement: preset.searchRequirement,
    screeningCriteria: preset.screeningCriteria,
    inputMode: preset.inputMode ?? 'wizard',
    collectOnly: preset.collectOnly ?? false,
    imReviewRequired: preset.imReviewRequired ?? false,
    platforms: preset.platforms?.length ? [...preset.platforms] : undefined,
    chatJobTitle: preset.chatJobTitle ?? '',
    collectParentGroup: preset.collectParentGroup ?? '',
  }
}
