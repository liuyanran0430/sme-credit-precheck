import { createContext, useContext, useState, useCallback, useEffect, useMemo } from 'react'
import type { ReactNode, Dispatch, SetStateAction } from 'react'
import { fetchApplications } from '../api/applications'
import { logger } from '../utils/logger'
import type {
  Application,
  ApplicationRow,
  ApplicationStatus,
  Material,
  ProcessingStage,
  ToastItem
} from '../types'

// 申请尚无 AI 摘要时，按当前进度给出提示文案
const STATUS_SUMMARY_HINTS: Record<string, string> = {
  check: 'AI 预审尚未开始，待材料分类完成后自动生成摘要。',
  precheck: '材料已就绪，点击详情页「🤖 开始 AI 预审」即可生成预审摘要。',
  supplement: '材料待补件，补齐后 AI 将重新预审并更新摘要。',
  manual: 'AI 预审已完成，待人工复核确认。',
  risk: '已通过人工复核，待风控复核。',
  approved: '申请已审批完成。',
  rejected: '申请已被人工复核否决，流程终止。'
}

export interface AppContextValue {
  apps: Application[]
  appsLoading: boolean
  setApps: Dispatch<SetStateAction<Application[]>>
  materialsMap: Record<string, Material[]>
  getMaterials: (appId: string) => Material[]
  setMaterials: (appId: string, updater: Material[] | ((cur: Material[]) => Material[])) => void
  updateApp: (appId: string, updater: Partial<Application> | ((app: Application) => Application)) => void
  addApp: (app: Application) => void
  toasts: ToastItem[]
  toast: (msg: string) => void
  processingMap: Record<string, ProcessingStage>
  setProcessing: (appId: string, stage: ProcessingStage | null) => void
}

const AppContext = createContext<AppContextValue | null>(null)

export function normalizeApplication(row: ApplicationRow): Application {
  const status = (row.status || 'check') as ApplicationStatus
  return {
    id: row.app_no,
    dbId: row.id,
    company: row.company_name || '',
    creditCode: row.credit_code || '',
    amount: Number(row.amount),
    product: row.product || '',
    status,
    manager: row.manager_name || '未分配',
    summary: row.ai_summary || STATUS_SUMMARY_HINTS[status] || '暂无 AI 摘要',
    supplementNote: row.supplement_note || '',
    supplementSource: row.supplement_source || null,
    riskReturned: !!row.risk_returned,
    conclusion: row.conclusion || null,
    submittedAt: row.created_at,
    slaDeadline: row.sla_deadline,
    createdAt: row.created_at,
    ai: '暂无结论',
    dti: null,
    gap: null,
    passRate: null,
    sla: row.sla_deadline ? `截止 ${row.sla_deadline.slice(0, 10)}` : '—',
    slaLevel: 'muted',
    submitDate: row.created_at ? row.created_at.slice(0, 10) : '—',
    upgradeReason: '—',
    archived: false,
    // AI 预审手动触发判定（后端计算）
    canPrecheck: row.can_precheck !== false,
    precheckDisabledReason: row.precheck_disabled_reason || null
  }
}

export function AppProvider({ children }: { children: ReactNode }) {
  const [apps, setApps] = useState<Application[]>([])
  const [appsLoading, setAppsLoading] = useState(true)
  const [materialsMap, setMaterialsMap] = useState<Record<string, Material[]>>({})
  const [toasts, setToasts] = useState<ToastItem[]>([])
  // 各申请的后台处理阶段：checking=材料检查中，analyzing=AI 预审中
  const [processingMap, setProcessingMap] = useState<Record<string, ProcessingStage>>({})

  // 更新某申请的后台处理阶段（null 表示处理结束）
  const setProcessing = useCallback((appId: string, stage: ProcessingStage | null) => {
    setProcessingMap((prev) => {
      const next = { ...prev }
      if (stage) next[appId] = stage
      else delete next[appId]
      return next
    })
  }, [])

  // 获取某申请的材料清单
  const getMaterials = useCallback(
    (appId: string) => materialsMap[appId] || [],
    [materialsMap]
  )

  // 更新某申请的材料清单
  const setMaterials = useCallback(
    (appId: string, updater: Material[] | ((cur: Material[]) => Material[])) => {
      setMaterialsMap((prev) => {
        const cur = prev[appId] || []
        const next = typeof updater === 'function' ? updater(cur) : updater
        return { ...prev, [appId]: next }
      })
    },
    []
  )

  // 更新申请
  const updateApp = useCallback(
    (appId: string, updater: Partial<Application> | ((app: Application) => Application)) => {
      setApps((prev) =>
        prev.map((a) =>
          a.id === appId
            ? typeof updater === 'function'
              ? updater(a)
              : { ...a, ...updater }
            : a
        )
      )
    },
    []
  )

  // 新增申请
  const addApp = useCallback((app: Application) => {
    setApps((prev) => [app, ...prev])
  }, [])

  // 弹出提示
  const toast = useCallback((msg: string) => {
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
      .then(({ items }) => {
        if (cancelled) return
        setApps(items.map(normalizeApplication))
      })
      .catch((error) => {
        if (cancelled) return
        logger.error('加载申请列表失败', error)
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
      toast,
      processingMap,
      setProcessing
    }),
    [
      apps,
      appsLoading,
      materialsMap,
      getMaterials,
      setMaterials,
      updateApp,
      addApp,
      toasts,
      toast,
      processingMap,
      setProcessing
    ]
  )

  return <AppContext.Provider value={value}>{children}</AppContext.Provider>
}

export function useApp(): AppContextValue {
  const ctx = useContext(AppContext)
  if (!ctx) throw new Error('useApp must be used within AppProvider')
  return ctx
}
