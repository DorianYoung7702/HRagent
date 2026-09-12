<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import {
  addJobPreset,
  deleteJobPreset,
  emptyFormDefaults,
  formFromPreset,
  loadActivePresetId,
  loadJobPresets,
  persistJobPreset,
  resolvePresetPositionName,
  saveActivePresetId,
  updateJobPreset,
  type PresetInputMode,
  type PresetPlatformKey,
  type SavedJobPreset,
} from '../utils/jobPresets'
import { getRuntimeSettings } from '../api'
import type { HRPreferenceMemory, JobQaProfile } from '../types'
import {
  buildWizardScreeningCriteria,
  buildWizardPreferenceMemory,
  buildWizardSearchRequirement,
  defaultRequirementWizard,
  wizardFromPreset,
  type RequirementWizardState,
} from '../utils/requirementWizard'
import OutreachModePicker from './OutreachModePicker.vue'

defineProps<{ loginReady?: boolean; pdfImportReady?: boolean }>()

export type InputMode = PresetInputMode
export type PlatformKey = PresetPlatformKey

type StartMeta = {
  platforms: PlatformKey[]
  collect_only?: boolean
  im_review_required?: boolean
  preset_id?: string
  preset_label?: string
  chat_job_title?: string
  collect_parent_group?: string
  preference_memory?: HRPreferenceMemory | null
  job_qa_profile?: JobQaProfile | null
  input_mode?: InputMode
  wizard_state?: RequirementWizardState | null
}

export type StartPayload = (
  | {
      mode: 'unified'
      unified_requirement: string
    }
  | {
      mode: 'split'
      search_requirement: string
      screening_criteria: string
    }
  ) &
  StartMeta

const emit = defineEmits<{
  (e: 'start', payload: StartPayload): void
  (e: 'pdf-import', payload: StartPayload, files: File[]): void
}>()

const INPUT_MODE_KEY = 'hr_agent_input_mode'
const PLATFORM_KEY = 'hr_agent_start_platforms'
const DEFAULT_PLATFORMS: PlatformKey[] = ['liepin', 'boss']
const PLATFORM_OPTIONS: Array<{ key: PlatformKey; label: string; hint: string }> = [
  { key: 'liepin', label: '猎聘 LPT', hint: '现有抓取与初筛流程' },
  { key: 'boss', label: 'BOSS 直聘', hint: '共用解析设定，并行执行入口' },
]

function loadInputMode(): InputMode {
  try {
    const v = localStorage.getItem(INPUT_MODE_KEY)
    if (v === 'wizard') return 'wizard'
    if (v === 'split') return 'split'
    if (v === 'unified') return 'unified'
    return 'wizard'
  } catch {
    return 'wizard'
  }
}

function loadPlatforms(): PlatformKey[] {
  try {
    const raw = JSON.parse(localStorage.getItem(PLATFORM_KEY) || '[]') as string[]
    const valid = raw.filter((v): v is PlatformKey => v === 'liepin' || v === 'boss')
    return valid.length ? Array.from(new Set(valid)) : [...DEFAULT_PLATFORMS]
  } catch {
    return [...DEFAULT_PLATFORMS]
  }
}

const inputMode = ref<InputMode>(loadInputMode())
const selectedPlatforms = ref<PlatformKey[]>(loadPlatforms())
const presets = ref<SavedJobPreset[]>([])
const activePresetId = ref<string | null>(null)
const unifiedRequirement = ref('')
const searchRequirement = ref('')
const screeningCriteria = ref('')
const wizard = ref(defaultRequirementWizard())
const collectOnly = ref(false)
const imReviewRequired = ref(false)
const autoReplyIm = computed({
  get: () => !imReviewRequired.value,
  set: (value: boolean) => {
    imReviewRequired.value = !value
  },
})
const collectFolderName = ref('')
const jobQaProfile = ref<JobQaProfile>({})
const suppressPresetPersist = ref(false)
const editingPresetId = ref<string | null>(null)
const editingPresetLabel = ref('')
const pdfFileInput = ref<HTMLInputElement | null>(null)

const showPresetDialog = ref(false)
const dialogLabel = ref('')
const dialogSearch = ref('')
const dialogCriteria = ref('')
const dialogJobQaProfile = ref<JobQaProfile>({})

const wizardSearchRequirement = computed(() => buildWizardSearchRequirement(wizard.value))
const wizardScreeningCriteria = computed(() => buildWizardScreeningCriteria(wizard.value))

watch(inputMode, (mode) => {
  try {
    localStorage.setItem(INPUT_MODE_KEY, mode)
  } catch {
    /* ignore */
  }
  persistActivePresetFields({ inputMode: mode })
})

watch(
  selectedPlatforms,
  (platforms) => {
    try {
      localStorage.setItem(PLATFORM_KEY, JSON.stringify(platforms))
    } catch {
      /* ignore */
    }
    persistActivePresetFields({ platforms: [...platforms] })
  },
  { deep: true },
)

function togglePlatform(platform: PlatformKey) {
  if (selectedPlatforms.value.includes(platform)) {
    if (selectedPlatforms.value.length <= 1) return
    selectedPlatforms.value = selectedPlatforms.value.filter((p) => p !== platform)
  } else {
    selectedPlatforms.value = [...selectedPlatforms.value, platform]
  }
}

