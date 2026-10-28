import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { fetchReport, submitManualReview } from '../api/applications'
import { useApp } from '../context/AppContext'
import { useAuth } from '../context/AuthContext'
import { fmt } from '../utils'

const CONCLUSION_LABELS = {
  pass: '符合',
  attention: '需关注',
  forbidden: '建议禁入',
  manual: '待人工核验'
}

const RISK_LEVEL_LABELS = {
  high: '高风险',
  medium: '中风险',
  low: '低风险'
}

// 补件类动作：任一出现即建议「退回补件」
const SUPPLEMENT_ACTIONS = new Set([
  'need_reshoot',
  'need_supplement',
  'missing_confirmed',
  'risk_explain',
  'consistency_explain'
])

// 否定性动作：推翻 AI 判断（误报排除）或要求补件时必须填写核验理由
const NEGATIVE_ACTIONS = new Set([
  ...SUPPLEMENT_ACTIONS,
  'risk_false',
  'consistency_false',
  'conflict_false'
])

const ACTION_LABELS = {
  ok: '核验无误',
  need_reshoot: '需补件 / 重拍',
  conflict_false: '误报排除',
  conflict_confirmed: '确认冲突存在',
  need_supplement: '确认有误，需补件',
  risk_false: '误报排除',
  risk_confirmed: '确认风险存在',
  risk_explain: '确认有误，需补件',
  consistency_false: '误报排除',
  consistency_confirmed: '确认差异存在',
  consistency_explain: '确认有误，需补件',
  complete_ok: '材料已齐，AI 误判',
  missing_confirmed: '缺件属实，需补件'
}

// 各类核验卡的选项配置（tone=reject 表示否定性动作，标红且必填理由）
const KIND_OPTIONS = {
  low: [
    { value: 'ok', label: '核验无误' },
    { value: 'need_reshoot', label: '需补件 / 重拍', tone: 'reject' }
  ],
  conflict: [
    { value: 'conflict_false', label: '误报排除' },
    { value: 'conflict_confirmed', label: '确认冲突存在', tone: 'reject' },
    { value: 'need_supplement', label: '确认有误，需补件', tone: 'reject' }
  ],
  consistency: [
    { value: 'consistency_false', label: '误报排除' },
    { value: 'consistency_confirmed', label: '确认差异存在', tone: 'reject' },
    { value: 'consistency_explain', label: '确认有误，需补件', tone: 'reject' }
  ],
  risk: [
    { value: 'risk_false', label: '误报排除' },
    { value: 'risk_confirmed', label: '确认风险存在', tone: 'reject' },
    { value: 'risk_explain', label: '确认有误，需补件', tone: 'reject' }
  ],
  completeness: [
    { value: 'complete_ok', label: '材料已齐，AI 误判' },
    { value: 'missing_confirmed', label: '缺件属实，需补件', tone: 'reject' }
  ]
}

const LOW_CHECK_LABELS = ['已核对原件', '数据无误', '需补件 / 重拍']
const RESHOOT_LABEL = '需补件 / 重拍'

const DECISION_META = {
  approve: { label: '通过，转风控复核', tone: 'ok' },
  supplement: { label: '退回补件', tone: 'warn' },
  reject: { label: '否决申请', tone: 'reject' }
}

