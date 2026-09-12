<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { getPdfImportReport, getPdfImportStatus, regeneratePdfImportReport } from '../api'
import type { ReplyJudgmentSummaryReport } from '../types'
import { renderMarkdownReport } from '../utils/markdownReport'

const props = defineProps<{ workflowId: string; embedded?: boolean }>()

const report = ref<ReplyJudgmentSummaryReport | null>(null)
const rankingState = ref('queued')
const rankingError = ref('')
const detailsOpen = ref(false)
const regenerating = ref(false)
let timer: ReturnType<typeof setInterval> | null = null

const renderedSummary = computed(() => renderMarkdownReport(report.value?.summary || ''))
const rankingStateLabel = computed(() => ({
  queued: '等待筛选完成',
  ranking: '综合排名生成中',
  completed: '综合排名已完成',
  failed: '综合排名生成失败',
}[rankingState.value] || rankingState.value))

async function refresh() {
  try {
    const [statusResult, reportResult] = await Promise.all([
      getPdfImportStatus(props.workflowId),
      getPdfImportReport(props.workflowId),
    ])
    rankingState.value = statusResult.progress.ranking_state
    rankingError.value = statusResult.progress.ranking_error
    report.value = reportResult.ready ? reportResult.report : null
  } catch {
    /* Keep the last successful state while a workflow is being created. */
  }
}

async function regenerate() {
  regenerating.value = true
  try {
    await regeneratePdfImportReport(props.workflowId)
    await refresh()
  } finally {
    regenerating.value = false
  }
}

function startPolling() {
  if (timer) clearInterval(timer)
  void refresh()
  timer = setInterval(() => void refresh(), 2000)
}

onMounted(startPolling)
watch(() => props.workflowId, startPolling)
onUnmounted(() => { if (timer) clearInterval(timer) })
</script>

<template>
  <section class="pdf-ranking-panel" :class="{ card: !embedded }">
    <header>
      <div>
        <h2>综合排名</h2>
        <p>全部通过初筛的候选人均会获得最终名次；排名 Agent 会复核初筛分数靠前的人选。</p>
      </div>
      <span class="state" :class="rankingState">{{ rankingStateLabel }}</span>
    </header>

    <div class="actions">
      <button type="button" class="btn-secondary" :disabled="regenerating || rankingState === 'ranking'" @click="regenerate">
        {{ regenerating || rankingState === 'ranking' ? '排名生成中…' : '重新生成排名' }}
      </button>
    </div>
    <p v-if="rankingError" class="error">{{ rankingError }}</p>
    <p v-else-if="!report" class="hint">PDF 筛选完成后将自动生成综合排名和推进建议。</p>

    <template v-else>
      <div class="summary" v-html="renderedSummary"></div>
      <button type="button" class="btn-secondary" @click="detailsOpen = !detailsOpen">
        {{ detailsOpen ? '收起候选人详情' : `查看 ${report.ranked_candidates.length} 位候选人详情` }}
      </button>
      <div v-if="detailsOpen" class="rank-list">
        <article v-for="item in report.ranked_candidates" :key="item.candidate_snapshot_id" class="rank-item">
          <div class="rank-head">
            <strong>#{{ item.rank }} {{ item.display_name || item.candidate_snapshot_id.slice(0, 8) }}</strong>
            <span>评分 {{ item.score ?? '-' }}</span>
            <span>优先级 {{ item.priority || 'medium' }}</span>
          </div>
          <p v-if="item.recommendation">{{ item.recommendation }}</p>
          <p v-if="item.talking_points.length" class="points">沟通切入：{{ item.talking_points.join('；') }}</p>
          <p v-if="item.risk_points.length" class="risks">风险点：{{ item.risk_points.join('；') }}</p>
        </article>
      </div>
    </template>
  </section>
</template>

<style scoped>
.pdf-ranking-panel { height: 100%; padding: 1rem; overflow: auto; }
header { display: flex; justify-content: space-between; gap: 1rem; align-items: start; }
h2 { margin: 0; font-size: 1rem; color: var(--primary-dark); }
header p, .hint, .error { margin: .35rem 0 0; color: var(--text-muted); font-size: .82rem; line-height: 1.5; }
.error { color: var(--error); }
.state { border: 1px solid #bfdbfe; color: var(--primary-dark); background: #eff6ff; padding: .3rem .55rem; border-radius: 8px; font-size: .8rem; white-space: nowrap; }
.state.completed { border-color: #86efac; color: #166534; background: #f0fdf4; }
.state.failed { border-color: #fecaca; color: #b91c1c; background: #fef2f2; }
.summary { margin: 1rem 0; }
.actions { margin-top: .65rem; }
.summary :deep(h3), .summary :deep(h4), .summary :deep(h5) { margin: 1rem 0 .45rem; color: var(--primary-dark); }
.summary :deep(p), .summary :deep(li) { font-size: .86rem; line-height: 1.6; }
.summary :deep(.markdown-table-wrap) { overflow-x: auto; }
.summary :deep(table) { width: 100%; border-collapse: collapse; font-size: .8rem; }
.summary :deep(th), .summary :deep(td) { border: 1px solid var(--border); padding: .45rem; text-align: left; vertical-align: top; }
.summary :deep(th) { background: var(--primary-light); }
.rank-list { display: grid; gap: .6rem; margin-top: .8rem; }
.rank-item { border: 1px solid var(--border); border-radius: 8px; padding: .75rem; }
.rank-head { display: flex; flex-wrap: wrap; gap: .5rem .75rem; align-items: center; }
.rank-head span { color: var(--text-muted); font-size: .8rem; }
.rank-item p { margin: .45rem 0 0; font-size: .84rem; line-height: 1.5; }
.points { color: #166534; }
.risks { color: #b45309; }
</style>