function activePreset(): SavedJobPreset | null {
  if (!activePresetId.value) return null
  return presets.value.find((p) => p.id === activePresetId.value) ?? null
}

function resolvePositionName(): string {
  return resolvePresetPositionName(activePreset())
}

function normalizeJobQaProfile(profile?: JobQaProfile | null): JobQaProfile {
  return {
    responsibilities: profile?.responsibilities || '',
    work_location: profile?.work_location || '',
    salary_range: profile?.salary_range || '',
    work_mode: profile?.work_mode || '',
    interview_process: profile?.interview_process || '',
    company_intro: profile?.company_intro || '',
    team_intro: profile?.team_intro || '',
    start_time: profile?.start_time || '',
    recruiting_status: profile?.recruiting_status || '',
    custom_notes: profile?.custom_notes || '',
  }
}

function persistActivePresetFields(patch: Parameters<typeof persistJobPreset>[1]) {
  if (suppressPresetPersist.value || !activePresetId.value) return
  persistJobPreset(activePresetId.value, patch)
  presets.value = loadJobPresets()
}

function buildActivePresetSnapshot(): Parameters<typeof persistJobPreset>[1] {
  const preset = activePreset()
  const positionNameValue = resolvePositionName()
  const generatedSearch =
    inputMode.value === 'wizard'
      ? wizardSearchRequirement.value
      : searchRequirement.value.trim()
  const generatedCriteria =
    inputMode.value === 'wizard'
      ? wizardScreeningCriteria.value
      : screeningCriteria.value.trim()

  return {
    searchRequirement: generatedSearch,
    screeningCriteria: generatedCriteria,
    unifiedRequirement:
      inputMode.value === 'unified'
        ? unifiedRequirement.value.trim()
        : preset?.unifiedRequirement || '',
    chatJobTitle: positionNameValue,
    collectParentGroup: collectFolderName.value.trim(),
    inputMode: inputMode.value,
    wizardState:
      inputMode.value === 'wizard'
        ? { ...wizard.value }
        : preset?.wizardState ?? null,
    collectOnly: collectOnly.value,
    imReviewRequired: imReviewRequired.value,
    platforms: [...selectedPlatforms.value],
    jobQaProfile: normalizeJobQaProfile(jobQaProfile.value),
    preferenceMemory:
      inputMode.value === 'wizard'
        ? buildWizardPreferenceMemory(wizard.value)
        : preset?.preferenceMemory ?? null,
  }
}

function syncActivePresetFromForm() {
  persistActivePresetFields(buildActivePresetSnapshot())
}

function applyPreset(id: string) {
  const preset = presets.value.find((p) => p.id === id)
  if (!preset) return
  suppressPresetPersist.value = true
  activePresetId.value = id
  saveActivePresetId(id)
  const form = formFromPreset(preset)
  if (form.inputMode) {
    inputMode.value = form.inputMode
  }
  unifiedRequirement.value = form.unifiedRequirement
  searchRequirement.value = form.searchRequirement
  screeningCriteria.value = form.screeningCriteria
  wizard.value = wizardFromPreset({
    label: preset.label,
    searchRequirement: preset.searchRequirement,
    screeningCriteria: preset.screeningCriteria,
    chatJobTitle: preset.chatJobTitle,
    collectParentGroup: preset.collectParentGroup,
    wizardState: preset.wizardState,
  })
  jobQaProfile.value = normalizeJobQaProfile(preset.jobQaProfile)
  collectFolderName.value = preset.collectParentGroup?.trim() || ''
  collectOnly.value = form.collectOnly ?? false
  imReviewRequired.value = form.imReviewRequired ?? false
  if (form.platforms?.length) {
    selectedPlatforms.value = form.platforms.filter(
      (p): p is PlatformKey => p === 'liepin' || p === 'boss',
    )
    if (!selectedPlatforms.value.length) {
      selectedPlatforms.value = [...DEFAULT_PLATFORMS]
    }
  }
  window.setTimeout(() => {
    suppressPresetPersist.value = false
  }, 0)
}

function applyEmptyForm() {
  suppressPresetPersist.value = true
  activePresetId.value = null
  saveActivePresetId(null)
  const empty = emptyFormDefaults()
  unifiedRequirement.value = empty.unifiedRequirement
  searchRequirement.value = empty.searchRequirement
  screeningCriteria.value = empty.screeningCriteria
  wizard.value = defaultRequirementWizard()
  jobQaProfile.value = normalizeJobQaProfile(null)
  collectFolderName.value = ''
  window.setTimeout(() => {
    suppressPresetPersist.value = false
  }, 0)
}

async function applyRuntimeDefaultsIfAvailable() {
  try {
    const runtime = await getRuntimeSettings()
    suppressPresetPersist.value = true
    if (runtime.default_screening_criteria && !screeningCriteria.value.trim()) {
      screeningCriteria.value = runtime.default_screening_criteria
      wizard.value.mustHave = runtime.default_screening_criteria
    }
    if (runtime.default_collect_parent_group && !collectFolderName.value.trim()) {
      collectFolderName.value = runtime.default_collect_parent_group
    }
  } catch {
    /* defaults are optional */
  } finally {
    window.setTimeout(() => {
      suppressPresetPersist.value = false
    }, 0)
  }
}

watch(
  jobQaProfile,
  (profile) => {
    persistActivePresetFields({
      jobQaProfile: normalizeJobQaProfile(profile),
    })
  },
  { deep: true },
)

