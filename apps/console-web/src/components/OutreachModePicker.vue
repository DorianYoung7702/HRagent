<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  collectOnly: boolean
  autoReplyIm: boolean
  disabled?: boolean
}>()

const emit = defineEmits<{
  'update:collectOnly': [boolean]
  'update:autoReplyIm': [boolean]
  change: [{ collectOnly: boolean; autoReplyIm: boolean }]
}>()

type PrimaryMode = 'collect' | 'im'

const primaryMode = computed<PrimaryMode>({
  get: () => (props.collectOnly ? 'collect' : 'im'),
  set: (mode) => {
    applyMode(mode, mode === 'im' ? props.autoReplyIm : true)
  },
})

const imSendAuto = computed({
  get: () => props.autoReplyIm,
  set: (auto) => {
    applyMode('im', auto)
  },
})

function applyMode(primary: PrimaryMode, autoReply: boolean) {
  const next = {
    collectOnly: primary === 'collect',
    autoReplyIm: primary === 'im' ? autoReply : props.autoReplyIm,
  }
  if (next.collectOnly === props.collectOnly && next.autoReplyIm === props.autoReplyIm) {
    return
  }
  emit('update:collectOnly', next.collectOnly)
  emit('update:autoReplyIm', next.autoReplyIm)
  emit('change', next)
}

function selectImAuto() {
  applyMode('im', true)
}

function selectImManual() {
  applyMode('im', false)
}
</script>

<template>
  <div class="outreach-mode-picker" :class="{ disabled }">
    <div class="mode-row primary" role="radiogroup" aria-label="运行方式">
      <button
        type="button"
        class="mode-option"
        :class="{ active: primaryMode === 'collect' }"
        :disabled="disabled"
        @click="primaryMode = 'collect'"
      >
        <span class="mode-title">仅收藏模式</span>
        <span class="mode-desc">只收藏到岗位文件夹，不开聊、不发 IM</span>
      </button>
      <button
        type="button"
        class="mode-option"
        :class="{ active: primaryMode === 'im' }"
        :disabled="disabled"
        @click="primaryMode = 'im'"
      >
        <span class="mode-title">IM 沟通</span>
        <span class="mode-desc">开聊并发送追问 / 要简历 / 回复话术</span>
      </button>
    </div>

    <div
      v-if="primaryMode === 'im'"
      class="mode-row secondary"
      role="radiogroup"
      aria-label="IM 发送方式"
    >
      <button
        type="button"
        class="mode-option compact"
        :class="{ active: imSendAuto }"
        :disabled="disabled"
        @click="selectImAuto"
      >
        <span class="mode-title">自动回复 IM</span>
        <span class="mode-desc">生成后直接发送</span>
      </button>
      <button
        type="button"
        class="mode-option compact"
        :class="{ active: !imSendAuto }"
        :disabled="disabled"
        @click="selectImManual"
      >
        <span class="mode-title">人工确认后发送</span>
        <span class="mode-desc">开聊后生成草稿，改字后发送（仍会立即开聊）</span>
      </button>
    </div>
  </div>
</template>

<style scoped>
.outreach-mode-picker {
  display: flex;
  flex-direction: column;
  gap: 0.55rem;
  width: 100%;
}

.outreach-mode-picker.disabled {
  opacity: 0.65;
  pointer-events: none;
}

.mode-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0.45rem;
}

.mode-option {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 0.2rem;
  padding: 0.65rem 0.75rem;
  text-align: left;
  border: 1.5px solid var(--border);
  border-radius: 10px;
  background: var(--card);
  color: var(--text);
  cursor: pointer;
  transition:
    border-color 0.15s ease,
    background 0.15s ease,
    box-shadow 0.15s ease;
}

.mode-option:hover:not(:disabled) {
  border-color: var(--primary);
  background: var(--primary-light);
}

.mode-option.active {
  border-color: var(--primary);
  background: var(--primary-light);
  box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--primary) 35%, transparent);
}

.mode-option:disabled {
  cursor: not-allowed;
}

.mode-option.compact {
  padding: 0.55rem 0.7rem;
}

.mode-title {
  font-size: 0.88rem;
  font-weight: 600;
  color: var(--text);
}

.mode-desc {
  font-size: 0.74rem;
  line-height: 1.35;
  color: var(--text-muted);
}

.mode-row.secondary .mode-option.active .mode-title {
  color: var(--primary-dark);
}
</style>
