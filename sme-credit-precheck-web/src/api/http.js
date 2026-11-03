const TOKEN_KEY = 'sme_token'
const TRACE_ID_KEY = 'sme_trace_id'

export function getToken() {
  return localStorage.getItem(TOKEN_KEY) || ''
}

export function setToken(token) {
  if (token) {
    localStorage.setItem(TOKEN_KEY, token)
  } else {
    localStorage.removeItem(TOKEN_KEY)
  }
}

/**
 * 获取/生成 trace_id：16 位十六进制，存 localStorage 供同一次会话复用，
 * 后端会通过响应头 X-Trace-Id 回传，这里也会同步更新。
 */
export function getTraceId() {
  let traceId = localStorage.getItem(TRACE_ID_KEY)
  if (!traceId) {
    traceId = generateTraceId()
    localStorage.setItem(TRACE_ID_KEY, traceId)
  }
  return traceId
}

/** 从后端响应头读取 X-Trace-Id 并同步到本地 */
export function syncTraceIdFromResponse(response) {
  const serverTraceId = response.headers.get('X-Trace-Id')
  if (serverTraceId) {
    localStorage.setItem(TRACE_ID_KEY, serverTraceId)
  }
}

function generateTraceId() {
  // 优先用 crypto.randomUUID，兜底用时间戳 + 随机数
  if (window.crypto?.randomUUID) {
    return window.crypto.randomUUID().replace(/-/g, '').slice(0, 16)
  }
  return `${Date.now().toString(16)}${Math.random().toString(16).slice(2, 10)}`
}

/** 组装带 Bearer 令牌 + trace_id 的请求头 */
export function authHeaders(extra = {}) {
  const token = getToken()
  const headers = {
    'X-Request-ID': getTraceId(),
    ...extra,
  }
  if (token) {
    headers.Authorization = `Bearer ${token}`
  }
  return headers
}

/** 解析后端错误响应，返回可读的错误文案 */
export async function readError(response) {
  try {
    const data = await response.json()
    if (Array.isArray(data.detail)) {
      return data.detail.map((item) => item.msg).join('；')
    }
    return data.detail || data.message || `HTTP ${response.status}`
  } catch {
    return `HTTP ${response.status}`
  }
}

/** 令牌失效：清理登录态并通知上层跳转登录页 */
export function handleUnauthorized() {
  setToken('')
  window.dispatchEvent(new Event('sme-auth-expired'))
}
