import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useApp } from '../context/AppContext'
import { exportReport, fetchReport } from '../api/applications'
import ReportSections, { CONCLUSION_LABELS } from '../components/ReportSections'

export default function ReportView() {
  const { id } = useParams()
  const { apps, appsLoading, toast } = useApp()
  const navigate = useNavigate()

  // 未指定申请时（侧边栏直接进入），默认查看申请列表中第一个申请的报告
  const targetId = id || apps[0]?.id
  const app = apps.find((a) => a.id === targetId)

  useEffect(() => {
    if (!id && !appsLoading && apps.length) {
      navigate(`/report/${apps[0].id}`, { replace: true })
    }
  }, [id, appsLoading, apps, navigate])

  const [report, setReport] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [exporting, setExporting] = useState(false)

  useEffect(() => {
    if (!app?.id) return undefined
    let cancelled = false
    setReport(null)
    setLoading(true)
    setError('')
    ;(async () => {
      try {
        // 报告页统一展示预审落库快照，不再实时计算
        const data = await fetchReport(app.id)
        if (cancelled) return
        setReport(data)
      } catch (err) {
        if (!cancelled) setError(err.message || '材料完整性分析失败')
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [app?.id])

  if (appsLoading) {
    return (
      <div className="page">
        <div className="card review-empty">
          <div className="review-empty-icon loading">…</div>
          <h2>正在加载申请…</h2>
        </div>
      </div>
    )
  }

  if (!targetId) {
    return (
      <div className="page">
        <div className="card review-empty">
          <div className="review-empty-icon loading">—</div>
          <h2>暂无申请</h2>
          <p>当前申请列表为空，无法查看 AI 预审报告。请先提交申请。</p>
          <div className="review-empty-actions">
            <button className="btn btn-primary" onClick={() => navigate('/')}>
              返回申请列表
            </button>
          </div>
        </div>
      </div>
    )
  }

  if (!app) {
    return (
      <div className="page">
        <div className="card review-empty">
          <h2>申请不存在</h2>
          <p>未找到对应的申请记录，请从申请列表重新进入。</p>
          <div className="review-empty-actions">
            <button className="btn btn-primary" onClick={() => navigate('/')}>
              返回申请列表
            </button>
          </div>
        </div>
      </div>
    )
  }

  const handleExport = async () => {
    if (!report) {
      toast('暂无可导出的预审报告')
      return
    }
    setExporting(true)
    try {
      await exportReport(app.id)
      toast('预审报告已导出')
    } catch (err) {
      toast(err.message || '导出失败，请稍后重试')
    } finally {
      setExporting(false)
    }
  }

  return (
    <div className="page">
      <div className="crumb">
        <button className="link" onClick={() => navigate(`/detail/${app.id}`)}>
          ← 返回申请详情
        </button>
      </div>

      <div className="page-head">
        <div>
          <h1>
            AI 预审报告：<span className="mono">{app.id}</span>
          </h1>
          <div className="meta">
            {report
              ? `AI 预审结论：${CONCLUSION_LABELS[report.conclusion] || report.conclusion} · ${report.summary || ''}`
              : '尚未生成 AI 预审报告'}
          </div>
        </div>
        <div className="actions-right">
          <button
            className="btn btn-secondary"
            onClick={handleExport}
            disabled={exporting || !report}
          >
            {exporting ? '正在导出…' : '导出预审报告'}
          </button>
          <button className="btn btn-primary" onClick={() => navigate(`/review/${app.id}`)}>
            进入人工复核
          </button>
        </div>
      </div>

      <ReportSections
        report={report}
        loading={loading}
        error={error}
        onReview={() => navigate(`/review/${app.id}`)}
      />
    </div>
  )
}
