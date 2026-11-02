<script setup>
/**
 * AssistantView —— 智能助手（核心页面）
 *
 * 关键点：
 *  - 用 fetch + ReadableStream 手工解析 SSE（见 api/sse.js），因为 EventSource 无法带 Authorization 头
 *  - token 事件累积拼接，实现「逐字」流式显示
 *  - tool_call / tool_result 渲染成工具卡片，status 事件渲染成步骤时间线
 *  - interrupt 事件弹出写操作审批卡片，用户批准后调 /api/agent/resume 继续同一线程
 *  - 支持 AbortController 中途停止
 */
import { ref, nextTick, onMounted, computed } from 'vue'
import { chatWithAgent, resumeAgent, getAgentStatus } from '../api/endpoints.js'
import StepTimeline from '../components/StepTimeline.vue'
import ToolCallCard from '../components/ToolCallCard.vue'
import ApprovalCard from '../components/ApprovalCard.vue'

const QUICK_PROMPTS = [
  '一学期最多能选多少学分',
  '帮我选 CS202',
  '退课有什么限制',
  '我的课表',
  '我的成绩',
  '还有哪些课能选',
  '毕业设计查重率要求多少',
]

const turns = ref([])          // 对话消息列表
const input = ref('')
const streaming = ref(false)   // 是否有流正在进行
const threadId = ref('')       // 最近一次会话线程 id
const modelInfo = ref(null)
const chatRef = ref(null)
let aborter = null
let seq = 0

const nextId = () => `t${++seq}`

const isFake = computed(() => modelInfo.value && modelInfo.value.is_fake)
const hasPendingApproval = computed(() => turns.value.some((t) => t.approval))

/** 新建一条 assistant 轮次对象 */
function newAssistantTurn() {
  return {
    id: nextId(),
    role: 'assistant',
    text: '',
    steps: [],
    tools: [],
    approval: null,
    error: '',
    done: false,
    running: true,
    stopped: false,
  }
}

function scrollToBottom() {
  nextTick(() => {
    const el = chatRef.value
    if (el) el.scrollTop = el.scrollHeight
  })
}

/** 往时间线追加一条步骤（相邻重复则跳过） */
function pushStep(turn, label, kind = 'stage') {
  if (!label) return
  const last = turn.steps[turn.steps.length - 1]
  if (last && last.label === label && last.kind === kind) return
  turn.steps.push({ label, kind })
}

/** 统一处理一个 SSE 事件，写入指定 assistant 轮次 */
function applyEvent(turn, evt) {
  const { event, data } = evt
  switch (event) {
    case 'meta':
      modelInfo.value = data.model || modelInfo.value
      if (data.thread_id) { threadId.value = data.thread_id; turn.threadId = data.thread_id }
      break

    case 'start':
      if (data.thread_id) { threadId.value = data.thread_id; turn.threadId = data.thread_id }
      break

    case 'status':
      pushStep(turn, data.label, data.stage === 'done' ? 'done' : 'stage')
      break

    case 'tool_call': {
      const t = {
        id: data.id || `tool_${turn.tools.length}`,
        name: data.name,
        label: data.label || data.name,
        args: data.args || {},
        status: 'running',
        ok: null,
        summary: '',
        content: '',
      }
      turn.tools.push(t)
      pushStep(turn, `调用工具：${t.label}`, 'tool')
      break
    }

    case 'tool_result': {
      const t = turn.tools.find((x) => x.id === data.id)
        || turn.tools.find((x) => x.name === data.name && x.status === 'running')
      if (t) {
        t.decision = data.decision || ''
        t.status = data.decision === 'reject'
          ? 'rejected'
          : (data.ok === false ? 'fail' : 'ok')
        t.ok = data.ok !== false
        t.summary = data.summary || ''
        t.content = data.content || ''
        if (data.label) t.label = data.label
      }
      break
    }

    case 'token':
      // 关键：累积拼接文本片段，实现流式逐字输出
      turn.text += data.text || ''
      scrollToBottom()
      break

    case 'interrupt':
      turn.approval = { actions: data.actions || [] }
      if (data.thread_id) { turn.threadId = data.thread_id; threadId.value = data.thread_id }
      pushStep(turn, '等待你确认写操作…', 'stage')
      break

    case 'done':
      turn.done = true
      turn.running = false
      turn.approval = null
      pushStep(turn, '已完成', 'done')
      break

    case 'error':
      turn.error = data.message || '发生未知错误'
      turn.running = false
      break

    default:
      break
  }
  scrollToBottom()
}

