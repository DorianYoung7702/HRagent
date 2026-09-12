<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import type { CandidateItem, ShortlistItem } from '../types'
import { getCandidates, getShortlist, openResumeLibrary } from '../api'
import { subscribeWorkflowRefresh } from '../utils/workflowRefreshBus'

const props = defineProps<{
  workflowId: string
  embedded?: boolean
  active?: boolean
}>()

const tab = ref<'observe' | 'followup' | 'exclude' | 'all'>('all')
const candidates = ref<CandidateItem[]>([])
const shortlist = ref<ShortlistItem[]>([])
const jumpingId = ref<string | null>(null)
const jumpMessage = ref<string | null>(null)
let timer: ReturnType<typeof setInterval> | null = null
let unsubscribeRefresh: (() => void) | null = null

function pollMs() {
  return props.active ? 2000 : 5000
}

function restartTimer() {
  if (timer) clearInterval(timer)
  timer = setInterval(refresh, pollMs())
}

const observeList = computed(() =>
  candidates.value.filter((c) => c.screening?.level === 'observe'),
)
const followupList = computed(() =>
  candidates.value.filter((c) => c.screening?.level === 'followup'),
)
const excludeList = computed(() =>
  candidates.value.filter((c) => c.screening?.level === 'exclude'),
)

const displayList = computed(() => {
  if (tab.value === 'observe') return observeList.value
  if (tab.value === 'followup') return followupList.value
  if (tab.value === 'exclude') return excludeList.value
  return candidates.value
})

function levelBadge(level: string | null | undefined) {
  if (level === 'observe') return 'badge-observe'
  if (level === 'followup') return 'badge-followup'
  if (level === 'exclude') return 'badge-exclude'
  return 'badge-exclude'
}

function levelLabel(level: string | null | undefined) {
  const map: Record<string, string> = { observe: '观察', followup: '追问', exclude: '排除' }
  return level ? map[level] || level : '—'
}

function isFollowupPassed(c: CandidateItem) {
  return Boolean(c.metadata?.followup_passed || c.screening?.score_detail?.followup_passed)
}

function criteriaVersion(c: CandidateItem) {
  const version = c.screening?.score_detail?.criteria_version
  return typeof version === 'number' || typeof version === 'string' ? String(version) : ''
}

function candidateSubtitle(c: CandidateItem) {
  const meta = c.metadata || {}
  const age = meta.age || meta.card_age
  const agePart = age ? `${age}岁` : ''
  const school =
    (meta.school as string) ||
    (meta.card_school as string) ||
    (typeof c.education === 'string' ? c.education : '') ||
    ''
  const parts = [agePart, school].filter(Boolean)
  return parts.length ? parts.join(' · ') : '—'
}

async function refresh() {
  try {
    candidates.value = await getCandidates(props.workflowId)
  } catch {
    /* ignore */
  }
  try {
    const sl = await getShortlist(props.workflowId)
    shortlist.value = sl.candidates
  } catch {
    shortlist.value = []
  }
}

function canJumpToLibrary(c: CandidateItem) {
  return c.platform !== 'local_pdf' && (c.screening?.level === 'observe' || c.screening?.level === 'followup')
}

async function jumpToResumeLibrary(c: CandidateItem) {
  if (!canJumpToLibrary(c) || jumpingId.value) return
  jumpingId.value = c.id
  jumpMessage.value = null
  try {
    const res = await openResumeLibrary(props.workflowId, c.id)
    jumpMessage.value = res.message || '已打开在线简历，任务完成'
  } catch (e) {
    jumpMessage.value = e instanceof Error ? e.message : '跳转失败'
  } finally {
    jumpingId.value = null
  }
}

function bindRefreshSubscription(id: string) {
  unsubscribeRefresh?.()
  unsubscribeRefresh = subscribeWorkflowRefresh(id, () => {
    refresh()
  })
}

function resetState() {
  candidates.value = []
  shortlist.value = []
  jumpingId.value = null
  jumpMessage.value = null
}

