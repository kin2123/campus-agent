<script setup>
/**
 * AuditView —— 审计与安全
 *  · 统计卡片：WEB vs AI 操作数、成功 / 被拒绝数
 *  · 操作日志表：可按来源（WEB / AI）筛选，AI 操作有明显标识
 *  · 审批台账：pending / approved / rejected 三色标签
 *  · 安全自检：MCP 连接、工具读写数量、工具描述是否非空、参数是否泄漏身份字段
 */
import { ref, computed, onMounted } from 'vue'
import {
  getAuditStats, getAuditLogs, getPendingActions, getAgentStatus, getAgentTools,
} from '../api/endpoints.js'

const stats = ref(null)
const logs = ref([])
const pending = ref([])
const status = ref(null)
const tools = ref(null)

const sourceFilter = ref('')
const loadingLogs = ref(false)
const err = ref('')

/* ---------- 数据加载 ---------- */
async function loadLogs() {
  loadingLogs.value = true
  try {
    logs.value = await getAuditLogs({
      source: sourceFilter.value || undefined,
      limit: 50,
    })
  } catch (e) {
    err.value = e.message || '加载日志失败'
    logs.value = []
  } finally {
    loadingLogs.value = false
  }
}

async function loadAll() {
  err.value = ''
  const [s, p, st, tl] = await Promise.allSettled([
    getAuditStats(), getPendingActions(), getAgentStatus(), getAgentTools(),
  ])
  if (s.status === 'fulfilled') stats.value = s.value
  if (p.status === 'fulfilled') pending.value = p.value.items || []
  if (st.status === 'fulfilled') status.value = st.value
  if (tl.status === 'fulfilled') tools.value = tl.value
  await loadLogs()
}

/* ---------- 派生数据 ---------- */
const pendingCount = computed(() => ({
  pending: pending.value.filter((x) => x.status === 'pending').length,
  approved: pending.value.filter((x) => x.status === 'approved').length,
  rejected: pending.value.filter((x) => x.status === 'rejected').length,
}))

const summary = computed(() => (tools.value && tools.value.summary) || null)
const mcpAudit = computed(() => (status.value && status.value.mcp && status.value.mcp.audit) || null)

/** 安全自检项：每项 { name, pass, detail } */
const checks = computed(() => {
  const list = []
  const conn = status.value && status.value.mcp && status.value.mcp.connected
  list.push({
    name: 'MCP 工具服务连接',
    pass: !!conn,
    detail: conn ? '已连接，工具清单已下发' : '未连接或不可用',
  })

  const sm = summary.value
  if (sm) {
    const empty = sm.empty_description || []
    list.push({
      name: '工具描述完整性',
      pass: empty.length === 0,
      detail: empty.length === 0
        ? `全部 ${sm.total} 个工具均有非空描述`
        : `${empty.length} 个工具缺少描述：${empty.join(', ')}`,
    })

    const leaks = sm.identity_leaks || []
    list.push({
      name: '身份字段泄漏检查',
      pass: leaks.length === 0,
      detail: leaks.length === 0
        ? '无工具参数携带用户身份（身份由后端注入，模型无法伪装）'
        : `检测到身份字段泄漏：${leaks.join(', ')}`,
    })

    list.push({
      name: '写工具纳入审批',
      pass: !!(mcpAudit.value && mcpAudit.value.ok),
      detail: mcpAudit.value && mcpAudit.value.ok
        ? (mcpAudit.value.hint || '所有写工具均已纳入人工审批清单')
        : '存在未纳管的写工具',
    })
  }
  return list
})

const allChecksPass = computed(() => checks.value.length > 0 && checks.value.every((c) => c.pass))

function fmtTime(t) {
  if (!t) return '—'
  return String(t).replace('T', ' ').slice(0, 19)
}

function truncate(s, n = 60) {
  if (!s) return '—'
  return s.length > n ? s.slice(0, n) + '…' : s
}

onMounted(loadAll)
</script>

