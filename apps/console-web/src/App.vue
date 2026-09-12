<script setup lang="ts">
import { onMounted, ref } from 'vue'
import AppLayout from './components/AppLayout.vue'
import LoginSetup from './components/LoginSetup.vue'
import RuntimeSetupPanel from './components/RuntimeSetupPanel.vue'
import SearchForm, { type StartPayload } from './components/SearchForm.vue'
import TaskStatus from './components/TaskStatus.vue'
import ConsoleTabs from './components/ConsoleTabs.vue'
import LoadingSpinner from './components/LoadingSpinner.vue'
import ParseStreamLog from './components/ParseStreamLog.vue'
import ConsoleSkeleton from './components/ConsoleSkeleton.vue'
import RunningTasksBar from './components/RunningTasksBar.vue'
import {
  getWorkflow,
  getRuntimeSettings,
  updateRuntimeSettings,
  parseSearchIntentStream,
  startDemo,
  startPdfImport,
  listWorkflows,
  cancelWorkflow,
  deleteWorkflow,
  type PlatformStartResult,
} from './api'
import ParseSummary from './components/ParseSummary.vue'
import {
  clearParsedFromStorage,
  loadParsedFromStorage,
  parsedFromWorkflow,
  saveParsedToStorage,
  workflowPositionName,
} from './utils/parseSummary'
import { persistJobPreset } from './utils/jobPresets'
import type { SearchIntentOutput, WorkflowInfo } from './types'

type BootPhase = 'idle' | 'parsing' | 'launching' | 'ready' | 'error'

const pageView = ref<'home' | 'console'>('home')
const workflowId = ref<string | null>(null)
const parsedPreview = ref<SearchIntentOutput | null>(null)
const bootPhase = ref<BootPhase>('idle')
const startError = ref('')
const showHistory = ref(false)
const history = ref<WorkflowInfo[]>([])
const deletingWorkflowId = ref<string | null>(null)
const loginReady = ref(false)
const setupReady = ref(false)
const platformStartResults = ref<PlatformStartResult[]>([])
const runningTasksBarRef = ref<InstanceType<typeof RunningTasksBar> | null>(null)

const bootMessage = ref('')
const bootSubmessage = ref('')
const parseStreamText = ref('')
const parseStreamStatuses = ref<string[]>([])

const PLATFORM_LABELS: Record<string, string> = {
  liepin: '猎聘 LPT',
  boss: 'BOSS 直聘',
  local_pdf: '本地 PDF',
}

function platformText(platforms: string[]): string {
  return platforms.map((p) => PLATFORM_LABELS[p] || p).join(' / ')
}

async function restoreParsedPreview(id: string) {
  const cached = loadParsedFromStorage(id)
  if (cached?.parse_summary) {
    parsedPreview.value = cached
    return
  }
  try {
    const wf = await getWorkflow(id)
    parsedPreview.value = parsedFromWorkflow(wf)
  } catch {
    parsedPreview.value = null
  }
}

async function readUrlWorkflow() {
  const params = new URLSearchParams(window.location.search)
  const id = params.get('workflow_id')
  if (id) {
    workflowId.value = id
    pageView.value = 'console'
    bootPhase.value = 'ready'
    await restoreParsedPreview(id)
  }
}

function setWorkflowId(id: string) {
  workflowId.value = id
  const url = new URL(window.location.href)
  url.searchParams.set('workflow_id', id)
  window.history.replaceState({}, '', url.toString())
}