watch(
  wizard,
  () => {
    if (inputMode.value !== 'wizard') return
    syncActivePresetFromForm()
  },
  { deep: true },
)

watch(
  () => resolvePositionName(),
  () => {
    syncActivePresetFromForm()
  },
)

watch([unifiedRequirement, searchRequirement, screeningCriteria, collectOnly, collectFolderName], () => {
  syncActivePresetFromForm()
})

async function initPresets() {
  presets.value = loadJobPresets()
  const savedActive = loadActivePresetId()
  if (savedActive && presets.value.some((p) => p.id === savedActive)) {
    applyPreset(savedActive)
  } else if (presets.value.length > 0) {
    applyPreset(presets.value[0].id)
  } else {
    applyEmptyForm()
  }
  await applyRuntimeDefaultsIfAvailable()
}

function openAddDialog() {
  dialogLabel.value = ''
  if (inputMode.value === 'unified') {
    dialogSearch.value = unifiedRequirement.value.trim()
    dialogCriteria.value = ''
  } else if (inputMode.value === 'wizard') {
    dialogSearch.value = wizardSearchRequirement.value
    dialogCriteria.value = wizardScreeningCriteria.value
  } else {
    dialogSearch.value = searchRequirement.value.trim()
    dialogCriteria.value = screeningCriteria.value.trim()
  }
  dialogJobQaProfile.value = normalizeJobQaProfile(jobQaProfile.value)
  showPresetDialog.value = true
}

function cancelDialog() {
  showPresetDialog.value = false
}

function saveNewPreset() {
  const label = dialogLabel.value.trim()
  const searchRequirementText = dialogSearch.value.trim()
  const screeningCriteriaText = dialogCriteria.value.trim()
  if (!label) {
    window.alert('请填写筛选需求名称')
    return
  }
  if (!searchRequirementText) {
    window.alert('请填写搜索需求')
    return
  }
  if (!screeningCriteriaText && inputMode.value === 'split') {
    window.alert('请填写 HR 评判标准')
    return
  }

  const criteria =
    screeningCriteriaText ||
    (inputMode.value === 'unified'
      ? unifiedRequirement.value.split('【HR偏好】').slice(1).join('【HR偏好】').trim()
      : inputMode.value === 'wizard'
        ? wizardScreeningCriteria.value
      : '')

  if (inputMode.value === 'wizard') {
    wizard.value.jobTitle = label
  }

  const preset = addJobPreset({
    label,
    searchRequirement: searchRequirementText,
    screeningCriteria: criteria || '（请补充 HR 评判标准）',
    chatJobTitle: label,
    collectParentGroup: '',
    jobQaProfile: normalizeJobQaProfile(dialogJobQaProfile.value),
    inputMode: inputMode.value,
    wizardState:
      inputMode.value === 'wizard' ? ({ ...wizard.value } as RequirementWizardState) : null,
    collectOnly: collectOnly.value,
    platforms: [...selectedPlatforms.value],
    unifiedRequirement:
      inputMode.value === 'unified' ? unifiedRequirement.value.trim() : '',
  })
  presets.value = loadJobPresets()
  applyPreset(preset.id)
  showPresetDialog.value = false
}

function removePreset(id: string) {
  const preset = presets.value.find((p) => p.id === id)
  if (!preset) return
  if (!window.confirm(`确定删除筛选需求「${preset.label}」？`)) return

  presets.value = deleteJobPreset(id)
  if (activePresetId.value === id) {
    if (presets.value.length > 0) applyPreset(presets.value[0].id)
    else applyEmptyForm()
  }
}

function startPresetRename(id: string, event?: Event) {
  event?.stopPropagation?.()
  const preset = presets.value.find((p) => p.id === id)
  if (!preset) return
  editingPresetId.value = id
  editingPresetLabel.value = preset.label
}

function setPresetEditInput(el: HTMLInputElement | null, id: string) {
  if (editingPresetId.value !== id || !el) return
  void nextTick(() => {
    el.focus()
    el.select()
  })
}

function cancelPresetRename() {
  editingPresetId.value = null
  editingPresetLabel.value = ''
}

function commitPresetRename(id: string) {
  if (editingPresetId.value !== id) return
  const newLabel = editingPresetLabel.value.trim()
  cancelPresetRename()
  if (!newLabel) return

  const preset = presets.value.find((p) => p.id === id)
  if (!preset || preset.label === newLabel) return

  updateJobPreset(id, {
    label: newLabel,
    chatJobTitle: newLabel,
  })
  presets.value = loadJobPresets()

  if (activePresetId.value === id) {
    wizard.value.jobTitle = newLabel
    syncActivePresetFromForm()
  }
}

