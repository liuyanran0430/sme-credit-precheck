import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useApp } from '../context/AppContext'
import { fetchCompleteness, fetchReport } from '../api/applications'
import { MATERIAL_CATEGORIES } from '../constants'

const CONCLUSION_LABELS = {
  pass: '通过',
  attention: '需关注',
  forbidden: '建议禁入',
  manual: '待人工核验'
}

// 一致性校验三态展示
const CONSISTENCY_STATUS = {
  pass: { label: '一致', cls: 'ok' },
  fail: { label: '不一致', cls: 'fail' },
  uncertain: { label: '待人工', cls: 'uncertain' }
}

const SEVERITY_LABELS = { high: '高', medium: '中', low: '低', none: '—' }

const SOURCE_LABELS = MATERIAL_CATEGORIES.reduce(
  (acc, item) => ({ ...acc, [item.key]: item.label }),
  { application: '申请信息' }
)

const EMPTY_CELL = { textAlign: 'center', padding: 36, color: '#94a3b8' }

export default function ReportView() {
  const { id } = useParams()
  const { apps, toast } = useApp()
  const navigate = useNavigate()

  const app = apps.find((a) => a.id === id) || apps[0]

  const [report, setReport] = useState(null)
  const [completeness, setCompleteness] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!app?.id) return undefined
    let cancelled = false
    setLoading(true)
    setError('')
    ;(async () => {
      try {
        // 优先使用已落库的预审报告，未生成时实时分析材料完整性
        const data = await fetchReport(app.id)
        if (cancelled) return
        setReport(data)
        const result = data?.completeness || (await fetchCompleteness(app.id))
        if (!cancelled) setCompleteness(result)
      } catch (err) {
        if (!cancelled) setError(err.message || '材料完整性分析失败')
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [app?.id])

  if (!app) return <div className="page">申请不存在</div>

  const requiredCats = (completeness?.categories || []).filter((c) => c.required)
  const satisfiedCount = requiredCats.filter((c) => c.count > 0).length
  const totalCount = requiredCats.length || 5
  const allRequired = satisfiedCount === totalCount
  const otherCount =
    (completeness?.categories || []).find((c) => c.category === 'other')?.count || 0

  const checks = report?.consistency?.checks || []
  const failCount = checks.filter((c) => c.status === 'fail').length
  const uncertainCount = checks.filter((c) => c.status === 'uncertain').length

  return (
    <div className="page">
      <div className="crumb">
        <button className="link" onClick={() => navigate(`/detail/${app.id}`)}>
          ← 返回申请详情
        </button>
      </div>

      <div className="page-head">
        <div>
          <h1>
            AI 预审报告：<span className="mono">{app.id}</span>
          </h1>
          <div className="meta">
            {report
              ? `AI 预审结论：${CONCLUSION_LABELS[report.conclusion] || report.conclusion} · ${report.summary || ''}`
              : '尚未生成 AI 预审报告'}
          </div>
        </div>
        <div className="actions-right">
          <button className="btn btn-secondary" onClick={() => toast('暂无可导出的预审报告')}>
            导出预审包
          </button>
          <button className="btn btn-primary" onClick={() => navigate(`/review/${app.id}`)}>
            进入人工复核
          </button>
        </div>
      </div>

      {/* 一、材料完整性结论 */}
      <section className="card section-card">
        <div className="section-head">
          <h2>一、材料完整性结论</h2>
        </div>
        <div className="section-body">
          {loading ? (
            <div className="mat-empty">正在分析材料完整性…</div>
          ) : error ? (
            <div className="mat-empty">{error}</div>
          ) : (
            <div className="completeness">
              <div className="completeness-head">
                <span>必备材料齐全度</span>
                <span className={allRequired ? 'ok' : 'warn'}>
                  {allRequired ? '✓ ' : '! '}
                  {satisfiedCount}/{totalCount} 类
                </span>
              </div>
              <div className="completeness-bar">
                {requiredCats.map((c) => (
                  <i
                    key={c.category}
                    className={c.count > 0 ? '' : 'missing'}
                    title={`${c.label}：${c.count} 份`}
                  />
                ))}
              </div>
              <div className="completeness-labels">
                {requiredCats.map((c) => (
                  <span key={c.category} title={`${c.label}：${c.count} 份`}>
                    {c.label}
                  </span>
                ))}
              </div>

              {otherCount > 0 && (
                <div className="completeness-extra">
                  其他类材料 {otherCount} 份（不计入必备材料）
                </div>
              )}

              {(completeness?.issues || []).length > 0 && (
                <ul className="completeness-issues">
                  {completeness.issues.map((issue, idx) => (
                    <li key={idx}>{issue.message}</li>
                  ))}
                </ul>
              )}
            </div>
          )}
        </div>
      </section>

      {/* 二、一致性校验 */}
      <section className="card section-card">
        <div className="section-head">
          <h2>二、一致性校验</h2>
          <span className={failCount ? 'warn' : 'ok'}>
            {checks.length === 0
              ? '待生成'
              : failCount
                ? `${failCount} 项不一致`
                : uncertainCount
                  ? `${uncertainCount} 项待人工`
                  : '全部一致'}
          </span>
        </div>
        <div className="section-body">
          {checks.length === 0 ? (
            <div className="consistency-placeholder">
              尚未生成一致性校验结果，完成材料分类与 AI 预审后将在此展示企业名称、
              统一社会信用代码、期间与金额勾稽等比对结果。
            </div>
          ) : (
            <div className="check-list">
              {checks.map((check, idx) => {
                const state = CONSISTENCY_STATUS[check.status] || CONSISTENCY_STATUS.uncertain
                return (
                  <div className={`check-item ${state.cls}`} key={`${check.check_item}-${idx}`}>
                    <div className="check-top">
                      <span className="check-name">{check.check_item}</span>
                      <span className="check-tags">
                        <span className={`check-badge ${state.cls}`}>{state.label}</span>
                        <span className="check-severity">
                          严重度 {SEVERITY_LABELS[check.severity] || check.severity}
                        </span>
                      </span>
                    </div>
                    {(check.values || []).length > 0 && (
                      <div className="check-values">
                        {check.values.slice(0, 4).map((item, valueIdx) => (
                          <span className="check-value" key={valueIdx}>
                            <b>{SOURCE_LABELS[item.source] || item.source}</b>
                            {item.value}
                          </span>
                        ))}
                        {check.values.length > 4 && (
                          <span className="check-more">
                            等 {check.values.length} 条取值
                          </span>
                        )}
                      </div>
                    )}
                    {check.suggestion && <div className="check-tip">{check.suggestion}</div>}
                  </div>
                )
              })}
            </div>
          )}
        </div>
      </section>

      {/* 三、准入规则匹配 */}
      <section className="card section-card">
        <div className="section-head">
          <h2>三、准入规则匹配（逐条依据）</h2>
        </div>
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>规则项</th>
                <th>客户值</th>
                <th>规则要求</th>
                <th>结论</th>
                <th>依据条款</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td colSpan={5} style={EMPTY_CELL}>
                  暂无准入规则匹配结果
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      {/* 三、风险信号汇总 */}
      <section className="card section-card">
        <div className="section-head">
          <h2>四、风险信号汇总（按维度 / 优先级）</h2>
        </div>
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>维度</th>
                <th>信号</th>
                <th>优先级</th>
                <th>置信度</th>
                <th>证据引用</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td colSpan={5} style={EMPTY_CELL}>
                  暂无风险信号
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      {/* 四、低置信 / 规则冲突项 */}
      <section className="card section-card conflict">
        <div className="section-head">
          <h2>五、低置信 / 规则冲突项（强制人工核验）</h2>
        </div>
        <div className="section-body">
          <div className="mat-empty">暂无低置信或规则冲突项。</div>
        </div>
      </section>
    </div>
  )
}