async function handleStart(inputs: StartPayload) {
  const selectedPlatforms = inputs.platforms.length ? inputs.platforms : ['liepin']
  pageView.value = 'console'
  bootPhase.value = 'parsing'
  bootMessage.value = '正在智能解析搜索需求'
  bootSubmessage.value =
    inputs.mode === 'unified'
      ? `AI 正在从一段话拆出搜索词与筛选参数，用于 ${platformText(selectedPlatforms)}…`
      : `AI 正在提取关键词、城市、年限与处理份数，用于 ${platformText(selectedPlatforms)}…`
  startError.value = ''
  workflowId.value = null
  parsedPreview.value = null
  platformStartResults.value = []
  parseStreamText.value = ''
  parseStreamStatuses.value = []

  const positionName = (
    inputs.chat_job_title ||
    inputs.preset_label ||
    ''
  ).trim()

  const parseBody =
    inputs.mode === 'unified'
      ? { unified_requirement: inputs.unified_requirement, position_name: positionName }
      : {
          search_requirement: inputs.search_requirement,
          screening_criteria: inputs.screening_criteria,
          position_name: positionName,
        }

  try {
    const parsed = await parseSearchIntentStream(parseBody, {
      onStatus: (text) => {
        parseStreamStatuses.value.push(text)
      },
      onDelta: (text) => {
        parseStreamText.value += text
      },
    })
    const userRequirement =
      inputs.mode === 'unified' ? inputs.unified_requirement : inputs.search_requirement
    const baseCriteria =
      parsed.screening_criteria || (inputs.mode === 'split' ? inputs.screening_criteria : '')
    parsedPreview.value = {
      ...parsed,
      search_requirement: parsed.search_requirement?.trim() || userRequirement,
      screening_criteria: baseCriteria,
    }

    const finalMemory = inputs.preference_memory ?? null
    const finalCriteria =
      finalMemory?.screening_criteria?.trim() ||
      baseCriteria ||
      (inputs.mode === 'split' ? inputs.screening_criteria : '')
    const resolvedChatJobTitle = positionName
    const resolvedCollectFolder = (inputs.collect_parent_group || '').trim()
    if (inputs.preset_id) {
      persistJobPreset(inputs.preset_id, {
        searchRequirement:
          inputs.mode === 'unified' ? inputs.unified_requirement : inputs.search_requirement,
        screeningCriteria: finalCriteria,
        unifiedRequirement:
          inputs.mode === 'unified' ? inputs.unified_requirement : undefined,
        chatJobTitle: resolvedChatJobTitle,
        collectParentGroup: resolvedCollectFolder,
        preferenceMemory: finalMemory ?? inputs.preference_memory ?? null,
        jobQaProfile: inputs.job_qa_profile ?? null,
        inputMode: inputs.input_mode,
        wizardState: inputs.wizard_state ?? null,
        collectOnly: inputs.collect_only ?? false,
        imReviewRequired: inputs.im_review_required ?? false,
        platforms: inputs.platforms,
      })
    }
    parsedPreview.value = {
      ...(parsedPreview.value || parsed),
      screening_criteria: finalCriteria,
      chat_job_title: resolvedChatJobTitle,
    }

    bootPhase.value = 'launching'
    bootMessage.value = '解析完成，正在启动筛选任务'
    bootSubmessage.value =
      selectedPlatforms.length > 1
        ? `正在并行启动：${platformText(selectedPlatforms)}…`
        : `正在启动：${platformText(selectedPlatforms)}…`

    try {
      await updateRuntimeSettings({
        default_screening_criteria: finalCriteria,
        default_chat_job_title: resolvedChatJobTitle,
        default_collect_parent_group: resolvedCollectFolder,
        default_hr_preference_memory: finalMemory ?? inputs.preference_memory ?? null,
      })
    } catch {
      /* runtime defaults are best-effort */
    }

    const res = await startDemo({
      platforms: selectedPlatforms,
      search_requirement:
        inputs.mode === 'unified' ? inputs.unified_requirement : inputs.search_requirement,
      screening_criteria: finalCriteria,
      keywords: parsed.keywords,
      city: parsed.city,
      cities: parsed.cities?.length ? parsed.cities : [parsed.city],
      current_cities: parsed.current_cities ?? [],
      experience: parsed.experience,
      education: parsed.education ?? {},
      other_filters: parsed.other_filters ?? {},
      target_count: parsed.target_count,
      job_description: parsed.job_description,
      chat_job_title: resolvedChatJobTitle,
      collect_parent_group: resolvedCollectFolder,
      name: resolvedChatJobTitle || parsed.name,
      parse_summary: parsed.parse_summary,
      collect_only: inputs.collect_only ?? false,
      im_review_required: inputs.im_review_required ?? false,
      preset_id: inputs.preset_id ?? '',
      preset_label: inputs.preset_label ?? '',
      hr_preference_memory: finalMemory ?? null,
      job_qa_profile: inputs.job_qa_profile ?? null,
    })
    platformStartResults.value =
      res.platform_results ?? [
        {
          platform: selectedPlatforms[0],
          platform_label: platformText([selectedPlatforms[0]]),
          workflow_id: res.workflow_id,
          status: res.status,
          console_url: res.console_url,
          message: res.message,
        },
      ]
    setWorkflowId(res.workflow_id)
    for (const item of platformStartResults.value) {
      saveParsedToStorage(item.workflow_id, parsedPreview.value!)
    }
    bootPhase.value = 'ready'
    runningTasksBarRef.value?.refresh()
  } catch (e) {
    bootPhase.value = 'error'
    startError.value = e instanceof Error ? e.message : '启动失败'
  }
}