function buildStartPayload(requireCollectFolder: boolean): StartPayload | null {
  const preset = activePreset()
  const positionNameValue = resolvePositionName()
  if (!positionNameValue) {
    window.alert('请先选中筛选需求并填写名称（点击「编辑」可修改；该名称用于猎聘开聊选岗）')
    return null
  }
  const collectFolderValue = collectFolderName.value.trim()
  if (requireCollectFolder && !collectFolderValue) {
    window.alert('请填写收藏文件夹名（猎聘侧栏关键词，如：嵌入式）')
    return null
  }
  const wizardPreferenceMemory =
    inputMode.value === 'wizard' ? buildWizardPreferenceMemory(wizard.value) : null
  const presetMeta = {
    platforms: [...selectedPlatforms.value],
    preset_id: preset?.id,
    preset_label: positionNameValue,
    chat_job_title: positionNameValue,
    collect_parent_group: collectFolderValue,
    preference_memory: wizardPreferenceMemory ?? preset?.preferenceMemory ?? null,
    job_qa_profile: normalizeJobQaProfile(jobQaProfile.value),
    input_mode: inputMode.value,
    wizard_state:
      inputMode.value === 'wizard' ? ({ ...wizard.value } as RequirementWizardState) : null,
  }
  if (inputMode.value === 'unified') {
    return {
      mode: 'unified',
      unified_requirement: unifiedRequirement.value,
      collect_only: collectOnly.value,
      im_review_required: imReviewRequired.value,
      ...presetMeta,
    }
  } else if (inputMode.value === 'wizard') {
    return {
      mode: 'split',
      search_requirement: wizardSearchRequirement.value,
      screening_criteria: wizardScreeningCriteria.value,
      collect_only: collectOnly.value,
      im_review_required: imReviewRequired.value,
      ...presetMeta,
    }
  } else {
    return {
      mode: 'split',
      search_requirement: searchRequirement.value,
      screening_criteria: screeningCriteria.value,
      collect_only: collectOnly.value,
      im_review_required: imReviewRequired.value,
      ...presetMeta,
    }
  }
}

function handleStart() {
  const payload = buildStartPayload(true)
  if (payload) emit('start', payload)
}

function openPdfPicker() {
  const payload = buildStartPayload(false)
  if (!payload) return
  pdfFileInput.value?.click()
}

function handlePdfFiles(event: Event) {
  const input = event.target as HTMLInputElement
  const files = Array.from(input.files || [])
  input.value = ''
  if (!files.length) return
  const payload = buildStartPayload(false)
  if (payload) emit('pdf-import', payload, files)
}

onMounted(initPresets)
</script>

