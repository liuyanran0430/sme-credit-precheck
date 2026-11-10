import { useEffect, useMemo, useState } from 'react'
import { useApp } from '../context/AppContext'
import { fetchReport, submitRiskDecision } from '../api/applications'
import Modal from '../components/Modal'
import type { ApplicationStatus, Report, RiskLevel, RiskReviewItemPayload, RiskSignal } from '../types'

type DecisionKey = 'pass' | 'reject' | 'deny'

const DECISIONS: { key: DecisionKey; label: string; icon: string; cls: string }[] = [
  { key: 'pass', label: '通过', icon: '✓', cls: 'pass' },
  { key: 'reject', label: '退回补件', icon: '↩', cls: 'reject' },
  { key: 'deny', label: '拒绝', icon: '✕', cls: 'deny' }
]

// 前端选项键 → 申请状态流转
const DECISION_STATUS_MAP: Record<DecisionKey, ApplicationStatus> = {
  pass: 'approved',
  reject: 'supplement',
  deny: 'rejected'
}
const DECISION_STATUS_LABEL: Record<DecisionKey, string> = {
  pass: '已审批',
  reject: '待补件',
  deny: '已否决'
}

const LEVEL_ORDER: Record<RiskLevel, number> = { high: 0, medium: 1, low: 2 }
const LEVEL_LABEL: Record<string, string> = { high: '高风险', medium: '中风险', low: '低风险' }

interface RiskDraft {
  action?: 'confirm' | 'exclude'
  comment: string
}

interface ProcessModalProps {
  appId: string
  onClose: () => void
}

