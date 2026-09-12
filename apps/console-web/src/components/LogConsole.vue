<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import type { WorkflowEvent } from '../types'
import { getEvents, subscribeEvents } from '../api'
import { notifyWorkflowRefresh, shouldRefreshFromEvent } from '../utils/workflowRefreshBus'

const props = defineProps<{ workflowId: string; embedded?: boolean }>()

const events = ref<WorkflowEvent[]>([])
const containerRef = ref<HTMLElement | null>(null)
const selectedLevel = ref('all')
const selectedCategory = ref('all')
const keyword = ref('')
const autoScroll = ref(true)
const expandedMetaId = ref<number | null>(null)
let es: EventSource | null = null
let lastId = 0

const categories = computed(() => [...new Set(events.value.map((event) => event.category))].sort())
const filteredEvents = computed(() => {
  const needle = keyword.value.trim().toLowerCase()
  return events.value.filter((event) => {
    if (selectedLevel.value !== 'all' && event.level !== selectedLevel.value) return false
    if (selectedCategory.value !== 'all' && event.category !== selectedCategory.value) return false
    if (!needle) return true
    return `${event.message} ${event.category} ${JSON.stringify(event.meta || {})}`.toLowerCase().includes(needle)
  })
})

function levelClass(level: string) {
  return `log-${level}`
}

function categoryClass(category: string, meta?: Record<string, unknown>) {
  const phase = meta?.phase as string | undefined
  if (category === 'parse') return `log-cat-parse ${phase ? `log-phase-${phase}` : ''}`
  if (category === 'screen') return `log-cat-screen ${phase ? `log-phase-${phase}` : ''}`
  return ''
}

function formatTime(ts: string) {
  try {
    return new Date(ts).toLocaleTimeString('zh-CN', { hour12: false })
  } catch {
    return ts
  }
}

async function loadHistory() {
  const res = await getEvents(props.workflowId, lastId)
  for (const ev of res.events) {
    if (ev.id > lastId) {
      events.value.push(ev)
      lastId = ev.id
    }
  }
  await scrollBottom()
}

async function scrollBottom() {
  if (!autoScroll.value) return
  await nextTick()
  if (containerRef.value) {
    containerRef.value.scrollTop = containerRef.value.scrollHeight
  }
}

function metaText(meta?: Record<string, unknown>) {
  return JSON.stringify(meta || {}, null, 2)
}

function scrollTopSmooth() {
  containerRef.value?.scrollTo({ top: 0, behavior: 'smooth' })
  window.scrollTo({ top: 0, behavior: 'smooth' })
}

function connect() {
  es?.close()
  es = subscribeEvents(
    props.workflowId,
    (ev) => {
      if (ev.id > lastId) {
        events.value.push(ev)
        lastId = ev.id
        scrollBottom()
        if (shouldRefreshFromEvent(ev)) {
          notifyWorkflowRefresh(props.workflowId, ev.category)
        }
      }
    },
    () => {
      setTimeout(connect, 3000)
    },
  )
}

onMounted(async () => {
  await loadHistory()
  connect()
})

onUnmounted(() => es?.close())

watch(
  () => props.workflowId,
  async () => {
    events.value = []
    lastId = 0
    await loadHistory()
    connect()
  },
)
</script>

<template>
  <div class="log-console" :class="{ card: !embedded, embedded }">
    <div class="log-header">
      <h2>实时日志控制台</h2>
      <span class="log-count">{{ filteredEvents.length }}/{{ events.length }} 条</span>
    </div>
    <div class="log-controls">
      <select v-model="selectedLevel" aria-label="日志级别">
        <option value="all">全部级别</option><option value="info">信息</option><option value="success">成功</option><option value="warn">警告</option><option value="error">错误</option>
      </select>
      <select v-model="selectedCategory" aria-label="日志阶段">
        <option value="all">全部阶段</option><option v-for="category in categories" :key="category" :value="category">{{ category }}</option>
      </select>
      <input v-model="keyword" type="search" placeholder="搜索日志" aria-label="搜索日志" />
      <label class="auto-scroll"><input v-model="autoScroll" type="checkbox" />自动滚动</label>
    </div>
    <div ref="containerRef" class="log-body">
      <div v-if="filteredEvents.length === 0" class="log-empty">暂无匹配日志</div>
      <div
        v-for="ev in filteredEvents"
        :key="ev.id"
        class="log-line"
        :class="[levelClass(ev.level), categoryClass(ev.category, ev.meta)]"
      >
        <span class="log-time">{{ formatTime(ev.ts) }}</span>
        <span class="log-cat" :class="`cat-${ev.category}`">[{{ ev.category }}]</span>
        <span class="log-msg">{{ ev.message }}</span>
        <button v-if="Object.keys(ev.meta || {}).length" type="button" class="meta-toggle" @click="expandedMetaId = expandedMetaId === ev.id ? null : ev.id">
          {{ expandedMetaId === ev.id ? '收起' : '详情' }}
        </button>
        <pre v-if="expandedMetaId === ev.id" class="log-meta">{{ metaText(ev.meta) }}</pre>
      </div>
    </div>
    <button
      type="button"
      class="log-scroll-top"
      aria-label="返回日志顶部"
      title="返回顶部"
      @click="scrollTopSmooth"
    >
      ↑
    </button>
  </div>
