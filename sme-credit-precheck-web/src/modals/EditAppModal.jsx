import { useMemo, useState } from 'react'
import { useApp } from '../context/AppContext'
import { updateApplication } from '../api/applications'
import { PRODUCTS } from '../constants'
import Modal from '../components/Modal'

export default function EditAppModal({ app, onClose, onSaved }) {
  const { toast } = useApp()

  const initial = useMemo(
    () => ({
      company: app?.company || '',
      creditCode: app?.creditCode || '',
      amount: app?.amount != null ? String(app.amount) : '',
      product: app?.product || PRODUCTS[0]
    }),
    [app]
  )

  const [company, setCompany] = useState(initial.company)
  const [creditCode, setCreditCode] = useState(initial.creditCode)
  const [amount, setAmount] = useState(initial.amount)
  const [product, setProduct] = useState(initial.product)
  const [submitting, setSubmitting] = useState(false)

  const productOptions = PRODUCTS.includes(initial.product)
    ? PRODUCTS
    : [initial.product, ...PRODUCTS]

  const changed =
    company.trim() !== initial.company.trim() ||
    creditCode.trim() !== initial.creditCode.trim() ||
    Number(amount) !== Number(initial.amount) ||
    product !== initial.product

  const handleClose = () => {
    if (!submitting) onClose()
  }

  const handleSubmit = async () => {
    if (submitting) return

    const parsedAmount = Number(amount)
    if (!company.trim()) {
      toast('请输入企业名称')
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
    if (!changed) {
      toast('未修改任何信息')
      return
    }

    setSubmitting(true)
    try {
      const updated = await updateApplication(app.id, {
        company_name: company.trim(),
        credit_code: creditCode.trim(),
        amount: parsedAmount,
        product
      })
      onSaved?.(updated)
      toast(`申请 ${app.id} 已更新，AI 预审报告已重新生成`)
      setSubmitting(false)
      onClose()
    } catch (error) {
      setSubmitting(false)
      toast(error.message || '保存失败，请稍后重试')
    }
  }

  return (
    <Modal
      title={`编辑申请 ${app?.id || ''}`}
      onClose={handleClose}
      footer={
        <>
          <button className="btn btn-secondary" onClick={handleClose} disabled={submitting}>
            取消
          </button>
          <button className="btn btn-primary" onClick={handleSubmit} disabled={submitting}>
            {submitting ? '保存中...' : '保存修改'}
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
          placeholder="请输入企业全称"
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
          placeholder="请输入贷款金额"
          value={amount}
          onChange={(e) => setAmount(e.target.value)}
        />
      </div>

      <div>
        <label>
          贷款类型 <span className="req">*</span>
        </label>
        <select value={product} onChange={(e) => setProduct(e.target.value)}>
          {productOptions.map((p) => (
            <option key={p} value={p}>
              {p}
            </option>
          ))}
        </select>
      </div>

      <div className="hint">修改后将重新生成 AI 预审报告，申请材料与分类结果不受影响。</div>
    </Modal>
  )
}
