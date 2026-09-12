<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import {
  getReplyJudgmentQueue,
  getReplyJudgmentReport,
  getReplyJudgmentStatus,
  openResumeLibrary,
  startReplyJudgment,
  stopReplyJudgment,
} from '../api'
import type { ReplyJudgmentSummaryReport } from '../types'

const props = defineProps<{ workflowId: string; embedded?: boolean }>()

type JudgmentResult = {
  candidate_snapshot_id?: string
  display_name?: string | null
  ok?: boolean
  skipped?: boolean
  updated_level?: string
  followup_passed?: boolean
  summary_for_list?: string
  error?: string
}

type JudgmentStatus = {
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
  results: JudgmentResult[]
  report_ready?: boolean
  summary_report?: ReplyJudgmentSummaryReport | null
  report_error?: string | null
  message: string
}

const queueCount = ref(0)
const status = ref<JudgmentStatus | null>(null)
const report = ref<ReplyJudgmentSummaryReport | null>(null)
const busy = ref(false)
const actionMessage = ref('')
const reportCollapsed = ref(false)
const jumpingId = ref<string | null>(null)
const jumpMessage = ref('')

const running = computed(() => status.value?.running ?? false)
const activeReport = computed(() => report.value || status.value?.summary_report)
const reportCandidates = computed(() => activeReport.value?.ranked_candidates || [])
const renderedSummary = computed(() => renderMarkdown(activeReport.value?.summary || ''))

const phaseLabel = computed(() => {
  const p = status.value?.phase || 'standby'
  const map: Record<string, string> = {
    standby: '待机',
    judging: '回复终判中',
    summarizing: '总结排名中',
    stopped: '已停止',
  }
  return map[p] || p
})

const levelLabel = (level?: string) => {
  const map: Record<string, string> = {
    observe: '候选',
    followup: '继续追问',
    exclude: '排除',
  }
  return level ? map[level] || level : '-'
}

const priorityLabel = (priority?: string) => {
  const map: Record<string, string> = {
    high: '高',
    medium: '中',
    low: '低',
  }
  return priority ? map[priority] || priority : '中'
}

