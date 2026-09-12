<script setup lang="ts">
import { onMounted, onUnmounted, ref, watch } from 'vue'
import { getPdfImportStatus } from '../api'

const props = defineProps<{ workflowId: string; embedded?: boolean }>()

const status = ref('SCREENING')
const progress = ref({ total: 0, processing: 0, completed: 0, duplicate: 0, failed: 0, state: 'queued' })
let timer: ReturnType<typeof setInterval> | null = null

async function refresh() {
  try {
    const result = await getPdfImportStatus(props.workflowId)
    status.value = result.status
    progress.value = result.progress
  } catch {
    /* The regular task status panel still reports API errors. */
  }
}

function startPolling() {
  if (timer) clearInterval(timer)
  void refresh()
  timer = setInterval(refresh, 1500)
}

onMounted(startPolling)
watch(() => props.workflowId, startPolling)
onUnmounted(() => { if (timer) clearInterval(timer) })
</script>

<template>
  <section class="pdf-import-panel" :class="{ card: !embedded }">
    <header>
      <div>
        <h2>一次性 PDF 解析</h2>
        <p>原 PDF、文件名、原文和去重指纹均不会保存。</p>
      </div>
      <span class="state">{{ status === 'SCREENING_COMPLETED' ? '已完成' : status === 'PARTIAL_FAILED' ? '已中断' : '处理中' }}</span>
    </header>
    <div class="counts">
      <div><strong>{{ progress.total }}</strong><span>总数</span></div>
      <div><strong>{{ progress.processing }}</strong><span>处理中</span></div>
      <div><strong>{{ progress.completed }}</strong><span>已完成</span></div>
      <div><strong>{{ progress.duplicate }}</strong><span>重复</span></div>
      <div><strong>{{ progress.failed }}</strong><span>失败</span></div>
    </div>
    <p class="hint">失败或中断的文件不会保留，需重新选择后上传。</p>
  </section>
</template>

<style scoped>
.pdf-import-panel { height: 100%; padding: 1rem; overflow: auto; }
header { display: flex; justify-content: space-between; gap: 1rem; align-items: start; }
h2 { margin: 0; font-size: 1rem; color: var(--primary-dark); }
header p, .hint { margin: .35rem 0 0; color: var(--text-muted); font-size: .82rem; line-height: 1.5; }
.state { border: 1px solid #bfdbfe; color: var(--primary-dark); background: #eff6ff; padding: .3rem .55rem; border-radius: 8px; font-size: .8rem; white-space: nowrap; }
.counts { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: .65rem; margin-top: 1.15rem; }
.counts div { border: 1px solid var(--border); border-radius: 8px; padding: .75rem; display: flex; flex-direction: column; gap: .2rem; }
.counts strong { font-size: 1.35rem; color: var(--primary-dark); }
.counts span { font-size: .78rem; color: var(--text-muted); }
@media (max-width: 700px) { .counts { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
</style>
