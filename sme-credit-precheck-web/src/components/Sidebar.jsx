import { useApp } from '../context/AppContext'
import { useAuth } from '../context/AuthContext'
import { useNavigate, useLocation } from 'react-router-dom'

const MANAGER_NAV = [
  { path: '/', label: '申请列表', icon: '📋' },
  { path: '/detail', label: '申请详情', icon: '📄' },
  { path: '/report', label: 'AI 预审报告', icon: '🤖' },
  { path: '/review', label: '人工复核', icon: '✍️' }
]

const RISK_NAV = [{ path: '/risk', label: '风控队列', icon: '🛡️', badge: true }]

const ROLE_LABEL = {
  manager: '普惠金融客户经理',
  risk: '风控审批专员',
  admin: '系统管理员'
}

function navOf(role) {
  if (role === 'risk') return RISK_NAV
  if (role === 'admin') return [...MANAGER_NAV, ...RISK_NAV]
  return MANAGER_NAV
}

export default function Sidebar() {
  const { apps } = useApp()
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()

  const items = navOf(user.role)
  const riskCount = apps.filter((a) => a.status === 'risk' && !a.archived).length

  return (
    <aside className="app-sidebar">
      <div className="sidebar-logo">
        <div className="logo-icon">🏦</div>
        <div>
          小微企业授信
          <br />
          智能预审系统
        </div>
      </div>

      <nav className="app-nav">
        {items.map((n) => {
          const active =
            n.path === '/' ? location.pathname === '/' : location.pathname.startsWith(n.path)
          return (
            <button
              key={n.path}
              className={`nav-item ${active ? 'active' : ''}`}
              onClick={() => navigate(n.path)}
            >
              <span className="nav-icon">{n.icon}</span>
              <span>{n.label}</span>
              {n.badge && riskCount > 0 ? <span className="nav-badge">{riskCount}</span> : null}
            </button>
          )
        })}
      </nav>

      <div className="user-card">
        <div className="avatar">{user.full_name.slice(0, 1)}</div>
        <div className="user-meta">
          <div className="user-name">{user.full_name}</div>
          <div>{ROLE_LABEL[user.role] || user.role}</div>
        </div>
        <button className="sidebar-logout" onClick={logout} title="退出登录">
          退出
        </button>
      </div>
    </aside>
  )
}
