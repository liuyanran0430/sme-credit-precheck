import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import { fetchMe, login as loginApi, logout as logoutApi } from '../api/auth'
import { getToken } from '../api/http'

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null)
  const [loading, setLoading] = useState(true)

  // 首次进入：有令牌则恢复登录态
  useEffect(() => {
    if (!getToken()) {
      setLoading(false)
      return
    }
    let cancelled = false
    fetchMe()
      .then((data) => {
        if (!cancelled) setUser(data)
      })
      .catch(() => {
        if (!cancelled) setUser(null)
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  // 任意接口返回 401 时清理登录态，路由会自动跳转登录页
  useEffect(() => {
    const onExpired = () => setUser(null)
    window.addEventListener('sme-auth-expired', onExpired)
    return () => window.removeEventListener('sme-auth-expired', onExpired)
  }, [])

  const login = useCallback(async (username, password) => {
    const loggedUser = await loginApi(username, password)
    setUser(loggedUser)
    return loggedUser
  }, [])

  const logout = useCallback(() => {
    logoutApi()
    setUser(null)
  }, [])

  const value = useMemo(
    () => ({ user, loading, login, logout }),
    [user, loading, login, logout]
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}
