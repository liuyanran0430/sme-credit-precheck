const TOKEN_KEY = 'sme_token'

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

/** 组装带 Bearer 令牌的请求头 */
export function authHeaders(extra = {}) {
  const token = getToken()
  return token ? { ...extra, Authorization: `Bearer ${token}` } : { ...extra }
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
