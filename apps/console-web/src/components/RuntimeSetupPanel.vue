<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import {
  getRuntimeSettings,
  updateRuntimeSettings,
} from '../api'
import type { RuntimeSettings } from '../types'

const emit = defineEmits<{ (e: 'ready-change', ready: boolean): void }>()

const runtime = ref<RuntimeSettings | null>(null)
const deepseekKey = ref('')
const companyName = ref('')
const loading = ref(true)
const savingRuntime = ref(false)
const error = ref('')

const runtimeReady = computed(
  () =>
    Boolean(runtime.value?.deepseek_configured) &&
    Boolean(runtime.value?.hr_identity_configured),
)
const allReady = computed(() => runtimeReady.value)

async function refresh() {
  loading.value = true
  error.value = ''
  try {
    runtime.value = await getRuntimeSettings()
    if (runtime.value?.hr_company_name && !companyName.value) {
      companyName.value = runtime.value.hr_company_name
    }
  } catch (e) {
    error.value = e instanceof Error ? e.message : '加载配置失败'
  } finally {
    loading.value = false
    emit('ready-change', allReady.value)
  }
}

async function submitRuntime() {
  if (!deepseekKey.value.trim() || !companyName.value.trim()) {
    error.value = '请填写 DeepSeek API Key 与招聘方身份'
    return
  }
  savingRuntime.value = true
  error.value = ''
  try {
    runtime.value = await updateRuntimeSettings({
      deepseek_api_key: deepseekKey.value.trim(),
      hr_company_name: companyName.value.trim(),
    })
    deepseekKey.value = ''
    await refresh()
  } catch (e) {
    error.value = e instanceof Error ? e.message : '保存失败'
  } finally {
    savingRuntime.value = false
  }
}

onMounted(refresh)
</script>

<template>
  <section class="card runtime-setup">
    <h2>LLM 配置</h2>
    <p class="hint">配置用于简历解析、筛选和候选人总结的模型 API Key。</p>

    <div v-if="loading" class="muted">正在加载配置…</div>

    <template v-else>
      <div class="block">
        <div class="block-head">
          <h3>DeepSeek API Key 与招聘方身份</h3>
          <span :class="['badge', runtimeReady ? 'ok' : 'warn']">
            {{ runtimeReady ? '已配置' : '待配置' }}
          </span>
        </div>
        <p class="muted">
          DeepSeek Key 用于 AI 解析与初筛；招聘方身份会写入 IM/追问话术（如您的猎头公司或甲方品牌）。
        </p>
        <p v-if="runtime?.deepseek_configured" class="muted">
          当前 Key：{{ runtime.deepseek_api_key_masked || '已配置' }}
        </p>
        <p v-if="runtime?.hr_company_name" class="muted">当前身份：{{ runtime.hr_company_name }}</p>
        <label class="field">
          <span>DeepSeek API Key</span>
          <input
            v-model="deepseekKey"
            type="password"
            autocomplete="off"
            placeholder="sk-..."
          />
        </label>
        <label class="field">
          <span>招聘方身份 / 公司名</span>
          <input v-model="companyName" type="text" placeholder="例如：某某猎头 / 某某科技 HR" />
        </label>
        <button class="btn-primary" :disabled="savingRuntime" @click="submitRuntime">
          {{ savingRuntime ? '保存中…' : runtimeReady ? '更新配置' : '保存并继续' }}
        </button>
      </div>

      <p v-if="allReady" class="ok-text">配置已完成，可以开始筛选任务。</p>
      <p v-if="error" class="error">{{ error }}</p>
    </template>
  </section>
</template>

<style scoped>
.runtime-setup h2 {
  font-size: 1.05rem;
  margin-bottom: 0.35rem;
  color: var(--primary-dark);
}

.hint {
  color: var(--text-muted);
  font-size: 0.88rem;
  margin-bottom: 0.85rem;
}

.block {
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 0.85rem;
  margin-bottom: 0.75rem;
}

.block-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
  margin-bottom: 0.45rem;
}

.block-head h3 {
  font-size: 0.95rem;
}

.row {
  display: flex;
  gap: 0.5rem;
  margin-top: 0.5rem;
}

.row input {
  flex: 1;
}

.field {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  margin: 0.55rem 0;
  font-size: 0.85rem;
}

.badge {
  font-size: 0.75rem;
  padding: 0.15rem 0.45rem;
  border-radius: 999px;
}

.badge.ok {
  background: #e6f7ee;
  color: #1b7f4a;
}

.badge.warn {
  background: #fff4e5;
  color: #b45309;
}

.muted {
  color: var(--text-muted);
  font-size: 0.85rem;
}

.warn-text {
  color: #b45309;
  font-size: 0.85rem;
}

.ok-text {
  color: #1b7f4a;
  font-size: 0.9rem;
}

.error {
  color: var(--error);
  font-size: 0.88rem;
  margin-top: 0.5rem;
}
</style>
