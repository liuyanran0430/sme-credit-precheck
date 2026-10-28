import { useState } from 'react'
import { useApp } from '../context/AppContext'
import { submitRiskDecision } from '../api/applications'
import Modal from '../components/Modal'

const DECISIONS = [
  { key: 'pass', label: '通过', icon: '✓', cls: 'pass' },
  { key: 'reject', label: '退回补件', icon: '↩', cls: 'reject' },
  { key: 'deny', label: '拒绝', icon: '✕', cls: 'deny' }
]

// 前端选项键 → 申请状态流转
const DECISION_STATUS_MAP = { pass: 'approved', reject: 'supplement', deny: 'rejected' }
const DECISION_STATUS_LABEL = { pass: '已审批', reject: '待补件', deny: '已否决' }

export default function ProcessModal({ appId, onClose }) {
  const { updateApp, toast } = useApp()
  const [opinion, setOpinion] = useState('')
  const [opinionError, setOpinionError] = useState(false)
  const [decision, setDecision] = useState(null)
  const [submitting, setSubmitting] = useState(false)

  const handleSubmit = async () => {
    if (submitting) return
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
    setSubmitting(true)
    try {
      await submitRiskDecision(appId, {
        decision,
        opinion: opinion.trim()
      })
      updateApp(appId, { status: DECISION_STATUS_MAP[decision] })
      toast(`已提交「${decObj.label}」，状态已流转至${DECISION_STATUS_LABEL[decision]}`)
      onClose()
    } catch (error) {
      toast(error.message || '风控决策提交失败')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Modal
      title={`风控复核决策 · ${appId}`}
      onClose={onClose}
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
