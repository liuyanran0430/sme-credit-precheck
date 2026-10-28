import { useEffect, useState } from 'react'
import { fetchManualReviews, fetchMaterials, fetchReport } from '../api/applications'
import Modal from '../components/Modal'
import PreviewModal from './PreviewModal'
import ReportSections from '../components/ReportSections'
import { useApp } from '../context/AppContext'
import { MATERIAL_CATEGORIES } from '../constants'
import { normalizeMaterial } from '../utils'

const DECISION_LABELS = {
  pass: '通过，转风控复核',
  conditional: '有条件通过',
  reject: '退回补件',
  further: '补充调查',
  deny: '否决申请'
}

// 按文件扩展名区分图片与文档
function isImage(name) {
  const ext = (name.split('.').pop() || '').toLowerCase()
  return ['png', 'jpg', 'jpeg'].includes(ext)
}

function fileIcon(name) {
  return isImage(name) ? '🖼️' : '📄'
}

/**
 * 查看弹窗：左侧展示 AI 预审报告（与报告页格式一致）与客户经理复核意见，
 * 右侧按类别分区展示材料文件（只读，单击图标可预览完整文件）。
 */
export default function PackageModal({ app, onClose }) {
  const { getMaterials, setMaterials } = useApp()
  const [report, setReport] = useState(null)
  const [reviews, setReviews] = useState([])
  const [loading, setLoading] = useState(true)
  const [preview, setPreview] = useState(null)
  const materials = getMaterials(app.id)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    Promise.allSettled([
      fetchReport(app.id).then((data) => {
        if (!cancelled) setReport(data)
      }),
      fetchManualReviews(app.id).then((data) => {
        if (!cancelled) setReviews(Array.isArray(data) ? data : [])
      }),
      fetchMaterials(app.id).then((rows) => {
        if (!cancelled) setMaterials(app.id, rows.map(normalizeMaterial))
      })
    ]).finally(() => {
      if (!cancelled) setLoading(false)
    })
    return () => {
      cancelled = true
    }
  }, [app.id, setMaterials])

  const latestReview = reviews[0] || null

  // 按固定分类顺序分组，「其他」自然排在底部
  const sections = MATERIAL_CATEGORIES.map((c) => ({
    ...c,
    files: materials.filter((m) => (m.category || 'other') === c.key)
  }))

  return (
    <>
      <Modal
        xlarge
        title={
          <>
            预审报告与材料 · {app.id}
            <span className="cat-title-hint cat-title-hint-muted">单击图标查看完整文件</span>
          </>
        }
        onClose={onClose}
        footer={
          <button className="btn btn-secondary" onClick={onClose}>
            关闭
          </button>
        }
      >
        <div className="pkg-split">
          {/* 左侧：AI 预审报告 + 客户经理复核意见 */}
          <div className="pkg-col-report">
            {loading ? (
              <div className="pkg-loading">预审报告加载中…</div>
            ) : report ? (
              <>
                <ReportSections report={report} />

                <section className="card section-card">
                  <div className="section-head">
                    <h2>客户经理复核意见</h2>
                  </div>
                  <div className="section-body">
                    {latestReview ? (
                      <div>
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
                      <div className="mat-empty">暂无客户经理复核意见</div>
                    )}
                  </div>
                </section>
              </>
            ) : (
              <div className="pkg-empty">预审报告尚未生成</div>
            )}
          </div>

          {/* 右侧：材料清单（只读） */}
          <div className="pkg-col-materials">
            <section className="card section-card">
              <div className="section-head">
                <h2>材料清单（{materials.length}）</h2>
              </div>
              <div className="section-body">
                {materials.length ? (
                  <div className="cat-scroll">
                    {sections.map((s) => (
                      <section className="cat-section" key={s.key}>
                        <div className="cat-section-head">
                          <span className="cat-section-icon">{s.icon}</span>
                          <span className="cat-section-label">{s.label}</span>
                          <span className="cat-section-count">{s.files.length} 份</span>
                        </div>
                        {s.files.length ? (
                          <div className="cat-files">
                            {s.files.map((m) => (
                              <div className="cat-file" key={m.id}>
                                <button
                                  type="button"
                                  className={`cat-thumb ${isImage(m.name) ? 'image' : 'pdf'}`}
                                  onClick={() => setPreview(m)}
                                  title={`点击预览 ${m.name}`}
                                >
                                  {fileIcon(m.name)}
                                </button>
                                <div className="cat-file-main">
                                  <div className="cat-file-name" title={m.name}>
                                    {m.name}
                                  </div>
                                </div>
                              </div>
                            ))}
                          </div>
                        ) : (
                          <div className="cat-empty">暂无文件</div>
                        )}
                      </section>
                    ))}
                  </div>
                ) : (
                  <div className="mat-empty">暂无材料文件。</div>
                )}
              </div>
            </section>
          </div>
        </div>
      </Modal>

      {preview ? (
        <PreviewModal appId={app.id} material={preview} onClose={() => setPreview(null)} />
      ) : null}
    </>
  )
}
