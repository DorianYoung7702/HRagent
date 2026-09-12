<script setup lang="ts">

import { computed, onMounted, onUnmounted, ref, watch } from 'vue'

import {
  draftDialogueReply,
  getJobQaProfile,
  getWorkflow,
  listConversations,
  prepareFollowupIm,
  sendDialogueDraft,
  sendFollowupIm,
  sendOutreachMessage,
  updateJobQaProfile,
  updateOutreachMessage,
  updateWorkflowRuntimeOptions,
} from '../api'

import OutreachModePicker from './OutreachModePicker.vue'

import type { JobQaProfile, WorkflowInfo } from '../types'



const props = defineProps<{ workflowId: string; embedded?: boolean }>()



const IM_ACTIVE = new Set([

  'FETCHING',

  'SCREENING_COMPLETED',

  'CONVERSATIONS_STARTED',

  'PARTIAL_FAILED',

  'FETCH_COMPLETED',

  'SCREENING',

])



const workflow = ref<WorkflowInfo | null>(null)

const conversations = ref<

  Array<{

    id: string

    display_name: string | null

    subtitle: string | null

    conversation_type: string

    status: string

    need_resume_request: boolean

    last_agent_reason: string | null

    latest_outbound: string | null

    latest_inbound: string | null

    messages: Array<{

      id?: string

      direction: string

      message_text: string

      status: string

      round: number | null

      extracted_fields?: Record<string, unknown>

    }>

  }>

>([])

type PendingDraftItem = {
  conversationId: string
  messageId: string
  displayName: string
  conversationType: string
  round: number | null
  messageText: string
}

const expandedConvId = ref<string | null>(null)
const busy = ref(false)
const actionMessage = ref('')
const optionsSaving = ref(false)
const collectOnly = ref(false)
const autoReplyIm = ref(true)
const jobQaProfile = ref<JobQaProfile>({})
const qaSaving = ref(false)
const qaMessage = ref('')
const draftEdits = ref<Record<string, string>>({})



const imActive = computed(() => IM_ACTIVE.has(workflow.value?.status || ''))

const imReviewRequired = computed(() => !autoReplyIm.value)

const pendingDrafts = computed((): PendingDraftItem[] => {
  const items: PendingDraftItem[] = []
  for (const c of conversations.value) {
    for (const m of c.messages || []) {
      if (
        m.direction === 'outbound' &&
        (m.status === 'drafted' || m.status === 'failed') &&
        m.id
      ) {
        items.push({
          conversationId: c.id,
          messageId: m.id,
          displayName: c.display_name || '未知',
          conversationType: c.conversation_type,
          round: m.round,
          messageText: m.message_text,
        })
      }
    }
  }
  return items
})

const stats = computed(() => {

  const sent = conversations.value.filter((c) =>

    c.messages?.some((m) => m.direction === 'outbound' && m.status === 'sent'),

  ).length

  const replied = conversations.value.filter((c) => c.latest_inbound).length

  const pendingResume = conversations.value.filter((c) => c.need_resume_request).length

  return {
    sent,
    replied,
    pendingResume,
    pendingDrafts: pendingDrafts.value.length,
    total: conversations.value.length,
  }

})



const statusHint = computed(() => {
  const s = workflow.value?.status || ''

  if (collectOnly.value) {
    return '仅收藏模式：判定后只收藏，不开聊、不发 IM'
  }

  if (imReviewRequired.value) {
    return 'IM 人工确认：初筛「追问/观察」仍会立即开聊，话术只生成草稿，请在下方改字后发送'
  }

  const map: Record<string, string> = {
    FETCHING: '抓取中：判定后将自动开聊并发送 IM',
    SCREENING: '正在初筛…',
    FETCH_COMPLETED: '抓取完成，正在初筛…',
    SCREENING_COMPLETED: '初筛完成，IM 自动跟进中',
    CONVERSATIONS_STARTED: 'IM 跟进中：同步回复并自动发送',
  }

  return map[s] || (imActive.value ? '流程运行中…' : `当前状态「${s}」`)
})



function convTypeLabel(t: string) {

  const map: Record<string, string> = {

    followup: '追问',

    resume_request: '要简历',

    observe: '观察',

  }

  return map[t] || t

}

