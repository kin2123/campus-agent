<script setup>
import { ref, onMounted } from 'vue'
import { login, getDemoAccounts } from '../api/endpoints.js'

const emit = defineEmits(['logged-in'])

const username = ref('')
const password = ref('')
const loading = ref(false)
const error = ref('')
const demos = ref([])
const demoLoading = ref(true)

async function handleLogin() {
  error.value = ''
  if (!username.value || !password.value) {
    error.value = '请输入学号/工号和密码'
    return
  }
  loading.value = true
  try {
    const data = await login(username.value.trim(), password.value)
    emit('logged-in', data)
  } catch (e) {
    error.value = e.message || '登录失败'
  } finally {
    loading.value = false
  }
}

function fillDemo(acc) {
  username.value = acc.username
  password.value = acc.password
  error.value = ''
}

const roleLabel = { student: '学生', teacher: '教师', admin: '教务管理员' }

onMounted(async () => {
  try {
    const data = await getDemoAccounts()
    demos.value = data.accounts || []
  } catch {
    demos.value = []
  } finally {
    demoLoading.value = false
  }
})
</script>

<template>
  <div class="login-page">
    <div class="login-bg"></div>

    <div class="login-box">
      <!-- 左：品牌介绍 -->
      <div class="brand-side">
        <div class="logo">◎</div>
        <h1>校园课程智能助手</h1>
        <p class="tagline">AI Agent · RAG · MCP 全栈演示系统</p>
        <ul class="feature-list">
          <li><span class="dot"></span>Agent 对话，SSE 流式逐字返回</li>
          <li><span class="dot"></span>写操作需人工审批，全程可审计</li>
          <li><span class="dot"></span>RAG 知识库检索，回答有据可依</li>
          <li><span class="dot"></span>MCP 工具标准化，身份不泄漏给模型参数</li>
        </ul>
      </div>

      <!-- 右：登录表单 + 演示账号 -->
      <div class="form-side">
        <h2>登录</h2>
        <p class="form-sub">使用学号 / 工号与密码登录</p>

        <form @submit.prevent="handleLogin">
          <label class="field">
            <span>学号 / 工号</span>
            <input
              v-model="username"
              class="input"
              placeholder="例如 20230101"
              autocomplete="username"
            />
          </label>
          <label class="field">
            <span>密码</span>
            <input
              v-model="password"
              class="input"
              type="password"
              placeholder="演示密码 123456"
              autocomplete="current-password"
            />
          </label>

          <div v-if="error" class="error-box">{{ error }}</div>

          <button class="btn btn-primary login-btn" type="submit" :disabled="loading">
            <span v-if="loading" class="spinner"></span>
            {{ loading ? '登录中…' : '登 录' }}
          </button>
        </form>

        <div class="demo-block">
          <div class="demo-title">
            演示账号
            <span class="mute2 small">（点击即可填入）</span>
          </div>
          <div v-if="demoLoading" class="muted small" style="padding:8px 0">加载中…</div>
          <div v-else class="demo-list">
            <button
              v-for="d in demos"
              :key="d.username"
              class="demo-item"
              type="button"
              @click="fillDemo(d)"
            >
              <div class="demo-left">
                <span class="demo-name">{{ d.name || d.username }}</span>
                <span class="tag tag-accent">{{ roleLabel[d.role] || d.role }}</span>
              </div>
              <div class="demo-cred mono">{{ d.username }} / {{ d.password }}</div>
              <div v-if="d.note" class="demo-note">{{ d.note }}</div>
            </button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.login-page {
  position: relative;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: auto;
  padding: 24px;
}
.login-bg {
  position: absolute;
  inset: 0;
  background:
    radial-gradient(700px 400px at 20% 10%, rgba(78,161,255,.10), transparent 60%),
    radial-gradient(600px 380px at 85% 90%, rgba(167,139,250,.08), transparent 60%);
  pointer-events: none;
}

.login-box {
  position: relative;
  display: flex;
  width: 100%;
  max-width: 920px;
  background: var(--bg-panel);
  border: 1px solid var(--border);
  border-radius: 16px;
  box-shadow: var(--shadow);
  overflow: hidden;
}

/* 左侧品牌区 */
.brand-side {
  flex: 1.05;
  padding: 44px 38px;
  background: linear-gradient(160deg, #161b26 0%, #12151d 100%);
  border-right: 1px solid var(--border);
}
.logo {
  font-size: 40px;
  color: var(--accent);
  text-shadow: 0 0 24px rgba(78,161,255,.55);
  line-height: 1;
}
.brand-side h1 { font-size: 22px; margin: 18px 0 6px; }
.tagline { color: var(--text-dim); font-size: 13px; margin: 0 0 26px; }
.feature-list { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 12px; }
.feature-list li { display: flex; align-items: center; gap: 10px; font-size: 13px; color: var(--text-dim); }
.dot {
  width: 6px; height: 6px; border-radius: 50%;
  background: var(--accent);
  box-shadow: 0 0 8px rgba(78,161,255,.8);
  flex-shrink: 0;
}

/* 右侧表单区 */
.form-side { flex: 1; padding: 40px 38px; }
.form-side h2 { margin: 0 0 4px; font-size: 19px; }
.form-sub { color: var(--text-mute); font-size: 12.5px; margin: 0 0 22px; }

.field { display: block; margin-bottom: 14px; }
.field span { display: block; font-size: 12.5px; color: var(--text-dim); margin-bottom: 6px; }

.error-box {
  background: var(--danger-soft);
  border: 1px solid rgba(240,97,109,.35);
  color: #ff9aa3;
  border-radius: var(--radius-sm);
  padding: 8px 12px;
  font-size: 12.5px;
  margin-bottom: 14px;
}

.login-btn { width: 100%; padding: 10px; font-size: 14px; }

/* 演示账号 */
.demo-block { margin-top: 26px; border-top: 1px solid var(--border); padding-top: 18px; }
.demo-title { font-size: 12.5px; color: var(--text-dim); margin-bottom: 10px; }
.demo-list { display: flex; flex-direction: column; gap: 8px; max-height: 220px; overflow: auto; }
.demo-item {
  text-align: left;
  background: var(--bg-panel-2);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 9px 12px;
  cursor: pointer;
  font-family: inherit;
  color: var(--text);
  transition: all .15s;
}
.demo-item:hover { border-color: var(--accent); background: var(--bg-elevated); }
.demo-left { display: flex; align-items: center; gap: 8px; }
.demo-name { font-size: 13px; font-weight: 600; }
.demo-cred { font-size: 11.5px; color: var(--text-mute); margin-top: 2px; }
.demo-note { font-size: 11px; color: var(--text-dim); margin-top: 2px; }

@media (max-width: 760px) {
  .brand-side { display: none; }
}
</style>
