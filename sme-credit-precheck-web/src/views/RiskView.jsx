import { useEffect, useMemo, useState } from 'react'
import { useApp } from '../context/AppContext'
import { fetchManualReviews, fetchReport } from '../api/applications'
import { fmt } from '../utils'
import ProcessModal from '../modals/ProcessModal'
import PackageModal from '../modals/PackageModal'

// 复核结论标签（与后端 ReviewDecision 枚举对应）
const DECISION_LABELS = {
  pass: '通过，转风控复核',
  conditional: '有条件通过',
  reject: '退回补件',
  further: '补充调查',
  deny: '否决申请'
}

export default function RiskView() {
  const { apps } = useApp()
  const [selected, setSelected] = useState(null)
  const [processId, setProcessId] = useState(null)
  const [packageId, setPackageId] = useState(null)
  const [reviews, setReviews] = useState([])
  const [report, setReport] = useState(null)

  const rows = apps.filter((a) => a.status === 'risk' && !a.archived)
  const cur = rows.find((r) => r.id === selected) || rows[0] || null
  const curId = cur?.id

  // 选中件变化时拉取客户经理人工复核记录，取最新一条展示
  useEffect(() => {
    if (!curId) {
      setReviews([])
      return undefined
    }
    let cancelled = false
    fetchManualReviews(curId)
      .then((data) => {
        if (!cancelled) setReviews(Array.isArray(data) ? data : [])
      })
      .catch(() => {
        if (!cancelled) setReviews([])
      })
    return () => {
      cancelled = true
    }
  }, [curId])

  // 选中件变化时拉取最新 AI 预审报告，用于统计符合/存疑/冲突项数量
  useEffect(() => {
    if (!curId) {
      setReport(null)
      return undefined
    }
    let cancelled = false
    fetchReport(curId)
      .then((data) => {
        if (!cancelled) setReport(data)
      })
      .catch(() => {
        if (!cancelled) setReport(null)
      })
    return () => {
      cancelled = true
    }
  }, [curId])

  const latestReview = reviews[0] || null

  // 准入规则三态与冲突项统计
  const ruleStats = useMemo(() => {
    const rules = Array.isArray(report?.rule_results?.rules) ? report.rule_results.rules : []
    const conflicts = Array.isArray(report?.conflicts) ? report.conflicts : []
    return {
      pass: rules.filter((r) => r.result === 'pass').length,
      uncertain: rules.filter((r) => r.result === 'uncertain').length,
      conflicts: conflicts.length
    }
  }, [report])

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
                <th>AI 预审结果</th>
                <th>申请编号</th>
                <th>企业名称</th>
                <th>统一社会信用代码</th>
                <th>产品类型</th>
                <th style={{ textAlign: 'right' }}>申请金额</th>
                <th style={{ textAlign: 'center' }}>操作</th>
              </tr>
            </thead>
            <tbody>
              {rows.length === 0 ? (
                <tr>
                  <td colSpan={7} style={{ textAlign: 'center', padding: 44, color: '#94a3b8' }}>
                    暂无待处理申请
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
                      {a.conclusion === 'pass' ? (
                        <span className="pri pri-mid">通过</span>
                      ) : (
                        <span className="pri pri-high">不通过</span>
                      )}
                    </td>
                    <td style={{ fontWeight: 600, color: 'var(--slate-800)' }}>{a.id}</td>
                    <td>
                      {a.company}
                      {a.riskReturned ? (
                        <span className="tag tag-src-risk" title="曾被风控退回补件，材料补齐后回流">
                          补件已补齐
                        </span>
                      ) : null}
                    </td>
                    <td style={{ fontFamily: 'monospace', fontSize: 12 }}>{a.creditCode || '—'}</td>
                    <td>{a.product || '—'}</td>
                    <td className="num-right">{fmt(a.amount)} 万元</td>
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
              <div className="risk-reason">
                ✓ {ruleStats.pass} 项符合，⚠ {ruleStats.uncertain} 项存疑，✕ {ruleStats.conflicts} 项冲突
              </div>
            </div>
            <div className="actions-right">
              <button
                className="btn btn-secondary btn-sm"
                onClick={() => setPackageId(cur.id)}
              >
                查看预审报告和材料清单
              </button>
              <button className="btn btn-primary btn-sm" onClick={() => setProcessId(cur.id)}>
                立即处理
              </button>
            </div>
          </div>
          <div className="risk-detail-grid">
            <div className="info-box">
              <h4>AI 预审摘要</h4>
              <div className="info-row">
                <span>预审结论</span>
                <span className="v">
                  {cur.conclusion === 'pass' ? (
                    <span className="pri pri-mid">通过</span>
                  ) : (
                    <span className="pri pri-high">不通过</span>
                  )}
                </span>
              </div>
              <div className="risk-ai-summary" title={cur.summary}>
                {cur.summary || '暂无 AI 预审摘要'}
              </div>
            </div>
            <div className="info-box">
              <h4>客户经理复核意见</h4>
              {latestReview ? (
                <div className="review-opinion">
                  <div className="info-row">
                    <span>复核人</span>
                    <span className="v">{latestReview.reviewer}</span>
                  </div>
                  <div className="info-row">
                    <span>复核结论</span>
                    <span className="v">
                      {DECISION_LABELS[latestReview.decision] || latestReview.decision}
                    </span>
                  </div>
                  <div className="info-row">
                    <span>决策说明</span>
                    <span className="v" title={latestReview.comment || '无'}>
                      {latestReview.comment || '无'}
                    </span>
                  </div>
                </div>
              ) : (
                <div className="quote">暂无客户经理复核意见</div>
              )}
            </div>
          </div>
        </div>
      ) : null}

      {processId ? <ProcessModal appId={processId} onClose={() => setProcessId(null)} /> : null}
      {packageId
        ? (() => {
            const pkgApp = rows.find((r) => r.id === packageId)
            return pkgApp ? (
              <PackageModal app={pkgApp} onClose={() => setPackageId(null)} />
            ) : null
          })()
        : null}
    </div>
  )
}