<template>
  <div class="page">
    <div class="page-head">
      <div>
        <h2>审计与安全</h2>
        <p class="muted small">所有操作留痕可追溯；写操作需人工审批；Agent 工具权限可自检</p>
      </div>
      <button class="btn btn-ghost" @click="loadAll">刷新</button>
    </div>

    <div v-if="err" class="notice-err notice">{{ err }}</div>

    <!-- 统计卡片 -->
    <div class="stat-row">
      <div class="card stat">
        <div class="stat-value">{{ stats ? stats.total : '—' }}</div>
        <div class="stat-label">操作总数</div>
        <div v-if="stats" class="stat-sub">
          <span class="tag tag-accent">WEB {{ stats.by_source?.WEB ?? 0 }}</span>
          <span class="tag tag-purple">AI {{ stats.by_source?.AI ?? 0 }}</span>
        </div>
      </div>
      <div class="card stat">
        <div class="stat-value ok">{{ stats ? stats.by_result?.SUCCESS ?? 0 : '—' }}</div>
        <div class="stat-label">成功</div>
      </div>
      <div class="card stat">
        <div class="stat-value warn">{{ stats ? stats.by_result?.REJECTED ?? 0 : '—' }}</div>
        <div class="stat-label">被拒绝</div>
      </div>
      <div class="card stat">
        <div class="stat-value danger">{{ stats ? stats.by_result?.FAILED ?? 0 : '—' }}</div>
        <div class="stat-label">失败</div>
      </div>
      <div class="card stat">
        <div class="stat-value">{{ pendingCount.pending }}</div>
        <div class="stat-label">待审批操作</div>
      </div>
    </div>

    <!-- 安全自检 -->
    <div class="card section">
      <div class="between" style="margin-bottom: 12px">
        <h3 class="section-title">安全自检</h3>
        <span
          class="verdict"
          :class="allChecksPass ? 'verdict-ok' : 'verdict-bad'"
        >
          {{ allChecksPass ? '✓ 全部通过' : '⚠ 存在未通过项' }}
        </span>
      </div>

      <div class="check-grid">
        <div
          v-for="c in checks"
          :key="c.name"
          class="check-item"
          :class="c.pass ? 'check-ok' : 'check-bad'"
        >
          <div class="check-head">
            <span class="check-mark">{{ c.pass ? '✓' : '✕' }}</span>
            <span class="check-name">{{ c.name }}</span>
            <span class="tag" :class="c.pass ? 'tag-ok' : 'tag-danger'">
              {{ c.pass ? '通过' : '未通过' }}
            </span>
          </div>
          <div class="check-detail">{{ c.detail }}</div>
        </div>
      </div>

      <div v-if="summary" class="tool-counts">
        <span class="tc-item">工具总数 <b>{{ summary.total }}</b></span>
        <span class="tc-sep">·</span>
        <span class="tc-item">读工具 <b class="ok">{{ summary.read }}</b></span>
        <span class="tc-sep">·</span>
        <span class="tc-item">写工具 <b class="warn">{{ summary.write }}</b></span>
        <span class="tc-sep">·</span>
        <span class="tc-item">MCP 状态
          <b :class="(status && status.mcp && status.mcp.connected) ? 'ok' : 'danger'">
            {{ (status && status.mcp && status.mcp.connected) ? '已连接' : '未连接' }}
          </b>
        </span>
      </div>

      <div v-if="status && status.model" class="model-line">
        <span class="muted small">模型：</span>
        <span class="tag" :class="status.model.is_fake ? 'tag-warn' : 'tag-ok'">
          {{ status.model.provider }}{{ status.model.is_fake ? '（内置脚本假模型）' : '' }}
        </span>
        <span v-if="status.model.is_fake" class="small muted">{{ status.model.note }}</span>
      </div>
    </div>

    <!-- 操作日志 -->
    <div class="card section">
      <div class="between" style="margin-bottom: 12px">
        <h3 class="section-title">操作日志</h3>
        <div class="tabs">
          <button
            v-for="opt in [{ v: '', l: '全部' }, { v: 'WEB', l: 'WEB' }, { v: 'AI', l: 'AI' }]"
            :key="opt.v"
            class="tab"
            :class="{ active: sourceFilter === opt.v }"
            @click="sourceFilter = opt.v; loadLogs()"
          >
            {{ opt.l }}
          </button>
        </div>
      </div>

      <div v-if="loadingLogs" class="empty"><span class="spinner"></span> 加载中…</div>
      <div v-else-if="!logs.length" class="empty">暂无日志</div>
      <div v-else class="table-scroll">
        <table class="table">
          <thead>
            <tr>
              <th style="width:56px">ID</th>
              <th style="width:90px">用户</th>
              <th style="width:130px">动作</th>
              <th style="width:70px">来源</th>
              <th style="width:80px">结果</th>
              <th>说明</th>
              <th style="width:150px">时间</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="log in logs" :key="log.id" :class="{ 'row-ai': log.source === 'AI' }">
              <td class="mono">{{ log.id }}</td>
              <td class="mono">{{ log.username }}</td>
              <td class="mono small">{{ log.action }}</td>
              <td>
                <span class="tag" :class="log.source === 'AI' ? 'tag-purple' : 'tag-mute'">
                  {{ log.source === 'AI' ? '◆ AI' : 'WEB' }}
                </span>
              </td>
              <td>
                <span
                  class="tag"
                  :class="{
                    'tag-ok': log.result === 'SUCCESS',
                    'tag-warn': log.result === 'REJECTED',
                    'tag-danger': log.result === 'FAILED',
                  }"
                >{{ log.result }}</span>
              </td>
              <td class="small">
                <span :title="log.detail || ''">{{ log.message || truncate(log.detail) }}</span>
              </td>
              <td class="small muted">{{ fmtTime(log.created_at) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- 审批台账 -->
    <div class="card section">
      <div class="between" style="margin-bottom: 12px">
        <h3 class="section-title">Agent 审批台账</h3>
        <div class="row small">
          <span class="tag tag-warn">待审批 {{ pendingCount.pending }}</span>
          <span class="tag tag-ok">已批准 {{ pendingCount.approved }}</span>
          <span class="tag tag-danger">已拒绝 {{ pendingCount.rejected }}</span>
        </div>
      </div>

      <div v-if="!pending.length" class="empty">暂无审批记录</div>
      <div v-else class="table-scroll">
        <table class="table">
          <thead>
            <tr>
              <th style="width:56px">ID</th>
              <th style="width:190px">工具</th>
              <th>参数</th>
              <th style="width:90px">状态</th>
              <th style="width:100px">执行结果</th>
              <th style="width:150px">发起时间</th>
              <th style="width:150px">决定时间</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="a in pending" :key="a.id">
              <td class="mono">{{ a.id }}</td>
              <td class="mono small">
                {{ a.tool_name }}
                <div class="mute2" style="font-size:11px">{{ a.thread_id }}</div>
              </td>
              <td class="mono small">{{ truncate(a.args, 70) }}</td>
              <td>
                <span
                  class="tag"
                  :class="{
                    'tag-warn': a.status === 'pending',
                    'tag-ok': a.status === 'approved',
                    'tag-danger': a.status === 'rejected',
                  }"
                >
                  {{ { pending: '待审批', approved: '已批准', rejected: '已拒绝' }[a.status] || a.status }}
                </span>
              </td>
              <td>
                <span
                  v-if="a.result"
                  class="tag"
                  :class="{
                    'tag-ok': a.result === 'SUCCESS',
                    'tag-warn': a.result === 'NOT_EXECUTED',
                    'tag-danger': a.result === 'FAILED' || a.result === 'REJECTED',
                  }"
                  :title="a.error || ''"
                >
                  {{ { SUCCESS: '成功', FAILED: '失败', REJECTED: '已拒绝', NOT_EXECUTED: '未执行' }[a.result] || a.result }}
                </span>
                <span v-else class="small mute2">—</span>
                <div v-if="a.error" class="mute2" :title="a.error" style="font-size:11px">
                  {{ truncate(a.error, 24) }}
                </div>
              </td>
              <td class="small muted">{{ fmtTime(a.created_at) }}</td>
              <td class="small muted">{{ fmtTime(a.decided_at) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>

<style scoped>
.page { height: 100%; overflow-y: auto; padding: 22px 24px; }
.page-head { display: flex; align-items: flex-start; justify-content: space-between; margin-bottom: 16px; }
.page-head h2 { margin: 0 0 2px; font-size: 18px; }
.page-head p { margin: 0; }

.notice { display: flex; align-items: center; gap: 10px; border-radius: var(--radius-sm); padding: 10px 14px; font-size: 13px; margin-bottom: 14px; }
.notice-err { background: var(--danger-soft); border: 1px solid rgba(240,97,109,.35); color: #ff9aa3; }

.stat-row { display: flex; gap: 14px; margin-bottom: 18px; flex-wrap: wrap; }
.stat { flex: 1; min-width: 130px; padding: 16px 18px; }
.stat-value { font-size: 28px; font-weight: 700; line-height: 1.1; }
.stat-value.ok { color: var(--ok); }
.stat-value.warn { color: var(--warn); }
.stat-value.danger { color: var(--danger); }
.stat-label { font-size: 12px; color: var(--text-dim); margin-top: 6px; }
.stat-sub { display: flex; gap: 6px; margin-top: 8px; }

.section { padding: 16px 18px; margin-bottom: 18px; }
.section-title { margin: 0; font-size: 14px; font-weight: 600; }

.verdict { padding: 5px 12px; border-radius: 20px; font-size: 12.5px; font-weight: 600; }
.verdict-ok { background: var(--ok-soft); color: var(--ok); border: 1px solid rgba(53,201,138,.4); }
.verdict-bad { background: var(--danger-soft); color: var(--danger); border: 1px solid rgba(240,97,109,.4); }

.check-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 10px; }
.check-item { border-radius: var(--radius-sm); padding: 11px 13px; border: 1px solid var(--border); background: var(--bg-panel-2); }
.check-ok { border-left: 3px solid var(--ok); }
.check-bad { border-left: 3px solid var(--danger); }
.check-head { display: flex; align-items: center; gap: 8px; }
.check-mark { font-size: 14px; }
.check-ok .check-mark { color: var(--ok); }
.check-bad .check-mark { color: var(--danger); }
.check-name { font-size: 13px; font-weight: 600; }
.check-head .tag { margin-left: auto; }
.check-detail { font-size: 11.5px; color: var(--text-dim); margin-top: 6px; line-height: 1.5; }

.tool-counts { display: flex; align-items: center; gap: 10px; margin-top: 14px; font-size: 12.5px; color: var(--text-dim); flex-wrap: wrap; }
.tool-counts b { color: var(--text); }
.tool-counts b.ok { color: var(--ok); }
.tool-counts b.warn { color: var(--warn); }
.tool-counts b.danger { color: var(--danger); }
.tc-sep { color: var(--border-strong); }

.model-line { display: flex; align-items: center; gap: 8px; margin-top: 12px; flex-wrap: wrap; }

.tabs { display: flex; gap: 3px; background: var(--bg-panel-2); padding: 3px; border-radius: var(--radius-sm); border: 1px solid var(--border); }
.tab { padding: 5px 14px; border: none; background: transparent; color: var(--text-dim); font-family: inherit; font-size: 12.5px; cursor: pointer; border-radius: 5px; }
.tab.active { background: var(--accent-soft); color: var(--accent); }

.table-scroll { max-height: 420px; overflow: auto; }
.row-ai { background: rgba(167,139,250,.05); }
</style>