function normalizeJobQaProfile(profile?: JobQaProfile | null): JobQaProfile {
  return {
    responsibilities: profile?.responsibilities || '',
    work_location: profile?.work_location || '',
    salary_range: profile?.salary_range || '',
    work_mode: profile?.work_mode || '',
    interview_process: profile?.interview_process || '',
    company_intro: profile?.company_intro || '',
    team_intro: profile?.team_intro || '',
    start_time: profile?.start_time || '',
    recruiting_status: profile?.recruiting_status || '',
    custom_notes: profile?.custom_notes || '',
  }
}

function dialogueMetaLabel(fields?: Record<string, unknown>) {
  if (!fields || fields.agent_type !== 'candidate_dialogue_agent') return ''
  const question = String(fields.question_type || 'unknown')
  const source = String(fields.answer_source || '')
  const auto = fields.auto_send_allowed ? '自动' : '人工'
  return `${auto} · ${question}${source ? ` · ${source}` : ''}`
}

function hasDialogueDraft(c: {
  messages?: Array<{ direction: string; status: string; extracted_fields?: Record<string, unknown> }>
}) {
  return Boolean(
    c.messages?.some(
      (m) =>
        m.direction === 'outbound' &&
        (m.status === 'drafted' || m.status === 'failed') &&
        m.extracted_fields?.agent_type === 'candidate_dialogue_agent',
    ),
  )
}



function draftText(messageId: string, fallback: string) {
  return draftEdits.value[messageId] ?? fallback
}

function setDraftText(messageId: string, text: string) {
  draftEdits.value = { ...draftEdits.value, [messageId]: text }
}

async function handlePrepareAllDrafts() {
  busy.value = true
  actionMessage.value = ''
  try {
    const res = await prepareFollowupIm(props.workflowId)
    const newCount = res.new_count ?? res.count ?? 0
    const reused = res.reused_count ?? 0
    if (newCount > 0) {
      actionMessage.value = `已生成 ${newCount} 条新追问草稿`
    } else if (reused > 0) {
      actionMessage.value = `已有 ${reused} 条追问草稿，未重复生成`
    } else {
      actionMessage.value = '暂无需要生成的追问草稿'
    }
    await refreshConversations()
  } catch (e) {
    actionMessage.value = e instanceof Error ? e.message : '生成草稿失败'
  } finally {
    busy.value = false
  }
}

async function handleSendAllDrafts() {
  if (!pendingDrafts.value.length) {
    actionMessage.value = '暂无待发送草稿'
    return
  }
  if (!window.confirm(`确认发送全部 ${pendingDrafts.value.length} 条 IM 草稿？`)) return
  busy.value = true
  actionMessage.value = ''
  try {
    const res = await sendFollowupIm(props.workflowId, true)
    actionMessage.value = res.message || '批量发送已在后台启动'
    await refreshConversations()
  } catch (e) {
    actionMessage.value = e instanceof Error ? e.message : '批量发送失败'
  } finally {
    busy.value = false
  }
}

async function handleSaveDraft(messageId: string) {
  const text = (draftEdits.value[messageId] || '').trim()
  if (!text) {
    actionMessage.value = '草稿不能为空'
    return
  }
  busy.value = true
  actionMessage.value = ''
  try {
    await updateOutreachMessage(messageId, text)
    actionMessage.value = '草稿已保存'
    await refreshConversations()
  } catch (e) {
    actionMessage.value = e instanceof Error ? e.message : '保存失败'
  } finally {
    busy.value = false
  }
}

async function handleSendDraft(item: PendingDraftItem) {
  busy.value = true
  actionMessage.value = ''
  try {
    const edited = (draftEdits.value[item.messageId] ?? item.messageText).trim()
    if (edited !== item.messageText.trim()) {
      await updateOutreachMessage(item.messageId, edited)
    }
    await sendOutreachMessage(item.messageId)
    actionMessage.value = `已发送：${item.displayName}`
    delete draftEdits.value[item.messageId]
    await refreshConversations()
  } catch (e) {
    actionMessage.value = e instanceof Error ? e.message : '发送失败'
  } finally {
    busy.value = false
  }
}

function toggleConv(id: string) {

  expandedConvId.value = expandedConvId.value === id ? null : id

}



let timer: ReturnType<typeof setInterval> | null = null



