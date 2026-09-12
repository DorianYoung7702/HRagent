<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { getExecutionControl, pauseExecution, resumeExecution } from '../api'
import { notifyWorkflowRefresh, subscribeWorkflowRefresh } from '../utils/workflowRefreshBus'

const props = defineProps<{
  workflowId: string | null
  visible?: boolean
}>()

const state = ref<{
  paused: boolean
  global_paused: boolean
  can_pause: boolean
} | null>(null)
const busy = ref(false)
let timer: ReturnType<typeof setInterval> | null = null
let unsubscribeRefresh: (() => void) | null = null

const isPaused = computed(() => Boolean(state.value?.paused))
const canControl = computed(() => Boolean(props.workflowId && state.value?.can_pause))
const showBar = computed(() => Boolean(props.visible !== false && props.workflowId))

async function refresh() {
  if (!props.workflowId) {
    state.value = null
    return
  }
  try {
    state.value = await getExecutionControl(props.workflowId)
  } catch {
    /* ignore */
  }
}

async function togglePause() {
  if (!props.workflowId || busy.value) return
  if (!canControl.value && !isPaused.value) return
  busy.value = true
  try {
    if (isPaused.value) {
      await resumeExecution(props.workflowId)
    } else {
      await pauseExecution(props.workflowId)
    }
    await refresh()
    notifyWorkflowRefresh(props.workflowId, 'control')
  } catch {
    /* ignore */
  } finally {
    busy.value = false
  }
}

onMounted(() => {
  refresh()
  timer = setInterval(refresh, 8000)
  if (props.workflowId) {
    unsubscribeRefresh = subscribeWorkflowRefresh(props.workflowId, () => {
      void refresh()
    })
  }
})

watch(
  () => props.workflowId,
  (id, prev) => {
    unsubscribeRefresh?.()
    unsubscribeRefresh = null
    if (id) {
      unsubscribeRefresh = subscribeWorkflowRefresh(id, () => {
        void refresh()
      })
    }
    if (id !== prev) {
      void refresh()
    }
  },
)

onUnmounted(() => {
  if (timer) clearInterval(timer)
  unsubscribeRefresh?.()
})
</script>

<template>
  <button
    v-if="showBar"
    type="button"
    class="btn-pause-task"
    :class="isPaused ? 'resume' : 'pause'"
    :disabled="busy || (!canControl && !isPaused)"
    :title="!canControl && !isPaused ? '当前任务已结束，无法暂停' : ''"
    @click="togglePause"
  >
    {{ busy ? '处理中…' : isPaused ? '继续运行' : '暂停任务' }}
  </button>
</template>

<style scoped>
.btn-pause-task {
  padding: 0.45rem 0.85rem;
  border-radius: 8px;
  font-size: 0.85rem;
  font-weight: 600;
  white-space: nowrap;
  cursor: pointer;
}

.btn-pause-task.pause {
  background: #fff;
  color: #b45309;
  border: 1.5px solid #f59e0b;
}

.btn-pause-task.pause:hover:not(:disabled) {
  background: #fffbeb;
}

.btn-pause-task.resume {
  background: linear-gradient(135deg, var(--primary), var(--primary-dark));
  color: #fff;
  border: none;
  box-shadow: 0 2px 8px rgba(74, 159, 217, 0.35);
}

.btn-pause-task:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
</style>
