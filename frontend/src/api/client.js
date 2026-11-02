/**
 * client.js —— 统一的后端请求封装
 *
 * 职责：
 *  1. 自动携带 Authorization: Bearer <token>
 *  2. 统一解析成功/失败响应，抛出带 message 的错误
 *  3. 401 时清理登录态并通知外层回到登录页
 *
 * 说明：所有请求都走相对路径 /api/...，由 Vite devServer 代理到 127.0.0.1:18000，
 * 因此浏览器里是同源请求，不需要也无法直接访问后端绝对地址。
 */

const TOKEN_KEY = 'campus_token'
const USER_KEY = 'campus_user'

/** token 存储（localStorage） */
export function getToken() {
  return localStorage.getItem(TOKEN_KEY) || ''
}
export function setToken(token) {
  if (token) localStorage.setItem(TOKEN_KEY, token)
}
export function clearToken() {
  localStorage.removeItem(TOKEN_KEY)
  localStorage.removeItem(USER_KEY)
}

/** 本地缓存用户信息，用于刷新后免闪登录页 */
export function getStoredUser() {
  try {
    return JSON.parse(localStorage.getItem(USER_KEY) || 'null')
  } catch {
    return null
  }
}
export function setStoredUser(user) {
  if (user) localStorage.setItem(USER_KEY, JSON.stringify(user))
}

/* ---------- 401 回调 ---------- */
let unauthorizedHandler = null
/** 由 App.vue 注册：未授权时清理状态并跳回登录 */
export function onUnauthorized(fn) {
  unauthorizedHandler = fn
}

/**
 * 业务错误：携带后端返回的 detail（string 或 {code,message}）
 */
export class ApiError extends Error {
  constructor(message, { status = 0, code = '', payload = null } = {}) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.payload = payload
  }
}

/**
 * 从后端错误响应体里提取人类可读的错误信息。
 * 兼容两种形态：
 *   {"detail": "xxx"}
 *   {"detail": {"code": "COURSE_FULL", "message": "xxx"}}
 */
function extractError(status, body) {
  let message = `请求失败（HTTP ${status}）`
  let code = ''
  const detail = body && body.detail
  if (typeof detail === 'string') {
    message = detail
  } else if (detail && typeof detail === 'object') {
    message = detail.message || message
    code = detail.code || ''
  } else if (body && typeof body.message === 'string') {
    message = body.message
  }
  return { message, code }
}

/**
 * 底层请求。返回解析后的 JSON（或文本）。
 * @param {string} path  形如 "/api/courses"
 * @param {object} opts  { method, body, headers, signal, raw }
 */
export async function request(path, opts = {}) {
  const { method = 'GET', body, headers = {}, signal, raw = false } = opts
  const finalHeaders = { ...headers }

  const token = getToken()
  if (token) finalHeaders['Authorization'] = `Bearer ${token}`

  let payload = body
  if (body !== undefined && body !== null && !(body instanceof FormData)) {
    finalHeaders['Content-Type'] = 'application/json'
    payload = JSON.stringify(body)
  }

  let res
  try {
    res = await fetch(path, { method, headers: finalHeaders, body: payload, signal })
  } catch (e) {
    if (e && e.name === 'AbortError') throw e
    throw new ApiError('网络请求失败，请确认后端服务已启动', { status: 0 })
  }

  // 401：登录失效
  if (res.status === 401) {
    clearToken()
    if (unauthorizedHandler) unauthorizedHandler()
    throw new ApiError('登录已失效，请重新登录', { status: 401 })
  }

  if (raw) return res

  const text = await res.text()
  let data = null
  if (text) {
    try {
      data = JSON.parse(text)
    } catch {
      data = text
    }
  }

  if (!res.ok) {
    const { message, code } = extractError(res.status, data)
    throw new ApiError(message, { status: res.status, code, payload: data })
  }
  return data
}

export const get = (path, opts) => request(path, { ...opts, method: 'GET' })
export const post = (path, body, opts) => request(path, { ...opts, method: 'POST', body })
export const del = (path, opts) => request(path, { ...opts, method: 'DELETE' })

/** 拼接查询串，自动跳过空值 */
export function qs(params = {}) {
  const parts = []
  Object.entries(params).forEach(([k, v]) => {
    if (v === undefined || v === null || v === '') return
    parts.push(`${encodeURIComponent(k)}=${encodeURIComponent(v)}`)
  })
  return parts.length ? `?${parts.join('&')}` : ''
}