function escapeHtml(text: string) {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

function renderInlineMarkdown(text: string) {
  return escapeHtml(text)
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
}

function isMarkdownTableLine(line: string) {
  const text = line.trim()
  return text.startsWith('|') && text.endsWith('|') && text.split('|').length >= 3
}

function isMarkdownTableSeparator(line: string) {
  return /^\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?$/.test(line.trim())
}

function splitMarkdownTableRow(line: string) {
  return line
    .trim()
    .replace(/^\|/, '')
    .replace(/\|$/, '')
    .split('|')
    .map((cell) => cell.trim())
}

function renderMarkdownTable(lines: string[]) {
  const rows = lines.filter((line) => isMarkdownTableLine(line) && !isMarkdownTableSeparator(line))
  if (!rows.length) return ''
  const header = splitMarkdownTableRow(rows[0])
  const body = rows.slice(1).map(splitMarkdownTableRow)
  const th = header.map((cell) => `<th>${renderInlineMarkdown(cell)}</th>`).join('')
  const trs = body
    .map((row) => `<tr>${row.map((cell) => `<td>${renderInlineMarkdown(cell)}</td>`).join('')}</tr>`)
    .join('')
  return `<div class="markdown-table-wrap"><table><thead><tr>${th}</tr></thead><tbody>${trs}</tbody></table></div>`
}

function renderMarkdown(markdown: string) {
  const lines = (markdown || '').replace(/\r\n/g, '\n').split('\n')
  const html: string[] = []
  let listOpen = false

  const closeList = () => {
    if (listOpen) {
      html.push('</ul>')
      listOpen = false
    }
  }

  for (let i = 0; i < lines.length; i += 1) {
    const line = lines[i].trim()
    if (!line) {
      closeList()
      continue
    }
    if (isMarkdownTableLine(line)) {
      closeList()
      const tableLines: string[] = []
      for (; i < lines.length; i += 1) {
        const next = lines[i].trim()
        const nextNonEmpty = lines.slice(i + 1).find((candidate) => candidate.trim())
        if (!next && nextNonEmpty && isMarkdownTableLine(nextNonEmpty.trim())) {
          continue
        }
        if (isMarkdownTableLine(next)) {
          tableLines.push(next)
          continue
        }
        i -= 1
        break
      }
      html.push(renderMarkdownTable(tableLines))
      continue
    }
    if (/^-{3,}$/.test(line)) {
      closeList()
      html.push('<hr>')
      continue
    }
    const heading = /^(#{1,3})\s+(.+)$/.exec(line)
    if (heading) {
      closeList()
      const level = Math.min(heading[1].length + 2, 5)
      html.push(`<h${level}>${renderInlineMarkdown(heading[2])}</h${level}>`)
      continue
    }
    const bullet = /^[-*]\s+(.+)$/.exec(line)
    if (bullet) {
      if (!listOpen) {
        html.push('<ul>')
        listOpen = true
      }
      html.push(`<li>${renderInlineMarkdown(bullet[1])}</li>`)
      continue
    }
    const ordered = /^\d+[.)]\s+(.+)$/.exec(line)
    if (ordered) {
      if (!listOpen) {
        html.push('<ul>')
        listOpen = true
      }
      html.push(`<li>${renderInlineMarkdown(ordered[1])}</li>`)
      continue
    }
    closeList()
    html.push(`<p>${renderInlineMarkdown(line)}</p>`)
  }

  closeList()
  return html.join('')
}

async function refreshQueue() {
  try {
    const res = await getReplyJudgmentQueue(props.workflowId)
    queueCount.value = res.count
  } catch {
    queueCount.value = 0
  }
}

async function refreshReport() {
  try {
    const res = await getReplyJudgmentReport(props.workflowId)
    report.value = res.ready ? res.report : null
  } catch {
    report.value = null
  }
}

async function refreshStatus() {
  try {
    const next = await getReplyJudgmentStatus(props.workflowId)
    status.value = next
    if (!next.running) {
      await refreshReport()
    } else if (next.summary_report) {
      report.value = next.summary_report
    }
  } catch {
    status.value = null
  }
}

async function handleStart() {
  busy.value = true
  actionMessage.value = ''
  report.value = null
  try {
    const res = await startReplyJudgment(props.workflowId)
    actionMessage.value = res.message || '回复判定 Agent 已启动'
    await refreshStatus()
    await refreshQueue()
  } catch (e) {
    actionMessage.value = e instanceof Error ? e.message : '启动失败'
  } finally {
    busy.value = false
  }
}

async function handleStop() {
  busy.value = true
  actionMessage.value = ''
  try {
    const res = await stopReplyJudgment(props.workflowId)
    actionMessage.value = res.message || '已请求停止'
    await refreshStatus()
  } catch (e) {
    actionMessage.value = e instanceof Error ? e.message : '停止失败'
  } finally {
    busy.value = false
  }
}

async function jumpToResumeLibrary(snapshotId: string) {
  if (!snapshotId || jumpingId.value) return
  jumpingId.value = snapshotId
  jumpMessage.value = ''
  try {
    const res = await openResumeLibrary(props.workflowId, snapshotId)
    jumpMessage.value = res.message || '已打开简历库'
  } catch (e) {
    jumpMessage.value = e instanceof Error ? e.message : '跳转简历库失败'
  } finally {
    jumpingId.value = null
  }
}

let timer: ReturnType<typeof setInterval> | null = null

function resetState() {
  queueCount.value = 0
  status.value = null
  report.value = null
  busy.value = false
  actionMessage.value = ''
  reportCollapsed.value = false
  jumpingId.value = null
  jumpMessage.value = ''
}

function startPolling() {
  if (timer) clearInterval(timer)
  timer = setInterval(() => {
    refreshStatus()
    if (!running.value) refreshQueue()
  }, 3000)
}

async function loadAll() {
  await Promise.all([refreshQueue(), refreshStatus(), refreshReport()])
}

onMounted(() => {
  void loadAll()
  startPolling()
})

watch(
  () => props.workflowId,
  (id, prev) => {
    if (id === prev) return
    resetState()
    if (id) {
      void loadAll()
      startPolling()
    } else if (timer) {
      clearInterval(timer)
      timer = null
    }
  },
)

onUnmounted(() => {
  if (timer) clearInterval(timer)
})
</script>

<template>
  <div class="reply-judgment-panel" :class="{ card: !embedded, embedded }">
    <h2 v-if="!embedded">最终判定</h2>
    <p class="hint">
      手动启动后先串行收集回复并终判，再自动生成候选人优先级排序和总结报告。
    </p>

    <div class="status-row">
      <span class="phase-badge" :class="status?.phase || 'standby'">{{ phaseLabel }}</span>
      <span class="queue-count">待处理 {{ queueCount }} 人</span>
    </div>

    <div class="stage-row">
      <span :class="{ active: status?.phase === 'judging', done: status?.phase === 'summarizing' || status?.report_ready }">
        1 回复终判
      </span>
      <span :class="{ active: status?.phase === 'summarizing', done: status?.report_ready }">
        2 总结排名
      </span>
    </div>

    <p v-if="status?.message" class="status-msg">{{ status.message }}</p>
    <p v-if="running && status?.current_name" class="progress-line">
      正在处理：{{ status.current_name }}（{{ status.current_index }}/{{ status.total }}）
    </p>
    <p v-if="status?.report_error" class="error-msg">
      总结排名失败：{{ status.report_error }}
    </p>

    <div class="actions">
      <button class="btn-primary" :disabled="busy || running" @click="handleStart">
        启动最终判定
      </button>
      <button class="btn-secondary" :disabled="busy || !running" @click="handleStop">
        停止
      </button>
    </div>
    <p v-if="actionMessage" class="action-msg">{{ actionMessage }}</p>

    <div v-if="status && status.processed > 0" class="stats-row">
      <span>已处理 {{ status.processed }}</span>
      <span>追问通过 {{ status.passed }}</span>
      <span>仍需追问 {{ status.still_followup }}</span>
      <span>排除 {{ status.excluded }}</span>
      <span>跳过 {{ status.skipped }}</span>
      <span v-if="status.failed">失败 {{ status.failed }}</span>
    </div>

    <div v-if="status?.results?.length" class="result-list">
      <h3>最近终判结果</h3>
      <div v-for="(r, i) in status.results" :key="i" class="result-item">
        <div class="result-head">
          <strong>{{ r.display_name || r.candidate_snapshot_id?.slice(0, 8) }}</strong>
          <span v-if="r.ok && !r.skipped" class="level-tag">{{ levelLabel(r.updated_level) }}</span>
          <span v-if="r.followup_passed" class="pass-tag">追问通过</span>
          <span v-else-if="r.skipped" class="skip-tag">跳过</span>
          <span v-else-if="!r.ok" class="fail-tag">失败</span>
        </div>
        <p v-if="r.summary_for_list" class="result-summary">{{ r.summary_for_list }}</p>
        <p v-else-if="r.error" class="result-error">{{ r.error }}</p>
      </div>
    </div>

    <div v-if="activeReport" class="summary-report" :class="{ collapsed: reportCollapsed }">
      <div class="summary-report-head">
        <h3>候选人总结报告</h3>
        <button type="button" class="btn-collapse" @click="reportCollapsed = !reportCollapsed">
          {{ reportCollapsed ? '展开' : '收起' }}
        </button>
      </div>
      <div v-show="!reportCollapsed" class="report-markdown" v-html="renderedSummary"></div>
    </div>

    <p v-if="jumpMessage" class="jump-banner" :class="{ error: jumpMessage.includes('失败') || jumpMessage.includes('未') }">
      {{ jumpMessage }}
    </p>

    <div v-if="activeReport && reportCandidates.length" class="rank-list report-rank-list">
      <h3>候选人优先级列表</h3>
        <div v-for="item in reportCandidates" :key="item.candidate_snapshot_id" class="rank-item">
          <div class="rank-head">
            <strong>#{{ item.rank }} {{ item.display_name || item.candidate_snapshot_id.slice(0, 8) }}</strong>
            <span class="priority-tag">优先级 {{ priorityLabel(item.priority) }}</span>
            <span v-if="item.followup_passed" class="pass-tag">追问通过</span>
            <button
              type="button"
              class="btn-jump"
              :disabled="jumpingId === item.candidate_snapshot_id"
              @click="jumpToResumeLibrary(item.candidate_snapshot_id)"
            >
              {{ jumpingId === item.candidate_snapshot_id ? '正在打开…' : '跳转简历库' }}
            </button>
          </div>
          <p v-if="item.recommendation" class="recommendation">{{ item.recommendation }}</p>
          <p v-if="item.talking_points.length" class="points">
            沟通切入：{{ item.talking_points.join('；') }}
          </p>
          <p v-if="item.risk_points.length" class="risks">
            风险点：{{ item.risk_points.join('；') }}
          </p>
        </div>
    </div>

    <p v-if="!activeReport && !running && queueCount === 0" class="empty-hint">
      暂无待判定会话。需要先通过 IM 发出追问或要简历，候选人回复后再启动最终判定。
    </p>
  </div>
</template>

<style scoped>
.reply-judgment-panel {
  display: flex;
  flex-direction: column;
  min-height: 0;
}

.reply-judgment-panel.embedded {
  height: 100%;
  padding: 0.65rem 0.85rem 0.75rem;
  overflow: hidden;
}

.reply-judgment-panel.embedded .result-list,
.reply-judgment-panel.embedded .report-rank-list {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
}

.reply-judgment-panel.embedded .summary-report {
  flex-shrink: 0;
  max-height: 42%;
  overflow-y: auto;
}

.reply-judgment-panel h2 {
  font-size: 1.05rem;
  color: var(--primary-dark);
  margin-bottom: 0.5rem;
}

.hint {
  font-size: 0.78rem;
  color: var(--text-muted);
  margin-bottom: 0.45rem;
  line-height: 1.45;
}

.status-row,
.stage-row,
.actions,
.stats-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
}

