<script setup>
/**
 * StepTimeline —— Agent 执行过程时间线
 * 展示「正在思考 → 正在调用工具 → 等待你确认 → 已完成」这类阶段变化。
 * steps: Array<{ label:string, kind:'stage'|'tool'|'done'|'error' }>
 */
defineProps({
  steps: { type: Array, default: () => [] },
  running: { type: Boolean, default: false },
})

const iconOf = (kind) => ({
  stage: '◇',
  tool: '▸',
  done: '✓',
  error: '✕',
}[kind] || '·')
</script>

<template>
  <ol class="timeline" v-if="steps.length || running">
    <li
      v-for="(s, i) in steps"
      :key="i"
      class="tl-item"
      :class="['k-' + (s.kind || 'stage'), { last: i === steps.length - 1 && !running }]"
    >
      <span class="tl-icon">{{ iconOf(s.kind) }}</span>
      <span class="tl-label">{{ s.label }}</span>
    </li>
    <li v-if="running" class="tl-item k-active">
      <span class="tl-icon"><span class="spinner" style="width:11px;height:11px;border-width:2px"></span></span>
      <span class="tl-label">处理中…</span>
    </li>
  </ol>
</template>

<style scoped>
.timeline {
  list-style: none;
  margin: 4px 0 10px;
  padding: 0 0 0 4px;
}
.tl-item {
  position: relative;
  display: flex;
  align-items: center;
  gap: 9px;
  padding: 3px 0 3px 0;
  font-size: 12.5px;
  color: var(--text-dim);
}
/* 竖线 */
.tl-item::before {
  content: '';
  position: absolute;
  left: 8px;
  top: 0;
  bottom: 0;
  width: 1px;
  background: var(--border-strong);
}
.tl-item:first-child::before { top: 50%; }
.tl-item:last-child::before,
.tl-item.last::before { bottom: 50%; }
.tl-icon {
  position: relative;
  z-index: 1;
  width: 17px;
  height: 17px;
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  background: var(--bg-panel-2);
  border: 1px solid var(--border-strong);
  font-size: 9px;
  color: var(--text-mute);
}
.tl-label { line-height: 1.4; }

.k-done .tl-icon { color: var(--ok); border-color: rgba(53,201,138,.5); background: var(--ok-soft); }
.k-done .tl-label { color: var(--ok); }
.k-tool .tl-icon { color: var(--accent); border-color: rgba(78,161,255,.5); background: var(--accent-soft); }
.k-tool .tl-label { color: var(--text); }
.k-error .tl-icon { color: var(--danger); border-color: rgba(240,97,109,.5); background: var(--danger-soft); }
.k-error .tl-label { color: var(--danger); }
.k-stage .tl-label { color: var(--text-dim); }
.k-active .tl-icon { border-color: var(--accent); }
.k-active .tl-label { color: var(--accent); }
</style>