async function refreshWorkflow() {
  try {
    workflow.value = await getWorkflow(props.workflowId)
    syncRuntimeOptionsFromWorkflow()
  } catch {
    workflow.value = null
  }
}

function syncRuntimeOptionsFromWorkflow() {
  const cfg = workflow.value?.config as {
    fetch?: { collect_only?: boolean }
    outreach?: { im_review_required?: boolean }
  } | undefined
  collectOnly.value = Boolean(cfg?.fetch?.collect_only)
  autoReplyIm.value = !Boolean(cfg?.outreach?.im_review_required)
}

async function onOutreachModeChange(next: { collectOnly: boolean; autoReplyIm: boolean }) {
  optionsSaving.value = true
  actionMessage.value = ''
  try {
    const res = await updateWorkflowRuntimeOptions(props.workflowId, {
      collect_only: next.collectOnly,
      im_auto_reply: next.autoReplyIm,
    })
    collectOnly.value = res.collect_only
    autoReplyIm.value = res.im_auto_reply
    await refreshWorkflow()
    if (res.collect_only) {
      actionMessage.value = '已切换为仅收藏模式'
    } else if (res.im_auto_reply) {
      actionMessage.value = '已切换为 IM 自动回复'
    } else {
      actionMessage.value = '已切换为 IM 人工确认后发送'
    }
  } catch (e) {
    syncRuntimeOptionsFromWorkflow()
    actionMessage.value = e instanceof Error ? e.message : '切换失败'
  } finally {
    optionsSaving.value = false
  }
}



async function refreshConversations() {

  try {

    const res = await listConversations(props.workflowId)

    conversations.value = res.conversations

  } catch {

    conversations.value = []

  }

}

async function refreshJobQaProfile() {
  try {
    const res = await getJobQaProfile(props.workflowId)
    jobQaProfile.value = normalizeJobQaProfile(res.profile)
  } catch {
    jobQaProfile.value = normalizeJobQaProfile(null)
  }
}

async function handleSaveJobQaProfile() {
  qaSaving.value = true
  qaMessage.value = ''
  try {
    const res = await updateJobQaProfile(props.workflowId, normalizeJobQaProfile(jobQaProfile.value))
    jobQaProfile.value = normalizeJobQaProfile(res.profile)
    qaMessage.value = '岗位问答资料已保存，后续回复立即生效'
  } catch (e) {
    qaMessage.value = e instanceof Error ? e.message : '保存失败'
  } finally {
    qaSaving.value = false
  }
}

async function handleDraftDialogue(conversationId: string) {
  busy.value = true
  actionMessage.value = ''
  try {
    await draftDialogueReply(conversationId)
    actionMessage.value = '已生成候选人回复草稿'
    await refreshConversations()
  } catch (e) {
    actionMessage.value = e instanceof Error ? e.message : '生成草稿失败'
  } finally {
    busy.value = false
  }
}

async function handleSendDialogue(conversationId: string) {
  busy.value = true
  actionMessage.value = ''
  try {
    await sendDialogueDraft(conversationId)
    actionMessage.value = '草稿已发送'
    await refreshConversations()
  } catch (e) {
    actionMessage.value = e instanceof Error ? e.message : '发送失败'
  } finally {
    busy.value = false
  }
}



function resetState() {
  workflow.value = null
  conversations.value = []
  expandedConvId.value = null
  busy.value = false
  actionMessage.value = ''
  optionsSaving.value = false
  collectOnly.value = false
  autoReplyIm.value = true
  jobQaProfile.value = normalizeJobQaProfile(null)
  qaSaving.value = false
  qaMessage.value = ''
  draftEdits.value = {}
}

function startPolling() {
  if (timer) clearInterval(timer)
  timer = setInterval(() => {
    refreshWorkflow()
    refreshConversations()
  }, 4000)
}

async function loadAll() {
  await Promise.all([refreshWorkflow(), refreshConversations(), refreshJobQaProfile()])
}

onMounted(() => {
  void loadAll()
  startPolling()
})

watch(
  () => props.workflowId,
  (id, prev) => {
    if (id === prev) return
    resetState()
    if (id) {
      void loadAll()
      startPolling()
    } else if (timer) {
      clearInterval(timer)
      timer = null
    }
  },
)



