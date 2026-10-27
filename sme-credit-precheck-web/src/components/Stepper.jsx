import { STEPS } from '../utils'

/**
 * 流程步骤条
 * @param {number} active 当前步骤索引（0 开始）
 */
export default function Stepper({ active }) {
  return (
    <div className="stepper">
      {STEPS.map((s, i) => (
        <div key={s} className={`step ${i < active ? 'done' : ''} ${i === active ? 'current' : ''}`}>
          <div className="dot">{i < active ? '✓' : i + 1}</div>
          <div className="step-label">{s}</div>
        </div>
      ))}
    </div>
  )
}
