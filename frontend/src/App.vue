<script setup>
import { ref, onMounted } from 'vue'
import {
  getStoredUser, setStoredUser, setToken, clearToken, getToken, onUnauthorized,
} from './api/client.js'
import { getMe } from './api/endpoints.js'

import LoginView from './views/LoginView.vue'
import AssistantView from './views/AssistantView.vue'
import CoursesView from './views/CoursesView.vue'
import ScheduleView from './views/ScheduleView.vue'
import AuditView from './views/AuditView.vue'

const user = ref(getStoredUser())
const current = ref('assistant')
const booting = ref(true)

const NAV = [
  { key: 'assistant', label: '智能助手', icon: '◆' },
  { key: 'courses', label: '课程列表', icon: '▤' },
  { key: 'schedule', label: '我的课表 / 成绩', icon: '▦' },
  { key: 'audit', label: '审计与安全', icon: '⛨' },
]

const roleLabel = { student: '学生', teacher: '教师', admin: '教务管理员' }

// 401 时由 client.js 回调：清空登录态回到登录页
onUnauthorized(() => {
  user.value = null
})

function handleLoggedIn(payload) {
  setToken(payload.access_token)
  setStoredUser(payload.user)
  user.value = payload.user
  current.value = 'assistant'
}

function handleLogout() {
  clearToken()
  user.value = null
}

onMounted(async () => {
  // 有 token 时校验一次，拿到最新用户信息；失败自动回登录页
  if (getToken()) {
    try {
      const me = await getMe()
      setStoredUser(me)
      user.value = me
    } catch {
      clearToken()
      user.value = null
    }
  }
  booting.value = false
})
</script>

<template>
  <div v-if="booting" class="boot">
    <span class="spinner"></span>
    <span class="muted">正在初始化…</span>
  </div>

  <!-- 未登录：登录页 -->
  <LoginView v-else-if="!user" @logged-in="handleLoggedIn" />

  <!-- 已登录：顶栏 + 页面 -->
  <div v-else class="shell">
    <header class="topbar">
      <div class="brand">
        <span class="logo">◎</span>
        <div>
          <div class="brand-title">校园课程智能助手</div>
          <div class="brand-sub">AI Agent · RAG · MCP 全栈演示</div>
        </div>
      </div>

      <nav class="nav">
        <button
          v-for="item in NAV"
          :key="item.key"
          class="nav-item"
          :class="{ active: current === item.key }"
          @click="current = item.key"
        >
          <span class="nav-icon">{{ item.icon }}</span>{{ item.label }}
        </button>
      </nav>

      <div class="userbox">
        <div class="user-meta">
          <span class="user-name">{{ user.name || user.username }}</span>
          <span class="tag tag-accent">{{ roleLabel[user.role] || user.role }}</span>
        </div>
        <button class="btn btn-ghost btn-sm" @click="handleLogout">退出</button>
      </div>
    </header>

    <main class="content">
      <AssistantView v-show="current === 'assistant'" />
      <CoursesView v-if="current === 'courses'" />
      <ScheduleView v-if="current === 'schedule'" />
      <AuditView v-if="current === 'audit'" />
    </main>
  </div>
</template>

<style scoped>
.boot {
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
}

.shell {
  height: 100%;
  display: flex;
  flex-direction: column;
}

.topbar {
  display: flex;
  align-items: center;
  gap: 24px;
  padding: 0 20px;
  height: 60px;
  background: var(--bg-panel);
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
}

.brand { display: flex; align-items: center; gap: 10px; min-width: 210px; }
.logo {
  font-size: 24px;
  color: var(--accent);
  text-shadow: 0 0 14px rgba(78,161,255,.5);
}
.brand-title { font-size: 15px; font-weight: 600; line-height: 1.25; }
.brand-sub { font-size: 11px; color: var(--text-mute); letter-spacing: .03em; }

.nav { display: flex; gap: 4px; flex: 1; }
.nav-item {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 8px 14px;
  border: 1px solid transparent;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--text-dim);
  font-size: 13.5px;
  font-family: inherit;
  cursor: pointer;
  transition: all .15s;
}
.nav-item:hover { background: var(--bg-panel-2); color: var(--text); }
.nav-item.active {
  background: var(--accent-soft);
  border-color: rgba(78,161,255,.35);
  color: var(--accent);
}
.nav-icon { font-size: 12px; opacity: .85; }

.userbox { display: flex; align-items: center; gap: 12px; }
.user-meta { display: flex; align-items: center; gap: 8px; }
.user-name { font-size: 13px; color: var(--text); }

.content { flex: 1; min-height: 0; overflow: hidden; }
</style>