/** 跑一次流；step 负责把事件写入对应轮次 */
async function runStream(startFn, turn) {
  streaming.value = true
  turn.running = true
  aborter = new AbortController()
  try {
    await startFn({
      onEvent: (evt) => applyEvent(turn, evt),
      signal: aborter.signal,
    })
  } catch (e) {
    if (e && e.name === 'AbortError') {
      turn.stopped = true
      pushStep(turn, '已手动停止', 'error')
    } else {
      turn.error = e.message || '请求失败'
      pushStep(turn, `出错：${turn.error}`, 'error')
    }
    turn.running = false
  } finally {
    streaming.value = false
    turn.running = false
    aborter = null
    scrollToBottom()
  }
}

function send(textArg) {
  const content = (textArg ?? input.value).trim()
  if (!content || streaming.value || hasPendingApproval.value) return
  input.value = ''

  turns.value.push({ id: nextId(), role: 'user', text: content })
  const turn = newAssistantTurn()
  turns.value.push(turn)
  scrollToBottom()

  runStream(
    (handlers) => chatWithAgent(content, threadId.value || undefined, handlers),
    turn,
  )
}

function stop() {
  if (aborter) aborter.abort()
}

/* ---------- 审批 ---------- */
async function onSubmitDecisions(turn, decisions) {
  const savedApproval = turn.approval
  turn.approval = null
  turn.error = ''
  const tid = turn.threadId || threadId.value
  await runStream(
    (handlers) => resumeAgent(tid, decisions, handlers),
    turn,
  )
  // 失败时把卡片放回来：否则 409/网络故障后用户失去重试入口。
  // 成功会置 done；模型再次请求审批会给出新的 approval；手动停止则不恢复。
  if (!turn.done && !turn.approval && !turn.stopped && savedApproval) {
    turn.approval = savedApproval
  }
}

function clearChat() {
  if (streaming.value) return
  turns.value = []
  threadId.value = ''
}

function onKeydown(e) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    send()
  }
}

onMounted(async () => {
  try {
    const st = await getAgentStatus()
    modelInfo.value = st.model
  } catch {
    /* 忽略：拿不到自检信息不影响对话 */
  }
})
</script>

<template>
  <div class="assistant">
    <!-- 顶部状态条 -->
    <div class="agent-bar">
      <div class="row">
        <span class="agent-title">智能助手</span>
        <span class="tag" :class="modelInfo && modelInfo.is_fake ? 'tag-warn' : 'tag-ok'">
          <span v-if="!modelInfo" class="spinner" style="width:10px;height:10px;border-width:2px"></span>
          {{ modelInfo ? (modelInfo.provider || 'model') : '加载中' }}
        </span>
      </div>
      <div class="row small muted wrap">
        <template v-if="isFake">
          <span class="fake-note">
            ⓘ 当前为内置脚本假模型：<b>链路真实、推理为规则模拟</b>，并非接入真实大模型
          </span>
        </template>
        <template v-else-if="modelInfo">
          <span class="fake-note">{{ modelInfo.note }}</span>
        </template>
      </div>
    </div>

    <!-- 对话区 -->
    <div class="chat" ref="chatRef">
      <div v-if="!turns.length" class="welcome">
        <div class="welcome-logo">◎</div>
        <h2>你好，我是校园课程智能助手</h2>
        <p class="muted">
          可以问我选课规则、课程信息、我的课表与成绩。涉及选课 / 退课这类写操作时，
          我会先请求你确认再执行。
        </p>
      </div>

      <div v-for="turn in turns" :key="turn.id" class="turn" :class="turn.role">
        <!-- 用户消息 -->
        <div v-if="turn.role === 'user'" class="msg-user">
          <div class="bubble-user">{{ turn.text }}</div>
        </div>

        <!-- 助手消息 -->
        <div v-else class="msg-assistant">
          <div class="avatar">◎</div>
          <div class="assistant-body">
            <StepTimeline :steps="turn.steps" :running="turn.running && !turn.approval" />

            <ToolCallCard v-for="t in turn.tools" :key="t.id" :tool="t" />

            <ApprovalCard
              v-if="turn.approval"
              :actions="turn.approval.actions"
              :busy="streaming"
              @submit="onSubmitDecisions(turn, $event)"
            />

            <div v-if="turn.text" class="bubble-ai">
              {{ turn.text }}<span v-if="turn.running" class="caret">▋</span>
            </div>

            <div v-else-if="turn.running && !turn.approval && !turn.tools.length" class="bubble-ai dim">
              正在思考<span class="caret">▋</span>
            </div>

            <div v-if="turn.error" class="err-box">⚠ {{ turn.error }}</div>
            <div v-if="turn.stopped" class="stop-box">已停止本次回答</div>
          </div>
        </div>
      </div>
    </div>

    <!-- 输入区 -->
    <div class="composer">
      <div class="quick-row">
        <button
          v-for="q in QUICK_PROMPTS"
          :key="q"
          class="quick-btn"
          :disabled="streaming || hasPendingApproval"
          @click="send(q)"
        >
          {{ q }}
        </button>
      </div>

      <div class="input-row">
        <textarea
          v-model="input"
          class="input composer-input"
          rows="1"
          :placeholder="hasPendingApproval ? '请先在上方完成审批' : '输入你的问题，Enter 发送，Shift+Enter 换行'"
          @keydown="onKeydown"
          :disabled="streaming || hasPendingApproval"
        ></textarea>

        <button
          v-if="!streaming"
          class="btn btn-primary"
          :disabled="!input.trim() || hasPendingApproval"
          @click="send()"
        >
          发送
        </button>
        <button v-else class="btn btn-danger" @click="stop">停止</button>

        <button
          class="btn btn-ghost"
          :disabled="streaming || hasPendingApproval || !turns.length"
          @click="clearChat"
        >
          清空
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.assistant {
  height: 100%;
  display: flex;
  flex-direction: column;
  min-height: 0;
}