onMounted(() => {
  refresh()
  restartTimer()
  bindRefreshSubscription(props.workflowId)
})

watch(
  () => props.workflowId,
  (id, prev) => {
    if (id === prev) return
    resetState()
    if (id) {
      bindRefreshSubscription(id)
      void refresh()
      restartTimer()
    } else {
      unsubscribeRefresh?.()
      unsubscribeRefresh = null
      if (timer) clearInterval(timer)
      timer = null
    }
  },
)

onUnmounted(() => {
  if (timer) clearInterval(timer)
  unsubscribeRefresh?.()
})
</script>

<template>
  <div class="candidate-list" :class="{ card: !embedded, embedded }">
    <div class="list-header">
      <h2 v-if="!embedded">筛选清单</h2>
      <div class="tabs">
        <button :class="{ active: tab === 'observe' }" @click="tab = 'observe'">
          观察 ({{ observeList.length }})
        </button>
        <button :class="{ active: tab === 'followup' }" @click="tab = 'followup'">
          追问 ({{ followupList.length }})
        </button>
        <button :class="{ active: tab === 'exclude' }" @click="tab = 'exclude'">
          排除 ({{ excludeList.length }})
        </button>
        <button :class="{ active: tab === 'all' }" @click="tab = 'all'">
          全部 ({{ candidates.length }})
        </button>
      </div>
    </div>

    <div v-if="jumpMessage" class="jump-banner" :class="{ error: jumpMessage.includes('失败') || jumpMessage.includes('未') }">
      {{ jumpMessage }}
    </div>

    <div v-if="displayList.length === 0" class="empty">
      暂无{{ tab === 'observe' ? '观察' : tab === 'followup' ? '追问' : tab === 'exclude' ? '排除' : '' }}候选人，任务进行中请稍候…
    </div>

    <div v-else class="cards">
      <div v-for="c in displayList" :key="c.id" class="cand-card">
        <div class="cand-top">
          <strong>{{ c.display_name || '未知' }}</strong>
          <span class="badge" :class="levelBadge(c.screening?.level)">
            {{ levelLabel(c.screening?.level) }}
          </span>
          <span v-if="isFollowupPassed(c)" class="followup-passed-badge">追问通过</span>
          <span v-if="c.platform === 'local_pdf'" class="pdf-badge">一次性 PDF 解析</span>
          <span v-if="criteriaVersion(c)" class="criteria-version-badge">
            标准 v{{ criteriaVersion(c) }}
          </span>
        </div>
        <div class="cand-meta">{{ candidateSubtitle(c) }}</div>
        <div v-if="c.screening?.resume_summary" class="cand-summary">
          <span class="label">AI 简历总结</span>
          <p>{{ c.screening.resume_summary }}</p>
        </div>
        <div v-if="c.screening?.reason" class="cand-reason">
          <span class="label">AI 判定理由</span>
          <p>{{ c.screening.reason }}</p>
        </div>
        <div v-if="c.screening?.criteria_analysis" class="cand-analysis">
          <span class="label">标准对照</span>
          <p>{{ c.screening.criteria_analysis }}</p>
        </div>
        <div v-if="c.screening?.summary_for_list" class="cand-enrich">
          <span class="label">IM 补充</span>
          <p>{{ c.screening.summary_for_list }}</p>
        </div>
        <div v-if="c.metadata?.need_resume_request" class="cand-resume-flag">待索要简历</div>
        <div v-if="c.screening?.missing_info?.length" class="cand-followup">
          待追问：{{ c.screening.missing_info[0].question }}
        </div>
        <div v-if="canJumpToLibrary(c)" class="cand-actions">
          <button
            type="button"
            class="btn-jump"
            :disabled="jumpingId === c.id"
            @click="jumpToResumeLibrary(c)"
          >
            {{ jumpingId === c.id ? '正在打开…' : '跳转简历库' }}
          </button>
        </div>
      </div>
    </div>

    <div v-if="shortlist.length" class="shortlist-note">
      Shortlist 已生成 {{ shortlist.length }} 人
    </div>
  </div>
