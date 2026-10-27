import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useApp } from '../context/AppContext'
import { fmt } from '../utils'
import ProcessModal from '../modals/ProcessModal'

export default function RiskView() {
  const { apps } = useApp()
  const navigate = useNavigate()
  const [selected, setSelected] = useState(null)
  const [processId, setProcessId] = useState(null)

  const rows = apps.filter((a) => a.status === 'risk' && !a.archived)
  const cur = rows.find((r) => r.id === selected) || rows[0] || null

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1>风控复核队列</h1>
          <div className="meta">风控人员 · 待处理 {rows.length} 件</div>
        </div>
      </div>

      <div className="card">
        <div className="table-wrap">
          <table className="risk-table">
            <thead>
              <tr>
                <th>优先级</th>
                <th>申请编号</th>
                <th>企业名称</th>
                <th style={{ textAlign: 'right' }}>申请金额</th>
                <th>升级原因</th>
                <th>等待时长</th>
                <th style={{ textAlign: 'center' }}>操作</th>
              </tr>
            </thead>
            <tbody>
              {rows.length === 0 ? (
                <tr>
                  <td colSpan={7} style={{ textAlign: 'center', padding: 44, color: '#94a3b8' }}>
                    队列已清空，暂无待处理升级件
                  </td>
                </tr>
              ) : (
                rows.map((a) => (
                  <tr
                    key={a.id}
                    className={cur && cur.id === a.id ? 'selected' : ''}
                    onClick={() => setSelected(a.id)}
                  >
                    <td>
                      <span className={`pri ${a.amount >= 200 ? 'pri-high' : 'pri-mid'}`}>
                        {a.amount >= 200 ? '高' : '中'}
                      </span>
                    </td>
                    <td style={{ fontWeight: 600, color: 'var(--slate-800)' }}>{a.id}</td>
                    <td>{a.company}</td>
                    <td className="num-right">{fmt(a.amount)} 万元</td>
                    <td>{a.upgradeReason}</td>
                    <td>—</td>
                    <td style={{ textAlign: 'center' }}>
                      <button
                        className="btn btn-primary btn-sm"
                        onClick={(e) => {
                          e.stopPropagation()
                          setProcessId(a.id)
                        }}
                      >
                        处理
                      </button>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>

      {cur ? (
        <div className="card risk-detail">
          <div className="risk-detail-head">
            <div>
              <h2>
                选中件摘要：{cur.id} <span className="tag tag-slate">{cur.company}</span>
              </h2>
              <div className="risk-reason">⚠ 升级原因：{cur.upgradeReason}</div>
            </div>
            <div className="actions-right">
              <button
                className="btn btn-secondary btn-sm"
                onClick={() => navigate(`/detail/${cur.id}`)}
              >
                查看完整预审包
              </button>
              <button className="btn btn-primary btn-sm" onClick={() => setProcessId(cur.id)}>
                立即处理
              </button>
            </div>
          </div>
          <div className="risk-detail-grid">
            <div className="info-box">
              <h4>关联信号</h4>
              <div className="info-row">
                <span>流水月均还款额占收入</span>
                <span className="v warn">{cur.dti == null ? '—' : `${cur.dti}%`}</span>
              </div>
              <div className="info-row">
                <span>流水与合同金额偏离</span>
                <span className="v danger">{cur.gap == null ? '—' : `${cur.gap}%`}</span>
              </div>
              <div className="info-row">
                <span>预估通过率</span>
                <span className="v">{cur.passRate == null ? '—' : `${cur.passRate}%`}</span>
              </div>
            </div>
            <div className="info-box">
              <h4>客户经理复核意见</h4>
              <div className="quote">暂无客户经理复核意见</div>
            </div>
          </div>
        </div>
      ) : null}

      {processId ? <ProcessModal appId={processId} onClose={() => setProcessId(null)} /> : null}
    </div>
  )
}