.status-row {
  gap: 0.75rem;
  margin-bottom: 0.45rem;
}

.stage-row {
  gap: 0.5rem;
  margin-bottom: 0.45rem;
}

.stage-row span {
  font-size: 0.75rem;
  padding: 0.18rem 0.5rem;
  border-radius: 4px;
  color: var(--text-muted);
  background: #f3f4f6;
}

.stage-row span.active {
  color: #1d4ed8;
  background: #eff6ff;
}

.stage-row span.done {
  color: #047857;
  background: #ecfdf5;
}

.phase-badge {
  font-size: 0.75rem;
  font-weight: 600;
  padding: 0.15rem 0.5rem;
  border-radius: 4px;
}

.phase-badge.standby {
  background: #ecfdf5;
  color: #047857;
}

.phase-badge.judging,
.phase-badge.summarizing {
  background: #eff6ff;
  color: #1d4ed8;
}

.phase-badge.stopped {
  background: #fef2f2;
  color: #b91c1c;
}

.queue-count,
.stats-row,
.result-list h3,
.summary-report h3 {
  font-size: 0.82rem;
  color: var(--text-muted);
}

.status-msg,
.progress-line,
.error-msg {
  font-size: 0.82rem;
  padding: 0.35rem 0.6rem;
  border-radius: 6px;
  margin-bottom: 0.45rem;
}

