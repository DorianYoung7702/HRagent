<script setup lang="ts">
import { onMounted, onUnmounted, ref, watch } from 'vue'
import {
  cancelLiepinLogin,
  clearAndReloginLiepin,
  completeLiepinLogin,
  getLiepinLoginStatus,
  verifyLiepinLogin,
} from '../api'
import type { LiepinLoginStatus } from '../types'

const emit = defineEmits<{ (e: 'ready-change', ready: boolean): void }>()

const status = ref<LiepinLoginStatus | null>(null)
const busy = ref(false)
const error = ref('')
let pollTimer: ReturnType<typeof setInterval> | null = null

function applyStatus(data: LiepinLoginStatus) {
  status.value = data
  emit('ready-change', !!data.can_start_task)
}

async function refresh(silent = false) {
  if (!silent) busy.value = true
  if (!silent) error.value = ''
  try {
    const data = await getLiepinLoginStatus()
    applyStatus(data)
  } catch (e) {
    if (!silent) error.value = e instanceof Error ? e.message : '获取登录状态失败'
    emit('ready-change', false)
  } finally {
    if (!silent) busy.value = false
  }
}

async function handleRelogin() {
  busy.value = true
  error.value = ''
  try {
    applyStatus(await clearAndReloginLiepin())
    startPoll()
  } catch (e) {
    error.value = e instanceof Error ? e.message : '操作失败'
  } finally {
    busy.value = false
  }
}

async function handleComplete() {
  busy.value = true
  error.value = ''
  try {
    applyStatus(await completeLiepinLogin())
    stopPoll()
  } catch (e) {
    error.value = e instanceof Error ? e.message : '保存失败'
  } finally {
    busy.value = false
  }
}

async function handleCancel() {
  busy.value = true
  try {
    applyStatus(await cancelLiepinLogin())
    stopPoll()
  } finally {
    busy.value = false
  }
}

async function handleVerify() {
  busy.value = true
  error.value = ''
  try {
    applyStatus(await verifyLiepinLogin())
  } catch (e) {
    error.value = e instanceof Error ? e.message : '检测失败'
    emit('ready-change', false)
  } finally {
    busy.value = false
  }
}

function startPoll() {
  stopPoll()
  pollTimer = setInterval(() => {
    if (status.value?.status === 'waiting') refresh(true)
  }, 3000)
}

function stopPoll() {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

const badgeClass = () => {
  const s = status.value?.status
  if (s === 'ready') return 'badge-ok'
  if (s === 'waiting' || s === 'verifying') return 'badge-warn'
  if (s === 'error') return 'badge-err'
  return 'badge-idle'
}

const badgeText = () => {
  const s = status.value?.status
  if (s === 'ready') return '已就绪'
  if (s === 'waiting') return '等待登录'
  if (s === 'verifying') return '验证中'
  if (s === 'error') return '需重新登录'
  return '未初始化'
}

watch(
  () => status.value?.status,
  (s) => {
    if (s === 'waiting') startPoll()
    else stopPoll()
  },
)

onMounted(() => refresh(true))
onUnmounted(stopPoll)
</script>

<template>
  <section class="card login-setup">
    <div class="head">
      <h2>猎聘登录</h2>
      <span class="badge" :class="badgeClass()">{{ badgeText() }}</span>
    </div>
    <p class="hint">
      登录信息保存在<strong>运行本系统的电脑</strong>上。首次使用或登录过期时，点击「清除并重新登录」，
      在服务器弹出的浏览器窗口完成猎聘登录，再回到此处点「我已完成登录」。
    </p>

    <div v-if="busy && status?.status === 'verifying'" class="verifying">
      <span class="mini-spin" />
      正在检测登录态，请稍候…
    </div>

    <div
      v-if="status?.verify_result"
      class="verify-result"
      :class="status.verify_result.logged_in ? 'verify-ok' : 'verify-fail'"
    >
      <p class="verify-title">
        {{ status.verify_result.logged_in ? '✓ 检测通过：已登录' : '✗ 检测未通过：未登录' }}
      </p>
      <ul>
        <li><strong>页面类型</strong>{{ status.verify_result.page_type }}</li>
        <li><strong>当前 URL</strong>{{ status.verify_result.url }}</li>
        <li><strong>可启动任务</strong>{{ status.can_start_task ? '是' : '否' }}</li>
      </ul>
    </div>

    <p v-if="status?.message" class="msg">{{ status.message }}</p>
    <p v-if="status?.error" class="err">{{ status.error }}</p>
    <p v-if="error" class="err">{{ error }}</p>
    <p v-if="status?.profile_path" class="path">缓存目录：{{ status.profile_path }}</p>

    <div class="actions">
      <template v-if="status?.status !== 'waiting'">
        <button class="btn-primary" :disabled="busy" @click="handleRelogin">
          清除并重新登录
        </button>
        <button class="btn-secondary" :disabled="busy" @click="handleVerify">
          {{ busy && status?.status === 'verifying' ? '检测中…' : '检测登录态' }}
        </button>
      </template>
      <template v-else>
        <button class="btn-primary" :disabled="busy" @click="handleComplete">我已完成登录</button>
        <button class="btn-secondary" :disabled="busy" @click="handleCancel">取消</button>
      </template>
    </div>
  </section>
</template>

<style scoped>
.login-setup {
  border: 2px solid #b8daf0;
  margin-bottom: 1rem;
}

.head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  margin-bottom: 0.5rem;
}

.head h2 {
  font-size: 1.05rem;
  color: var(--primary-dark);
}

.badge {
  font-size: 0.8rem;
  padding: 0.25rem 0.65rem;
  border-radius: 999px;
  font-weight: 600;
}

.badge-ok {
  background: #d1fae5;
  color: #047857;
}

.badge-warn {
  background: #fef3c7;
  color: #b45309;
}

.badge-err {
  background: #fee2e2;
  color: #b91c1c;
}

.badge-idle {
  background: #e8f4fc;
  color: var(--primary-dark);
}

.hint {
  font-size: 0.88rem;
  color: var(--text-muted);
  line-height: 1.55;
  margin-bottom: 0.5rem;
}

.verifying {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 0.9rem;
  color: var(--primary-dark);
  margin-bottom: 0.75rem;
}

.mini-spin {
  width: 16px;
  height: 16px;
  border: 2px solid var(--primary-light);
  border-top-color: var(--primary);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

.verify-result {
  border-radius: 8px;
  padding: 0.75rem 1rem;
  margin-bottom: 0.75rem;
  font-size: 0.88rem;
}

.verify-ok {
  background: #ecfdf5;
  border: 1px solid #6ee7b7;
}

.verify-fail {
  background: #fef2f2;
  border: 1px solid #fca5a5;
}

.verify-title {
  font-weight: 600;
  margin-bottom: 0.5rem;
}

.verify-result ul {
  list-style: none;
  line-height: 1.6;
}

.verify-result strong {
  color: var(--text-muted);
  margin-right: 0.35rem;
}

.msg {
  font-size: 0.9rem;
  color: var(--primary-dark);
  background: var(--primary-light);
  padding: 0.6rem 0.85rem;
  border-radius: 8px;
  margin-bottom: 0.5rem;
}

.err {
  color: var(--error);
  font-size: 0.88rem;
  margin-bottom: 0.5rem;
}

.path {
  font-size: 0.78rem;
  color: var(--text-muted);
  word-break: break-all;
  margin-bottom: 0.75rem;
}

.actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.6rem;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}
</style>