async function handlePdfImport(inputs: StartPayload, files: File[]) {
  pageView.value = 'console'
  bootPhase.value = 'parsing'
  bootMessage.value = '正在解析岗位筛选标准'
  bootSubmessage.value = `将按当前岗位标准一次性处理 ${files.length} 份 PDF 简历…`
  startError.value = ''
  workflowId.value = null
  parsedPreview.value = null
  platformStartResults.value = []
  parseStreamText.value = ''
  parseStreamStatuses.value = []

  const positionName = (inputs.chat_job_title || inputs.preset_label || '').trim()
  const parseBody =
    inputs.mode === 'unified'
      ? { unified_requirement: inputs.unified_requirement, position_name: positionName }
      : {
          search_requirement: inputs.search_requirement,
          screening_criteria: inputs.screening_criteria,
          position_name: positionName,
        }

  try {
    const parsed = await parseSearchIntentStream(parseBody, {
      onStatus: (text) => parseStreamStatuses.value.push(text),
      onDelta: (text) => { parseStreamText.value += text },
    })
    const baseCriteria =
      parsed.screening_criteria || (inputs.mode === 'split' ? inputs.screening_criteria : '')
    const finalMemory = inputs.preference_memory ?? null
    const finalCriteria = finalMemory?.screening_criteria?.trim() || baseCriteria
    parsedPreview.value = {
      ...parsed,
      search_requirement:
        parsed.search_requirement?.trim() ||
        (inputs.mode === 'unified' ? inputs.unified_requirement : inputs.search_requirement),
      screening_criteria: finalCriteria,
      chat_job_title: positionName,
    }
    if (inputs.preset_id) {
      persistJobPreset(inputs.preset_id, {
        screeningCriteria: finalCriteria,
        preferenceMemory: finalMemory,
        jobQaProfile: inputs.job_qa_profile ?? null,
      })
    }
    bootPhase.value = 'launching'
    bootMessage.value = '正在导入并启动筛选'
    bootSubmessage.value = 'PDF 不会保存到本机数据库或任务日志。'
    const res = await startPdfImport(
      {
        name: positionName || parsed.name || 'PDF 简历筛选',
        job_id: inputs.preset_id || 'local_pdf_import',
        job_description: parsed.job_description,
        screening_criteria: finalCriteria,
        preset_id: inputs.preset_id || '',
        preset_label: positionName,
        hr_preference_memory: finalMemory,
      },
      files,
    )
    platformStartResults.value = [{
      platform: 'local_pdf',
      platform_label: PLATFORM_LABELS.local_pdf,
      workflow_id: res.workflow_id,
      status: res.status,
      console_url: res.console_url,
      message: res.message,
    }]
    setWorkflowId(res.workflow_id)
    saveParsedToStorage(res.workflow_id, parsedPreview.value)
    bootPhase.value = 'ready'
    runningTasksBarRef.value?.refresh()
  } catch (e) {
    bootPhase.value = 'error'
    startError.value = e instanceof Error ? e.message : 'PDF 导入失败'
  }
}

