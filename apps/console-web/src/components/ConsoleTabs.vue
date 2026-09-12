<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import LogConsole from './LogConsole.vue'
import CandidateList from './CandidateList.vue'
import FollowupPanel from './FollowupPanel.vue'
import ReplyJudgmentPanel from './ReplyJudgmentPanel.vue'
import PdfImportPanel from './PdfImportPanel.vue'
import PdfRankingPanel from './PdfRankingPanel.vue'
import { getWorkflow } from '../api'

const props = defineProps<{ workflowId: string }>()

const tab = ref<'log' | 'list' | 'im' | 'judgment' | 'import' | 'ranking'>('log')
const isPdfImport = ref(false)

async function refreshPlatform() {
  try {
    const workflow = await getWorkflow(props.workflowId)
    isPdfImport.value = workflow.platform === 'local_pdf'
    if (isPdfImport.value && (tab.value === 'im' || tab.value === 'judgment')) tab.value = 'import'
  } catch {
    isPdfImport.value = false
  }
}

onMounted(refreshPlatform)
watch(() => props.workflowId, refreshPlatform)
</script>

<template>
  <div class="console-tabs card">
    <div class="tab-bar">
      <button type="button" :class="{ active: tab === 'log' }" @click="tab = 'log'">
        实时日志
      </button>
      <button v-if="isPdfImport" type="button" :class="{ active: tab === 'import' }" @click="tab = 'import'">
        导入进度
      </button>
      <button type="button" :class="{ active: tab === 'list' }" @click="tab = 'list'">
        筛选清单
      </button>
      <button v-if="isPdfImport" type="button" :class="{ active: tab === 'ranking' }" @click="tab = 'ranking'">
        综合排名
      </button>
      <button v-if="!isPdfImport" type="button" :class="{ active: tab === 'im' }" @click="tab = 'im'">
        IM 跟进
      </button>
      <button v-if="!isPdfImport" type="button" :class="{ active: tab === 'judgment' }" @click="tab = 'judgment'">
        回复判定
      </button>
    </div>
    <div class="tab-body">
      <LogConsole v-if="tab === 'log'" :workflow-id="workflowId" embedded />
      <PdfImportPanel v-if="isPdfImport && tab === 'import'" :workflow-id="workflowId" embedded />
      <CandidateList v-if="tab === 'list'" :workflow-id="workflowId" embedded active />
      <PdfRankingPanel v-if="isPdfImport && tab === 'ranking'" :workflow-id="workflowId" embedded />
      <FollowupPanel v-if="tab === 'im'" :workflow-id="workflowId" embedded />
      <ReplyJudgmentPanel v-if="tab === 'judgment'" :workflow-id="workflowId" embedded />
    </div>
  </div>
</template>

<style scoped>
.console-tabs {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
  padding: 0;
  overflow: hidden;
}

.tab-bar {
  display: flex;
  flex-shrink: 0;
  border-bottom: 1px solid var(--border);
  background: var(--primary-light);
}

.tab-bar button {
  padding: 0.6rem 1.25rem;
  font-size: 0.9rem;
  font-weight: 600;
  color: var(--text-muted);
  background: transparent;
  border: none;
  border-bottom: 2px solid transparent;
  border-radius: 0;
}

.tab-bar button.active {
  color: var(--primary-dark);
  background: var(--card);
  border-bottom-color: var(--primary);
}

.tab-body {
  flex: 1;
  min-height: 0;
  overflow: hidden;
  position: relative;
}

.tab-body > :deep(*) {
  height: 100%;
  min-height: 0;
}
</style>
