import { useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useApp, normalizeApplication } from '../context/AppContext'
import { createApplication, uploadMaterials } from '../api/applications'
import { PRODUCTS } from '../constants'
import { formatSize, normalizeMaterial } from '../utils'
import Modal from '../components/Modal'

export default function NewAppModal({ onClose }) {
  const { addApp, setMaterials, toast } = useApp()
  const navigate = useNavigate()

  const [company, setCompany] = useState('')
  const [creditCode, setCreditCode] = useState('')
  const [amount, setAmount] = useState('')
  const [product, setProduct] = useState(PRODUCTS[0])
  const [files, setFiles] = useState([])
  const [submitting, setSubmitting] = useState(false)
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

    const parsedAmount = Number(amount)
    if (!company.trim()) {
      toast('请输入企业名称')
      return
    }
    if (!creditCode.trim()) {
      toast('请输入统一社会信用代码')
      return
    }
    if (!/^[0-9A-Z]{18}$/.test(creditCode.trim())) {
      toast('请输入18位统一社会信用代码（数字或大写字母）')
      return
    }
    if (!amount || Number.isNaN(parsedAmount) || parsedAmount <= 0) {
      toast('请输入正确的贷款金额')
      return
    }
    if (!files.length) {
      toast('请至少上传一份申请材料')
      return
    }
    const oversized = files.find((f) => f.size > 20 * 1024 * 1024)
    if (oversized) {
      toast(`文件 ${oversized.name} 超过 20MB`)
      return
    }

    setSubmitting(true)
    try {
      const created = await createApplication({
        company_name: company.trim(),
        credit_code: creditCode.trim(),
        amount: parsedAmount,
        product
      })

      const newId = created.app_no
      addApp(normalizeApplication(created))

      let uploadError = ''
      let mats = files.map((f) => ({
        name: f.name,
        category: 'other',
        ver: 'v1.0',
        update: '今天',
        status: 'pending',
        files: 1
      }))
      try {
        const uploaded = await uploadMaterials(newId, files.map((f) => f.file))
        mats = uploaded.map(normalizeMaterial)
      } catch (error) {
        console.error(error)
        uploadError = error.message || '材料上传失败'
      }
      setMaterials(newId, mats)

      if (uploadError) {
        toast(`申请 ${newId} 已创建，材料上传失败：${uploadError}`)
      } else {
        toast(`申请 ${newId} 已提交，已进入材料检查状态`)
      }

      setSubmitting(false)
      onClose()
      // 提交后直接进入该申请的详情页，查看材料检查情况
      navigate(`/detail/${newId}`)
    } catch (error) {
      setSubmitting(false)
      toast(error.message || '提交申请失败，请稍后重试')
    }
  }

  return (
    <Modal
      title="提交新申请"
      onClose={handleClose}
      footer={
        <>
          <button className="btn btn-secondary" onClick={handleClose} disabled={submitting}>
            取消
          </button>
          <button className="btn btn-primary" onClick={handleSubmit} disabled={submitting}>
            {submitting ? '提交中...' : '提交申请'}
          </button>
        </>
      }
    >
      <div>
        <label>
          企业名称 <span className="req">*</span>
        </label>
        <input
          type="text"
          placeholder="请输入企业全称，例如：上海德信精密机械有限公司"
          maxLength={60}
          value={company}
          onChange={(e) => setCompany(e.target.value)}
        />
      </div>

      <div>
        <label>
          统一社会信用代码 <span className="req">*</span>
        </label>
        <input
          type="text"
          placeholder="请输入18位统一社会信用代码"
          maxLength={18}
          value={creditCode}
          onChange={(e) => setCreditCode(e.target.value.toUpperCase())}
        />
      </div>

      <div>
        <label>
          贷款金额（万元） <span className="req">*</span>
        </label>
        <input
          type="number"
          min="0"
          step="0.01"
          placeholder="请输入贷款金额，例如：120"
          value={amount}
          onChange={(e) => setAmount(e.target.value)}
        />
      </div>

      <div>
        <label>
          贷款类型 <span className="req">*</span>
        </label>
        <select value={product} onChange={(e) => setProduct(e.target.value)}>
          {PRODUCTS.map((p) => (
            <option key={p} value={p}>
              {p}
            </option>
          ))}
        </select>
      </div>

      <div>
        <label>
          上传申请材料 <span className="req">*</span>
        </label>
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
      </div>

      <div className="hint">提交后系统将自动进行 OCR 抽取与 AI 预审，申请将进入「待材料检查」状态。</div>
    </Modal>
  )
}