<template>
  <div class="search-form">
    <div class="mode-bar card">
      <span class="mode-label">输入方式</span>
      <div class="mode-switch">
        <button
          type="button"
          :class="{ active: inputMode === 'wizard' }"
          @click="inputMode = 'wizard'"
        >
          向导填写
        </button>
        <button
          type="button"
          :class="{ active: inputMode === 'unified' }"
          @click="inputMode = 'unified'"
        >
          一段话
        </button>
        <button
          type="button"
          :class="{ active: inputMode === 'split' }"
          @click="inputMode = 'split'"
        >
          分栏填写
        </button>
      </div>
      <p class="mode-hint">
        <template v-if="inputMode === 'wizard'">
          HR 只填岗位画像与筛选偏好，系统自动生成搜索需求和评判标准
        </template>
        <template v-else-if="inputMode === 'unified'">
          AI 从一段话同时拆出：搜索栏关键词、猎聘筛选、HR 偏好
        </template>
        <template v-else>
          搜索需求与 HR 评判标准分开填写，分别解析猎聘参数与初筛标准
        </template>
      </p>
    </div>

    <div class="platform-bar card">
      <span class="mode-label">启动平台</span>
      <div class="platform-options">
        <label
          v-for="platform in PLATFORM_OPTIONS"
          :key="platform.key"
          class="platform-option"
          :class="{ active: selectedPlatforms.includes(platform.key) }"
        >
          <input
            type="checkbox"
            :checked="selectedPlatforms.includes(platform.key)"
            @change="togglePlatform(platform.key)"
          />
          <span>
            <strong>{{ platform.label }}</strong>
            <em>{{ platform.hint }}</em>
          </span>
        </label>
      </div>
      <p class="mode-hint">同一套解析结果会分发到已选平台；多个平台会创建独立任务并并行启动。</p>
    </div>

    <section class="card section qa-section">
      <h2>岗位候选人问答资料</h2>
      <p class="hint">跟随当前岗位预设保存；下次点击岗位标签会自动加载，只用于 IM 白名单自动回复。</p>
      <div class="qa-grid">
        <label>
          <span>岗位职责</span>
          <textarea v-model="jobQaProfile.responsibilities" rows="2" placeholder="候选人问工作内容时的回答依据" />
        </label>
        <label>
          <span>工作地点</span>
          <input v-model="jobQaProfile.work_location" type="text" placeholder="例如：深圳南山" />
        </label>
        <label>
          <span>薪资范围</span>
          <input v-model="jobQaProfile.salary_range" type="text" placeholder="例如：15-25K，13薪" />
        </label>
        <label>
          <span>工作模式</span>
          <input v-model="jobQaProfile.work_mode" type="text" placeholder="例如：双休 / 坐班 / 出差频率" />
        </label>
        <label>
          <span>面试流程</span>
          <input v-model="jobQaProfile.interview_process" type="text" placeholder="例如：HR初聊-业务面-终面" />
        </label>
        <label>
          <span>到岗时间</span>
          <input v-model="jobQaProfile.start_time" type="text" placeholder="例如：一个月内优先" />
        </label>
        <label>
          <span>招聘状态</span>
          <input v-model="jobQaProfile.recruiting_status" type="text" placeholder="例如：岗位仍在招聘中" />
        </label>
        <label>
          <span>公司/团队介绍</span>
          <textarea v-model="jobQaProfile.company_intro" rows="2" placeholder="候选人问公司、团队时的基础回答" />
        </label>
      </div>
    </section>

    <div class="form-grid" :class="{ split: inputMode === 'split', wizard: inputMode === 'wizard' }">
      <section class="card section preset-section">
        <h2>筛选需求</h2>
        <p class="hint">
          已保存的需求会永久保留在本机。点击「编辑」修改名称；该名称用于<strong>猎聘开聊选岗</strong>（须与在招岗位一致）
        </p>
        <label class="collect-folder-field">
          <span>收藏文件夹名</span>
          <input
            v-model="collectFolderName"
            type="text"
            placeholder="如：嵌入式（猎聘侧栏关键词，不必与岗位全称一致）"
          />
        </label>
        <p class="hint collect-folder-hint">
          初筛「观察 / 追问」会收藏进该文件夹；只需与猎聘简历库侧栏名称<strong>部分匹配</strong>即可（如岗位「嵌入式软件工程师」可填「嵌入式」）
        </p>
        <div v-if="presets.length === 0" class="preset-empty">暂无保存的需求，请添加</div>
        <div class="preset-tabs">
          <div v-for="preset in presets" :key="preset.id" class="preset-item">
            <div
              class="preset-card"
              :class="{ active: activePresetId === preset.id && editingPresetId !== preset.id }"
              @click="editingPresetId === preset.id ? undefined : applyPreset(preset.id)"
            >
              <input
                v-if="editingPresetId === preset.id"
                :ref="(el) => setPresetEditInput(el as HTMLInputElement | null, preset.id)"
                v-model="editingPresetLabel"
                type="text"
                class="preset-edit-input"
                placeholder="筛选需求名称"
                @keydown.enter.prevent="commitPresetRename(preset.id)"
                @keydown.esc.prevent="cancelPresetRename"
                @click.stop
              />
              <span v-else class="preset-label">{{ preset.label }}</span>
            </div>
            <button
              type="button"
              class="preset-edit"
              @click.stop="
                editingPresetId === preset.id
                  ? commitPresetRename(preset.id)
                  : startPresetRename(preset.id, $event)
              "
            >
              {{ editingPresetId === preset.id ? '完成' : '编辑' }}
            </button>
            <button
              type="button"
              class="preset-del"
              title="删除"
              @click.stop="removePreset(preset.id)"
            >
              ×
            </button>
          </div>
        </div>
        <button type="button" class="preset-add" @click="openAddDialog">+ 添加新的筛选需求</button>
      </section>

      <template v-if="inputMode === 'wizard'">
        <section class="card section input-section wizard-section">
          <h2>岗位画像</h2>
          <p class="hint">把招聘经验拆成字段，城市、年限、学历不会进入搜索栏关键词</p>
          <div class="wizard-fields">
            <label>
              <span>岗位类型</span>
              <select v-model="wizard.jobType">
                <option>开发/技术</option>
                <option>销售</option>
                <option>运营</option>
                <option>产品</option>
                <option>财务/职能</option>
                <option>管理岗</option>
              </select>
            </label>
            <label class="wide">
              <span>搜索关键词</span>
              <input v-model="wizard.keywords" type="text" placeholder="只写搜人关键词，如：开发工程师 架构师" />
            </label>
            <label>
              <span>目前城市</span>
              <input v-model="wizard.currentCity" type="text" placeholder="例如：深圳" />
            </label>
            <label>
              <span>期望城市</span>
              <input v-model="wizard.expectedCity" type="text" placeholder="例如：深圳" />
            </label>
            <label>
              <span>经验年限</span>
              <input v-model="wizard.experience" type="text" placeholder="例如：1-5年" />
            </label>
            <label>
              <span>目标份数</span>
              <input v-model.number="wizard.targetCount" type="number" min="1" max="50" />
            </label>
            <label>
              <span>学历</span>
              <input v-model="wizard.degree" type="text" placeholder="本科 / 硕士" />
            </label>
            <label>
              <span>院校要求</span>
              <input v-model="wizard.schoolTiers" type="text" placeholder="985 / 211 / 海外留学" />
            </label>
            <label class="wide">
              <span>行业/业务背景</span>
              <input v-model="wizard.industry" type="text" placeholder="例如：SaaS、智能制造、跨境电商" />
            </label>
            <label class="wide">
              <span>技能/能力关键词</span>
              <textarea v-model="wizard.skills" rows="3" placeholder="每行一条，例如：Python&#10;微服务架构&#10;团队管理" />
            </label>
          </div>
        </section>

        <section class="card section input-section criteria-section wizard-section">
          <h2>筛选偏好</h2>
          <p class="hint">这些内容会生成 AI 判定「观察 / 追问 / 排除」的标准</p>
          <div class="wizard-criteria">
            <label>
              <span>必备</span>
              <textarea
                v-model="wizard.mustHave"
                placeholder="每行一条；候选人必须满足的正向要求（如：必须有美签）"
              />
            </label>
            <label>
              <span>快速淘汰</span>
              <textarea
                v-model="wizard.quickReject"
                placeholder="每行一条；简历证据明确时可直接排除（如：近一年两次及以上主动跳槽）"
              />
            </label>
            <label>
              <span>加分</span>
              <textarea v-model="wizard.niceToHave" placeholder="每行一条，用于简历排序" />
            </label>
            <label>
              <span>追问</span>
              <textarea v-model="wizard.followup" placeholder="简历没写清时要确认的问题" />
            </label>
          </div>
          <div class="wizard-preview">
            <strong>生成预览</strong>
            <p>搜索需求：{{ wizardSearchRequirement || '待填写' }}</p>
            <details>
              <summary>查看 AI 初筛标准</summary>
              <pre>{{ wizardScreeningCriteria }}</pre>
            </details>
          </div>
        </section>
      </template>

      <template v-else-if="inputMode === 'unified'">
        <section class="card section input-section">
          <h2>综合招聘需求</h2>
          <p class="hint">
            用一段话描述岗位、筛选与 HR 要求。AI 将拆成<strong>搜索栏</strong>、<strong>猎聘筛选</strong>、<strong>HR
            偏好</strong>三类
          </p>
          <textarea
            v-model="unifiedRequirement"
            class="field-input"
            placeholder="例：西班牙语 美签 海外销售 base深圳 3-10年经验"
          />
        </section>
      </template>

      <template v-else>
        <section class="card section input-section">
          <h2>搜索需求</h2>
          <p class="hint">描述要搜的人才方向，AI 解析后填入猎聘搜索栏与筛选项</p>
          <textarea
            v-model="searchRequirement"
            class="field-input"
            placeholder="例如：深圳 ToB 大客户销售，智能制造，3年以上，处理20份简历"
          />
        </section>

        <section class="card section input-section criteria-section">
          <h2>HR 评判标准</h2>
          <p class="hint">拿到在线简历后 AI 判定「观察 / 追问 / 排除」的规则</p>
          <textarea
            v-model="screeningCriteria"
            class="field-input"
            placeholder="例如：ToB 大客户经验、制造业客户、3年以上销售为硬性要求…"
          />
        </section>
      </template>
    </div>

    <div class="actions">
      <OutreachModePicker
        v-model:collect-only="collectOnly"
        v-model:auto-reply-im="autoReplyIm"
        class="start-mode-picker"
      />
      <p v-if="!collectOnly" class="collect-hint communicate-hint">
        沟通模式下：初筛「追问/观察」会先收藏并立即开聊；猎聘已显示「继续沟通」的候选人将跳过重复开聊
      </p>
      <p v-if="!collectOnly && imReviewRequired" class="collect-hint communicate-hint">
        人工确认模式：仍会立即开聊，IM 只生成草稿不自动发送
      </p>
      <p v-if="!loginReady" class="login-warn">
        请先在上方完成登录与 API Key 配置后再开始筛选。
      </p>
      <button
        class="btn-primary start-btn"
        :disabled="!loginReady || selectedPlatforms.length === 0"
        @click="handleStart"
      >
        一键开始
      </button>
      <input
        ref="pdfFileInput"
        class="pdf-file-input"
        type="file"
        accept="application/pdf,.pdf"
        multiple
        @change="handlePdfFiles"
      />
      <button type="button" class="btn-secondary pdf-import-btn" :disabled="!pdfImportReady" @click="openPdfPicker">
        批量导入 PDF
      </button>
      <p class="pdf-import-hint">仅支持有文本层的 PDF；每批最多 1000 份，单份不超过 30MB、整批不超过 5GB，按 10 份并行处理，原文件和文件名不会保存。</p>
    </div>

    <div v-if="showPresetDialog" class="preset-dialog-overlay" @click.self="cancelDialog">
      <div class="preset-dialog card">
        <h3>添加新的筛选需求</h3>
        <p class="dialog-hint">保存后下次打开仍可选用；启动任务时 HR 标准会写入该任务数据库</p>
        <label class="dialog-field">
          <span>名称（开聊选岗，须与猎聘在招岗位一致）</span>
          <input v-model="dialogLabel" type="text" placeholder="例如：拉美中方销售 / 高级薪酬绩效专员" />
        </label>
        <label class="dialog-field">
          <span>搜索需求</span>
          <textarea v-model="dialogSearch" rows="4" placeholder="猎聘搜索方向、城市、年限、份数等" />
        </label>
        <label v-if="inputMode === 'split'" class="dialog-field">
          <span>HR 评判标准</span>
          <textarea v-model="dialogCriteria" rows="6" placeholder="观察 / 追问 / 排除规则" />
        </label>
        <label v-else class="dialog-field">
          <span>HR 评判标准（可选，不填则从一段话里解析）</span>
          <textarea v-model="dialogCriteria" rows="4" placeholder="可留空，由 AI 从综合需求中拆分" />
        </label>
        <div class="dialog-actions">
          <button type="button" class="btn-secondary" @click="cancelDialog">取消</button>
          <button type="button" class="btn-primary" @click="saveNewPreset">保存</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.search-form {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
  width: 100%;
}