function handleNewTask() {
  if (
    pageView.value === 'console' &&
    workflowId.value &&
    bootPhase.value === 'ready'
  ) {
    const ok = window.confirm(
      '当前任务将在后台继续运行（独立浏览器窗口）。\n确定返回首页并配置新的猎聘筛选任务？',
    )
    if (!ok) return
  }
  pageView.value = 'home'
  workflowId.value = null
  parsedPreview.value = null
  platformStartResults.value = []
  bootPhase.value = 'idle'
  bootMessage.value = ''
  bootSubmessage.value = ''
  parseStreamText.value = ''
  parseStreamStatuses.value = []
  startError.value = ''
  showHistory.value = false
  const url = new URL(window.location.href)
  url.searchParams.delete('workflow_id')
  window.history.replaceState({}, '', url.toString())
  runningTasksBarRef.value?.refresh()
}

async function handleExitTask() {
  if (bootPhase.value === 'parsing' || bootPhase.value === 'launching') {
    if (!window.confirm('解析或启动尚未完成，确定返回主界面？')) {
      return
    }
    handleNewTask()
    return
  }

  if (!workflowId.value) {
    if (!window.confirm('确定返回主界面？')) {
      return
    }
    handleNewTask()
    return
  }

  if (
    !window.confirm(
      '确定退出本次任务？正在运行的抓取/初筛/IM 跟进将停止，已处理的候选人数据会保留。',
    )
  ) {
    return
  }

  try {
    await cancelWorkflow(workflowId.value)
  } catch (e) {
    const msg = e instanceof Error ? e.message : '停止任务失败'
    if (!window.confirm(`${msg}\n仍返回主界面？`)) {
      return
    }
  }
  handleNewTask()
}

function formatHistoryTime(w: WorkflowInfo): string {
  const raw = w.log_summary?.last_ts || w.updated_at || w.created_at
  if (!raw) return '—'
  try {
    return new Date(raw).toLocaleString('zh-CN', { hour12: false })
  } catch {
    return raw
  }
}

function historyLogPreview(w: WorkflowInfo): string {
  const summary = w.log_summary
  if (!summary?.last_message) {
    return summary?.event_count ? `共 ${summary.event_count} 条日志` : '暂无日志'
  }
  const prefix = summary.event_count > 1 ? `[${summary.event_count}条] ` : ''
  return `${prefix}${summary.last_message}`
}

function historyLogLevelClass(w: WorkflowInfo): string {
  const level = w.log_summary?.last_level || 'info'
  return `history-log-${level}`
}

async function handleShowHistory() {
  showHistory.value = !showHistory.value
  if (showHistory.value) {
    try {
      history.value = await listWorkflows()
    } catch {
      history.value = []
    }
  }
}

async function openWorkflow(id: string) {
  setWorkflowId(id)
  pageView.value = 'console'
  bootPhase.value = 'ready'
  showHistory.value = false
  if (!platformStartResults.value.some((item) => item.workflow_id === id)) {
    platformStartResults.value = []
  }
  await restoreParsedPreview(id)
  runningTasksBarRef.value?.refresh()
}

const DELETE_CONFIRM_TEXT = '删除'

async function handleDeleteWorkflow(w: WorkflowInfo, event?: MouseEvent) {
  event?.stopPropagation()
  if (deletingWorkflowId.value) return

  const firstOk = window.confirm(
    `确定删除历史任务「${workflowPositionName(w)}」？\n\n将永久删除该任务在本地数据库中的全部数据：候选人快照、初筛结果、短名单与 IM 对话记录。\n\n此操作不可恢复。`,
  )
  if (!firstOk) return

  const typed = window.prompt(
    `二次确认：请输入「${DELETE_CONFIRM_TEXT}」以从数据库中删除该任务全部数据。`,
    '',
  )
  if (typed?.trim() !== DELETE_CONFIRM_TEXT) {
    if (typed !== null) {
      window.alert(`未确认删除。请输入「${DELETE_CONFIRM_TEXT}」以继续。`)
    }
    return
  }

  deletingWorkflowId.value = w.id
  try {
    await deleteWorkflow(w.id)
    clearParsedFromStorage(w.id)
    history.value = history.value.filter((item) => item.id !== w.id)
    if (workflowId.value === w.id) {
      handleNewTask()
    }
  } catch (e) {
    const msg = e instanceof Error ? e.message : '删除失败'
    window.alert(`删除失败：${msg}`)
  } finally {
    deletingWorkflowId.value = null
  }
}

