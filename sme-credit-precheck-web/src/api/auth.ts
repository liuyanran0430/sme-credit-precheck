import { authHeaders, handleUnauthorized, readError, setToken } from './http'
import type { User } from '../types'

const API_PREFIX = '/api/v1'

interface LoginResponse {
  access_token: string
  user: User
}

/** 登录，成功后保存访问令牌并返回用户信息 */
export async function login(username: string, password: string): Promise<User> {
  const response = await fetch(`${API_PREFIX}/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({ username, password })
  })
  if (!response.ok) {
    throw new Error(await readError(response))
  }
  const data = (await response.json()) as LoginResponse
  setToken(data.access_token)
  return data.user
}

/** 用已保存的令牌获取当前登录用户 */
export async function fetchMe(): Promise<User> {
  const response = await fetch(`${API_PREFIX}/auth/me`, { headers: authHeaders() })
  if (response.status === 401) {
    setToken('')
    throw new Error('登录已过期，请重新登录')
  }
  if (!response.ok) {
    throw new Error(await readError(response))
  }
  return (await response.json()) as User
}

/** 退出登录：仅清理本地令牌 */
export function logout(): void {
  setToken('')
}

export { handleUnauthorized }
