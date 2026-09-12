<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import type { WorkflowInfo } from '../types'
import { getWorkflow } from '../api'
import { workflowPositionName } from '../utils/parseSummary'
import { subscribeWorkflowRefresh } from '../utils/workflowRefreshBus'

const props = defineProps<{
  workflowId: string
}>()

const workflow = ref<WorkflowInfo | null>(null)
const pausedOverride = ref<boolean | null>(null)
let timer: ReturnType<typeof setInterval> | null = null
let unsubscribeRefresh: (() => void) | null = null
let currentPollMs = 0

const taskName = computed(() =>
  workflow.value ? workflowPositionName(workflow.value) : '',
)

const isRunning = computed(() => {
  const s = workflow.value?.status || ''
  return (
    s === 'FETCHING' ||
    s === 'SCREENING' ||
    s === 'CONVERSATIONS_STARTED' ||
    s === 'SCREENING_COMPLETED'
  )
})

const isPaused = computed(() => {
  if (pausedOverride.value !== null) return pausedOverride.value
  return Boolean((workflow.value?.config as { paused?: boolean })?.paused)
})

const statusLabel = computed(() => {
  if (isPaused.value && isRunning.value) return '已暂停'
  const s = workflow.value?.status || ''
  const map: Record<string, string> = {
    CREATED: '已创建',
    FETCHING: '抓取中',
    FETCH_COMPLETED: '抓取完成',
    SCREENING: '初筛中',
    SCREENING_COMPLETED: '初筛完成',
    CONVERSATIONS_STARTED: 'IM 跟进中',
    PARTIAL_FAILED: '部分完成',
    FAILED: '失败',
  }
  return map[s] || s
})

const statusBadge = computed(() => {
  if (isPaused.value && isRunning.value) return 'badge-paused'
  const s = workflow.value?.status || ''
  if (s === 'SCREENING_COMPLETED' || s === 'CONVERSATIONS_STARTED') return 'badge-running'
  if (s === 'FETCH_COMPLETED') return 'badge-done'
  if (s === 'FAILED') return 'badge-failed'
  if (s === 'FETCHING' || s === 'SCREENING') return 'badge-running'
  return 'badge-running'
})

const candidateCount = computed(() => {
  const cfg = workflow.value?.config as { candidate_count?: number; fetch?: { target_count?: number } }
  return cfg?.candidate_count ?? 0
})

const targetCount = computed(() => {
  const cfg = workflow.value?.config as { fetch?: { target_count?: number } }
  return cfg?.fetch?.target_count ?? 20
})

const progressPct = computed(() => Math.min(100, (candidateCount.value / targetCount.value) * 100))

const keywords = computed(() => {
  if (workflow.value?.platform === 'local_pdf') return '一次性 PDF 解析'
  const cfg = workflow.value?.config as { fetch?: { search?: { keywords?: string } } }
  return cfg?.fetch?.search?.keywords || '—'
})

const collectOnly = computed(() => {
  const cfg = workflow.value?.config as { fetch?: { collect_only?: boolean } }
  return Boolean(cfg?.fetch?.collect_only)
})

function pollMs() {
  return isRunning.value ? 2000 : 4000
}

function restartTimer() {
  const ms = pollMs()
  if (timer && ms === currentPollMs) return
  currentPollMs = ms
  if (timer) clearInterval(timer)
  timer = setInterval(refresh, ms)
}

async function refresh() {
  try {
    const wf = await getWorkflow(props.workflowId)
    workflow.value = wf
    const cfg = wf.config as { paused?: boolean }
    pausedOverride.value = Boolean(cfg.paused)
    restartTimer()
  } catch {
    /* ignore */
  }
}

function bindRefreshSubscription(id: string) {
  unsubscribeRefresh?.()
  unsubscribeRefresh = subscribeWorkflowRefresh(id, () => {
    refresh()
  })
}

onMounted(() => {
  refresh()
  bindRefreshSubscription(props.workflowId)
})

watch(
  () => props.workflowId,
  (id, prev) => {
    if (id === prev) return
    workflow.value = null
    pausedOverride.value = null
    if (id) {
      bindRefreshSubscription(id)
      void refresh()
    } else {
      unsubscribeRefresh?.()
      unsubscribeRefresh = null
    }
  },
)

onUnmounted(() => {
  if (timer) clearInterval(timer)
  unsubscribeRefresh?.()
})
</script>

<template>
  <div class="task-status card">
    <div v-if="workflow" class="status-body">
      <div class="status-row">
        <span class="badge" :class="statusBadge">{{ statusLabel }}</span>
        <span v-if="collectOnly" class="badge badge-collect">仅收藏</span>
        <span class="task-name" :title="taskName">{{ taskName }}</span>
        <span class="progress-text">{{ candidateCount }} / {{ targetCount }}</span>
        <div class="progress-bar">
          <div
            class="progress-fill"
            :class="{ paused: isPaused }"
            :style="{ width: `${progressPct}%` }"
          />
        </div>
      </div>
      <div class="status-meta">
        <span class="kw" :title="keywords">关键词 {{ keywords }}</span>
        <span v-if="isPaused" class="pause-hint">已暂停，点右上角「继续运行」恢复</span>
        <span v-if="workflow.error_message" class="error-box">{{ workflow.error_message }}</span>
      </div>
    </div>
    <div v-else class="loading">加载中...</div>
  </div>
</template>

<style scoped>
.task-status {
  padding: 0.65rem 1rem;
}

.status-body {
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
}

.status-row {
  display: flex;
  align-items: center;
  gap: 0.65rem;
  min-width: 0;
}

.task-name {
  font-size: 0.9rem;
  font-weight: 600;
  color: var(--text);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  flex: 1;
  min-width: 0;
}

.progress-text {
  font-size: 0.85rem;
  color: var(--text-muted);
  white-space: nowrap;
  flex-shrink: 0;
}

.progress-bar {
  width: 120px;
  height: 6px;
  background: var(--primary-light);
  border-radius: 3px;
  overflow: hidden;
  flex-shrink: 0;
}

.progress-fill {
  height: 100%;
  background: linear-gradient(90deg, var(--primary), var(--primary-dark));
  border-radius: 3px;
  transition: width 0.4s ease;
}

.progress-fill.paused {
  background: linear-gradient(90deg, #fbbf24, #f59e0b);
}

.status-meta {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  flex-wrap: wrap;
  font-size: 0.8rem;
  min-width: 0;
}

.kw {
  color: var(--text-muted);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 100%;
}

.badge-paused {
  background: #fef3c7;
  color: #b45309;
}

.badge-collect {
  background: #e0f2fe;
  color: #0369a1;
}

.pause-hint {
  color: #92400e;
  background: #fffbeb;
  padding: 0.15rem 0.5rem;
  border-radius: 4px;
}

.error-box {
  color: #991b1b;
  background: #fee2e2;
  padding: 0.15rem 0.5rem;
  border-radius: 4px;
}

.loading {
  color: var(--text-muted);
  font-size: 0.85rem;
}
</style>
