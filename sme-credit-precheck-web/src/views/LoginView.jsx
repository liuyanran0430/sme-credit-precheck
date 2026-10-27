import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'

const ROLE_TEXT = {
  manager: '客户经理',
  risk: '风控人员',
  admin: '管理员'
}

const ROLE_HOME = { manager: '/', risk: '/risk', admin: '/' }

export default function LoginView() {
  const { login } = useAuth()
  const navigate = useNavigate()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)

  const handleSubmit = async (event) => {
    event.preventDefault()
    if (!username.trim() || !password) {
      setError('请输入用户名和密码')
      return
    }
    setSubmitting(true)
    setError('')
    try {
      const user = await login(username.trim(), password)
      navigate(ROLE_HOME[user.role] || '/', { replace: true })
    } catch (err) {
      setError(err.message || '登录失败，请稍后重试')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="login-page">
      <div className="login-card">
        <div className="login-brand">
          <div className="login-logo">🏦</div>
          <h1>小微企业授信智能预审系统</h1>
          <p>企业授信申请 · 材料智能分类 · AI 预审 · 人工与风控复核</p>
          <div className="login-roles">
            {Object.entries(ROLE_TEXT).map(([key, label]) => (
              <span key={key} className="login-role">
                {label}
              </span>
            ))}
          </div>
        </div>

        <form className="login-form" onSubmit={handleSubmit}>
          <h2>账号登录</h2>
          <label className="login-field">
            <span>用户名</span>
            <input
              type="text"
              value={username}
              autoComplete="username"
              placeholder="请输入用户名"
              onChange={(e) => setUsername(e.target.value)}
            />
          </label>
          <label className="login-field">
            <span>密码</span>
            <input
              type="password"
              value={password}
              autoComplete="current-password"
              placeholder="请输入密码"
              onChange={(e) => setPassword(e.target.value)}
            />
          </label>

          {error ? <div className="login-error">{error}</div> : null}

          <button className="btn login-submit" type="submit" disabled={submitting}>
            {submitting ? (
              <>
                <span className="login-spinner" aria-hidden="true" />
                登录中…
              </>
            ) : (
              '登录'
            )}
          </button>
          <div className="login-hint">登录后按账号角色进入对应工作台</div>
        </form>
      </div>
    </div>
  )
}