.mode-bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.65rem 1rem;
  padding: 0.75rem 1rem;
  border-color: #b8daf0;
}

.platform-bar {
  display: grid;
  grid-template-columns: auto minmax(280px, 1fr) minmax(240px, 1.1fr);
  align-items: center;
  gap: 0.65rem 1rem;
  padding: 0.75rem 1rem;
  border-color: #b8daf0;
}

.mode-label {
  font-size: 0.88rem;
  font-weight: 600;
  color: var(--primary-dark);
}

.mode-switch {
  display: inline-flex;
  border-radius: 8px;
  overflow: hidden;
  border: 1px solid var(--border);
  background: var(--primary-light);
}

.mode-switch button {
  padding: 0.4rem 1rem;
  font-size: 0.85rem;
  font-weight: 600;
  color: var(--text-muted);
  background: transparent;
  border-radius: 0;
}

.mode-switch button.active {
  background: linear-gradient(135deg, var(--primary), var(--primary-dark));
  color: #fff;
}

.mode-hint {
  flex: 1;
  min-width: 200px;
  font-size: 0.78rem;
  color: var(--text-muted);
  margin: 0;
  line-height: 1.4;
}

.platform-options {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
}

.platform-option {
  display: inline-flex;
  align-items: center;
  gap: 0.55rem;
  min-width: 180px;
  padding: 0.55rem 0.7rem;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: #fff;
  cursor: pointer;
}