</template>

<style scoped>
.log-console {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  position: relative;
}

.log-console.embedded {
  padding: 0.75rem 1rem 0.85rem;
}

.log-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 0.5rem;
  gap: 0.5rem;
  flex-shrink: 0;
}

.log-header h2 {
  font-size: 1.05rem;
  color: var(--primary-dark);
  flex: 1;
}

.log-count {
  font-size: 0.8rem;
  color: var(--text-muted);
}

.log-controls { display: flex; flex-wrap: wrap; gap: .45rem; margin-bottom: .55rem; }
.log-controls select, .log-controls input[type='search'] { min-height: 2rem; border: 1px solid var(--border); border-radius: 4px; background: var(--card); padding: .3rem .45rem; color: var(--text); font-size: .78rem; }
.log-controls input[type='search'] { flex: 1; min-width: 9rem; }
.auto-scroll { display: inline-flex; align-items: center; gap: .25rem; color: var(--text-muted); font-size: .78rem; }

.log-body {
  flex: 1;
  min-height: 0;
  background: var(--log-bg);
  border-radius: 8px;
  border: 1px solid var(--border);
  padding: 0.6rem 0.75rem;
  overflow-y: auto;
  font-family: 'Cascadia Code', 'Consolas', monospace;
  font-size: 0.82rem;
  line-height: 1.55;
}

.log-empty {
  color: var(--text-muted);
  text-align: center;
  padding: 1rem;
}

.log-line {
  padding: 0.12rem 0;
  word-break: break-word;
}

.meta-toggle { margin-left: .45rem; border: 0; background: transparent; color: var(--primary); font-size: .75rem; cursor: pointer; }
.log-meta { margin: .35rem 0 .2rem 5.65rem; padding: .45rem; overflow-x: auto; border-left: 2px solid var(--primary-light); background: color-mix(in srgb, var(--card) 90%, var(--primary-light)); color: var(--text-muted); font: inherit; font-size: .75rem; white-space: pre-wrap; }

.log-cat-parse .log-msg,
.cat-parse {
  color: #0369a1;
}

.log-cat-screen .log-msg,
.cat-screen {
  color: #047857;
}

.log-phase-summary .log-msg,
.log-phase-reason .log-msg,
.log-phase-criteria_analysis .log-msg,
.log-phase-notes .log-msg {
  font-weight: 500;
}

.log-phase-highlight .log-msg {
  padding-left: 0.5rem;
  color: #0c4a6e;
}

.log-phase-decision .log-msg {
  font-weight: 700;
}

.log-time {
  color: var(--text-muted);
  margin-right: 0.5rem;
}

.log-cat {
  margin-right: 0.4rem;
  font-weight: 600;
}

.log-info .log-msg { color: var(--text); }
.log-success .log-msg { color: var(--success); }
.log-warn .log-msg { color: var(--warn); }
.log-error .log-msg { color: var(--error); font-weight: 600; }

.log-scroll-top {
  position: fixed;
  right: 1.35rem;
  bottom: 1.25rem;
  z-index: 40;
  width: 2.6rem;
  height: 2.6rem;
  border: 1px solid color-mix(in srgb, var(--primary) 55%, var(--border));
  border-radius: 999px;
  background: color-mix(in srgb, var(--card) 92%, var(--primary-light));
  color: var(--primary-dark);
  box-shadow: 0 10px 24px rgba(20, 71, 112, 0.18);
  font-size: 1.15rem;
  font-weight: 700;
  line-height: 1;
  cursor: pointer;
  transition:
    transform 0.16s ease,
    box-shadow 0.16s ease,
    background 0.16s ease;
}

.log-scroll-top:hover {
  transform: translateY(-2px);
  background: var(--primary-light);
  box-shadow: 0 14px 30px rgba(20, 71, 112, 0.22);
}

.log-scroll-top:active {
  transform: translateY(0);
}

@media (max-width: 720px) {
  .log-scroll-top {
    right: 0.9rem;
    bottom: 0.9rem;
  }
}
</style>
