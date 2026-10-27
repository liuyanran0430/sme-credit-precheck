import { useState } from 'react'
import Modal from '../components/Modal'
import PreviewModal from './PreviewModal'
import { useApp } from '../context/AppContext'
import { updateMaterialCategory } from '../api/applications'
import { MATERIAL_CATEGORIES } from '../constants'

// 按文件扩展名区分图片与文档
function isImage(name) {
  const ext = (name.split('.').pop() || '').toLowerCase()
  return ['png', 'jpg', 'jpeg'].includes(ext)
}

function fileIcon(name) {
  return isImage(name) ? '🖼️' : '📄'
}

/**
 * 修改分类弹窗：按类别分区展示全部材料文件，
 * 图标可点击预览，右侧下拉框修改类别。
 */
export default function CategoryModal({ appId, materials, onClose, onSaved }) {
  const { toast } = useApp()
  const [changes, setChanges] = useState({}) // materialId -> 新类别
  const [saving, setSaving] = useState(false)
  const [preview, setPreview] = useState(null)
  const changedCount = Object.keys(changes).length

  // 应用下拉框选择后的类别，实时重新分组
  const effectiveCategory = (m) => changes[m.id] || m.category || 'other'
  // 「其他」分区置顶展示，便于优先处理待人工分类的文件
  const sections = [
    ...MATERIAL_CATEGORIES.filter((c) => c.key === 'other'),
    ...MATERIAL_CATEGORIES.filter((c) => c.key !== 'other')
  ].map((c) => ({
    ...c,
    files: materials.filter((m) => effectiveCategory(m) === c.key)
  }))

  const handleChange = (m, category) => {
    setChanges((prev) => {
      const next = { ...prev }
      if (category === (m.category || 'other')) {
        delete next[m.id]
      } else {
        next[m.id] = category
      }
      return next
    })
  }

  const handleSave = async () => {
    setSaving(true)
    let okCount = 0
    let failed = false
    for (const [id, category] of Object.entries(changes)) {
      try {
        await updateMaterialCategory(appId, id, category)
        okCount += 1
      } catch (err) {
        console.error(err)
        failed = true
      }
    }
    setSaving(false)
    if (okCount) {
      toast(`已更新 ${okCount} 个文件的类别`)
      onSaved?.()
      onClose()
    }
    if (failed) {
      toast('部分文件类别保存失败，请重试')
    }
  }

  return (
    <>
      <Modal
        wide
        title="修改分类"
        onClose={onClose}
        footer={
          <div className="cat-foot">
            <span className="muted">
              {changedCount ? `已选择 ${changedCount} 个文件的新类别` : '单击文件图标可预览内容'}
            </span>
            <div className="actions-right">
              <button className="btn btn-secondary" onClick={onClose} disabled={saving}>
                取消
              </button>
              <button
                className="btn btn-primary"
                onClick={handleSave}
                disabled={saving || !changedCount}
              >
                {saving ? '保存中…' : '保存修改'}
              </button>
            </div>
          </div>
        }
      >
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
                      <div
                        className={`cat-file ${changes[m.id] ? 'changed' : ''}`}
                        key={m.id}
                      >
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
                          <div
                            className={`cat-file-reason ${m.reason ? '' : 'empty'}`}
                            title={m.reason || '暂无 AI 分类依据'}
                          >
                            {m.reason || '暂无 AI 分类依据'}
                          </div>
                          <div className="cat-file-foot">
                            <select
                              className="cat-select"
                              value={effectiveCategory(m)}
                              onChange={(e) => handleChange(m, e.target.value)}
                            >
                              {MATERIAL_CATEGORIES.map((c) => (
                                <option key={c.key} value={c.key}>
                                  {c.label}
                                </option>
                              ))}
                            </select>
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
          <div className="mat-empty">暂无材料文件，请先上传材料。</div>
        )}
      </Modal>

      {preview ? (
        <PreviewModal appId={appId} material={preview} onClose={() => setPreview(null)} />
      ) : null}
    </>
  )
}
