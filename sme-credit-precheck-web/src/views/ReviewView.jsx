import { useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useApp } from '../context/AppContext'
import { fmt } from '../utils'

export default function ReviewView() {
  const { id } = useParams()
  const { apps, updateApp, toast } = useApp()
  const navigate = useNavigate()

  const app = apps.find((a) => a.id === id) || apps[0]
  const [reviewState, setReviewState] = useState({})

  if (!app) return <div className="page">申请不存在</div>

  const items = []
  const done = Object.keys(reviewState).length

  const handleChange = (itemId, value) => {
    setReviewState((prev) => ({ ...prev, [itemId]: value }))
  }

  const handleSubmit = () => {
    if (!items.length) {
      toast('暂无可复核项，无法提交复核结果')
      return
    }
    if (done < items.length) {
      toast(`还有 ${items.length - done} 项复核任务未完成，请全部核实后提交。`)
      return
    }
    updateApp(app.id, {
      status: 'risk',
      sla: '风控处理中',
      slaLevel: 'muted',
      upgradeReason: '人工复核后升级'
    })
    toast('复核结果已成功提交，状态已流转至风控复核。')
    setTimeout(() => navigate('/risk'), 900)
  }

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
          </h1>
          <div className="meta">
            复核人：{app.manager}（普惠金融客户经理） · 申请金额 ¥ {fmt(app.amount)} 万元 · 截止{' '}
            {app.submitDate}（{app.sla}）
          </div>
        </div>
      </div>

      <div className="card review-summary">
        <div>
          <b>复核清单总计 {items.length} 项</b>
        </div>
        <div className="legend">
          <span className="muted">暂无可复核项</span>
        </div>
        <div className="review-progress">
          <div className="track">
            <div
              className={`fill ${items.length && done === items.length ? 'done' : ''}`}
              style={{ width: `${items.length ? (done / items.length) * 100 : 0}%` }}
            />
          </div>
          <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--slate-500)' }}>
            {done}/{items.length}
          </span>
        </div>
      </div>

      <div>
        {items.length ? (
          items.map((item) => (
          <section key={item.id} className={`card review-card type-${item.type}`}>
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

            {item.checks ? (
              <div className="checks">
                <h5>人工必填核验项</h5>
                <label>
                  <input type="checkbox" /> 已核对原件
                </label>
                <label>
                  <input type="checkbox" /> 数据正确无误
                </label>
                <label>
                  <input type="checkbox" /> 需补件 / 重拍
                </label>
              </div>
            ) : null}

            <div className="rc-actions">
              <div className="seg">
                <label>
                  <input
                    type="radio"
                    name={`rv-${item.id}`}
                    checked={reviewState[item.id] === 'adopt'}
                    onChange={() => handleChange(item.id, 'adopt')}
                  />
                  <span>采纳结论</span>
                </label>
                <label>
                  <input
                    type="radio"
                    name={`rv-${item.id}`}
                    checked={reviewState[item.id] === 'modify'}
                    onChange={() => handleChange(item.id, 'modify')}
                  />
                  <span>修改</span>
                </label>
                <label className="reject">
                  <input
                    type="radio"
                    name={`rv-${item.id}`}
                    checked={reviewState[item.id] === 'reject'}
                    onChange={() => handleChange(item.id, 'reject')}
                  />
                  <span>推翻</span>
                </label>
              </div>
              <textarea placeholder="请输入复核理由（必填）..." />
            </div>
          </section>
          ))
        ) : (
          <div className="card">
            <div className="mat-empty">暂无可复核项，等待 AI 预审报告生成。</div>
          </div>
        )}
      </div>

      <div className="card action-bar">
        <div style={{ fontSize: 12, color: 'var(--slate-500)' }}>复核结果尚未提交</div>
        <div className="actions-right">
          <button className="btn btn-secondary" onClick={() => toast('暂无可保存的复核草稿')} disabled={!items.length}>
            存为草稿
          </button>
          <button className="btn btn-primary" onClick={handleSubmit} disabled={!items.length}>
            提交复核结果
          </button>
        </div>
      </div>
    </div>
  )
}
