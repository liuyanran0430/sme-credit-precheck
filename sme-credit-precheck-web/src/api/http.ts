const TOKEN_KEY = 'sme_token'

export function getToken(): string {
  return localStorage.getItem(TOKEN_KEY) || ''
}

export function setToken(token: string): void {
  if (token) {
    localStorage.setItem(TOKEN_KEY, token)
  } else {
    localStorage.removeItem(TOKEN_KEY)
  }
}

/** 组装带 Bearer 令牌的请求头 */
export function authHeaders(extra: Record<string, string> = {}): Record<string, string> {
  const token = getToken()
  const headers: Record<string, string> = { ...extra }
  if (token) {
    headers.Authorization = `Bearer ${token}`
  }
  return headers
}

interface ErrorDetailItem {
  msg: string
}

interface ErrorBody {
  detail?: string | ErrorDetailItem[]
  message?: string
}

/** 解析后端错误响应，返回可读的错误文案 */
export async function readError(response: Response): Promise<string> {
  try {
    const data = (await response.json()) as ErrorBody
    if (Array.isArray(data.detail)) {
      return data.detail.map((item) => item.msg).join('；')
    }
    return data.detail || data.message || `HTTP ${response.status}`
  } catch {
    return `HTTP ${response.status}`
  }
}

/** 令牌失效：清理登录态并通知上层跳转登录页 */
export function handleUnauthorized(): void {
  setToken('')
  window.dispatchEvent(new Event('sme-auth-expired'))
}