onUnmounted(() => {

  if (timer) clearInterval(timer)

})

</script>



<template>

  <div class="followup-panel" :class="{ card: !embedded, embedded }">

    <h2 v-if="!embedded">IM 跟进</h2>

    <p class="hint">
      查看 IM 会话与待发送草稿；初筛完成后系统自动跟进，无需手动启动 Agent。
    </p>

    <p class="status-hint">{{ statusHint }}</p>

    <OutreachModePicker
      :collect-only="collectOnly"
      :auto-reply-im="autoReplyIm"
      :disabled="optionsSaving || !imActive"
      class="runtime-mode-picker"
      @change="onOutreachModeChange"
    />

    <p v-if="actionMessage" class="action-msg">{{ actionMessage }}</p>

    <section v-if="imReviewRequired || pendingDrafts.length" class="draft-panel">
      <div class="draft-head">
        <strong>待发送 IM 草稿</strong>
        <span v-if="stats.pendingDrafts" class="draft-badge">{{ stats.pendingDrafts }} 条</span>
      </div>
      <p v-if="imReviewRequired" class="draft-hint">
        人工审核已开启：全部轮次话术需确认后才会发出
      </p>
      <div class="draft-toolbar">
        <button class="btn-secondary compact" :disabled="busy" @click="handlePrepareAllDrafts">
          重新生成追问草稿
        </button>
        <button
          class="btn-primary compact"
          :disabled="busy || !pendingDrafts.length"
          @click="handleSendAllDrafts"
        >
          确认发送全部草稿
        </button>
      </div>
      <div v-if="pendingDrafts.length" class="draft-list">
        <div v-for="item in pendingDrafts" :key="item.messageId" class="draft-item">
          <div class="draft-meta">
            <strong>{{ item.displayName }}</strong>
            <span class="type-tag">{{ convTypeLabel(item.conversationType) }}</span>
            <span v-if="item.round" class="round-tag">第 {{ item.round }} 轮</span>
          </div>
          <textarea
            :value="draftText(item.messageId, item.messageText)"
            rows="3"
            class="draft-input"
            @input="setDraftText(item.messageId, ($event.target as HTMLTextAreaElement).value)"
          />
          <div class="draft-actions">
            <button class="btn-secondary compact" :disabled="busy" @click="handleSaveDraft(item.messageId)">
              保存
            </button>
            <button class="btn-primary compact" :disabled="busy" @click="handleSendDraft(item)">
              发送本条
            </button>
          </div>
        </div>
      </div>
      <p v-else class="empty-hint">暂无待发送草稿</p>
    </section>

    <section class="qa-panel">
      <div class="qa-head">
        <strong>岗位问答资料</strong>
        <button class="btn-secondary compact" :disabled="qaSaving" @click="handleSaveJobQaProfile">
          保存资料
        </button>
      </div>
      <div class="qa-fields">
        <input v-model="jobQaProfile.salary_range" placeholder="薪资范围" />
        <input v-model="jobQaProfile.work_location" placeholder="工作地点" />
        <input v-model="jobQaProfile.work_mode" placeholder="工作模式" />
        <input v-model="jobQaProfile.interview_process" placeholder="面试流程" />
        <input v-model="jobQaProfile.start_time" placeholder="到岗时间" />
        <input v-model="jobQaProfile.recruiting_status" placeholder="招聘状态" />
        <textarea v-model="jobQaProfile.responsibilities" rows="2" placeholder="岗位职责" />
        <textarea v-model="jobQaProfile.company_intro" rows="2" placeholder="公司/团队介绍" />
      </div>
      <p v-if="qaMessage" class="qa-msg">{{ qaMessage }}</p>
    </section>

    <div v-if="stats.total" class="stats-row">

      <span>会话 {{ stats.total }}</span>

      <span>已发送 {{ stats.sent }}</span>

      <span>有回复 {{ stats.replied }}</span>

      <span v-if="stats.pendingDrafts">待发送 {{ stats.pendingDrafts }}</span>

      <span v-if="stats.pendingResume">待要简历 {{ stats.pendingResume }}</span>

    </div>



    <div v-if="conversations.length" class="conv-list">

      <h3>对话记录</h3>

      <div v-for="c in conversations" :key="c.id" class="conv-block">

        <button type="button" class="conv-summary" @click="toggleConv(c.id)">

          <div class="conv-head">

            <div class="conv-title">

              <strong>{{ c.display_name || '未知' }}</strong>

              <span class="conv-sub">{{ c.subtitle || '—' }}</span>

            </div>

            <span class="badge badge-running">{{ c.status }}</span>

          </div>

          <div class="conv-tags">

            <span class="type-tag">{{ convTypeLabel(c.conversation_type) }}</span>

            <span v-if="c.need_resume_request" class="resume-flag">待要简历</span>

          </div>

        </button>

        <div v-show="expandedConvId === c.id" class="conv-body">

          <div v-if="c.messages?.length" class="msg-thread">

            <div

              v-for="(m, mi) in c.messages"

              :key="mi"

              class="msg-bubble"

              :class="m.direction === 'outbound' ? 'msg-out' : 'msg-in'"

            >

              <span class="msg-dir">{{ m.direction === 'outbound' ? '发出' : '收到' }}</span>

              <p>{{ m.message_text }}</p>

              <small v-if="dialogueMetaLabel(m.extracted_fields)" class="msg-meta">
                {{ dialogueMetaLabel(m.extracted_fields) }}
              </small>

            </div>

          </div>

          <p v-else-if="c.latest_outbound" class="conv-preview">{{ c.latest_outbound }}</p>

          <p v-if="c.latest_inbound" class="conv-inbound">最新回复：{{ c.latest_inbound }}</p>

          <p v-if="c.last_agent_reason" class="conv-reason">{{ c.last_agent_reason }}</p>

          <div class="conv-actions">
            <button class="btn-secondary compact" :disabled="busy" @click="handleDraftDialogue(c.id)">
              生成回复草稿
            </button>
            <button
              v-if="hasDialogueDraft(c)"
              class="btn-primary compact"
              :disabled="busy"
              @click="handleSendDialogue(c.id)"
            >
              发送人工草稿
            </button>
          </div>

        </div>

      </div>

    </div>



    <p v-else-if="imActive" class="empty-hint">暂无 IM 会话，抓取判定追问/观察后将自动出现</p>

  </div>

