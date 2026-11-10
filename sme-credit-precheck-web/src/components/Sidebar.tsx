import { useApp } from '../context/AppContext'
import { useAuth } from '../context/AuthContext'
import { useNavigate, useLocation } from 'react-router-dom'

interface NavItem {
  path: string
  label: string
  icon: string
  badge?: boolean
}

const MANAGER_NAV: NavItem[] = [
  { path: '/', label: '申请列表', icon: '📋' },
  { path: '/detail', label: '申请详情', icon: '📄' },
  { path: '/report', label: 'AI 预审报告', icon: '🤖' },
  { path: '/review', label: '人工复核', icon: '✍️' },
  { path: '/chat', label: '授信助手', icon: '💬' }
]

const RISK_NAV: NavItem[] = [
  { path: '/risk', label: '风控队列', icon: '🛡️', badge: true },
  { path: '/chat', label: '风控预审助手', icon: '💬' }
]

const ROLE_LABEL: Record<string, string> = {
  manager: '普惠金融客户经理',
  risk: '风控审批专员',
  admin: '系统管理员'
}

function navOf(role?: string): NavItem[] {
  if (role === 'risk') return RISK_NAV
  if (role === 'admin') return [...MANAGER_NAV, ...RISK_NAV]
  return MANAGER_NAV
}

/** 从当前路由提取申请 id（/detail/:id、/report/:id、/review/:id） */
function appIdFromRoute(pathname: string): string | null {
  const m = pathname.match(/^\/(detail|report|review)\/([^/]+)/)
  return m ? m[2] : null
}

/** 从详情页路由提取当前申请，进入智能问答时携带，避免丢失 app_id 上下文 */
function appContextFromRoute(
  pathname: string,
  apps: ReturnType<typeof useApp>['apps']
): { appId: number; appNo: string; product: string } | null {
  if (!pathname.startsWith('/detail/') && !pathname.startsWith('/report/')) return null
  const id = pathname.split('/').pop()
  const app = apps.find((a) => a.id === id)
  if (!app?.dbId) return null
  return { appId: app.dbId, appNo: app.id, product: app.product }
}

export default function Sidebar() {
  const { apps } = useApp()
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()

  const items = navOf(user?.role)
  const riskCount = apps.filter((a) => a.status === 'risk' && !a.archived).length

  const goTo = (path: string) => {
    if (path === '/chat') {
      const ctx = appContextFromRoute(location.pathname, apps)
      if (ctx) {
        navigate(path, { state: ctx })
        return
      }
    }
    // 申请相关页面：保留当前正在查看的申请，避免跳到最新申请
    if (path === '/detail' || path === '/report' || path === '/review') {
      const currentId = appIdFromRoute(location.pathname)
      if (currentId) {
        navigate(`${path}/${currentId}`)
        return
      }
    }
    navigate(path)
  }

  return (
    <>
      {/* 抽屉开关：隐藏 checkbox + 汉堡按钮 label + 遮罩 label，均为 .app-sidebar 的兄弟节点 */}
      <input id="sidebar-toggle" type="checkbox" hidden />
      <label htmlFor="sidebar-toggle" className="sidebar-toggle-btn" aria-label="打开侧边栏">
        ☰
      </label>
      <label htmlFor="sidebar-toggle" className="sidebar-backdrop" aria-hidden="true" />

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
                onClick={() => goTo(n.path)}
              >
                <span className="nav-icon">{n.icon}</span>
                <span>{n.label}</span>
                {n.badge && riskCount > 0 ? <span className="nav-badge">{riskCount}</span> : null}
              </button>
            )
          })}
        </nav>

        <div className="user-card">
          <div className="avatar">{(user?.full_name || '?').slice(0, 1)}</div>
          <div className="user-meta">
            <div className="user-name">{user?.full_name}</div>
            <div>{ROLE_LABEL[user?.role || ''] || user?.role}</div>
          </div>
          <button className="sidebar-logout" onClick={logout} title="退出登录">
            退出
          </button>
        </div>
      </aside>
    </>
  )
}
