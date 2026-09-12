<script setup lang="ts">
import { ref } from 'vue'
import { chatPreferenceMemory } from '../api'
import type { HRPreferenceMemory, SearchIntentOutput } from '../types'

const props = defineProps<{
  currentRequirement: string
  parsed: SearchIntentOutput
  memory: HRPreferenceMemory
  presetLabel?: string | null
}>()

const emit = defineEmits<{
  (e: 'apply', payload: { memory: HRPreferenceMemory; saveToPreset: boolean }): void
  (e: 'skip'): void
}>()

const localMemory = ref<HRPreferenceMemory>({
  ...props.memory,
  quick_reject_rules: props.memory.quick_reject_rules ?? [],
})
const messages = ref<Array<{ role: string; content: string }>>([])
const input = ref('')
const loading = ref(false)
const error = ref('')
const saveToPreset = ref(Boolean(props.presetLabel))

async function sendMessage() {
  const text = input.value.trim()
  if (!text || loading.value) return
  messages.value.push({ role: 'user', content: text })
  input.value = ''
  loading.value = true
  error.value = ''
  try {
    const memory = await chatPreferenceMemory({
      current_requirement: props.currentRequirement,
      parsed_intent: props.parsed as unknown as Record<string, unknown>,
      screening_criteria: localMemory.value.screening_criteria || props.parsed.screening_criteria,
      preset_memory: localMemory.value,
      messages: messages.value,
    })
    localMemory.value = memory
    if (memory.assistant_message) {
      messages.value.push({ role: 'assistant', content: memory.assistant_message })
    }
  } catch (e) {
    error.value = e instanceof Error ? e.message : '偏好更新失败'
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="preference-overlay">
    <section class="preference-modal">
      <header class="preference-head">
        <div>
          <h2>筛选偏好补充</h2>
          <p>{{ presetLabel ? `当前预设：${presetLabel}` : '当前任务' }}</p>
        </div>
        <button type="button" class="btn-ghost" @click="emit('skip')">跳过</button>
      </header>

      <div class="preference-body">
        <div class="criteria-pane">
          <h3>当前筛选标准</h3>
          <textarea v-model="localMemory.screening_criteria" />
        </div>

        <div class="chat-pane">
          <h3>HR 偏好对话</h3>
          <div class="memory-grid">
            <div>
              <span>必备</span>
              <p>{{ localMemory.must_have.join('；') || '待补充' }}</p>
            </div>
            <div>
              <span>快速淘汰</span>
              <p>{{ localMemory.quick_reject_rules.join('；') || '待补充' }}</p>
            </div>
            <div>
              <span>加分</span>
              <p>{{ localMemory.nice_to_have.join('；') || '待补充' }}</p>
            </div>
            <div>
              <span>追问</span>
              <p>{{ localMemory.followup_questions.join('；') || '待补充' }}</p>
            </div>
          </div>

          <div class="messages">
            <div v-if="localMemory.assistant_message" class="msg assistant">
              {{ localMemory.assistant_message }}
            </div>
            <div v-for="(m, idx) in messages" :key="idx" class="msg" :class="m.role">
              {{ m.content }}
            </div>
          </div>

          <div class="chat-input">
            <textarea
              v-model="input"
              placeholder="例如：必须有美签；近一年两次跳槽可快速淘汰；拉美一线销售优先"
              @keydown.ctrl.enter.prevent="sendMessage"
            />
            <button type="button" :disabled="loading || !input.trim()" @click="sendMessage">
              {{ loading ? '更新中' : '发送' }}
            </button>
          </div>
          <p v-if="error" class="error">{{ error }}</p>
        </div>
      </div>

      <footer class="preference-actions">
        <label class="save-preset">
          <input v-model="saveToPreset" type="checkbox" :disabled="!presetLabel" />
          保存到当前岗位预设
        </label>
        <div class="action-buttons">
          <button type="button" class="btn-secondary" @click="emit('skip')">使用当前标准</button>
          <button
            type="button"
            class="btn-primary"
            @click="emit('apply', { memory: localMemory, saveToPreset })"
          >
            应用并启动
          </button>
        </div>
      </footer>
    </section>
  </div>
</template>

<style scoped>
.preference-overlay {
  position: fixed;
  inset: 0;
  z-index: 1000;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 1rem;
  background: rgba(15, 23, 42, 0.42);
}

.preference-modal {
  width: min(1080px, 96vw);
  max-height: 92vh;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--card);
  box-shadow: 0 20px 60px rgba(15, 23, 42, 0.24);
}

.preference-head,
.preference-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  padding: 0.9rem 1rem;
  border-bottom: 1px solid var(--border);
}

.preference-actions {
  border-top: 1px solid var(--border);
  border-bottom: none;
}

.preference-head h2 {
  font-size: 1.05rem;
  color: var(--primary-dark);
}

.preference-head p {
  color: var(--text-muted);
  font-size: 0.84rem;
}

.preference-body {
  display: grid;
  grid-template-columns: minmax(320px, 0.9fr) minmax(360px, 1.1fr);
  gap: 1rem;
  min-height: 0;
  padding: 1rem;
  overflow: auto;
}

.criteria-pane,
.chat-pane {
  min-height: 0;
}

.criteria-pane h3,
.chat-pane h3 {
  font-size: 0.92rem;
  margin-bottom: 0.5rem;
  color: var(--primary-dark);
}

.criteria-pane textarea {
  width: 100%;
  min-height: 420px;
  resize: vertical;
  padding: 0.75rem;
  border: 1px solid var(--border);
  border-radius: 8px;
  line-height: 1.55;
}

.memory-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0.5rem;
  margin-bottom: 0.75rem;
}

.memory-grid div {
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 0.55rem;
  background: var(--primary-light);
}

.memory-grid span {
  display: block;
  margin-bottom: 0.25rem;
  color: var(--text-muted);
  font-size: 0.76rem;
  font-weight: 700;
}

.memory-grid p,
.msg {
  font-size: 0.84rem;
  line-height: 1.45;
}

.messages {
  max-height: 180px;
  overflow: auto;
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
  margin-bottom: 0.75rem;
}

.msg {
  padding: 0.5rem 0.6rem;
  border-radius: 8px;
  background: #f8fafc;
}

.msg.user {
  align-self: flex-end;
  background: #e7f1ff;
}

.msg.assistant {
  align-self: flex-start;
}

.chat-input {
  display: grid;
  grid-template-columns: 1fr auto;
  gap: 0.5rem;
}

.chat-input textarea {
  min-height: 82px;
  resize: vertical;
  padding: 0.65rem;
  border: 1px solid var(--border);
  border-radius: 8px;
}

.action-buttons {
  display: flex;
  gap: 0.5rem;
}

.btn-primary,
.btn-secondary,
.btn-ghost,
.chat-input button {
  border-radius: 8px;
  padding: 0.55rem 0.85rem;
  border: 1px solid var(--border);
  cursor: pointer;
}

.btn-primary,
.chat-input button {
  background: var(--primary);
  border-color: var(--primary);
  color: white;
}

.btn-secondary {
  background: #fff;
}

.btn-ghost {
  background: transparent;
}

.save-preset {
  display: inline-flex;
  align-items: center;
  gap: 0.45rem;
  color: var(--text-muted);
  font-size: 0.85rem;
}

.error {
  margin-top: 0.45rem;
  color: var(--error);
  font-size: 0.83rem;
}

@media (max-width: 820px) {
  .preference-body {
    grid-template-columns: 1fr;
  }
}
</style>
