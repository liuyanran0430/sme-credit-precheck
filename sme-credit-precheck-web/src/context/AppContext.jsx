import { createContext, useContext, useState, useCallback, useEffect, useMemo } from 'react'
import { fetchApplications } from '../api/applications'

const AppContext = createContext(null)

export function normalizeApplication(row) {
  return {
    id: row.app_no,
    dbId: row.id,
    company: row.company_name,
    creditCode: row.credit_code || '',
    amount: Number(row.amount),
    product: row.product,
    status: row.status,
    manager: row.manager_name || '未分配',
    summary: row.ai_summary || '暂无 AI 摘要',
    submittedAt: row.submitted_at,
    slaDeadline: row.sla_deadline,
    createdAt: row.created_at,
    ai: '暂无结论',
    dti: null,
    gap: null,
    passRate: null,
    sla: row.sla_deadline ? `截止 ${row.sla_deadline.slice(0, 10)}` : '—',
    slaLevel: 'muted',
    submitDate: row.submitted_at ? row.submitted_at.slice(0, 10) : '—',
    upgradeReason: '—',
    archived: false
  }
}

export function AppProvider({ children }) {
  const [apps, setApps] = useState([])
  const [appsLoading, setAppsLoading] = useState(true)
  const [materialsMap, setMaterialsMap] = useState({})
  const [toasts, setToasts] = useState([])

  // 获取某申请的材料清单
  const getMaterials = useCallback((appId) => materialsMap[appId] || [], [materialsMap])

  // 更新某申请的材料清单
  const setMaterials = useCallback((appId, updater) => {
    setMaterialsMap((prev) => {
      const cur = prev[appId] || []
      const next = typeof updater === 'function' ? updater(cur) : updater
      return { ...prev, [appId]: next }
    })
  }, [])

  // 更新申请
  const updateApp = useCallback((appId, updater) => {
    setApps((prev) =>
      prev.map((a) => (a.id === appId ? (typeof updater === 'function' ? updater(a) : { ...a, ...updater }) : a))
    )
  }, [])

  // 新增申请
  const addApp = useCallback((app) => {
    setApps((prev) => [app, ...prev])
  }, [])

  // 弹出提示
  const toast = useCallback((msg) => {
    const id = Date.now() + Math.random()
    setToasts((prev) => [...prev, { id, msg }])
    setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id))
    }, 2600)
  }, [])

  // 从后端加载申请列表
  useEffect(() => {
    let cancelled = false
    fetchApplications()
      .then((items) => {
        if (cancelled) return
        setApps(items.map(normalizeApplication))
      })
      .catch((error) => {
        if (cancelled) return
        console.error(error)
        setApps([])
        toast('申请列表加载失败，请确认后端服务已启动')
      })
      .finally(() => {
        if (!cancelled) setAppsLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [toast])

  const value = useMemo(
    () => ({
      apps,
      appsLoading,
      setApps,
      materialsMap,
      getMaterials,
      setMaterials,
      updateApp,
      addApp,
      toasts,
      toast
    }),
    [apps, appsLoading, materialsMap, getMaterials, setMaterials, updateApp, addApp, toasts, toast]
  )

  return <AppContext.Provider value={value}>{children}</AppContext.Provider>
}

export function useApp() {
  const ctx = useContext(AppContext)
  if (!ctx) throw new Error('useApp must be used within AppProvider')
  return ctx
}