.status-msg,
.progress-line {
  color: #1e40af;
  background: #eff6ff;
}

.error-msg {
  color: #b91c1c;
  background: #fef2f2;
}

.actions {
  gap: 0.5rem;
  margin-bottom: 0.5rem;
}

.action-msg {
  font-size: 0.85rem;
  color: var(--primary-dark);
  margin-bottom: 0.5rem;
}

.stats-row {
  gap: 0.75rem;
  margin-bottom: 0.65rem;
}

.result-list h3,
.summary-report h3 {
  margin-bottom: 0.45rem;
}

.result-item,
.rank-item {
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 0.55rem 0.65rem;
  margin-bottom: 0.45rem;
  background: var(--bg);
}

.result-head,
.rank-head {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  flex-wrap: wrap;
}

.level-tag,
.pass-tag,
.skip-tag,
.fail-tag,
.priority-tag {
  font-size: 0.72rem;
  padding: 0.1rem 0.4rem;
  border-radius: 4px;
}

.level-tag,
.priority-tag {
  background: #dbeafe;
  color: #1e40af;
}

.pass-tag {
  background: #d1fae5;
  color: #047857;
}

.skip-tag {
  background: #f3f4f6;
  color: #6b7280;
}

.fail-tag {
  background: #fee2e2;
  color: #b91c1c;
}

