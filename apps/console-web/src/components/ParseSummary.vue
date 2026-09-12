<script setup lang="ts">
import { computed } from 'vue'
import type { SearchIntentOutput } from '../types'
import { formatOtherFilters } from '../utils/parseSummary'

const props = defineProps<{ parsed: SearchIntentOutput; compact?: boolean }>()

const otherLabel = computed(() => formatOtherFilters(props.parsed.other_filters))
const displaySummary = computed(() =>
  (props.parsed.parse_summary || '')
    .replace(/[^。；;\n]*(?:HR|偏好|评判标准|初筛标准)[^。；;\n]*[。；;]?/g, '')
    .trim(),
)
</script>

<template>
  <section :class="['parse-summary', compact ? 'parse-compact' : 'card']">
    <h2 v-if="!compact">搜索解析</h2>
    <p v-if="!compact && displaySummary" class="summary">{{ displaySummary }}</p>
    <div class="chip-groups">
      <div class="chip-row">
        <span class="group-label">搜索栏</span>
        <span class="chip"><strong>关键词</strong>{{ parsed.keywords }}</span>
      </div>
      <div class="chip-row">
        <span class="group-label">猎聘筛选</span>
        <span v-if="parsed.current_cities?.length" class="chip"><strong>目前城市</strong>{{ parsed.current_cities.join('、') }}</span>
        <span class="chip"><strong>期望城市</strong>{{ (parsed.cities?.length ? parsed.cities.join('、') : parsed.city) }}</span>
        <span class="chip"><strong>经验</strong>{{ parsed.experience }}</span>
        <span v-if="parsed.education?.degree" class="chip"><strong>学历</strong>{{ parsed.education.degree }}</span>
        <span v-if="parsed.education?.school_tiers?.length" class="chip"><strong>院校</strong>{{ parsed.education.school_tiers.join('、') }}</span>
        <span v-if="otherLabel" class="chip"><strong>其他</strong>{{ otherLabel }}</span>
        <span class="chip"><strong>份数</strong>{{ parsed.target_count }}</span>
        <span v-if="parsed.chat_job_title" class="chip"><strong>开聊岗位</strong>{{ parsed.chat_job_title }}</span>
      </div>
    </div>
  </section>
</template>

<style scoped>
.parse-summary {
  flex-shrink: 0;
  padding: 1rem 1.25rem;
  border: 2px solid var(--primary-light);
}

.parse-summary h2 {
  font-size: 1rem;
  color: var(--primary-dark);
  margin-bottom: 0.5rem;
}

.summary {
  background: var(--primary-light);
  padding: 0.75rem 1rem;
  border-radius: 8px;
  font-size: 0.9rem;
  line-height: 1.5;
  margin-bottom: 0.75rem;
}

.chip-groups {
  display: flex;
  flex-direction: column;
  gap: 0.45rem;
}

.chip-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.4rem;
}

.group-label {
  font-size: 0.72rem;
  font-weight: 700;
  color: var(--primary-dark);
  background: var(--primary-light);
  padding: 0.15rem 0.45rem;
  border-radius: 4px;
  flex-shrink: 0;
}

.chip {
  font-size: 0.78rem;
  background: #f5fafd;
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 0.25rem 0.5rem;
  white-space: nowrap;
}

.chip strong {
  color: var(--text-muted);
  font-weight: 600;
  margin-right: 0.3rem;
}

.parse-compact {
  flex-shrink: 0;
  width: min(320px, 32vw);
  padding: 0.55rem 0.75rem;
  background: var(--card);
  border-radius: var(--radius);
  border: 1px solid var(--border);
  box-shadow: var(--shadow);
  display: flex;
  align-items: center;
}

.parse-compact .chip-groups {
  gap: 0.25rem;
}

.parse-compact .group-label {
  display: none;
}
</style>