.platform-option.active {
  border-color: var(--primary);
  background: var(--primary-light);
}

.platform-option input {
  width: 1rem;
  height: 1rem;
  cursor: pointer;
}

.platform-option span {
  display: flex;
  flex-direction: column;
  gap: 0.1rem;
  min-width: 0;
}

.platform-option strong {
  color: var(--text);
  font-size: 0.86rem;
  line-height: 1.2;
}

.platform-option em {
  color: var(--text-muted);
  font-size: 0.74rem;
  font-style: normal;
  line-height: 1.25;
}

.form-grid {
  display: grid;
  grid-template-columns: minmax(200px, 0.85fr) minmax(320px, 2fr);
  gap: 0.75rem;
  align-items: stretch;
  min-height: 380px;
}

.form-grid.split {
  grid-template-columns: minmax(200px, 0.9fr) minmax(220px, 1fr) minmax(280px, 1.35fr);
}

.form-grid.wizard {
  grid-template-columns: minmax(190px, 0.72fr) minmax(360px, 1.35fr) minmax(360px, 1.35fr);
}

.section {
  display: flex;
  flex-direction: column;
  min-height: 0;
  padding: 1rem 1.1rem;
  overflow: hidden;
}

.section h2 {
  font-size: 1.02rem;
  color: var(--primary-dark);
  margin-bottom: 0.3rem;
  flex-shrink: 0;
}

.position-name-field input {
  width: 100%;
  padding: 0.55rem 0.75rem;
  border: 1px solid var(--border);
  border-radius: 8px;
  font-size: 0.95rem;
}

.preset-section,
.input-section,
.criteria-section {
  border-color: #b8daf0;
}

.hint {
  font-size: 0.8rem;
  color: var(--text-muted);
  margin-bottom: 0.65rem;
  line-height: 1.45;
  flex-shrink: 0;
}

.hint strong {
  color: var(--primary-dark);
  font-weight: 600;
}

.preset-empty {
  font-size: 0.82rem;
  color: var(--text-muted);
  padding: 0.5rem 0;
}

.preset-tabs {
  display: flex;
  flex-direction: column;
  gap: 0.45rem;
  flex: 1;
  min-height: 0;
  overflow-y: auto;
}

.preset-item {
  display: flex;
  align-items: stretch;
  gap: 0.35rem;
}

.preset-card {
  flex: 1;
  min-width: 0;
  display: flex;
  align-items: center;
  padding: 0.65rem 0.85rem;
  border-radius: 8px;
  background: var(--primary-light);
  border: 1.5px solid transparent;
  cursor: pointer;
}

.preset-card.active {
  background: linear-gradient(135deg, var(--primary), var(--primary-dark));
  border-color: var(--primary-dark);
  box-shadow: 0 2px 8px rgba(74, 159, 217, 0.35);
}

.preset-card.active .preset-label {
  color: #fff;
}

.preset-label {
  font-size: 0.86rem;
  font-weight: 600;
  line-height: 1.35;
  color: var(--text);
  word-break: break-word;
}

.preset-edit-input {
  width: 100%;
  padding: 0;
  font-size: 0.86rem;
  font-weight: 600;
  border: none;
  background: transparent;
  color: inherit;
  outline: none;
  min-width: 0;
}

.preset-card:not(.active) .preset-edit-input {
  color: var(--text);
}

.preset-edit {
  flex: 0 0 auto;
  min-width: 2.6rem;
  padding: 0 0.55rem;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: #fff;
  color: var(--primary-dark);
  font-size: 0.78rem;
  font-weight: 600;
  cursor: pointer;
}

.preset-edit:hover {
  border-color: var(--primary);
  background: #eff6ff;
}

.preset-del {
  width: 2rem;
  flex-shrink: 0;
  border-radius: 8px;
  background: #fff;
  color: #94a3b8;
  border: 1px solid var(--border);
  font-size: 1.1rem;
  line-height: 1;
}

.preset-del:hover {
  color: #dc2626;
  border-color: #fecaca;
  background: #fef2f2;
}

.preset-add {
  margin-top: 0.5rem;
  padding: 0.55rem 0.75rem;
  font-size: 0.84rem;
  font-weight: 600;
  border-radius: 8px;
  background: #fff;
  color: var(--primary-dark);
  border: 1.5px dashed #93c5fd;
  text-align: center;
}

.preset-add:hover {
  background: #eff6ff;
  border-color: var(--primary);
}