onMounted(async () => {
  await readUrlWorkflow()
  try {
    const runtime = await getRuntimeSettings()
    setupReady.value =
      runtime.deepseek_configured && runtime.hr_identity_configured
  } catch {
    setupReady.value = false
  }
})
</script>

<template>
  <AppLayout
    show-history
    :show-pause-control="pageView === 'console' && Boolean(workflowId)"
    :show-exit-task="pageView === 'console'"
    :workflow-id="workflowId"
    @new-task="handleNewTask"
    @exit-task="handleExitTask"
    @show-history="handleShowHistory"
  >
    <RunningTasksBar
      ref="runningTasksBarRef"
      :current-workflow-id="workflowId"
      @open="openWorkflow"
    />

    <div v-if="showHistory" class="history card">
      <h2>历史任务</h2>
      <p class="history-hint">每条历史任务绑定本地任务日志；点击进入后可查看完整实时日志与筛选清单。</p>
      <div v-if="history.length === 0" class="empty">暂无历史任务</div>
      <ul v-else>
        <li v-for="w in history" :key="w.id">
          <button
            type="button"
            class="history-item"
            @click="openWorkflow(w.id)"
          >
            <div class="history-main">
              <div class="history-head">
                <span class="history-name">{{ workflowPositionName(w) }}</span>
                <span class="badge badge-running">{{ w.status }}</span>
              </div>
              <div class="history-meta">
                <span>{{ formatHistoryTime(w) }}</span>
                <span v-if="w.platform" class="history-platform">{{ w.platform }}</span>
              </div>
              <p class="history-log" :class="historyLogLevelClass(w)">
                {{ historyLogPreview(w) }}
              </p>
            </div>
          </button>
          <button
            type="button"
            class="btn-delete"
            :disabled="deletingWorkflowId === w.id"
            title="从数据库删除该任务全部数据（含绑定日志）"
            @click="handleDeleteWorkflow(w, $event)"
          >
            {{ deletingWorkflowId === w.id ? '删除中…' : '删除' }}
          </button>
        </li>
      </ul>
    </div>

    <template v-if="pageView === 'home'">
      <RuntimeSetupPanel
        @ready-change="setupReady = $event"
      />
      <LoginSetup @ready-change="loginReady = $event" />
      <SearchForm
        :login-ready="loginReady && setupReady"
        :pdf-import-ready="setupReady"
        @start="handleStart"
        @pdf-import="handlePdfImport"
      />
    </template>

    <template v-else>
      <ParseSummary v-if="parsedPreview" :parsed="parsedPreview" />

      <section v-if="platformStartResults.length > 1" class="card platform-results">
        <span class="platform-results-title">平台任务</span>
        <div class="platform-result-list">
          <button
            v-for="item in platformStartResults"
            :key="item.workflow_id"
            type="button"
            class="platform-result"
            :class="{ active: workflowId === item.workflow_id }"
            :disabled="workflowId === item.workflow_id"
            @click="openWorkflow(item.workflow_id)"
          >
            <strong>{{ item.platform_label }}</strong>
            <span>{{ item.status }}</span>
          </button>
        </div>
      </section>

      <section
        v-if="bootPhase === 'parsing' || bootPhase === 'launching'"
        class="card boot-panel"
      >
        <LoadingSpinner :message="bootMessage" :submessage="bootSubmessage" />
        <ParseStreamLog
          v-if="bootPhase === 'parsing' && (parseStreamText || parseStreamStatuses.length)"
          :text="parseStreamText"
          :statuses="parseStreamStatuses"
        />
      </section>

      <section v-if="bootPhase === 'error'" class="card boot-error">
        <p class="error-title">启动失败</p>
        <p class="error">{{ startError }}</p>
        <button class="btn-secondary" @click="handleNewTask">返回修改</button>
      </section>

      <div v-if="workflowId" class="console-shell">
        <TaskStatus :key="workflowId" :workflow-id="workflowId" />
        <ConsoleTabs :key="workflowId" :workflow-id="workflowId" />
      </div>

      <ConsoleSkeleton
        v-else-if="bootPhase === 'parsing' || bootPhase === 'launching'"
      />
    </template>
  </AppLayout>