/* 顶部状态条 */
.agent-bar {
  padding: 12px 24px;
  border-bottom: 1px solid var(--border);
  background: var(--bg-panel);
  flex-shrink: 0;
  /* 显式建立层叠上下文并压过滚动区：
     否则对话区滚动时，最早的内容会盖到状态条上，出现文字叠字。 */
  position: relative;
  z-index: 2;
}
.agent-title { font-size: 14px; font-weight: 600; }
.fake-note { color: var(--warn); font-size: 12px; }
.fake-note b { color: #ffc978; }

/* 对话区 */
.chat {
  flex: 1;
  overflow-y: auto;
  padding: 22px 24px;
  min-height: 0;
  /* 对话区自己也是一层，且永远在状态条之下 */
  position: relative;
  z-index: 1;
  /* 用 smooth 的锚点滚动时留出顶部余量，避免首行贴边 */
  scroll-padding-top: 16px;
}

.welcome { max-width: 560px; margin: 40px auto; text-align: center; }
.welcome-logo {
  font-size: 46px;
  color: var(--accent);
  text-shadow: 0 0 28px rgba(78,161,255,.5);
}
.welcome h2 { font-size: 19px; margin: 12px 0 8px; }
.welcome p { font-size: 13px; line-height: 1.8; }

.turn { margin-bottom: 22px; }

.msg-user { display: flex; justify-content: flex-end; }
.bubble-user {
  max-width: 78%;
  background: var(--accent-dim);
  color: #eef5ff;
  padding: 10px 14px;
  border-radius: 12px 12px 3px 12px;
  font-size: 13.5px;
  white-space: pre-wrap;
  word-break: break-word;
}

.msg-assistant { display: flex; gap: 12px; align-items: flex-start; }
.avatar {
  width: 30px; height: 30px; flex-shrink: 0;
  display: flex; align-items: center; justify-content: center;
  border-radius: 50%;
  background: var(--bg-panel-2);
  border: 1px solid var(--border-strong);
  color: var(--accent);
  font-size: 15px;
}
.assistant-body { flex: 1; min-width: 0; }

.bubble-ai {
  background: var(--bg-panel);
  border: 1px solid var(--border);
  border-radius: 3px 12px 12px 12px;
  padding: 11px 14px;
  font-size: 13.5px;
  white-space: pre-wrap;
  word-break: break-word;
  line-height: 1.75;
}
.bubble-ai.dim { color: var(--text-mute); }

.caret {
  display: inline-block;
  margin-left: 1px;
  color: var(--accent);
  animation: blink 1s steps(1) infinite;
}
@keyframes blink { 50% { opacity: 0; } }

.err-box {
  margin-top: 8px;
  background: var(--danger-soft);
  border: 1px solid rgba(240,97,109,.35);
  color: #ff9aa3;
  border-radius: var(--radius-sm);
  padding: 8px 12px;
  font-size: 12.5px;
}
.stop-box { margin-top: 8px; font-size: 12px; color: var(--text-mute); }

/* 输入区 */
.composer {
  flex-shrink: 0;
  border-top: 1px solid var(--border);
  background: var(--bg-panel);
  padding: 12px 24px 16px;
}
.quick-row { display: flex; flex-wrap: wrap; gap: 7px; margin-bottom: 10px; }
.quick-btn {
  padding: 5px 11px;
  border-radius: 20px;
  border: 1px solid var(--border-strong);
  background: var(--bg-panel-2);
  color: var(--text-dim);
  font-size: 12px;
  font-family: inherit;
  cursor: pointer;
  transition: all .15s;
}
.quick-btn:hover:not(:disabled) { border-color: var(--accent); color: var(--accent); background: var(--accent-soft); }
.quick-btn:disabled { opacity: .45; cursor: not-allowed; }

.input-row { display: flex; gap: 10px; align-items: flex-end; }
.composer-input {
  resize: none;
  min-height: 40px;
  max-height: 140px;
  line-height: 1.5;
  font-size: 13.5px;
}
.input-row .btn { height: 40px; }
</style>
