import { STEPS } from '../utils'

/**
 * 流程步骤条
 * @param {number} active 当前步骤索引（0 开始）
 * @param {number} rejectedAt 被拒绝的步骤索引（-1 表示无），该节点图标变为叉子并标注已拒绝
 */
export default function Stepper({ active, rejectedAt = -1 }) {
  return (
    <div className="stepper">
      {STEPS.map((s, i) => {
        const isRejected = i === rejectedAt
        const done = i < active && !isRejected
        const current = i === active && !isRejected
        return (
          <div
            key={s}
            className={`step ${done ? 'done' : ''} ${current ? 'current' : ''} ${
              isRejected ? 'rejected' : ''
            }`}
          >
            <div className="dot">{isRejected ? '✕' : done ? '✓' : i + 1}</div>
            <div className="step-label">{isRejected ? `${s}（不通过）` : s}</div>
          </div>
        )
      })}
    </div>
  )
}