</template>

<style scoped>
.console-shell {
  display: flex;
  flex-direction: column;
  gap: 0.65rem;
  flex: 1;
  min-height: 0;
  height: calc(100vh - 4.5rem);
}

.console-shell > :not(.console-tabs) {
  flex-shrink: 0;
}

.boot-panel {
  border: 2px solid var(--primary-light);
  padding-bottom: 0;
}

.boot-error {
  text-align: center;
  padding: 1.25rem;
}

.platform-results {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  margin-bottom: 0.65rem;
  padding: 0.65rem 0.85rem;
  border-color: #b8daf0;
}

.platform-results-title {
  flex-shrink: 0;
  font-size: 0.84rem;
  font-weight: 700;
  color: var(--primary-dark);
}

.platform-result-list {
  display: flex;
  flex-wrap: wrap;
  gap: 0.45rem;
  min-width: 0;
}

.platform-result {
  display: inline-flex;
  align-items: center;
  gap: 0.45rem;
  padding: 0.38rem 0.62rem;
  border-radius: 8px;
  border: 1px solid var(--border);
  background: #fff;
  color: var(--text);
  font-size: 0.8rem;
  cursor: pointer;
}

.platform-result.active {
  border-color: var(--primary);
  background: var(--primary-light);
  cursor: default;
}

.platform-result strong {
  font-size: 0.82rem;
}

.platform-result span {
  color: var(--text-muted);
}

.error-title {
  font-weight: 600;
  color: var(--error);
  margin-bottom: 0.5rem;
}

.history {
  margin-bottom: 1rem;
}

.history h2 {
  font-size: 1rem;
  margin-bottom: 0.35rem;
  color: var(--primary-dark);
}

.history-hint {
  margin: 0 0 0.75rem;
  font-size: 0.82rem;
  color: var(--text-muted);
}

.history ul {
  list-style: none;
}

.history li {
  display: flex;
  align-items: stretch;
  justify-content: space-between;
  gap: 0.5rem;
  padding: 0.55rem 0.75rem;
  border-radius: 8px;
  font-size: 0.9rem;
  border: 1px solid var(--border);
  margin-bottom: 0.5rem;
}

.history-item {
  flex: 1;
  display: block;
  padding: 0;
  border: none;
  background: transparent;
  cursor: pointer;
  font: inherit;
  color: inherit;
  text-align: left;
  min-width: 0;
}

.history-item:hover .history-name {
  color: var(--primary-dark);
}

.history-main {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  min-width: 0;
}

.history-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
}

.history-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 0.45rem;
  font-size: 0.78rem;
  color: var(--text-muted);
}

.history-platform {
  text-transform: uppercase;
}

.history-log {
  margin: 0;
  font-size: 0.8rem;
  line-height: 1.45;
  color: var(--text-muted);
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  word-break: break-word;
}

.history-log-success {
  color: #1f7a43;
}

.history-log-warn {
  color: #b36b00;
}

.history-log-error {
  color: var(--error, #c0392b);
}

.history-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-weight: 600;
}

.btn-delete {
  flex-shrink: 0;
  border: 1px solid var(--error, #c0392b);
  background: transparent;
  color: var(--error, #c0392b);
  border-radius: 4px;
  padding: 0.2rem 0.55rem;
  font-size: 0.78rem;
  cursor: pointer;
}

.btn-delete:hover:not(:disabled) {
  background: color-mix(in srgb, var(--error, #c0392b) 12%, transparent);
}

.btn-delete:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.empty {
  color: var(--text-muted);
  font-size: 0.9rem;
}

.error {
  color: var(--error);
  margin-bottom: 1rem;
  font-size: 0.9rem;
}

@media (max-width: 768px) {
  .console-shell {
    height: auto;
    min-height: calc(100vh - 4.5rem);
  }

  .platform-results {
    align-items: flex-start;
    flex-direction: column;
  }
}
</style>