/** 由已保存的 AI 预审报告生成人工复核清单（按问题来源分类，内容已去重）。 */
function buildReviewItems(report) {
  if (!report) return []

  const items = []
  const matching = report.rule_results || {}
  const rules = Array.isArray(matching.rules) ? matching.rules : []
  const conflicts = Array.isArray(report.conflicts) ? report.conflicts : []
  const risks = Array.isArray(report.risk_signals) ? report.risk_signals : []
  const completeness = report.completeness || {}

  const failedHard = rules.filter((rule) => rule.result === 'fail' && rule.kind === 'hard')
  const failedSoft = rules.filter((rule) => rule.result === 'fail' && rule.kind === 'soft')
  const failed = [...failedHard, ...failedSoft]
  const uncertain = rules.filter((rule) => rule.result === 'uncertain')
  const failedIds = failed
    .slice(0, 4)
    .map((rule) => rule.rule_id)
    .join(' / ')

  let initialDesc
  if (failedHard.length) {
    initialDesc = `${failedIds} 等 ${failed.length} 条准入规则未通过，其中强规则 ${failedHard.length} 条命中否决项，需人工核验。`
  } else if (failed.length) {
    initialDesc = `${failedIds} 等 ${failed.length} 条准入规则未通过，未命中强规则否决项。`
  } else if (uncertain.length) {
    initialDesc = `${uncertain.length} 条准入规则证据不足，已在下方逐项列出，请逐条核验。`
  } else {
    initialDesc = `共 ${matching.total_count || rules.length} 条准入规则全部通过。`
  }

  // 准入初判：纯展示，不参与核验进度
  items.push({
    kind: 'initial',
    type: 'normal',
    title: `准入初判：${CONCLUSION_LABELS[report.conclusion] || '待人工核验'}`,
    tag: 'AI 结论',
    tagCls: 'blue',
    desc: initialDesc
  })

  conflicts.forEach((conflict) => {
    if (conflict.type === 'low_confidence') {
      items.push({
        kind: 'low',
        type: 'low',
        title: `低置信：${conflict.value || conflict.source || '材料'}（置信度 ${
          conflict.confidence ?? '—'
        }）`,
        tag: '低置信项',
        tagCls: 'slate',
        desc: conflict.reason,
        checks: true
      })
      return
    }
    const isData = conflict.type === 'data_inconsistent'
    items.push({
      kind: isData ? 'consistency' : 'conflict',
      type: 'warn',
      title: isData
        ? `一致性差异：${conflict.field || '字段'}取值不一致`
        : `规则冲突：${conflict.reason}`,
      tag: isData ? '一致性差异' : '规则冲突',
      tagCls: 'warn',
      desc: isData ? conflict.reason : null,
      conf: conflict.confidence,
      ref:
        conflict.value ||
        (conflict.rules && conflict.rules.length
          ? `规则 ${conflict.rules.join(' / ')}`
          : conflict.field)
    })
  })

  risks.forEach((signal) => {
    const detail = signal.evidence?.detail || ''
    items.push({
      kind: 'risk',
      type: 'risk',
      title: `风险信号：${signal.title}`,
      tag: '风险信号',
      tagCls: 'risk',
      desc: `提示：${detail}${signal.suggestion ? ` 建议：${signal.suggestion}` : ''}`,
      ref: RISK_LEVEL_LABELS[signal.level] || signal.level
    })
  })

  const issues = Array.isArray(completeness.issues) ? completeness.issues : []
  const missing = Array.isArray(completeness.missing) ? completeness.missing : []
  if (missing.length || issues.length) {
    const cats = Array.isArray(completeness.categories) ? completeness.categories : []
    const missingLabels = missing.map((key) => {
      const hit = cats.find((c) => c.category === key)
      return hit?.label || hit?.category || key
    })
    items.push({
      kind: 'completeness',
      type: 'warn',
      title: `材料完整性：缺件 ${missing.length} 类`,
      tag: '材料完整性',
      tagCls: 'warn',
      desc:
        [...missingLabels.map((label) => `缺失：${label}`), ...issues.map((i) => i.message)].join(
          '；'
        ) || '材料覆盖不完整'
    })
  }

  return items.map((item, index) => ({ ...item, id: index + 1 }))
}

function formatTime(date) {
  return date.toLocaleTimeString('zh-CN', { hour12: false })
}

