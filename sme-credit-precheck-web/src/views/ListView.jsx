import { useState, Fragment } from 'react'
import { useNavigate } from 'react-router-dom'
import { useApp, normalizeApplication } from '../context/AppContext'
import { useAuth } from '../context/AuthContext'
import { STATUS_MAP, PRODUCTS } from '../constants'
import { fmt } from '../utils'
import { deleteApplication } from '../api/applications'
import NewAppModal from '../modals/NewAppModal'
import EditAppModal from '../modals/EditAppModal'

const STAT_ITEMS = [
  { key: 'check', label: '待材料检查', color: '#0891b2' },
  { key: 'supplement', label: '待补件', color: '#d97706' },
  { key: 'manual', label: '待人工核验', color: '#7c3aed' },
  { key: 'risk', label: '待风控复核', color: '#dc2626' }
]

export default function ListView() {
  const { apps, appsLoading, setApps, toast } = useApp()
  const { user } = useAuth()
  const navigate = useNavigate()

  const [filters, setFilters] = useState({ status: '', product: '', search: '' })
  const [openAi, setOpenAi] = useState({})
  const [showNewApp, setShowNewApp] = useState(false)
  const [editingApp, setEditingApp] = useState(null)

  const handleDelete = async (a) => {
    const ok = window.confirm(
      `确定删除申请 ${a.id}（${a.company}）吗？\n` +
        '其关联的 AI 报告、复核记录、材料及上传文件将一并删除，且不可恢复。'
    )
    if (!ok) return
    try {
      await deleteApplication(a.id)
      setApps((prev) => prev.filter((x) => x.id !== a.id))
      toast(`申请 ${a.id} 已删除`)
    } catch (err) {
      toast(err.message || '删除失败，请稍后重试')
    }
  }

  const rows = apps.filter((a) => {
    if (filters.status && a.status !== filters.status) return false
    if (filters.product && a.product !== filters.product) return false
    if (filters.search) {
      const kw = filters.search.toLowerCase()
      if (!a.id.toLowerCase().includes(kw) && !a.company.toLowerCase().includes(kw)) return false
    }
    return true
  })

  const counts = {}
  apps.forEach((a) => (counts[a.status] = (counts[a.status] || 0) + 1))

  // 待处理 = 待材料检查 + 待补件 + 待人工核验
  const pendingCount = (counts.check || 0) + (counts.supplement || 0) + (counts.manual || 0)

  const mainActionOf = (a) => {
    if (a.status === 'supplement')
      return (
        <button
          className="btn btn-primary btn-sm act-btn"
          onClick={() => navigate(`/detail/${a.id}`)}
        >
          上传资料
        </button>
      )
    if (a.status === 'manual')
      return (
        <button className="btn btn-primary btn-sm act-btn" onClick={() => navigate(`/review/${a.id}`)}>
          去核验
        </button>
      )
    if (a.status === 'risk')
      return (
        <button className="btn btn-primary btn-sm act-btn" onClick={() => navigate(`/detail/${a.id}`)}>
          查看申请
        </button>
      )
    if (a.status === 'check')
      return (
        <button className="btn btn-primary btn-sm act-btn" onClick={() => navigate(`/detail/${a.id}`)}>
          去检查
        </button>
      )
    // 已审批 / 已拒绝 等终态：去查看
    return (
      <button className="btn btn-primary btn-sm act-btn" onClick={() => navigate(`/detail/${a.id}`)}>
        去查看
      </button>
    )
  }

  const toggleAi = (id) => {
    setOpenAi((prev) => ({ ...prev, [id]: !prev[id] }))
  }

  const setFilter = (key, val) => setFilters((prev) => ({ ...prev, [key]: val }))

  const toggleStat = (key) => {
    setFilters((prev) => ({ ...prev, status: prev.status === key ? '' : key }))
  }

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1>申请列表</h1>
          <div className="meta">
            客户经理：{user?.full_name || '—'} · 待处理 {pendingCount}
          </div>
        </div>
        <div className="actions-right">
          <button className="btn btn-primary" onClick={() => setShowNewApp(true)}>
            ＋ 提交申请
          </button>
        </div>
      </div>

      <div className="filter-bar card">
        <select value={filters.status} onChange={(e) => setFilter('status', e.target.value)}>
          <option value="">当前状态：全部</option>
          <option value="check">待材料检查</option>
          <option value="supplement">待补件</option>
          <option value="manual">待人工核验</option>
          <option value="risk">待风控复核</option>
          <option value="rejected">已拒绝</option>
        </select>
        <select value={filters.product} onChange={(e) => setFilter('product', e.target.value)}>
          <option value="">产品：全部</option>
          {PRODUCTS.map((p) => (
            <option key={p} value={p}>
              {p}
            </option>
          ))}
        </select>
        <input
          type="text"
          placeholder="搜索申请号 / 企业名称"
          value={filters.search}
          onChange={(e) => setFilter('search', e.target.value)}
        />
      </div>

      <div className="stats-bar">
        {STAT_ITEMS.map((s) => (
          <div
            key={s.key}
            className={`stat-chip ${filters.status === s.key ? 'active' : ''}`}
            onClick={() => toggleStat(s.key)}
          >
            <span className="dot" style={{ background: s.color }} />
            <span>{s.label}</span>
            <b>{counts[s.key] || 0}</b>
          </div>
        ))}
      </div>

      <div className="card">
        <div className="table-wrap list-table-wrap">
          <table className="list-table">
            <thead>
              <tr>
                <th className="col-id">申请编号</th>
                <th>企业名称</th>
                <th className="col-credit">统一社会信用代码</th>
                <th className="col-product">信用贷类型</th>
                <th className="col-amount">申请金额</th>
                <th className="col-status">当前状态</th>
                <th className="col-action">操作</th>
              </tr>
            </thead>
            <tbody>
              {appsLoading ? (
                <tr>
                  <td colSpan={7} style={{ textAlign: 'center', padding: 44, color: '#94a3b8' }}>
                    正在从数据库加载申请列表...
                  </td>
                </tr>
              ) : rows.length === 0 ? (
                <tr>
                  <td colSpan={7} style={{ textAlign: 'center', padding: 44, color: '#94a3b8' }}>
                    没有符合条件的申请
                  </td>
                </tr>
              ) : (
                rows.map((a) => {
                  const s = STATUS_MAP[a.status] || { label: a.status || '未知状态', cls: 'slate' }
                  return (
                    <Fragment key={a.id}>
                      <tr className="data-row">
                        <td className="col-id">
                          <span className="id-link" onClick={() => navigate(`/detail/${a.id}`)}>
                            {a.id}
                          </span>
                        </td>
                        <td className="company-cell" title={a.company}>
                          {a.company}
                        </td>
                        <td className="col-credit">
                          <span className="credit-code">{a.creditCode || '—'}</span>
                        </td>
                        <td className="col-product">{a.product}</td>
                        <td className="col-amount">{fmt(a.amount)} 万元</td>
                        <td className="col-status">
                          <span className={`tag tag-${s.cls}`}>{s.label}</span>
                          {a.status === 'supplement' && a.supplementSource === 'risk' ? (
                            <span className="tag tag-src-risk">风控退回</span>
                          ) : a.status === 'supplement' && a.supplementSource === 'manual' ? (
                            <span className="tag tag-src-manual">复核退回</span>
                          ) : null}
                        </td>
                        <td className="col-action">
                          <div className="act-group">
                            {mainActionOf(a)}
                            <button
                              className="btn btn-secondary btn-sm act-btn"
                              onClick={() => setEditingApp(a)}
                            >
                              编辑
                            </button>
                            <button
                              className="btn btn-danger-ghost btn-sm act-btn"
                              onClick={() => handleDelete(a)}
                            >
                              删除
                            </button>
                            <button className="btn btn-secondary btn-sm act-btn" onClick={() => toggleAi(a.id)}>
                              {openAi[a.id] ? '收起摘要' : 'AI 摘要'}
                            </button>
                          </div>
                        </td>
                      </tr>
                      {openAi[a.id] ? (
                        <tr className="ai-row open">
                          <td colSpan={7}>
                            <div className="ai-box">
                              <span className="ai-badge">AI 摘要</span>
                              <div>
                                {a.summary}
                                {a.status === 'risk' ? <span className="risk-flag">风险信号</span> : ''}
                                <button className="link" onClick={() => navigate(`/report/${a.id}`)}>
                                  [查看详情]
                                </button>
                              </div>
                            </div>
                          </td>
                        </tr>
                      ) : null}
                    </Fragment>
                  )
                })
              )}
            </tbody>
          </table>
        </div>
      </div>

      <div className="pager">
        <span>共 {rows.length} 条</span>
        <span>共 {apps.length} 条记录 · 第 1 / 1 页</span>
      </div>

      {showNewApp ? <NewAppModal onClose={() => setShowNewApp(false)} /> : null}
      {editingApp ? (
        <EditAppModal
          app={editingApp}
          onClose={() => setEditingApp(null)}
          onSaved={(updated) =>
            setApps((prev) =>
              prev.map((item) =>
                item.id === updated.app_no ? { ...item, ...normalizeApplication(updated) } : item
              )
            )
          }
        />
      ) : null}
    </div>
  )
}
