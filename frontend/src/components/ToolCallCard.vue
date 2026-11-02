<script setup>
/**
 * ToolCallCard —— 单个工具调用卡片
 * 展示：工具名 / 中文标签 / 参数 / 执行状态 / 结果摘要（可展开看完整返回）
 */
import { ref, computed } from 'vue'

const props = defineProps({
  tool: { type: Object, required: true },
})

const expanded = ref(false)

const statusKind = computed(() => {
  const s = props.tool.status
  if (s === 'running') return 'running'
  if (s === 'rejected') return 'rejected'
  if (props.tool.ok === false || s === 'fail') return 'fail'
  return 'ok'
})

const statusText = computed(() => ({
  running: '执行中',
  ok: '成功',
  fail: '失败',
  rejected: '已拒绝',
}[statusKind.value]))

const hasArgs = computed(() => {
  const a = props.tool.args
  return a && Object.keys(a).length > 0
})

const argsText = computed(() => {
  try {
    return JSON.stringify(props.tool.args || {}, null, 2)
  } catch {
    return String(props.tool.args)
  }
})
</script>

<template>
  <div class="tool-card" :class="'st-' + statusKind">
    <div class="tc-head">
      <span class="tc-dot"></span>
      <span class="tc-label">{{ tool.label || tool.name }}</span>
      <code class="tc-name mono">{{ tool.name }}</code>
      <span
        class="tag"
        :class="{
          'tag-accent': statusKind === 'running',
          'tag-ok': statusKind === 'ok',
          'tag-danger': statusKind === 'fail',
          'tag-warn': statusKind === 'rejected',
        }"
      >
        <span v-if="statusKind === 'running'" class="spinner" style="width:10px;height:10px;border-width:2px"></span>
        {{ statusText }}
      </span>
    </div>

    <div v-if="hasArgs" class="tc-row">
      <span class="tc-key">参数</span>
      <code class="tc-args mono">{{ argsText }}</code>
    </div>

    <div v-if="tool.summary" class="tc-row">
      <span class="tc-key">结果</span>
      <span class="tc-summary">{{ tool.summary }}</span>
    </div>

    <div v-if="tool.content" class="tc-detail">
      <button class="link-btn" @click="expanded = !expanded">
        {{ expanded ? '收起完整返回 ▲' : '查看完整返回 ▼' }}
      </button>
      <pre v-if="expanded" class="code-block">{{ tool.content }}</pre>
    </div>
  </div>
</template>

<style scoped>
.tool-card {
  border: 1px solid var(--border);
  border-left: 3px solid var(--text-mute);
  border-radius: var(--radius-sm);
  background: var(--bg-panel-2);
  padding: 10px 12px;
  margin: 8px 0;
}
.st-running { border-left-color: var(--accent); }
.st-ok { border-left-color: var(--ok); }
.st-fail { border-left-color: var(--danger); }
.st-rejected { border-left-color: var(--warn); }

.tc-head { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.tc-dot { width: 7px; height: 7px; border-radius: 50%; background: var(--accent); }
.st-ok .tc-dot { background: var(--ok); }
.st-fail .tc-dot { background: var(--danger); }
.st-rejected .tc-dot { background: var(--warn); }
.tc-label { font-size: 13px; font-weight: 600; }
.tc-name { color: var(--text-mute); font-size: 11.5px; }
.tc-head .tag { margin-left: auto; }

.tc-row { display: flex; gap: 8px; margin-top: 7px; font-size: 12.5px; align-items: flex-start; }
.tc-key { color: var(--text-mute); flex-shrink: 0; padding-top: 1px; min-width: 30px; }
.tc-args {
  background: #0b0d12;
  border: 1px solid var(--border);
  border-radius: 5px;
  padding: 3px 8px;
  color: #b9d0ea;
  white-space: pre-wrap;
  word-break: break-word;
}
.tc-summary { color: var(--text-dim); }

.tc-detail { margin-top: 8px; }
.link-btn {
  background: none;
  border: none;
  color: var(--accent);
  font-size: 12px;
  cursor: pointer;
  padding: 0;
  font-family: inherit;
}
.link-btn:hover { text-decoration: underline; }
.tc-detail .code-block { margin-top: 6px; }
</style>
