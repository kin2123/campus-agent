<script setup>
/**
 * ApprovalCard —— 写操作审批卡片
 *
 * 一个 interrupt 里可能有多个待执行操作（例如模型一次要求选两门课），
 * 因此必须逐项决定，不能一个按钮替所有操作做决定。
 * 提交的 decisions 顺序与后端 pending_actions 的顺序一致。
 */
import { computed, ref, watch } from 'vue'

const props = defineProps({
  actions: { type: Array, default: () => [] },
  busy: { type: Boolean, default: false },
})
const emit = defineEmits(['submit'])

const items = computed(() => props.actions || [])
const choices = ref([])

watch(
  () => props.actions,
  (value) => {
    choices.value = (value || []).map(() => 'approve')
  },
  { immediate: true, deep: true },
)

const approvedCount = computed(() => choices.value.filter((c) => c === 'approve').length)
const rejectedCount = computed(() => choices.value.filter((c) => c === 'reject').length)

function setChoice(index, choice) {
  choices.value[index] = choice
}

function setAll(choice) {
  choices.value = choices.value.map(() => choice)
}

function fmtArgs(args) {
  try {
    return JSON.stringify(args || {}, null, 2)
  } catch {
    return String(args)
  }
}

function submit() {
  emit(
    'submit',
    choices.value.map((choice) =>
      choice === 'approve'
        ? { type: 'approve' }
        : { type: 'reject', message: '我再想想' },
    ),
  )
}
</script>

<template>
  <div class="approval-card">
    <div class="ap-head">
      <span class="ap-icon">⚠</span>
      <div>
        <div class="ap-title">需要你确认的写操作</div>
        <div class="ap-sub">
          Agent 准备执行以下会修改数据的操作。请逐项选择，提交后才会真正执行。
        </div>
      </div>
    </div>

    <div class="ap-list">
      <div v-for="(a, i) in items" :key="i" class="ap-item">
        <div class="ap-item-head">
          <span class="ap-item-label">{{ a.label || a.name }}</span>
          <code class="mono ap-item-name">{{ a.name }}</code>
          <div class="ap-choice">
            <button
              class="choice"
              :class="{ 'on-ok': choices[i] === 'approve' }"
              :disabled="busy"
              @click="setChoice(i, 'approve')"
            >
              批准
            </button>
            <button
              class="choice"
              :class="{ 'on-reject': choices[i] === 'reject' }"
              :disabled="busy"
              @click="setChoice(i, 'reject')"
            >
              拒绝
            </button>
          </div>
        </div>
        <pre class="code-block ap-args">{{ fmtArgs(a.args) }}</pre>
        <div v-if="a.description" class="ap-desc">{{ a.description }}</div>
      </div>
    </div>

    <div class="ap-actions">
      <button class="btn btn-ghost btn-sm" :disabled="busy" @click="setAll('approve')">
        全部批准
      </button>
      <button class="btn btn-ghost btn-sm" :disabled="busy" @click="setAll('reject')">
        全部拒绝
      </button>
      <span class="spacer"></span>
      <button class="btn btn-ok" :disabled="busy || !items.length" @click="submit">
        <span v-if="busy" class="spinner" style="width:12px;height:12px;border-width:2px"></span>
        提交决定（批准 {{ approvedCount }} / 拒绝 {{ rejectedCount }}）
      </button>
    </div>
  </div>
</template>

<style scoped>
.approval-card {
  border: 1px solid var(--warn);
  border-radius: var(--radius);
  background: var(--bg-panel-2);
  padding: 14px;
  margin: 10px 0;
}
.ap-head { display: flex; gap: 10px; align-items: flex-start; }
.ap-icon {
  font-size: 18px;
  color: var(--warn);
  line-height: 1.2;
}
.ap-title { font-size: 14px; font-weight: 600; color: var(--warn); }
.ap-sub { font-size: 12px; color: var(--text-dim); margin-top: 2px; }

.ap-list { margin: 12px 0; display: flex; flex-direction: column; gap: 10px; }
.ap-item {
  background: rgba(0,0,0,.18);
  border: 1px solid rgba(240,162,60,.25);
  border-radius: var(--radius-sm);
  padding: 10px;
}
.ap-item-head { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; }
.ap-item-label { font-size: 13px; font-weight: 600; }
.ap-item-name { color: var(--text-mute); font-size: 11.5px; }
.ap-choice { margin-left: auto; display: flex; gap: 6px; }
.choice {
  padding: 4px 10px;
  border: 1px solid var(--border-strong);
  border-radius: 20px;
  background: transparent;
  color: var(--text-dim);
  font-family: inherit;
  font-size: 12px;
  cursor: pointer;
}
.choice:disabled { opacity: .5; cursor: not-allowed; }
.choice.on-ok { border-color: var(--ok); color: var(--ok); background: rgba(61,178,120,.12); }
.choice.on-reject { border-color: var(--danger); color: var(--danger); background: rgba(240,97,109,.12); }
.ap-args { max-height: 140px; }
.ap-desc {
  margin-top: 8px;
  font-size: 11.5px;
  color: var(--text-mute);
  white-space: pre-wrap;
  border-top: 1px dashed var(--border);
  padding-top: 8px;
}

.ap-actions { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.spacer { flex: 1; }
</style>
