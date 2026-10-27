import { Routes, Route, Navigate, useLocation } from 'react-router-dom'
import { AuthProvider, useAuth } from './context/AuthContext'
import { AppProvider } from './context/AppContext'
import Sidebar from './components/Sidebar'
import Toast from './components/Toast'
import LoginView from './views/LoginView'
import ListView from './views/ListView'
import DetailView from './views/DetailView'
import ReportView from './views/ReportView'
import ReviewView from './views/ReviewView'
import RiskView from './views/RiskView'

const ROLE_HOME = { manager: '/', risk: '/risk', admin: '/' }

// 各角色可访问的页面（路径前缀匹配）
const ACCESS = {
  manager: ['/', '/detail', '/report', '/review'],
  risk: ['/risk'],
  admin: ['/', '/detail', '/report', '/review', '/risk']
}

function homeOf(user) {
  return ROLE_HOME[user?.role] || '/'
}

function isAllowed(role, pathname) {
  const prefixes = ACCESS[role] || []
  return prefixes.some((p) => (p === '/' ? pathname === '/' : pathname === p || pathname.startsWith(`${p}/`)))
}

function Guard({ user, children }) {
  const location = useLocation()
  if (!isAllowed(user.role, location.pathname)) {
    return <Navigate to={homeOf(user)} replace />
  }
  return children
}

function AppRoutes() {
  const { user, loading } = useAuth()

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

  const guard = (element) => <Guard user={user}>{element}</Guard>

  return (
    <AppProvider>
      <Sidebar />
      <main className="app-main">
        <Routes>
          <Route path="/login" element={<Navigate to={homeOf(user)} replace />} />
          <Route path="/" element={guard(<ListView />)} />
          <Route path="/detail" element={guard(<DetailView />)} />
          <Route path="/detail/:id" element={guard(<DetailView />)} />
          <Route path="/report" element={guard(<ReportView />)} />
          <Route path="/report/:id" element={guard(<ReportView />)} />
          <Route path="/review" element={guard(<ReviewView />)} />
          <Route path="/review/:id" element={guard(<ReviewView />)} />
          <Route path="/risk" element={guard(<RiskView />)} />
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