</template>



<style scoped>

.followup-panel {
  display: flex;
  flex-direction: column;
  min-height: 0;
}

.followup-panel.embedded {
  height: 100%;
  padding: 0.65rem 0.85rem 0.75rem;
  overflow: hidden;
}

.followup-panel.embedded .conv-list {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  margin-top: 0.35rem;
}

.followup-panel h2 {

  font-size: 1.05rem;

  color: var(--primary-dark);

  margin-bottom: 0.5rem;

}



.hint {

  font-size: 0.78rem;

  color: var(--text-muted);

  margin-bottom: 0.45rem;

  line-height: 1.4;

}



.status-hint {

  font-size: 0.8rem;

  color: #1e40af;

  background: #eff6ff;

  padding: 0.35rem 0.6rem;

  border-radius: 6px;

  margin-bottom: 0.45rem;

  flex-shrink: 0;

}

.draft-panel {
  margin: 0.65rem 0;
  padding: 0.65rem 0.75rem;
  border: 1px solid #dbeafe;
  border-radius: 8px;
  background: #f8fbff;
  flex-shrink: 0;
}

.draft-head {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin-bottom: 0.35rem;
}

.draft-badge {
  font-size: 0.72rem;
  background: #fef3c7;
  color: #92400e;
  padding: 0.1rem 0.45rem;
  border-radius: 999px;
}

.draft-hint {
  font-size: 0.76rem;
  color: var(--text-muted);
  margin: 0 0 0.45rem;
}

.draft-toolbar {
  display: flex;
  flex-wrap: wrap;
  gap: 0.45rem;
  margin-bottom: 0.55rem;
}

.draft-list {
  display: flex;
  flex-direction: column;
  gap: 0.55rem;
}

.draft-item {
  padding: 0.55rem;
  border: 1px solid #e5e7eb;
  border-radius: 6px;
  background: #fff;
}

.draft-meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.35rem;
  margin-bottom: 0.35rem;
}

.round-tag {
  font-size: 0.72rem;
  color: #64748b;
}

.draft-input {
  width: 100%;
  box-sizing: border-box;
  font: inherit;
  padding: 0.4rem 0.5rem;
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  resize: vertical;
}

