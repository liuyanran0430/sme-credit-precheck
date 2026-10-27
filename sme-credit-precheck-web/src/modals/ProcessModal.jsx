import { useState } from 'react'
import { useApp } from '../context/AppContext'
import Modal from '../components/Modal'

const DECISIONS = [
  { key: 'pass', label: '通过', icon: '✓', cls: 'pass' },
  { key: 'cond', label: '有条件通过', icon: '☑', cls: 'cond' },
  { key: 'reject', label: '退回补件', icon: '↩', cls: 'reject' },
  { key: 'more', label: '补充调查', icon: '🔍', cls: 'more' }
]

export default function ProcessModal({ appId, onClose }) {
  const { updateApp, toast } = useApp()
  const [opinion, setOpinion] = useState('')
  const [mitigation, setMitigation] = useState('')
  const [decision, setDecision] = useState(null)

  const handleSubmit = () => {
    if (!opinion.trim()) {
      toast('请填写风控复核意见')
      return
    }
    if (!decision) {
      toast('请选择决策结论')
      return
    }

    const decObj = DECISIONS.find((d) => d.key === decision)
    updateApp(appId, (a) => ({
      ...a,
      archived: true,
      status: decision === 'reject' ? 'supplement' : a.status,
      sla: decision === 'reject' ? '补件剩 3 天' : a.sla,
      slaLevel: decision === 'reject' ? 'ok' : a.slaLevel
    }))

    toast(
      `已提交「${decObj.label}」，状态已流转至${decision === 'reject' ? '待补件' : '已复核转审批'}`
    )
    onClose()
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
        <label>风控复核意见</label>
        <textarea
          rows={4}
          placeholder="请输入详细的风险评估结论及决策理由..."
          value={opinion}
          onChange={(e) => setOpinion(e.target.value)}
        />
      </div>

      <div>
        <label>风险缓释条件（选填）</label>
        <input
          type="text"
          placeholder="例如：追加配偶担保 / 降低额度至 30 万..."
          value={mitigation}
          onChange={(e) => setMitigation(e.target.value)}
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