</template>

<style scoped>
.candidate-list {
  display: flex;
  flex-direction: column;
  min-height: 0;
}

.candidate-list.embedded {
  height: 100%;
  padding: 0.65rem 0.85rem 0.75rem;
}

.list-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 0.5rem;
  flex-wrap: wrap;
  gap: 0.5rem;
  flex-shrink: 0;
}

.list-header h2 {
  font-size: 1.05rem;
  color: var(--primary-dark);
}

.tabs {
  display: flex;
  gap: 0.35rem;
}

.tabs button {
  background: var(--primary-light);
  color: var(--text-muted);
  padding: 0.35rem 0.75rem;
  font-size: 0.82rem;
  border-radius: 6px;
  border: 1px solid transparent;
}

.tabs button.active {
  background: var(--primary);
  color: white;
  border-color: var(--primary-dark);
}

.empty {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  text-align: center;
  color: var(--text-muted);
  padding: 1rem;
  font-size: 0.85rem;
}

.cards {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  flex: 1;
  min-height: 0;
  overflow-y: auto;
}

.cand-card {
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 0.75rem 1rem;
}

.cand-top {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  flex-wrap: wrap;
  margin-bottom: 0.25rem;
}

.cand-top strong {
  margin-right: auto;
}

.followup-passed-badge {
  font-size: 0.72rem;
  font-weight: 600;
  padding: 0.12rem 0.42rem;
  border-radius: 4px;
  color: #047857;
  background: #d1fae5;
  white-space: nowrap;
}

.criteria-version-badge {
  font-size: 0.72rem;
  font-weight: 600;
  padding: 0.12rem 0.42rem;
  border-radius: 4px;
  color: #475569;
  background: #e2e8f0;
  white-space: nowrap;
}

.pdf-badge {
  color: #0f766e;
  background: #f0fdfa;
  border: 1px solid #99f6e4;
  border-radius: 8px;
  padding: 0.12rem 0.4rem;
  font-size: 0.72rem;
}

.cand-meta {
  font-size: 0.82rem;
  color: var(--text-muted);
}

.cand-summary,
.cand-reason,
.cand-analysis {
  margin-top: 0.5rem;
  font-size: 0.8rem;
  line-height: 1.45;
}

.cand-summary .label,
.cand-reason .label,
.cand-analysis .label {
  display: block;
  font-weight: 600;
  color: var(--primary-dark);
  margin-bottom: 0.2rem;
  font-size: 0.75rem;
}

.cand-summary p {
  color: #0369a1;
  background: #e0f2fe;
  padding: 0.4rem 0.55rem;
  border-radius: 6px;
}

.cand-reason p {
  color: #047857;
  background: #ecfdf5;
  padding: 0.4rem 0.55rem;
  border-radius: 6px;
}

.cand-analysis p {
  color: var(--text-muted);
  padding-left: 0.25rem;
}

.cand-enrich {
  margin-top: 0.35rem;
  font-size: 0.82rem;
  color: var(--primary-dark);
}

.cand-resume-flag {
  margin-top: 0.35rem;
  font-size: 0.78rem;
  color: #92400e;
}

.cand-followup {
  margin-top: 0.35rem;
  font-size: 0.8rem;
  color: var(--warn);
}

.cand-actions {
  margin-top: 0.55rem;
  display: flex;
  justify-content: flex-end;
}

.btn-jump {
  background: var(--primary);
  color: #fff;
  border: none;
  border-radius: 6px;
  padding: 0.35rem 0.75rem;
  font-size: 0.8rem;
  cursor: pointer;
}

.btn-jump:disabled {
  opacity: 0.65;
  cursor: wait;
}

.jump-banner {
  margin-bottom: 0.5rem;
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

.shortlist-note {
  margin-top: 0.4rem;
  font-size: 0.78rem;
  color: var(--text-muted);
  text-align: right;
  flex-shrink: 0;
}
</style>
