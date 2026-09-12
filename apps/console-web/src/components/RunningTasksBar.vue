<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import type { WorkflowInfo } from '../types'
import { listRunningWorkflows } from '../api'
import { workflowPositionName } from '../utils/parseSummary'

const props = defineProps<{
  currentWorkflowId?: string | null
}>()

const emit = defineEmits<{
  (e: 'open', workflowId: string): void
}>()

const tasks = ref<WorkflowInfo[]>([])
let timer: ReturnType<typeof setInterval> | null = null

const STATUS_LABELS: Record<string, string> = {
  CREATED: '正在启动',
  FETCHING: '抓取中',
  FETCH_COMPLETED: '抓取完成',
  SCREENING: '初筛中',
  SCREENING_COMPLETED: '初筛完成',
  CONVERSATIONS_STARTED: 'IM 跟进中',
}

function isPaused(w: WorkflowInfo): boolean {
  const cfg = w.config as { paused?: boolean } | undefined
  return Boolean(cfg?.paused)
}

function statusLabel(w: WorkflowInfo): string {
  if (isPaused(w)) {
    return '已挂起'
  }
  return STATUS_LABELS[w.status] || w.status
}

function taskTitle(w: WorkflowInfo): string {
  return workflowPositionName(w)
}

function browserProfile(w: WorkflowInfo): string {
  const cfg = w.config as { fetch?: { browser_profile?: string } } | undefined
  return cfg?.fetch?.browser_profile || ''
}

const visible = computed(() => tasks.value.length > 0)

async function refresh() {
  try {
    tasks.value = await listRunningWorkflows()
  } catch {
    tasks.value = []
  }
}

onMounted(() => {
  void refresh()
  timer = setInterval(refresh, 4000)
})

onUnmounted(() => {
  if (timer) clearInterval(timer)
})

defineExpose({ refresh })
</script>

<template>
  <section v-if="visible" class="running-tasks card">
    <div class="running-head">
      <strong>进行中的筛选任务</strong>
      <span class="hint">各任务独立浏览器窗口；点「新建任务」可并行开新任务，点击卡片随时切回查看</span>
    </div>
    <div class="running-list">
      <button
        v-for="task in tasks"
        :key="task.id"
        type="button"
        class="running-item"
        :class="{ active: task.id === currentWorkflowId }"
        @click="emit('open', task.id)"
      >
        <span class="title">{{ taskTitle(task) }}</span>
        <span class="status" :class="{ suspended: isPaused(task) }">
          {{ statusLabel(task) }}
        </span>
        <span v-if="browserProfile(task)" class="profile">{{ browserProfile(task) }}</span>
      </button>
    </div>
  </section>
</template>

<style scoped>
.running-tasks {
  margin-bottom: 1rem;
  padding: 0.75rem 1rem;
}

.running-head {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 0.5rem 1rem;
  margin-bottom: 0.65rem;
}

.running-head strong {
  font-size: 0.95rem;
}

.hint {
  font-size: 0.8rem;
  color: var(--muted, #64748b);
}

.running-list {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
}

.running-item {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 0.15rem;
  padding: 0.45rem 0.75rem;
  border: 1px solid var(--border, #dbeafe);
  border-radius: 8px;
  background: #fff;
  cursor: pointer;
  min-width: 8rem;
  text-align: left;
}

.running-item:hover {
  border-color: var(--primary, #4a9fd9);
}

.running-item.active {
  border-color: var(--primary, #4a9fd9);
  background: #eef7fd;
}

.title {
  font-weight: 600;
  font-size: 0.85rem;
  max-width: 14rem;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.status {
  font-size: 0.78rem;
  color: var(--primary, #2563eb);
}

.status.suspended {
  color: #b45309;
}

.profile {
  font-size: 0.72rem;
  color: var(--muted, #94a3b8);
  font-family: ui-monospace, monospace;
}
</style>