.draft-actions {
  display: flex;
  gap: 0.4rem;
  margin-top: 0.4rem;
}



.action-msg {

  font-size: 0.85rem;

  color: var(--primary-dark);

  margin-bottom: 0.65rem;

}

.runtime-mode-picker {
  margin-bottom: 0.75rem;
}



.stats-row {

  display: flex;

  flex-wrap: wrap;

  gap: 0.75rem;

  font-size: 0.82rem;

  color: var(--text-muted);

  margin-bottom: 0.75rem;

}



.empty-hint {

  flex: 1;

  display: flex;

  align-items: center;

  justify-content: center;

  font-size: 0.85rem;

  color: var(--text-muted);

  text-align: center;

  padding: 1rem;

}



.conv-list {

  margin-top: 0.5rem;

}



.conv-list h3 {

  font-size: 0.9rem;

  margin-bottom: 0.5rem;

  color: var(--text-muted);

}



.conv-block {

  border: 1px solid var(--border);

  border-radius: 8px;

  margin-bottom: 0.5rem;

  overflow: hidden;

}



.conv-summary {

  width: 100%;

  text-align: left;

  background: var(--primary-light);

  border: none;

  padding: 0.6rem 0.75rem;

  cursor: pointer;

  font: inherit;

}



.conv-summary:hover {

  background: #dbeafe;

}



.conv-head {

  display: flex;

  justify-content: space-between;

  align-items: flex-start;

  gap: 0.5rem;

}



.conv-title strong {

  display: block;

}



.conv-sub {

  font-size: 0.78rem;

  color: var(--text-muted);

  font-weight: normal;

}



.conv-tags {

  margin-top: 0.35rem;

  display: flex;

  gap: 0.35rem;

  flex-wrap: wrap;

}



.type-tag {

  font-size: 0.72rem;

  padding: 0.1rem 0.4rem;

  background: #e0e7ff;

  color: #3730a3;

  border-radius: 4px;

}



.conv-body {

  padding: 0.6rem 0.75rem;

  background: var(--bg);

  border-top: 1px solid var(--border);

  font-size: 0.85rem;

}



.msg-thread {

  display: flex;

  flex-direction: column;

  gap: 0.4rem;

}



.msg-bubble {

  padding: 0.45rem 0.55rem;

  border-radius: 6px;

  line-height: 1.4;

}



.msg-out {

  background: #e0f2fe;

  align-self: flex-end;

  max-width: 92%;

}



.msg-in {

  background: #f0fdf4;

  align-self: flex-start;

  max-width: 92%;

}



.msg-dir {

  font-size: 0.7rem;

  color: var(--text-muted);

  display: block;

  margin-bottom: 0.15rem;

}



.conv-preview,

.conv-inbound {

  line-height: 1.45;

}



.conv-reason {

  margin-top: 0.35rem;

  color: var(--text-muted);

  font-size: 0.8rem;

}



.resume-flag {

  font-size: 0.72rem;

  padding: 0.1rem 0.4rem;

  background: #fef3c7;

  color: #92400e;

  border-radius: 4px;

}

.qa-panel {
  border: 1px solid #dbe3ef;
  border-radius: 8px;
  padding: 0.65rem;
  margin: 0.45rem 0 0.65rem;
  background: #f8fafc;
  flex-shrink: 0;
}

.qa-head {
  display: flex;
  justify-content: space-between;
  gap: 0.75rem;
  align-items: center;
  margin-bottom: 0.5rem;
}

.qa-fields {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0.45rem;
}

.qa-fields input,
.qa-fields textarea {
  width: 100%;
  font: inherit;
  font-size: 0.82rem;
  resize: vertical;
}

.qa-msg,
.msg-meta {
  color: var(--text-muted);
  font-size: 0.74rem;
}

.msg-meta {
  display: block;
  margin-top: 0.25rem;
}

.conv-actions {
  display: flex;
  gap: 0.5rem;
  margin-top: 0.55rem;
  flex-wrap: wrap;
}

.compact {
  padding: 0.25rem 0.55rem;
  font-size: 0.78rem;
}

@media (max-width: 900px) {
  .qa-fields {
    grid-template-columns: 1fr;
  }
}

</style>

