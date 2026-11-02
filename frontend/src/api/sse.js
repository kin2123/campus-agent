/**
 * sse.js —— 手工解析 Server-Sent Events（SSE）
 *
 * ============================================================
 * 为什么不能用原生 EventSource？
 * ------------------------------------------------------------
 * 浏览器的 EventSource 只能发起 GET 请求，且**无法自定义请求头**，
 * 因此没法携带 `Authorization: Bearer <token>`；同时它也不支持
 * 自定义请求体。而本项目的 Agent 对话接口是：
 *     POST /api/agent/chat   body: {"message": "...", "thread_id": "..."}
 *     Header: Authorization: Bearer <token>
 * 所以必须改用 `fetch` + `ReadableStream`，自己按 SSE 协议切帧。
 * ============================================================
 *
 * SSE 帧格式（本项目后端使用的标准格式）：
 *     event: <事件名>\n
 *     data: <JSON 字符串>\n
 *     \n                       ← 空行代表一帧结束
 *
 * 关键点：网络分片不可控，一帧数据可能被拆到多次 read()，
 * 也可能一次 read() 拿到好几帧。因此必须维护缓冲区，
 * 按 "\n\n" 切割，最后一段不完整的内容留在缓冲区里等下一块。
 */

/**
 * 把一个 fetch 的 Response.body（只读流）解析成一个个 SSE 事件。
 *
 * @param {Response} response   fetch 返回对象，需 body 为 ReadableStream
 * @param {AbortSignal} signal  用于中途停止
 * @yields {{ event: string, data: any, raw: string }}
 */
export async function* readSSE(response, signal) {
  if (!response.body) {
    throw new Error('响应没有可读流（response.body 为空）')
  }
  const reader = response.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''

  try {
    while (true) {
      if (signal && signal.aborted) break
      const { done, value } = await reader.read()
      if (done) break
      // stream: true 保证多字节 UTF-8 字符被网络切断时不会乱码
      buffer += decoder.decode(value, { stream: true })

      // 统一换行符，兼容 \r\n
      buffer = buffer.replace(/\r\n/g, '\n')

      // 按空行切帧；最后一段（可能不完整）留在缓冲区
      let sepIndex
      while ((sepIndex = buffer.indexOf('\n\n')) !== -1) {
        const frame = buffer.slice(0, sepIndex)
        buffer = buffer.slice(sepIndex + 2)
        const evt = parseFrame(frame)
        if (evt) yield evt
      }
    }
    // 流结束时，缓冲区里可能还剩最后一帧（后端没补空行的情况）
    if (buffer.trim()) {
      const evt = parseFrame(buffer)
      if (evt) yield evt
    }
  } finally {
    // 主动取消读取，释放底层连接
    try {
      await reader.cancel()
    } catch {
      /* 忽略 */
    }
  }
}

/** 解析单个 SSE 帧文本，返回 { event, data, raw } */
function parseFrame(frame) {
  const lines = frame.split('\n')
  let event = 'message'
  const dataLines = []
  for (const line of lines) {
    if (line.startsWith('event:')) {
      event = line.slice(6).trim()
    } else if (line.startsWith('data:')) {
      // 规范：data 冒号后若有一个前导空格需去掉
      dataLines.push(line.slice(5).replace(/^ /, ''))
    }
    // 忽略 id: / retry: / 注释行(:) 等
  }
  if (dataLines.length === 0) return null
  const dataStr = dataLines.join('\n')
  let data = dataStr
  try {
    data = JSON.parse(dataStr)
  } catch {
    /* 非 JSON 就原样返回字符串 */
  }
  return { event, data, raw: frame }
}

/**
 * 高层封装：向指定 SSE 接口 POST，逐个事件回调。
 *
 * @param {string} url        例如 '/api/agent/chat'
 * @param {object} body       请求体
 * @param {object} options
 *   @param {(evt:{event:string,data:any}) => void} options.onEvent  每收到一帧调用
 *   @param {AbortSignal} options.signal                              停止信号
 *   @param {string} options.token                                    可选，默认取 localStorage
 * @returns {Promise<void>}
 */
export async function streamAgent(url, body, { onEvent, signal, token } = {}) {
  const authToken = token !== undefined ? token : localStorage.getItem('campus_token') || ''

  const headers = {
    'Content-Type': 'application/json',
    Accept: 'text/event-stream',
  }
  if (authToken) headers['Authorization'] = `Bearer ${authToken}`

  const res = await fetch(url, {
    method: 'POST',
    headers,
    body: JSON.stringify(body),
    signal,
  })

  if (res.status === 401) {
    const err = new Error('登录已失效，请重新登录')
    err.status = 401
    throw err
  }
  if (!res.ok) {
    // 后端在出错时可能返回 JSON 而不是 SSE 流
    let msg = `请求失败（HTTP ${res.status}）`
    try {
      const text = await res.text()
      const data = JSON.parse(text)
      const detail = data && data.detail
      if (typeof detail === 'string') msg = detail
      else if (detail && detail.message) msg = detail.message
    } catch {
      /* 保持默认信息 */
    }
    const err = new Error(msg)
    err.status = res.status
    throw err
  }

  for await (const evt of readSSE(res, signal)) {
    if (onEvent) onEvent(evt)
  }
}