export default function ReviewView() {
  const { id } = useParams()
  const { apps, appsLoading, updateApp, toast } = useApp()
  const { user } = useAuth()
  const navigate = useNavigate()

  // 未指定申请时（侧边栏直接进入），默认取申请列表中第一个待人工核验的申请
  const pendingApps = useMemo(
    () => apps.filter((item) => item.status === 'manual' && !item.archived),
    [apps]
  )
  const targetId = id || pendingApps[0]?.id
  const app = apps.find((item) => item.id === targetId)
  const draftKey = `review-draft-${targetId || 'none'}`

  const [report, setReport] = useState(null)
  const [loading, setLoading] = useState(true)
  const [submitting, setSubmitting] = useState(false)
  const [savedAt, setSavedAt] = useState(null)
  const [reviewState, setReviewState] = useState({})
  // 决策区：null 表示跟随系统推导结论
  const [manualDecision, setManualDecision] = useState(null)
  const [decisionComment, setDecisionComment] = useState('')
  const [supplementNote, setSupplementNote] = useState('')
  // 提交校验未通过的必填字段（核验项 id / decision / note），用于标红提示
  const [errors, setErrors] = useState({})
  const skipAutoSave = useRef(true)

  const items = useMemo(() => buildReviewItems(report), [report])
  // 准入初判为纯展示，不参与核验进度
  const checkItems = useMemo(() => items.filter((item) => item.kind !== 'initial'), [items])
  const done = checkItems.filter((item) => reviewState[item.id]?.action).length

  // AI 初判为建议禁入时，才允许人工否决
  const canReject = report?.conclusion === 'forbidden'

  // 系统推导结论：AI 初判建议禁入 → 否决；任一补件类动作 → 退回补件；否则通过转风控
  const derived = useMemo(() => {
    if (report?.conclusion === 'forbidden') return 'reject'
    const actions = checkItems
      .map((item) => reviewState[item.id]?.action)
      .filter(Boolean)
    return actions.some((action) => SUPPLEMENT_ACTIONS.has(action)) ? 'supplement' : 'approve'
  }, [checkItems, reviewState, report])

  const decision = manualDecision || derived
  const overridden = Boolean(manualDecision) && manualDecision !== derived

  // 补件类核验项（用于汇总补件说明与提交预览）
  const supplementItems = useMemo(
    () =>
      checkItems.filter((item) => SUPPLEMENT_ACTIONS.has(reviewState[item.id]?.action)),
    [checkItems, reviewState]
  )

  const autoNote = useMemo(
    () =>
      supplementItems
        .map((item) => reviewState[item.id]?.comment?.trim() || item.title)
        .join('；'),
    [supplementItems, reviewState]
  )

  // 切换到退回补件且说明为空时，自动带入汇总说明
  useEffect(() => {
    if (decision === 'supplement' && !supplementNote.trim() && autoNote) {
      setSupplementNote(autoNote)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [decision, autoNote])

  useEffect(() => {
    if (!id && !appsLoading && pendingApps.length) {
      navigate(`/review/${pendingApps[0].id}`, { replace: true })
    }
  }, [id, appsLoading, pendingApps, navigate])

  // 打开页面时读取本地草稿
  useEffect(() => {
    if (!targetId) return
    try {
      const raw = localStorage.getItem(draftKey)
      if (!raw) return
      const draft = JSON.parse(raw)
      setReviewState(draft.state || {})
      setManualDecision(draft.decision ?? null)
      setDecisionComment(draft.decisionComment || '')
      setSupplementNote(draft.supplementNote || '')
      setSavedAt(draft.savedAt ? new Date(draft.savedAt) : null)
    } catch {
      localStorage.removeItem(draftKey)
    }
  }, [draftKey, targetId])

  // 加载最新 AI 预审报告
  useEffect(() => {
    if (!targetId) {
      setLoading(false)
      return undefined
    }
    let cancelled = false
    setReport(null)
    setLoading(true)
    fetchReport(targetId)
      .then((data) => {
        if (!cancelled) setReport(data)
      })
      .catch((error) => {
        if (!cancelled) toast(error.message || 'AI 预审报告加载失败')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [targetId, toast])

  // 复核内容变化后自动保存草稿
  useEffect(() => {
    if (skipAutoSave.current) {
      skipAutoSave.current = false
      return undefined
    }
    if (!items.length || !Object.keys(reviewState).length) return undefined
    const timer = setTimeout(() => {
      const now = new Date()
      localStorage.setItem(
        draftKey,
        JSON.stringify({
          state: reviewState,
          decision: manualDecision,
          decisionComment,
          supplementNote,
          savedAt: now.toISOString()
        })
      )
      setSavedAt(now)
    }, 600)
    return () => clearTimeout(timer)
  }, [reviewState, manualDecision, decisionComment, supplementNote, items.length, draftKey])

  if (appsLoading) {
    return (
      <div className="page">
        <div className="card review-empty">
          <div className="review-empty-icon loading">…</div>
          <h2>正在加载待复核申请…</h2>
        </div>
      </div>
    )
  }

  if (!targetId) {
    return (
      <div className="page">
        <div className="card review-empty">
          <div className="review-empty-icon">✓</div>
          <h2>暂无待人工核验的申请</h2>
          <p>
            当前申请列表中没有需要人工复核的申请。新的复核任务会在 AI 预审完成后自动出现在这里。
          </p>
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

  const updateItem = (itemId, patch) => {
    setReviewState((prev) => ({
      ...prev,
      [itemId]: { ...prev[itemId], ...patch }
    }))
  }

  // 选择核验动作；低置信卡与核验勾选联动
  const selectAction = (item, action) => {
    setReviewState((prev) => {
      const cur = prev[item.id] || {}
      let checks = cur.checks || []
      if (item.kind === 'low') {
        if (action === 'need_reshoot' && !checks.includes(RESHOOT_LABEL)) {
          checks = [...checks, RESHOOT_LABEL]
        }
        if (action === 'ok') {
          checks = checks.filter((label) => label !== RESHOOT_LABEL)
        }
      }
      return { ...prev, [item.id]: { ...cur, action, checks } }
    })
  }

  // 低置信卡勾选联动：勾「需补件 / 重拍」自动标记为补件动作
  const toggleCheck = (itemId, label) => {
    setReviewState((prev) => {
      const cur = prev[itemId] || {}
      const selected = cur.checks || []
      const next = selected.includes(label)
        ? selected.filter((value) => value !== label)
        : [...selected, label]
      let action = cur.action
      if (label === RESHOOT_LABEL) {
        if (next.includes(label)) action = 'need_reshoot'
        else if (action === 'need_reshoot') action = undefined
      } else if (next.includes(label) && !next.includes(RESHOOT_LABEL) && !action) {
        action = 'ok'
      }
      return { ...prev, [itemId]: { ...cur, checks: next, action } }
    })
  }

  const saveDraft = () => {
    if (!Object.keys(reviewState).length) {
      toast('暂无可保存的复核草稿')
      return
    }
    const now = new Date()
    localStorage.setItem(
      draftKey,
      JSON.stringify({
        state: reviewState,
        decision: manualDecision,
        decisionComment,
        supplementNote,
        savedAt: now.toISOString()
      })
    )
    setSavedAt(now)
    toast('复核草稿已保存')
  }

  const scrollToField = (key) => {
    document
      .getElementById(`review-field-${key}`)
      ?.scrollIntoView({ behavior: 'smooth', block: 'center' })
  }

  const clearError = (key) => {
    setErrors((prev) => {
      if (!prev[key]) return prev
      const next = { ...prev }
      delete next[key]
      return next
    })
  }

  const handleSubmit = async () => {
    if (loading) {
      toast('AI 预审报告加载中，请稍候')
      return
    }
    if (!checkItems.length) {
      toast('暂无可核验项，无法提交复核结果')
      return
    }
    const pending = checkItems.filter((item) => !reviewState[item.id]?.action)
    if (pending.length) {
      toast(`还有 ${pending.length} 项未核验，请逐项完成核验后提交。`)
      scrollToField(pending[0].id)
      return
    }
    const noComment = checkItems.filter((item) => {
      const state = reviewState[item.id]
      return state?.action && NEGATIVE_ACTIONS.has(state.action) && !state.comment?.trim()
    })
    if (noComment.length) {
      setErrors((prev) => ({
        ...prev,
        ...Object.fromEntries(noComment.map((item) => [item.id, true]))
      }))
      toast(`第 ${noComment.map((item) => item.id).join('、')} 项未填写核验理由（必填）。`)
      scrollToField(noComment[0].id)
      return
    }
    if (overridden && !decisionComment.trim()) {
      setErrors((prev) => ({ ...prev, decision: true }))
      toast('人工覆盖系统建议结论时，请填写覆盖理由。')
      scrollToField('decision')
      return
    }
    if (decision === 'supplement' && !supplementNote.trim()) {
      setErrors((prev) => ({ ...prev, note: true }))
      toast('退回补件时，请填写补件说明。')
      scrollToField('decision')
      return
    }
    setErrors({})

    const payloadItems = checkItems.map((item) => ({
      item_id: item.id,
      action: reviewState[item.id].action,
      comment: reviewState[item.id].comment?.trim() || null
    }))

    setSubmitting(true)
    try {
      await submitManualReview(app.id, {
        reviewer: user?.full_name || app.manager,
        items: payloadItems,
        decision,
        comment: decisionComment.trim() || null,
        supplement_note: decision === 'supplement' ? supplementNote.trim() : null
      })
      localStorage.removeItem(draftKey)
      if (decision === 'approve') {
        updateApp(app.id, { status: 'risk', upgradeReason: '人工复核通过，转风控复核' })
        toast('复核结果已提交，申请已流转至风控复核。')
        setTimeout(() => navigate('/risk'), 900)
      } else if (decision === 'supplement') {
        updateApp(app.id, { status: 'supplement', upgradeReason: '人工复核后退回补件' })
        toast('复核结果已提交，申请已退回补件。')
        setTimeout(() => navigate(`/detail/${app.id}`), 900)
      } else {
        updateApp(app.id, { status: 'rejected', upgradeReason: '人工复核否决' })
        toast('复核结果已提交，申请已否决。')
        setTimeout(() => navigate('/'), 900)
      }
    } catch (error) {
      toast(error.message || '复核结果提交失败')
    } finally {
      setSubmitting(false)
    }
  }

  const confirmedRisk = checkItems.filter(
    (item) => reviewState[item.id]?.action === 'risk_confirmed'
  ).length

  // 提交前预览文案
  let previewText = ''
  if (checkItems.length) {
    if (decision === 'supplement') {
      previewText = `本次复核结论：退回补件 · 涉及 ${supplementItems.length} 项 · 补件说明：${
        supplementNote.trim() || '（待填写）'
      }`
    } else if (decision === 'reject') {
      previewText = '本次复核结论：否决申请 · 申请将进入「已拒绝」终态，不再流转'
    } else {
      previewText = `本次复核结论：通过 · 申请将流转至风控复核${
        confirmedRisk ? `（附 ${confirmedRisk} 项已确认风险提示）` : ''
      }`
    }
  }

  const legend = [
    {
      label: '规则冲突',
      color: '#eab308',
      count: items.filter((item) => item.kind === 'conflict').length
    },
    {
      label: '一致性差异',
      color: '#f97316',
      count: items.filter((item) => item.kind === 'consistency').length
    },
    {
      label: '低置信项',
      color: '#8b5cf6',
      count: items.filter((item) => item.kind === 'low').length
    },
    {
      label: '风险信号',
      color: '#ef4444',
      count: items.filter((item) => item.kind === 'risk').length
    },
    {
      label: '材料完整性',
      color: '#f59e0b',
      count: items.filter((item) => item.kind === 'completeness').length
    }
  ]

  return (
    <div className="page">
      <div className="crumb">
        <button className="link" onClick={() => navigate(`/report/${app.id}`)}>
          ← 返回报告
        </button>
      </div>

      <div className="page-head">
        <div>
          <h1>
            人工复核：<span className="mono">{app.id}</span>
            {report ? ` / 报告 ${report.version}` : ''}
          </h1>
          <div className="meta">
            复核人：{user?.full_name || app.manager}（普惠金融客户经理） · 申请金额 ¥{' '}
            {fmt(app.amount)} 万元
          </div>
        </div>
      </div>

      <div className="card review-summary">
        <div>
          <b>复核清单总计 {items.length} 项</b>
        </div>
        <div className="legend">
          {items.length ? (
            legend.map((entry) => (
              <span key={entry.label}>
                <i style={{ background: entry.color }} />
                {entry.label} {entry.count}
              </span>
            ))
          ) : (
            <span className="muted">{loading ? 'AI 预审报告加载中…' : '暂无可复核项'}</span>
          )}
        </div>
        <div className="review-progress">
          <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--slate-500)' }}>
            已核验 {done}/{checkItems.length}
          </span>
          <div className="track">
            <div
              className={`fill ${checkItems.length && done === checkItems.length ? 'done' : ''}`}
              style={{ width: `${checkItems.length ? (done / checkItems.length) * 100 : 0}%` }}
            />
          </div>
        </div>
      </div>

      <div>
        {items.length ? (
          items.map((item) => {
            const state = reviewState[item.id] || {}
            const options = KIND_OPTIONS[item.kind] || []
            const negative = state.action && NEGATIVE_ACTIONS.has(state.action)
            const isConfirmed =
              state.action === 'risk_confirmed' ||
              state.action === 'consistency_confirmed' ||
              state.action === 'conflict_confirmed'
            // 「确认有误，需补件」动作：文本框收集补件说明
            const isSupplementConfirm =
              state.action === 'need_supplement' ||
              state.action === 'risk_explain' ||
              state.action === 'consistency_explain'
            return (
              <section
                key={item.id}
                id={`review-field-${item.id}`}
                className={`card review-card type-${item.type}`}
              >
                <div className="rc-head">
                  <div className="rc-title">
                    <span className="num">{item.id}</span>
                    <h3>{item.title}</h3>
                    <span className={`tag tag-${item.tagCls}`}>{item.tag}</span>
                  </div>
                  <div style={{ display: 'flex', gap: 14, alignItems: 'center', flexWrap: 'wrap' }}>
                    {item.conf ? (
                      <div className="rc-conf">
                        AI 置信度 <b>{item.conf}</b>
                      </div>
                    ) : null}
                    {item.ref ? <div className="rc-ref">{item.ref}</div> : null}
                  </div>
                </div>

                {item.desc ? <div className="rc-desc">{item.desc}</div> : null}

                {item.kind === 'initial' ? null : (
                  <>
                    {item.checks ? (
                      <div className="checks">
                        <h5>人工核验勾选</h5>
                        {LOW_CHECK_LABELS.map((label) => (
                          <label key={label}>
                            <input
                              type="checkbox"
                              checked={(state.checks || []).includes(label)}
                              onChange={() => toggleCheck(item.id, label)}
                            />
                            {label}
                          </label>
                        ))}
                      </div>
                    ) : null}

                    <div className="rc-actions">
                      <div className="seg">
                        {options.map((option) => (
                          <label key={option.value} className={option.tone || ''}>
                            <input
                              type="radio"
                              name={`rv-${item.id}`}
                              checked={state.action === option.value}
                              onChange={() => selectAction(item, option.value)}
                            />
                            <span>{option.label}</span>
                          </label>
                        ))}
                      </div>
                      <textarea
                        className={errors[item.id] ? 'error' : ''}
                        placeholder={
                          isSupplementConfirm
                            ? '补件说明（必填）…'
                            : isConfirmed
                              ? '请输入核验理由（选填）…'
                              : negative
                                ? '请输入核验理由（必填）…'
                                : '补充说明（选填）…'
                        }
                        value={state.comment || ''}
                        onChange={(event) => {
                          updateItem(item.id, { comment: event.target.value })
                          clearError(item.id)
                        }}
                      />
                    </div>
                  </>
                )}
              </section>
            )
          })
        ) : (
          <div className="card">
            <div className="mat-empty">
              {loading ? 'AI 预审报告加载中…' : '暂无可复核项，等待 AI 预审报告生成。'}
            </div>
          </div>
        )}
      </div>

      <div className="card decision-bar" id="review-field-decision">
        <div className="decision-head">
          <div className="decision-suggest">
            系统建议结论：
            <b className={`decision-tag tone-${DECISION_META[derived].tone}`}>
              {DECISION_META[derived].label}
            </b>
            {overridden ? (
              <>
                <span className="decision-tag tone-override">已人工覆盖</span>
                <button className="link decision-reset" onClick={() => setManualDecision(null)}>
                  恢复建议
                </button>
              </>
            ) : null}
          </div>
          <div className="decision-saved">
            {savedAt ? `系统已于 ${formatTime(savedAt)} 自动保存草稿` : '复核结果尚未提交'}
          </div>
        </div>

        <div className="decision-body">
          <div className="seg decision-seg">
            {Object.entries(DECISION_META).map(([key, meta]) => (
              <label
                key={key}
                className={meta.tone}
                title={
                  key === 'reject' && !canReject
                    ? '仅当 AI 初判为「建议禁入」时可人工否决'
                    : undefined
                }
              >
                <input
                  type="radio"
                  name="review-decision"
                  checked={decision === key}
                  disabled={key === 'reject' && !canReject}
                  onChange={() => setManualDecision(key)}
                />
                <span>{meta.label}</span>
              </label>
            ))}
          </div>

          {decision === 'supplement' ? (
            <textarea
              className={`decision-note ${errors.note ? 'error' : ''}`}
              placeholder="补件说明（将展示在申请详情页，必填）…"
              value={supplementNote}
              onChange={(event) => {
                setSupplementNote(event.target.value)
                clearError('note')
              }}
            />
          ) : null}
          {overridden ? (
            <textarea
              className={`decision-note ${errors.decision ? 'error' : ''}`}
              placeholder="覆盖系统建议结论的理由（必填）…"
              value={decisionComment}
              onChange={(event) => {
                setDecisionComment(event.target.value)
                clearError('decision')
              }}
            />
          ) : null}
        </div>

        {previewText ? <div className="decision-preview">{previewText}</div> : null}

        <div className="decision-foot">
          <button
            className="btn btn-secondary"
            onClick={saveDraft}
            disabled={!items.length || submitting}
          >
            存为草稿
          </button>
          <button
            className="btn btn-primary"
            onClick={handleSubmit}
            disabled={!items.length || loading || submitting}
          >
            {submitting ? '提交中…' : '提交复核结果'}
          </button>
        </div>
      </div>
    </div>
  )
}
