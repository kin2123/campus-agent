/**
 * endpoints.js —— 后端业务接口的集中定义
 * 每个函数对应一个已实测可用的接口，路径与字段严格按后端契约。
 */
import { get, post, del, qs } from './client.js'
import { streamAgent } from './sse.js'

/* ---------------- 认证 ---------------- */
export const login = (username, password) =>
  post('/api/auth/login', { username, password })

export const getMe = () => get('/api/auth/me')

export const getDemoAccounts = () => get('/api/auth/demo-accounts')

/* ---------------- 课程 ---------------- */
/** @param {{keyword?:string, category?:string, only_available?:boolean}} p */
export const listCourses = (p = {}) =>
  get('/api/courses' + qs({
    keyword: p.keyword,
    category: p.category,
    only_available: p.only_available,
  }))

export const getCategories = () => get('/api/courses/categories')

export const getCourseByCode = (code) =>
  get(`/api/courses/by-code/${encodeURIComponent(code)}`)

/* ---------------- 我的 ---------------- */
export const getMySchedule = () => get('/api/me/schedule')

export const getMyGrades = () => get('/api/me/grades')

/* ---------------- 知识库（RAG） ---------------- */
/** @param {string} q @param {number} topK */
export const searchKnowledge = (q, topK = 4) =>
  post(`/api/knowledge/search${qs({ q, top_k: topK })}`)

export const getKnowledgeSources = () => get('/api/knowledge/sources')

/* ---------------- 审计 ---------------- */
/** @param {{source?:string, limit?:number}} p */
export const getAuditLogs = (p = {}) =>
  get('/api/audit/logs' + qs({ source: p.source, limit: p.limit ?? 50 }))

export const getAuditStats = () => get('/api/audit/stats')

export const getPendingActions = () => get('/api/audit/pending-actions')

/* ---------------- Agent 自检 ---------------- */
export const getAgentStatus = () => get('/api/agent/status')

export const getAgentTools = () => get('/api/agent/tools')

/* ---------------- 选课 / 退课（REST，不经 Agent） ---------------- */
export const enrollCourse = (courseCode) =>
  post('/api/enrollments', { course_code: courseCode })

export const dropCourse = (courseCode) =>
  del(`/api/enrollments/${encodeURIComponent(courseCode)}`)

/* ---------------- Agent 对话（SSE 流） ---------------- */
/**
 * 发起 Agent 对话。
 * @param {string} message
 * @param {string|undefined} threadId 续接同一会话时传入
 * @param {{onEvent:Function, signal:AbortSignal}} handlers
 */
export function chatWithAgent(message, threadId, handlers) {
  return streamAgent('/api/agent/chat', { message, thread_id: threadId }, handlers)
}

/**
 * 审批恢复：用户对写操作点「批准 / 拒绝」后调用。
 * @param {string} threadId
 * @param {Array<{type:'approve'|'reject', message?:string}>} decisions
 * @param {{onEvent:Function, signal:AbortSignal}} handlers
 */
export function resumeAgent(threadId, decisions, handlers) {
  return streamAgent('/api/agent/resume', { thread_id: threadId, decisions }, handlers)
}
