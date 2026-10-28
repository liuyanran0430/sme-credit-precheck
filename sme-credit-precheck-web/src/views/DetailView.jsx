import { useEffect, useRef, useState, Fragment } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useApp, normalizeApplication } from '../context/AppContext'
import { STATUS_MAP, MATERIAL_CATEGORIES } from '../constants'
import {
  fetchApplication,
  fetchManualReviews,
  fetchMaterials,
  fetchReport,
  fetchRiskReviews,
  materialFileUrl,
  deleteMaterial
} from '../api/applications'
import { fmt, matStatusText, normalizeMaterial, STEP_IDX } from '../utils'
import Stepper from '../components/Stepper'
import UploadModal from '../modals/UploadModal'
import PreviewModal from '../modals/PreviewModal'
import CategoryModal from '../modals/CategoryModal'
import ConfirmModal from '../components/ConfirmModal'

function groupStatus(files) {
  if (!files.length) return 'none'
  if (files.some((f) => f.status === 'pending')) return 'pending'
  if (files.some((f) => f.status === 'low')) return 'low'
  return 'ok'
}

// 缺件文案：产品专属必交材料展示规则文件中的具体要求（desc），其余展示类别名
function buildMissingLabels(data, product) {
  const cats = data?.categories || []
  return (data?.missing || []).map((key) => {
    const item = cats.find((c) => c.category === key)
    if (item?.requirement) return `${product}要求提供${item.requirement}`
    const local = MATERIAL_CATEGORIES.find((c) => c.key === key)
    return local ? local.label : key
  })
}

