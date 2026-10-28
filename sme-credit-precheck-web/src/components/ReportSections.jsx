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

// 准入规则三态展示（结论列胶囊标签）
const RULE_STATUS = {
  pass: { label: '符合', icon: '✓', cls: 'pass' },
  fail: { label: '不符合', icon: '✕', cls: 'fail' },
  uncertain: { label: '存疑', icon: '⚠', cls: 'uncertain' }
}

const RISK_LEVEL = {
  high: { label: '高', cls: 'fail' },
  medium: { label: '中', cls: 'uncertain' },
  low: { label: '低', cls: 'ok' }
}

const CONFLICT_TYPES = {
  low_confidence: '分类低置信',
  rule_conflict: '规则证据不足',
  data_inconsistent: '数据不一致'
}

const SOURCE_LABELS = MATERIAL_CATEGORIES.reduce(
  (acc, item) => ({ ...acc, [item.key]: item.label }),
  { application: '申请信息' }
)

const EMPTY_CELL = { textAlign: 'center', padding: 36, color: '#94a3b8' }

export { CONCLUSION_LABELS }

/**
 * AI 预审报告五段内容（材料完整性 / 一致性校验 / 准入规则匹配 / 风险信号 / 冲突项），
 * 供报告页与预审报告弹窗复用，保证展示格式一致。
 */
export default function ReportSections({ report, loading = false, error = '', onReview }) {
  const completeness = report?.completeness || null
  const requiredCats = (completeness?.categories || []).filter((c) => c.required)
  const satisfiedCount = requiredCats.filter((c) => c.satisfied).length
  const totalCount = requiredCats.length || 5
  const allRequired = satisfiedCount === totalCount
  const otherRequired = requiredCats.some((c) => c.category === 'other')
  const otherCount =
    (completeness?.categories || []).find((c) => c.category === 'other')?.count || 0

  const checks = report?.consistency?.checks || []
  const failCount = checks.filter((c) => c.status === 'fail').length
  const uncertainCount = checks.filter((c) => c.status === 'uncertain').length

  const ruleMatching = report?.rule_results
  const ruleItems = ruleMatching?.rules || []
  const riskSignals = report?.risk_signals || []
  const conflicts = report?.conflicts || []

  return (
    <>
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
                    className={c.satisfied ? '' : 'missing'}
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

              {otherCount > 0 && !otherRequired && (
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
                          <span className="check-more">等 {check.values.length} 条取值</span>
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
          {ruleMatching?.total_count > 0 && (
            <span className="check-severity">
              评分 {ruleMatching.score} 分 · {ruleMatching.level}·
              {ruleMatching.level_label || '—'} · 强规则未通过 {ruleMatching.hard_fail_count} 条 ·
              弱规则未通过 {ruleMatching.soft_fail_count} 条 · 待人工 {ruleMatching.uncertain_count} 条
            </span>
          )}
        </div>
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>规则项</th>
                <th>客户值</th>
                <th>规则要求</th>
                <th style={{ textAlign: 'center' }}>结论</th>
                <th>依据条款</th>
              </tr>
            </thead>
            <tbody>
              {ruleItems.length === 0 ? (
                <tr>
                  <td colSpan={5} style={EMPTY_CELL}>
                    暂无准入规则匹配结果
                  </td>
                </tr>
              ) : (
                ruleItems.map((rule) => {
                  const state = RULE_STATUS[rule.result] || RULE_STATUS.uncertain
                  return (
                    <tr key={rule.rule_id}>
                      <td>
                        <b>{rule.rule_name}</b>
                        <div className="mono">
                          {rule.rule_id} · {rule.kind === 'hard' ? '强规则' : '弱规则'}
                        </div>
                      </td>
                      <td>{rule.actual || '—'}</td>
                      <td>{rule.expected || '—'}</td>
                      <td style={{ textAlign: 'center' }}>
                        <span className={`rule-verdict ${state.cls}`}>
                          <span className="rule-verdict-icon">{state.icon}</span>
                          {state.label}
                        </span>
                      </td>
                      <td>{rule.detail || '—'}</td>
                    </tr>
                  )
                })
              )}
            </tbody>
          </table>
        </div>
      </section>

      {/* 四、风险信号汇总 */}
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
                <th>处理建议</th>
                <th>证据引用</th>
              </tr>
            </thead>
            <tbody>
              {riskSignals.length === 0 ? (
                <tr>
                  <td colSpan={5} style={EMPTY_CELL}>
                    暂无风险信号
                  </td>
                </tr>
              ) : (
                riskSignals.map((signal) => {
                  const level = RISK_LEVEL[signal.level] || RISK_LEVEL.medium
                  return (
                    <tr key={signal.signal_id}>
                      <td>{signal.category}</td>
                      <td>{signal.title}</td>
                      <td>
                        <span className={`check-badge ${level.cls}`}>{level.label}</span>
                      </td>
                      <td>{signal.suggestion || '—'}</td>
                      <td>
                        {signal.evidence?.source
                          ? `${SOURCE_LABELS[signal.evidence.source] || signal.evidence.source}：`
                          : ''}
                        {signal.evidence?.detail || '—'}
                      </td>
                    </tr>
                  )
                })
              )}
            </tbody>
          </table>
        </div>
      </section>

      {/* 五、低置信 / 规则冲突项 */}
      <section className="card section-card conflict">
        <div className="section-head">
          <h2>五、低置信 / 规则冲突项（强制人工核验）</h2>
          {onReview ? (
            <button className="btn btn-primary conflict-review-btn" onClick={onReview}>
              逐项核验 →
            </button>
          ) : null}
        </div>
        <div className="section-body">
          {conflicts.length === 0 ? (
            <div className="mat-empty">暂无低置信或规则冲突项。</div>
          ) : (
            <div className="check-list">
              {conflicts.map((item, idx) => (
                <div className="check-item uncertain" key={`${item.type}-${idx}`}>
                  <div className="check-top">
                    <span className="check-name">
                      {CONFLICT_TYPES[item.type] || item.type}
                      {item.rules?.length ? ` · ${item.rules.join('/')}` : ''}
                    </span>
                    <span className="check-tags">
                      {item.source && <span className="check-value">{item.source}</span>}
                      {item.field && <span className="check-value">{item.field}</span>}
                    </span>
                  </div>
                  <div className="check-tip">{item.reason}</div>
                  {item.value && <div className="check-tip">涉及取值：{item.value}</div>}
                </div>
              ))}
            </div>
          )}
        </div>
      </section>
    </>
  )
}
