<script setup lang="ts">
import { nextTick, ref, watch } from 'vue'

const props = defineProps<{ text: string; statuses?: string[] }>()

const bodyRef = ref<HTMLElement | null>(null)

watch(
  () => props.text,
  async () => {
    await nextTick()
    if (bodyRef.value) {
      bodyRef.value.scrollTop = bodyRef.value.scrollHeight
    }
  },
)
</script>

<template>
  <div class="parse-stream">
    <div v-if="statuses?.length" class="status-list">
      <p v-for="(line, i) in statuses" :key="i" class="status-line">{{ line }}</p>
    </div>
    <pre v-if="text" ref="bodyRef" class="stream-body">{{ text }}</pre>
  </div>
</template>

<style scoped>
.parse-stream {
  width: 100%;
  max-width: 920px;
  margin: 0 auto;
  padding: 0 1rem 1.25rem;
}

.status-list {
  margin-bottom: 0.65rem;
}

.status-line {
  font-size: 0.82rem;
  color: var(--primary-dark);
  padding: 0.2rem 0;
}

.status-line::before {
  content: '› ';
  color: var(--primary);
  font-weight: 700;
}

.stream-body {
  margin: 0;
  min-height: 72px;
  max-height: 220px;
  overflow-y: auto;
  background: var(--log-bg);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 0.75rem 0.9rem;
  font-family: 'Cascadia Code', 'Consolas', 'PingFang SC', monospace;
  font-size: 0.82rem;
  line-height: 1.55;
  color: #0c4a6e;
  white-space: pre-wrap;
  word-break: break-word;
}
</style>
