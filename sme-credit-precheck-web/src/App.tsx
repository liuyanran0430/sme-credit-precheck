import { useState } from 'react'
import type { ReactNode } from 'react'
import { Routes, Route, Navigate, useLocation, useNavigate } from 'react-router-dom'
import { AuthProvider, useAuth } from './context/AuthContext'
import { AppProvider } from './context/AppContext'
import Sidebar from './components/Sidebar'
import ChatPanel from './components/ChatPanel'
import Toast from './components/Toast'
import LoginView from './views/LoginView'
import ListView from './views/ListView'
import DetailView from './views/DetailView'
import ReportView from './views/ReportView'
import ReviewView from './views/ReviewView'
import RiskView from './views/RiskView'
import type { NewAppPrefill, User } from './types'

const ROLE_HOME: Record<string, string> = { manager: '/', risk: '/risk', admin: '/' }

// 各角色可访问的页面（路径前缀匹配）
const ACCESS: Record<string, string[]> = {
  manager: ['/', '/detail', '/report', '/review', '/chat'],
  risk: ['/risk', '/chat'],
  admin: ['/', '/detail', '/report', '/review', '/risk', '/chat']
}

function homeOf(user?: User | null): string {
  return ROLE_HOME[user?.role || ''] || '/'
}

function isAllowed(role: string, pathname: string): boolean {
  const prefixes = ACCESS[role] || []
  return prefixes.some((p) =>
    p === '/' ? pathname === '/' : pathname === p || pathname.startsWith(`${p}/`)
  )
}

function Guard({ user, children }: { user: User; children: ReactNode }) {
  const location = useLocation()
  if (!isAllowed(user.role, location.pathname)) {
    return <Navigate to={homeOf(user)} replace />
  }
  return <>{children}</>
}

function AppRoutes() {
  const { user, loading } = useAuth()
  const navigate = useNavigate()
  const [newAppPrefill, setNewAppPrefill] = useState<NewAppPrefill | null>(null)

  // P2：助手只预填，跳回列表页由用户确认并手动提交
  const openNewAppWith = (payload: Record<string, unknown>) => {
    setNewAppPrefill(payload as NewAppPrefill)
    navigate('/')
  }

  if (loading) {
    return <div className="boot-loading">正在加载…</div>
  }

  if (!user) {
    return (
      <Routes>
        <Route path="/login" element={<LoginView />} />
        <Route path="*" element={<Navigate to="/login" replace />} />
      </Routes>
    )
  }

  const guard = (element: ReactNode) => <Guard user={user}>{element}</Guard>

  return (
    <AppProvider>
      <Sidebar />
      <main className="app-main">
        <Routes>
          <Route path="/login" element={<Navigate to={homeOf(user)} replace />} />
          <Route
            path="/"
            element={guard(
              <ListView
                newAppInitial={newAppPrefill}
                onNewAppInitialConsumed={() => setNewAppPrefill(null)}
              />
            )}
          />
          <Route path="/detail" element={guard(<DetailView />)} />
          <Route path="/detail/:id" element={guard(<DetailView />)} />
          <Route path="/report" element={guard(<ReportView />)} />
          <Route path="/report/:id" element={guard(<ReportView />)} />
          <Route path="/review" element={guard(<ReviewView />)} />
          <Route path="/review/:id" element={guard(<ReviewView />)} />
          <Route path="/risk" element={guard(<RiskView />)} />
          <Route path="/chat" element={guard(<ChatPanel onPrefillNewApp={openNewAppWith} />)} />
          <Route path="*" element={<Navigate to={homeOf(user)} replace />} />
        </Routes>
      </main>
      <Toast />
    </AppProvider>
  )
}

export default function App() {
  return (
    <AuthProvider>
      <AppRoutes />
    </AuthProvider>
  )
}
