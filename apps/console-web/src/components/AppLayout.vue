<script setup lang="ts">
import GlobalPauseControl from './GlobalPauseControl.vue'

defineProps<{
  showHistory?: boolean
  showPauseControl?: boolean
  showExitTask?: boolean
  workflowId?: string | null
}>()
const emit = defineEmits<{
  (e: 'new-task'): void
  (e: 'show-history'): void
  (e: 'exit-task'): void
}>()
</script>

<template>
  <div class="layout">
    <header class="header">
      <div class="brand">
        <img class="logo" src="/logo.svg" alt="" width="40" height="40" />
        <div>
          <h1>HRagent</h1>
          <p>猎聘 LPT · PDF 简历 · 招聘工作台</p>
        </div>
      </div>
      <div class="header-actions">
        <GlobalPauseControl
          :workflow-id="workflowId ?? null"
          :visible="showPauseControl"
        />
        <button
          v-if="showExitTask"
          type="button"
          class="btn-exit-task"
          @click="emit('exit-task')"
        >
          退出任务
        </button>
        <button v-if="showHistory" class="btn-secondary" @click="emit('show-history')">历史任务</button>
        <button class="btn-secondary" @click="emit('new-task')">新建任务</button>
      </div>
    </header>
    <main class="main">
      <slot />
    </main>
  </div>
</template>

<style scoped>
.layout {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
}

.header {
  background: linear-gradient(135deg, #ffffff 0%, #e8f4fc 100%);
  border-bottom: 1px solid var(--border);
  padding: 0.75rem 1.25rem;
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 0.5rem;
  box-shadow: 0 2px 12px rgba(74, 159, 217, 0.08);
}

.brand {
  display: flex;
  align-items: center;
  gap: 1rem;
  min-width: 0;
  flex: 1 1 12rem;
}

.logo {
  width: 40px;
  height: 40px;
  border-radius: 10px;
  flex-shrink: 0;
  box-shadow: 0 4px 12px rgba(74, 159, 217, 0.4);
}

.brand h1 {
  font-size: 1.15rem;
  font-weight: 700;
  color: var(--text);
}

.brand p {
  font-size: 0.85rem;
  color: var(--text-muted);
  margin-top: 0.15rem;
}

.header-actions {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 0.5rem;
  flex: 1 1 auto;
}

.btn-exit-task {
  padding: 0.45rem 0.85rem;
  border-radius: 8px;
  border: 1px solid #e57373;
  background: #fff5f5;
  color: #c62828;
  font-size: 0.85rem;
  font-weight: 600;
  cursor: pointer;
}

.btn-exit-task:hover {
  background: #ffebee;
  border-color: #ef5350;
}

.main {
  flex: 1;
  min-height: 0;
  padding: 0.65rem 1rem 0.75rem;
  width: 100%;
  max-width: none;
  display: flex;
  flex-direction: column;
}
</style>