.result-summary,
.result-error,
.report-summary,
.recommendation,
.points,
.risks {
  font-size: 0.82rem;
  margin-top: 0.3rem;
  line-height: 1.4;
}

.result-summary,
.report-summary,
.recommendation {
  color: var(--text-muted);
}

.points {
  color: #047857;
}

.risks,
.result-error {
  color: #b91c1c;
}

.summary-report {
  margin-top: 0.55rem;
  min-height: 0;
  position: sticky;
  top: 0;
  z-index: 5;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--bg);
  box-shadow: 0 8px 18px rgba(15, 23, 42, 0.08);
  padding: 0.6rem 0.7rem;
}

.summary-report.collapsed {
  overflow: hidden;
}

.summary-report-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
}

.summary-report-head h3 {
  margin: 0;
}

.btn-collapse,
.btn-jump {
  border: none;
  border-radius: 6px;
  cursor: pointer;
  font-size: 0.76rem;
  line-height: 1.2;
}

.btn-collapse {
  color: #1e40af;
  background: #eff6ff;
  padding: 0.28rem 0.55rem;
}

.btn-jump {
  margin-left: auto;
  color: #fff;
  background: var(--primary);
  padding: 0.3rem 0.62rem;
}

.btn-jump:disabled {
  opacity: 0.65;
  cursor: wait;
}

.report-markdown {
  margin-top: 0.45rem;
  color: var(--text-muted);
  font-size: 0.82rem;
  line-height: 1.5;
}

.report-markdown :deep(p) {
  margin: 0.28rem 0;
}

.report-markdown :deep(h3),
.report-markdown :deep(h4),
.report-markdown :deep(h5) {
  margin: 0.45rem 0 0.25rem;
  color: var(--text);
  font-size: 0.86rem;
}

.report-markdown :deep(ul) {
  margin: 0.3rem 0 0.3rem 1.1rem;
  padding: 0;
}

.report-markdown :deep(li) {
  margin: 0.18rem 0;
}

.report-markdown :deep(code) {
  padding: 0.05rem 0.25rem;
  border-radius: 4px;
  background: #f3f4f6;
  color: #374151;
}

.report-markdown :deep(.markdown-table-wrap) {
  width: 100%;
  overflow-x: auto;
  margin: 0.45rem 0;
}

.report-markdown :deep(table) {
  width: 100%;
  min-width: 520px;
  border-collapse: collapse;
}

.report-markdown :deep(th),
.report-markdown :deep(td) {
  border: 1px solid var(--border);
  padding: 0.38rem 0.5rem;
  text-align: left;
  vertical-align: top;
  font-size: 0.78rem;
}

.report-markdown :deep(th) {
  background: #f8fafc;
  color: var(--text);
  font-weight: 600;
}

.report-markdown :deep(hr) {
  border: 0;
  border-top: 1px solid var(--border);
  margin: 0.6rem 0;
}

.report-rank-list {
  margin-top: 0.55rem;
}

.report-rank-list h3 {
  margin-bottom: 0.45rem;
}

.jump-banner {
  margin-top: 0.45rem;
  padding: 0.45rem 0.65rem;
  border-radius: 6px;
  font-size: 0.82rem;
  background: #ecfdf5;
  color: #047857;
}

.jump-banner.error {
  background: #fef2f2;
  color: #b91c1c;
}

.empty-hint {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 0.85rem;
  color: var(--text-muted);
  text-align: center;
  padding: 1rem;
}
</style>