export default function DetailView() {
  const { id } = useParams()
  const { apps, getMaterials, setMaterials, updateApp, processingMap, toast } = useApp()
  const navigate = useNavigate()
  const [showUpload, setShowUpload] = useState(false)

  const app = apps.find((a) => a.id === id) || apps[0]
  // 当前申请的后台处理阶段：checking=材料检查中，analyzing=AI 预审中
  const processing = app ? processingMap[app.id] : null
  const [expanded, setExpanded] = useState({})
  const [preview, setPreview] = useState(null)
  const [showCategory, setShowCategory] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(null) // 待删除的材料对象
  const [deleting, setDeleting] = useState(false)
  // 后端判定的缺失必备材料（公共五类 + 产品专属），由规则文件驱动
  const [missingCats, setMissingCats] = useState([])
  // AI 预审报告（用于详情页的预审摘要）
  const [report, setReport] = useState(null)
  // 已拒绝申请的被拒环节：3=人工复核，4=风控复核，-1=未拒绝
  const [rejectedAt, setRejectedAt] = useState(-1)

  // 重新拉取材料清单（修改分类后调用）
  const reloadMaterials = () => {
    fetchMaterials(app.id)
      .then((rows) => setMaterials(app.id, rows.map(normalizeMaterial)))
      .catch((error) => console.error(error))
  }

  // 刷新 AI 预审摘要与缺件提示（统一取预审落库快照 report.completeness）
  const refreshReport = () => {
    fetchReport(app.id)
      .then((data) => {
        setReport(data)
        setMissingCats(buildMissingLabels(data?.completeness, app.product))
      })
      .catch((error) => console.error(error))
  }

  // 刷新申请状态（AI 预审完成后进度会推进）
  const refreshApp = () => {
    fetchApplication(app.id)
      .then((row) => updateApp(app.id, normalizeApplication(row)))
      .catch((error) => console.error(error))
  }

  // 打开材料文件预览（页内弹窗）
  const openFile = (m) => {
    if (!m || !m.id) {
      toast('该文件暂无法预览')
      return
    }
    setPreview(m)
  }

  // 删除材料文件（应用内确认弹窗）
  const handleDeleteFile = (m) => {
    if (!m || !m.id) return
    setConfirmDelete(m)
  }

  const handleConfirmDelete = async () => {
    const m = confirmDelete
    if (!m) return
    setDeleting(true)
    try {
      await deleteMaterial(app.id, m.id)
      toast(`文件「${m.name}」已删除，已重新执行 AI 预审`)
      setConfirmDelete(null)
      reloadMaterials()
      // 删除后预审会重新判定，缺件时申请状态回到「待补件」
      refreshApp()
      refreshReport()
    } catch (err) {
      toast(err.message || '删除失败，请稍后重试')
    } finally {
      setDeleting(false)
    }
  }

  // 单文件类别直接打开预览；多文件类别展开/收起文件列表
  const handleView = (g) => {
    if (!g.files.length) {
      toast(`${g.label}暂无文件`)
      return
    }
    if (g.files.length === 1) {
      openFile(g.files[0])
      return
    }
    setExpanded((prev) => ({ ...prev, [g.key]: !prev[g.key] }))
  }

  // 申请状态变化（如后台 AI 预审完成）时刷新预审摘要与缺件提示
  const appStatus = app?.status
  const skipStatusWatch = useRef(true)
  useEffect(() => {
    if (skipStatusWatch.current) {
      skipStatusWatch.current = false
      return
    }
    if (!appStatus) return
    refreshReport()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [appStatus])

  useEffect(() => {
    if (!app) return
    let cancelled = false
    fetchMaterials(app.id)
      .then((rows) => {
        if (!cancelled) setMaterials(app.id, rows.map(normalizeMaterial))
      })
      .catch((error) => {
        if (!cancelled) console.error(error)
      })
    // 同步最新申请状态，确保预审后的进度条正确
    fetchApplication(app.id)
      .then((row) => {
        if (!cancelled) updateApp(app.id, normalizeApplication(row))
      })
      .catch((error) => {
        if (!cancelled) console.error(error)
      })
    // AI 预审摘要与缺件提示：统一读取预审落库快照，不再实时计算
    fetchReport(app.id)
      .then((data) => {
        if (!cancelled) {
          setReport(data)
          setMissingCats(buildMissingLabels(data?.completeness, app.product))
        }
      })
      .catch((error) => {
        if (!cancelled) console.error(error)
      })
    return () => {
      cancelled = true
    }
  }, [app?.id, setMaterials, updateApp])

  // 已拒绝申请：根据复核记录定位被拒环节（人工复核=3 / 风控复核=4）
  useEffect(() => {
    if (!app || app.status !== 'rejected') {
      setRejectedAt(-1)
      return undefined
    }
    let cancelled = false
    Promise.allSettled([fetchRiskReviews(app.id), fetchManualReviews(app.id)])
      .then(([riskRes, manualRes]) => {
        if (cancelled) return
        const riskDenied =
          riskRes.status === 'fulfilled' &&
          Array.isArray(riskRes.value) &&
          riskRes.value.some((r) => r.decision === 'deny')
        const manualDenied =
          manualRes.status === 'fulfilled' &&
          Array.isArray(manualRes.value) &&
          manualRes.value.some((r) => r.decision === 'deny')
        setRejectedAt(riskDenied ? 4 : manualDenied ? 3 : -1)
      })
      .catch(() => {})
    return () => {
      cancelled = true
    }
  }, [app?.id, app?.status])

  if (!app) return <div className="page">申请不存在</div>

  const s = STATUS_MAP[app.status] || { label: app.status || '未知状态', cls: 'slate' }
  const mats = getMaterials(app.id)
  const groups = MATERIAL_CATEGORIES.map((c) => ({
    ...c,
    files: mats.filter((m) => (m.category || 'other') === c.key)
  }))
  const filled = groups.filter((g) => g.files.length).length

  // AI 预审摘要：由预审报告中的规则匹配、风险信号与冲突项汇总
  const ruleMatching = report?.rule_results
  const ruleItems = ruleMatching?.rules || []
  const riskSignals = report?.risk_signals || []
  const conflicts = report?.conflicts || []
  const lowConfidenceConflicts = conflicts.filter((c) => c.type === 'low_confidence')
  const ruleConflicts = conflicts.filter((c) => c.type !== 'low_confidence')
  const highRiskSignals = riskSignals.filter((s) => s.level === 'high')
  const uncertainRules = ruleItems.filter(
    (rule) => rule.result === 'uncertain' || (rule.kind === 'soft' && rule.result === 'fail')
  )
  const uncertainText =
    uncertainRules.length === 0
      ? '暂无存疑项'
      : uncertainRules
          .slice(0, 3)
          .map(
            (rule) =>
              `${rule.rule_name}：实际 ${rule.actual || '—'}，要求 ${rule.expected || '—'}`
          )
          .join('；')
  const primaryRisk = highRiskSignals[0] || riskSignals[0]
  const primaryRiskText = primaryRisk
    ? `${primaryRisk.title}${
        primaryRisk.evidence?.detail ? `：${primaryRisk.evidence.detail}` : ''
      }`
    : '暂无风险信号'
  const evidenceCount = ruleItems.filter((rule) => rule.evidence).length
  const verdictTone =
    report?.conclusion === 'pass'
      ? 'pass'
      : report?.conclusion === 'forbidden'
        ? 'fail'
        : 'uncertain'
  const verdictLabel = report
    ? { pass: '符合', forbidden: '不符合', attention: '基本符合', manual: '基本符合' }[
        report.conclusion
      ] || '待人工核验'
    : '待生成'
  const generatedAt = report?.created_at
    ? String(report.created_at).replace('T', ' ').slice(0, 16)
    : '—'

  return (
    <div className="page">
      <div className="crumb">
        <button className="link" onClick={() => navigate('/')}>
          ← 返回申请列表
        </button>
      </div>

      <div className="page-head">
        <div>
          <h1>
            <span className="mono">{app.id}</span>
            <span className="company">{app.company}</span>
            <span className={`tag tag-${s.cls}`}>{s.label}</span>
          </h1>
          <div className="meta">
            提交于 {app.submitDate} · 产品：{app.product}
          </div>
        </div>
        <div className="actions-right">
          <button className="btn btn-primary" onClick={() => setShowUpload(true)}>
            ＋ 上传资料
          </button>
        </div>
      </div>

      {/* 后台处理阶段提示：材料检查中 / AI 预审中 */}
      {processing === 'checking' && (
        <div className="processing-banner">
          <span className="processing-spinner" />
          材料检查中：正在上传文件并进行 OCR 抽取与智能分类，完成后将自动进入 AI 预审…
        </div>
      )}
      {processing === 'analyzing' && (
        <div className="processing-banner">
          <span className="processing-spinner" />
          AI 预审中：材料检查完成，正在执行准入规则匹配与一致性校验…
        </div>
      )}

      <Stepper
        active={
          rejectedAt >= 0
            ? rejectedAt
            : processing === 'analyzing'
              ? 2
              : (STEP_IDX[app.status] ?? 3)
        }
        rejectedAt={rejectedAt}
      />

      <div className="stat-grid">
        <div className="card stat-card">
          <div className="stat-label">申请金额 & 产品</div>
          <div className="stat-value">
            ¥ {fmt(app.amount)} 万 <span className="pill">{app.product}</span>
          </div>
        </div>
        <div className="card stat-card">
          <div className="stat-label">客户经理 & 提交日期</div>
          <div className="stat-value-sm">
            {app.manager} · {app.submitDate}
          </div>
        </div>
        <div className="card stat-card">
          <div className="stat-label">材料合规 / 补件</div>
          {!report ? (
            <div className="stat-value-sm">待预审</div>
          ) : missingCats.length ? (
            <div className="stat-value-sm compliance-miss" title={missingCats.join('、')}>
              缺件：{missingCats.join('、')}
            </div>
          ) : (
            <div className="stat-value-sm compliance-ok">材料合规</div>
          )}
          {app.supplementNote ? (
            <div className="stat-note" title={app.supplementNote}>
              补件说明{app.supplementSource === 'risk' ? '（风控退回）' : app.supplementSource === 'manual' ? '（人工复核退回）' : ''}
              ：{app.supplementNote}
            </div>
          ) : null}
        </div>
      </div>

      <div className="detail-main">
        <aside className="card panel mat-panel">
          <div className="panel-head">
            <h3>
              材料清单{' '}
              <span className="muted">
                {filled} / {MATERIAL_CATEGORIES.length} 类 · {mats.length} 份
              </span>
            </h3>
            <button
              className="btn btn-secondary btn-sm"
              onClick={() => setShowCategory(true)}
              disabled={!mats.length}
            >
              修改分类
            </button>
          </div>
          <div className="panel-body">
            {groups.map((g) => {
              const status = groupStatus(g.files)
              const expandedFiles = expanded[g.key] && g.files.length > 1
              return (
                <Fragment key={g.key}>
                  <div
                    className={`mat-item ${status === 'low' ? 'low' : ''} ${
                      status === 'pending' ? 'pending' : ''
                    } ${status === 'none' ? 'none' : ''}`}
                  >
                    <div className="mat-icon">{g.icon}</div>
                    <div className="mat-info">
                      <div className="mat-name-row">
                        <span className="mat-name" title={g.label}>
                          {g.label}
                        </span>
                        <span className={`mat-status ${status}`}>{matStatusText({ status })}</span>
                      </div>
                      <div className="mat-ver">
                        {g.files.length ? `共 ${g.files.length} 份 · 更新 ${g.files[0].update}` : '暂无文件'}
                      </div>
                    </div>
                    <div className="mat-right">
                      <button
                        className="btn btn-ghost btn-xs"
                        onClick={() => handleView(g)}
                        disabled={!g.files.length}
                      >
                        {expandedFiles ? '收起' : '查看'}
                      </button>
                      <button
                        className="btn btn-danger-ghost btn-xs"
                        onClick={() => g.files.length === 1 && handleDeleteFile(g.files[0])}
                        disabled={g.files.length !== 1}
                        title={
                          g.files.length > 1 ? '多份文件请展开后按文件删除' : undefined
                        }
                      >
                        删除
                      </button>
                    </div>
                  </div>
                  {expandedFiles
                    ? g.files.map((f) => (
                        <div
                          key={f.id}
                          className="mat-item pending"
                          style={{ paddingLeft: 44 }}
                        >
                          <div className="mat-icon">📄</div>
                          <div className="mat-info">
                            <div className="mat-name" title={f.name}>
                              {f.name}
                            </div>
                            <div className="mat-ver">{f.update}</div>
                          </div>
                          <div className="mat-right">
                            <span className={`mat-status ${f.status}`}>{matStatusText(f)}</span>
                            <button
                              className="btn btn-ghost btn-xs"
                              onClick={() => openFile(f)}
                            >
                              查看
                            </button>
                            <button
                              className="btn btn-danger-ghost btn-xs"
                              onClick={() => handleDeleteFile(f)}
                            >
                              删除
                            </button>
                          </div>
                        </div>
                      ))
                    : null}
                </Fragment>
              )
            })}
          </div>
        </aside>

        <section className="card panel">
          <div className="panel-head">
            <h3>AI 预审摘要</h3>
            <div className="panel-meta">
              {report
                ? `报告版本 ${report.version || '—'} · 规则版本 ${report.rule_version || '—'} · 生成于 ${generatedAt}`
                : '暂无预审报告'}
            </div>
          </div>
          <div className="panel-body">
            {!report ? (
              <div className="mat-empty">该申请尚未生成 AI 预审报告。</div>
            ) : (
              <>
                <div className={`ai-verdict ${verdictTone}`}>
                  <div className="ai-verdict-title">
                    准入初判：<b>{verdictLabel}</b>
                  </div>
                  <div className="ai-verdict-counts">
                    <span className="pass">✓ {ruleMatching?.pass_count || 0} 项符合</span>
                    <span className="uncertain">⚠ {ruleMatching?.uncertain_count || 0} 项存疑</span>
                    <span className="fail">✕ {ruleConflicts.length} 项冲突</span>
                  </div>
                </div>

                <div className="ai-summary-grid">
                  <div>
                    <div className="ai-summary-label">存疑项</div>
                    <div className="ai-summary-box warn" title={uncertainText}>
                      <span className="ai-summary-clip">{uncertainText}</span>
                    </div>
                  </div>
                  <div>
                    <div className="ai-summary-label">风险信号</div>
                    <div className="ai-summary-box risk" title={primaryRiskText}>
                      <span className="ai-summary-clip">{primaryRiskText}</span>
                    </div>
                  </div>
                  <div>
                    <div className="ai-summary-label">
                      低置信项（{lowConfidenceConflicts.length}）
                    </div>
                    <ul className="ai-summary-list">
                      {lowConfidenceConflicts.length === 0 ? (
                        <li className="empty">暂无低置信项</li>
                      ) : (
                        lowConfidenceConflicts.map((item, idx) => (
                          <li key={`low-${idx}`}>{item.reason}</li>
                        ))
                      )}
                    </ul>
                  </div>
                  <div>
                    <div className="ai-summary-label">证据引用</div>
                    <div className="ai-summary-box evidence">
                      <span>已自动关联 {evidenceCount} 处证据</span>
                      <button
                        className="ai-summary-link"
                        onClick={() => navigate(`/report/${app.id}`)}
                      >
                        查看链路
                      </button>
                    </div>
                  </div>
                </div>

                <div className="ai-summary-stats">
                  <div>
                    <strong>{ruleConflicts.length}</strong>
                    <span>规则冲突</span>
                  </div>
                  <div>
                    <strong>{highRiskSignals.length}</strong>
                    <span>高风险信号</span>
                  </div>
                  <div>
                    <strong>{Math.round(report.pass_rate || 0)}%</strong>
                    <span>预估通过率</span>
                  </div>
                </div>
              </>
            )}
          </div>
          <div className="panel-foot right">
            <button className="btn btn-secondary" onClick={() => navigate(`/report/${app.id}`)}>
              查看完整预审报告
            </button>
            <button className="btn btn-primary" onClick={() => navigate(`/review/${app.id}`)}>
              进入人工复核
            </button>
          </div>
        </section>
      </div>

      {showUpload ? (
        <UploadModal
          appId={app.id}
          onClose={() => setShowUpload(false)}
          onUploaded={() => {
            reloadMaterials()
            refreshApp()
            refreshReport()
          }}
        />
      ) : null}
      {preview ? (
        <PreviewModal appId={app.id} material={preview} onClose={() => setPreview(null)} />
      ) : null}
      {showCategory ? (
        <CategoryModal
          appId={app.id}
          materials={mats}
          onClose={() => setShowCategory(false)}
          onSaved={() => {
            reloadMaterials()
            refreshApp()
            refreshReport()
          }}
        />
      ) : null}
      {confirmDelete ? (
        <ConfirmModal
          title="删除材料"
          message={`确定删除文件「${confirmDelete.name}」吗？\n对应的材料记录与上传文件将一并删除，且不可恢复。`}
          confirmText="删除"
          danger
          busy={deleting}
          onConfirm={handleConfirmDelete}
          onCancel={() => setConfirmDelete(null)}
        />
      ) : null}
    </div>
  )
}