.field-input {
  flex: 1;
  min-height: 0;
  resize: none;
  font-size: 0.88rem;
  line-height: 1.5;
}

.wizard-section {
  gap: 0.55rem;
}

.wizard-fields,
.wizard-criteria {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0.55rem;
  overflow-y: auto;
  min-height: 0;
  padding-right: 0.15rem;
}

.wizard-criteria {
  grid-template-columns: 1fr;
}

.wizard-fields label,
.wizard-criteria label {
  display: flex;
  flex-direction: column;
  gap: 0.28rem;
  min-width: 0;
  font-size: 0.78rem;
  font-weight: 600;
  color: var(--text);
}

.wizard-fields label.wide {
  grid-column: 1 / -1;
}

.wizard-fields input,
.wizard-fields select,
.wizard-fields textarea,
.wizard-criteria input,
.wizard-criteria textarea {
  min-width: 0;
  font-size: 0.84rem;
  line-height: 1.45;
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 0.5rem 0.6rem;
  background: #fff;
}

.wizard-fields textarea,
.wizard-criteria textarea {
  resize: vertical;
  min-height: 4.5rem;
}

.wizard-preview {
  border: 1px solid #c7d2fe;
  background: #f8fafc;
  border-radius: 8px;
  padding: 0.65rem 0.75rem;
  font-size: 0.78rem;
  line-height: 1.45;
  color: var(--text);
  flex-shrink: 0;
}

.wizard-preview strong {
  display: block;
  color: var(--primary-dark);
  margin-bottom: 0.25rem;
}

.wizard-preview p {
  margin: 0.2rem 0 0.4rem;
  color: var(--text-muted);
}

.wizard-preview summary {
  cursor: pointer;
  color: var(--primary-dark);
  font-weight: 600;
}

.wizard-preview pre {
  max-height: 10rem;
  overflow: auto;
  margin: 0.5rem 0 0;
  white-space: pre-wrap;
  word-break: break-word;
  font-size: 0.74rem;
  line-height: 1.45;
}

.actions {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding-top: 0.15rem;
  gap: 0.65rem;
}

.start-mode-picker {
  max-width: 720px;
  width: 100%;
}

.collect-hint {
  font-size: 0.78rem;
  color: var(--text-muted);
  flex-basis: 100%;
  text-align: center;
}

.collect-folder-field {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
  margin: 0.75rem 0 0.35rem;
  font-size: 0.85rem;
}

.collect-folder-field input {
  width: 100%;
}

.collect-folder-hint {
  margin-top: 0;
  margin-bottom: 0.5rem;
}

.start-btn {
  padding: 0.85rem 3rem;
  font-size: 1rem;
}

.pdf-file-input {
  display: none;
}

.pdf-import-btn {
  min-width: 10rem;
}

.pdf-import-hint {
  margin: -0.25rem 0 0;
  font-size: 0.78rem;
  color: var(--text-muted);
}

.login-warn {
  width: 100%;
  max-width: 720px;
  text-align: center;
  font-size: 0.88rem;
  color: #b45309;
  background: #fffbeb;
  border: 1px solid #fde68a;
  border-radius: 8px;
  padding: 0.65rem 1rem;
  margin-bottom: 0.75rem;
  line-height: 1.5;
}

.preset-dialog-overlay {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.45);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
  padding: 1rem;
}

.preset-dialog {
  width: min(520px, 100%);
  padding: 1.25rem;
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.preset-dialog h3 {
  margin: 0;
  font-size: 1.05rem;
  color: var(--primary-dark);
}

.dialog-hint {
  margin: 0;
  font-size: 0.78rem;
  color: var(--text-muted);
  line-height: 1.45;
}

.dialog-field {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
  font-size: 0.82rem;
  font-weight: 600;
  color: var(--text);
}

.dialog-field input,
.dialog-field textarea {
  font-weight: 400;
  resize: vertical;
}

.dialog-actions {
  display: flex;
  justify-content: flex-end;
  gap: 0.65rem;
  padding-top: 0.25rem;
}

.qa-section {
  margin-bottom: 1rem;
}

.qa-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0.75rem;
}

.qa-grid label {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
  font-size: 0.82rem;
  font-weight: 600;
  color: var(--text);
}

.qa-grid input,
.qa-grid textarea {
  width: 100%;
  font: inherit;
  font-weight: 400;
  resize: vertical;
}

@media (max-width: 1100px) {
  .platform-bar {
    grid-template-columns: 1fr;
  }

  .form-grid.split {
    grid-template-columns: 1fr 1fr;
    min-height: 0;
  }

  .form-grid.wizard {
    grid-template-columns: 1fr 1fr;
    min-height: 0;
  }

  .form-grid.split .preset-section {
    grid-column: 1 / -1;
  }

  .form-grid.wizard .preset-section {
    grid-column: 1 / -1;
  }

  .field-input {
    min-height: 160px;
  }
}

@media (max-width: 900px) {
  .form-grid {
    grid-template-columns: 1fr;
    min-height: 0;
  }

  .form-grid.split {
    grid-template-columns: 1fr;
  }

  .form-grid.wizard {
    grid-template-columns: 1fr;
  }

  .wizard-fields {
    grid-template-columns: 1fr;
  }

  .qa-grid {
    grid-template-columns: 1fr;
  }

  .field-input {
    min-height: 140px;
  }
}
</style>
