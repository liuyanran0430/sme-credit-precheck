import { useEffect, useState, Fragment } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useApp, normalizeApplication } from '../context/AppContext'
import { STATUS_MAP, MATERIAL_CATEGORIES } from '../constants'
import {
  fetchApplication,
  fetchMaterials,
  materialFileUrl,
  deleteMaterial
} from '../api/applications'
import { fmt, matStatusText, normalizeMaterial, STEP_IDX } from '../utils'
import Stepper from '../components/Stepper'
import UploadModal from '../modals/UploadModal'
import PreviewModal from '../modals/PreviewModal'
import CategoryModal from '../modals/CategoryModal'
import ConfirmModal from '../components/ConfirmModal'

function groupStatus(files) {
  if (!files.length) return 'none'
  if (files.some((f) => f.status === 'pending')) return 'pending'
  if (files.some((f) => f.status === 'low')) return 'low'
  return 'ok'
}

export default function DetailView() {
  const { id } = useParams()
  const { apps, getMaterials, setMaterials, updateApp, toast } = useApp()
  const navigate = useNavigate()
  const [showUpload, setShowUpload] = useState(false)

  const app = apps.find((a) => a.id === id) || apps[0]
  const [expanded, setExpanded] = useState({})
  const [preview, setPreview] = useState(null)
  const [showCategory, setShowCategory] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(null) // 待删除的材料对象
  const [deleting, setDeleting] = useState(false)

  // 重新拉取材料清单（修改分类后调用）
  const reloadMaterials = () => {
    fetchMaterials(app.id)
      .then((rows) => setMaterials(app.id, rows.map(normalizeMaterial)))
      .catch((error) => console.error(error))
  }

  // 刷新申请状态（AI 预审完成后进度会推进）
  const refreshApp = () => {
    fetchApplication(app.id)
      .then((row) => updateApp(app.id, normalizeApplication(row)))
      .catch((error) => console.error(error))
  }

  // 打开材料文件预览（页内弹窗）
  const openFile = (m) => {
    if (!m || !m.id) {
      toast('该文件暂无法预览')
      return
    }
    setPreview(m)
  }

  // 删除材料文件（应用内确认弹窗）
  const handleDeleteFile = (m) => {
    if (!m || !m.id) return
    setConfirmDelete(m)
  }

  const handleConfirmDelete = async () => {
    const m = confirmDelete
    if (!m) return
    setDeleting(true)
    try {
      await deleteMaterial(app.id, m.id)
      toast(`文件「${m.name}」已删除，已重新执行 AI 预审`)
      setConfirmDelete(null)
      reloadMaterials()
      // 删除后预审会重新判定，缺件时申请状态回到「待补件」
      refreshApp()
    } catch (err) {
      toast(err.message || '删除失败，请稍后重试')
    } finally {
      setDeleting(false)
    }
  }

  // 单文件类别直接打开预览；多文件类别展开/收起文件列表
  const handleView = (g) => {
    if (!g.files.length) {
      toast(`${g.label}暂无文件`)
      return
    }
    if (g.files.length === 1) {
      openFile(g.files[0])
      return
    }
    setExpanded((prev) => ({ ...prev, [g.key]: !prev[g.key] }))
  }

  useEffect(() => {
    if (!app) return
    let cancelled = false
    fetchMaterials(app.id)
      .then((rows) => {
        if (!cancelled) setMaterials(app.id, rows.map(normalizeMaterial))
      })
      .catch((error) => {
        if (!cancelled) console.error(error)
      })
    // 同步最新申请状态，确保预审后的进度条正确
    fetchApplication(app.id)
      .then((row) => {
        if (!cancelled) updateApp(app.id, normalizeApplication(row))
      })
      .catch((error) => {
        if (!cancelled) console.error(error)
      })
    return () => {
      cancelled = true
    }
  }, [app?.id, setMaterials, updateApp])

  if (!app) return <div className="page">申请不存在</div>

  const s = STATUS_MAP[app.status] || { label: app.status || '未知状态', cls: 'slate' }
  const mats = getMaterials(app.id)
  const groups = MATERIAL_CATEGORIES.map((c) => ({
    ...c,
    files: mats.filter((m) => (m.category || 'other') === c.key)
  }))
  const filled = groups.filter((g) => g.files.length).length

  // 前五类为必备材料（不含「其他」），缺件时提示具体类别
  const missingCats = groups
    .filter((g) => g.key !== 'other' && !g.files.length)
    .map((g) => g.label)

  return (
    <div className="page">
      <div className="crumb">
        <button className="link" onClick={() => navigate('/')}>
          ← 返回申请列表
        </button>
      </div>

      <div className="page-head">
        <div>
          <h1>
            <span className="mono">{app.id}</span>
            <span className="company">{app.company}</span>
            <span className={`tag tag-${s.cls}`}>{s.label}</span>
          </h1>
          <div className="meta">
            提交于 {app.submitDate} · 产品：{app.product}
          </div>
        </div>
        <div className="actions-right">
          <button className="btn btn-primary" onClick={() => setShowUpload(true)}>
            ＋ 上传资料
          </button>
        </div>
      </div>

      <Stepper active={STEP_IDX[app.status] ?? 3} />

      <div className="stat-grid">
        <div className="card stat-card">
          <div className="stat-label">申请金额 & 产品</div>
          <div className="stat-value">
            ¥ {fmt(app.amount)} 万 <span className="pill">{app.product}</span>
          </div>
        </div>
        <div className="card stat-card">
          <div className="stat-label">客户经理 & 提交日期</div>
          <div className="stat-value-sm">
            {app.manager} · {app.submitDate}
          </div>
        </div>
        <div className="card stat-card">
          <div className="stat-label">材料合规 / 补件</div>
          {missingCats.length ? (
            <div className="stat-value-sm compliance-miss" title={missingCats.join('、')}>
              缺件：{missingCats.join('、')}
            </div>
          ) : (
            <div className="stat-value-sm compliance-ok">材料合规</div>
          )}
        </div>
      </div>

      <div className="detail-main">
        <aside className="card panel mat-panel">
          <div className="panel-head">
            <h3>
              材料清单{' '}
              <span className="muted">
                {filled} / {MATERIAL_CATEGORIES.length} 类 · {mats.length} 份
              </span>
            </h3>
            <button
              className="btn btn-secondary btn-sm"
              onClick={() => setShowCategory(true)}
              disabled={!mats.length}
            >
              修改分类
            </button>
          </div>
          <div className="panel-body">
            {groups.map((g) => {
              const status = groupStatus(g.files)
              const expandedFiles = expanded[g.key] && g.files.length > 1
              return (
                <Fragment key={g.key}>
                  <div
                    className={`mat-item ${status === 'low' ? 'low' : ''} ${
                      status === 'pending' ? 'pending' : ''
                    } ${status === 'none' ? 'none' : ''}`}
                  >
                    <div className="mat-icon">{g.icon}</div>
                    <div className="mat-info">
                      <div className="mat-name-row">
                        <span className="mat-name" title={g.label}>
                          {g.label}
                        </span>
                        <span className={`mat-status ${status}`}>{matStatusText({ status })}</span>
                      </div>
                      <div className="mat-ver">
                        {g.files.length ? `共 ${g.files.length} 份 · 更新 ${g.files[0].update}` : '暂无文件'}
                      </div>
                    </div>
                    <div className="mat-right">
                      <button
                        className="btn btn-ghost btn-xs"
                        onClick={() => handleView(g)}
                        disabled={!g.files.length}
                      >
                        {expandedFiles ? '收起' : '查看'}
                      </button>
                      <button
                        className="btn btn-danger-ghost btn-xs"
                        onClick={() => g.files.length === 1 && handleDeleteFile(g.files[0])}
                        disabled={g.files.length !== 1}
                        title={
                          g.files.length > 1 ? '多份文件请展开后按文件删除' : undefined
                        }
                      >
                        删除
                      </button>
                    </div>
                  </div>
                  {expandedFiles
                    ? g.files.map((f) => (
                        <div
                          key={f.id}
                          className="mat-item pending"
                          style={{ paddingLeft: 44 }}
                        >
                          <div className="mat-icon">📄</div>
                          <div className="mat-info">
                            <div className="mat-name" title={f.name}>
                              {f.name}
                            </div>
                            <div className="mat-ver">{f.update}</div>
                          </div>
                          <div className="mat-right">
                            <span className={`mat-status ${f.status}`}>{matStatusText(f)}</span>
                            <button
                              className="btn btn-ghost btn-xs"
                              onClick={() => openFile(f)}
                            >
                              查看
                            </button>
                            <button
                              className="btn btn-danger-ghost btn-xs"
                              onClick={() => handleDeleteFile(f)}
                            >
                              删除
                            </button>
                          </div>
                        </div>
                      ))
                    : null}
                </Fragment>
              )
            })}
          </div>
        </aside>

        <section className="card panel">
          <div className="panel-head">
            <h3>AI 预审摘要</h3>
            <div className="panel-meta">暂无预审报告</div>
          </div>
          <div className="panel-body">
            <div className="mat-empty">该申请尚未生成 AI 预审报告。</div>
          </div>
          <div className="panel-foot right">
            <button className="btn btn-secondary" onClick={() => navigate(`/report/${app.id}`)}>
              查看完整预审报告
            </button>
            <button className="btn btn-primary" onClick={() => navigate(`/review/${app.id}`)}>
              进入人工复核
            </button>
          </div>
        </section>
      </div>

      {showUpload ? (
        <UploadModal
          appId={app.id}
          onClose={() => setShowUpload(false)}
          onUploaded={() => {
            reloadMaterials()
            refreshApp()
          }}
        />
      ) : null}
      {preview ? (
        <PreviewModal appId={app.id} material={preview} onClose={() => setPreview(null)} />
      ) : null}
      {showCategory ? (
        <CategoryModal
          appId={app.id}
          materials={mats}
          onClose={() => setShowCategory(false)}
          onSaved={() => {
            reloadMaterials()
            refreshApp()
          }}
        />
      ) : null}
      {confirmDelete ? (
        <ConfirmModal
          title="删除材料"
          message={`确定删除文件「${confirmDelete.name}」吗？\n对应的材料记录与上传文件将一并删除，且不可恢复。`}
          confirmText="删除"
          danger
          busy={deleting}
          onConfirm={handleConfirmDelete}
          onCancel={() => setConfirmDelete(null)}
        />
      ) : null}
    </div>
  )
}
