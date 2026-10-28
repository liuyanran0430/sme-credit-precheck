import { useRef, useState } from 'react'
import { useApp } from '../context/AppContext'
import { uploadMaterials, generateReport } from '../api/applications'
import { formatSize, normalizeMaterial } from '../utils'
import Modal from '../components/Modal'

export default function UploadModal({ appId, onClose, onUploaded }) {
  const { setMaterials, toast } = useApp()
  const [files, setFiles] = useState([])
  const [note, setNote] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [phase, setPhase] = useState('upload')
  const fileInputRef = useRef(null)

  const handleClose = () => {
    if (!submitting) onClose()
  }

  const removeFile = (idx) => {
    setFiles((prev) => prev.filter((_, i) => i !== idx))
  }

  const handleFileChange = (e) => {
    const list = Array.from(e.target.files || [])
    const supported = list.filter((f) => /\.(pdf|jpg|jpeg|png)$/i.test(f.name))
    if (supported.length !== list.length) {
      toast('仅支持 PDF / JPG / PNG 格式文件')
    }

    const existingKeys = new Set(files.map((f) => `${f.name}-${f.size}`))
    const batchKeys = new Set()
    const deduped = []
    const duplicated = []

    supported.forEach((f) => {
      const key = `${f.name}-${f.size}`
      if (existingKeys.has(key) || batchKeys.has(key)) {
        duplicated.push(f.name)
        return
      }
      batchKeys.add(key)
      deduped.push({ file: f, name: f.name, size: f.size })
    })

    if (duplicated.length) {
      toast(`已忽略重复文件：${[...new Set(duplicated)].join('、')}`)
    }

    setFiles((prev) => [...prev, ...deduped])
    e.target.value = ''
  }

  const handleSubmit = async () => {
    if (submitting) return
    if (!files.length) {
      toast('请先选择要上传的文件')
      return
    }

    setSubmitting(true)
    setPhase('upload')
    try {
      const created = await uploadMaterials(appId, files.map((f) => f.file))
      setMaterials(appId, (prev) => [...prev, ...created.map(normalizeMaterial)])

      setPhase('analyze')
      await generateReport(appId)

      toast(`已上传 ${files.length} 份资料${note ? '（' + note + '）' : ''}，材料抽取与 AI 预审已完成`)
      setSubmitting(false)
      onUploaded?.()
      onClose()
    } catch (error) {
      console.error(error)
      setSubmitting(false)
      toast(error.message || '材料上传失败，请稍后重试')
    }
  }

  return (
    <Modal
      title={`上传补充资料 · ${appId}`}
      onClose={handleClose}
      footer={
        <>
          <button className="btn btn-secondary" onClick={handleClose} disabled={submitting}>
            取消
          </button>
          <button className="btn btn-primary" onClick={handleSubmit} disabled={submitting}>
            {submitting ? (phase === 'analyze' ? 'AI 预审中...' : '上传中...') : '确认上传'}
          </button>
        </>
      }
    >
      <div className="upload-zone" onClick={() => fileInputRef.current?.click()}>
        <div className="upload-icon">📎</div>
        <div className="t1">点击选择文件，或将文件拖拽到此处</div>
        <div className="t2">支持 PDF / JPG / PNG，可一次选择多份，单个文件不超过 20MB</div>
        <input
          ref={fileInputRef}
          type="file"
          accept=".pdf,.jpg,.jpeg,.png,application/pdf,image/jpeg,image/png"
          multiple
          hidden
          onChange={handleFileChange}
        />
      </div>
      <div className="upload-list">
        {files.map((f, i) => (
          <div className="upload-file" key={i}>
            <span>📄</span>
            <span className="name" title={f.name}>
              {f.name}
            </span>
            <span className="size">{formatSize(f.size)}</span>
            <span className="del" onClick={() => removeFile(i)} title="移除">
              ✕
            </span>
          </div>
        ))}
      </div>

      <div>
        <label>上传说明（选填）</label>
        <textarea
          rows={2}
          placeholder="例如：补充 2024 年 9 月对公流水与最新纳税截图，请核查"
          value={note}
          onChange={(e) => setNote(e.target.value)}
        />
      </div>

      <div className="hint">
        每份文件将作为一条独立材料记录，系统自动进行 OCR 抽取与一致性校验，抽取结果同步更新到材料清单与 AI
        预审报告。
      </div>
    </Modal>
  )
}