export default function ProcessModal({ appId, onClose }: ProcessModalProps) {
  const { updateApp, toast } = useApp()
  const [opinion, setOpinion] = useState('')
  const [opinionError, setOpinionError] = useState(false)
  const [decision, setDecision] = useState<DecisionKey | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [report, setReport] = useState<Report | null>(null)
  const [loading, setLoading] = useState(true)
  const [drafts, setDrafts] = useState<Record<string, RiskDraft>>({})
  const [riskError, setRiskError] = useState(false)

  // 加载 AI 预审报告，取出风险信号供逐项复核
  useEffect(() => {
    let cancelled = false
    fetchReport(appId)
      .then((data) => {
        if (!cancelled) setReport(data)
      })
      .catch(() => {
        if (!cancelled) setReport(null)
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [appId])

  // 风险信号按严重度排序（高 → 中 → 低）
  const risks = useMemo(() => {
    const signals = report?.risk_signals || []
    return [...signals].sort(
      (a, b) => (LEVEL_ORDER[a.level] ?? 9) - (LEVEL_ORDER[b.level] ?? 9)
    )
  }, [report])

  const reviewedCount = risks.filter((s) => drafts[s.signal_id]?.action).length
  const allReviewed = risks.length === 0 || reviewedCount === risks.length

  const setAction = (signal: RiskSignal, action: 'confirm' | 'exclude') => {
    setDrafts((prev) => ({
      ...prev,
      [signal.signal_id]: { ...prev[signal.signal_id], action, comment: prev[signal.signal_id]?.comment || '' }
    }))
    setRiskError(false)
  }

  const setComment = (signal: RiskSignal, comment: string) => {
    setDrafts((prev) => ({
      ...prev,
      [signal.signal_id]: { ...prev[signal.signal_id], comment }
    }))
  }

  const buildItems = (): RiskReviewItemPayload[] =>
    risks.map((s) => ({
      signal_id: s.signal_id,
      title: s.title,
      action: drafts[s.signal_id]?.action as 'confirm' | 'exclude',
      comment: drafts[s.signal_id]?.comment.trim() || null
    }))

  const handleSubmit = async () => {
    if (submitting) return
    if (risks.length > 0 && !allReviewed) {
      setRiskError(true)
      toast(`还有 ${risks.length - reviewedCount} 项风险信号未复核`)
      return
    }
    if (!opinion.trim()) {
      setOpinionError(true)
      toast('请填写风控复核意见（必填）')
      return
    }
    if (!decision) {
      toast('请选择决策结论')
      return
    }

    const decObj = DECISIONS.find((d) => d.key === decision)
    if (!decObj) return
    setSubmitting(true)
    try {
      await submitRiskDecision(appId, {
        decision,
        opinion: opinion.trim(),
        items: risks.length > 0 ? buildItems() : null
      })
      updateApp(appId, { status: DECISION_STATUS_MAP[decision] })
      toast(`已提交「${decObj.label}」，状态已流转至${DECISION_STATUS_LABEL[decision]}`)
      onClose()
    } catch (error) {
      toast(error instanceof Error ? error.message : '风控决策提交失败')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Modal
      title={`风控复核决策 · ${appId}`}
      onClose={onClose}
      wide
      footer={
        <>
          <button className="btn btn-secondary" onClick={onClose}>
            取消
          </button>
          <button className="btn btn-primary" onClick={handleSubmit}>
            提交复核结论
          </button>
        </>
      }
    >
      <div className="hint">提示：处理前请务必研读客户经理复核记录，系统已自动关联相关风险预警信号。</div>

      <div className="risk-review-block">
        <div className="risk-review-head">
          <label>
            风险信号逐项复核{risks.length > 0 ? <span className="req"> *</span> : null}
          </label>
          {risks.length > 0 ? (
            <span className={`risk-review-progress${allReviewed ? ' done' : ''}`}>
              已复核 {reviewedCount}/{risks.length}
            </span>
          ) : null}
        </div>
        {loading ? (
          <div className="quote">正在加载 AI 预审报告…</div>
        ) : risks.length === 0 ? (
          <div className="quote">该申请未检测到风险信号</div>
        ) : (
          <div className={`risk-review-list${riskError ? ' has-error' : ''}`}>
            {risks.map((signal, idx) => {
              const draft = drafts[signal.signal_id] || { comment: '' }
              const detail = signal.evidence?.detail || ''
              return (
                <div
                  key={signal.signal_id}
                  className={`risk-item level-${signal.level}${draft.action ? ` ${draft.action}` : ''}`}
                >
                  <div className="risk-item-head">
                    <span className="risk-item-title">
                      {idx + 1}. {signal.title}
                    </span>
                    <span className={`risk-level-tag lv-${signal.level}`}>
                      {LEVEL_LABEL[signal.level] || signal.level}
                    </span>
                  </div>
                  {detail || signal.suggestion ? (
                    <div className="risk-item-desc">
                      {detail ? `提示：${detail}` : ''}
                      {signal.suggestion ? ` 建议：${signal.suggestion}` : ''}
                    </div>
                  ) : null}
                  <div className="risk-item-actions">
                    <label className={`risk-choice confirm${draft.action === 'confirm' ? ' sel' : ''}`}>
                      <input
                        type="radio"
                        name={`risk-${signal.signal_id}`}
                        checked={draft.action === 'confirm'}
                        onChange={() => setAction(signal, 'confirm')}
                      />
                      确认风险
                    </label>
                    <label className={`risk-choice exclude${draft.action === 'exclude' ? ' sel' : ''}`}>
                      <input
                        type="radio"
                        name={`risk-${signal.signal_id}`}
                        checked={draft.action === 'exclude'}
                        onChange={() => setAction(signal, 'exclude')}
                      />
                      误报排除
                    </label>
                    <input
                      className="risk-comment"
                      type="text"
                      placeholder="复核备注（可选）"
                      value={draft.comment}
                      onChange={(e) => setComment(signal, e.target.value)}
                    />
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </div>

      <div>
        <label>
          风控复核意见 <span className="req">*</span>
        </label>
        <textarea
          rows={4}
          className={opinionError ? 'error' : ''}
          placeholder="请输入详细的风险评估结论及决策理由（必填）..."
          value={opinion}
          onChange={(e) => {
            setOpinion(e.target.value)
            if (opinionError) setOpinionError(false)
          }}
        />
      </div>

      <div>
        <label>决策结论</label>
        <div className="decision-grid">
          {DECISIONS.map((d) => (
            <button
              key={d.key}
              className={`decision ${d.cls} ${decision === d.key ? 'sel' : ''}`}
              onClick={() => setDecision(d.key)}
            >
              <span className="ic">{d.icon}</span>
              {d.label}
            </button>
          ))}
        </div>
      </div>
    </Modal>
  )
}
