import type { ReactNode } from 'react'
import Modal from './Modal'

interface ConfirmModalProps {
  title?: ReactNode
  message: ReactNode
  confirmText?: string
  cancelText?: string
  danger?: boolean
  onConfirm: () => void
  onCancel: () => void
  busy?: boolean
}

/**
 * 通用确认弹窗（替代原生 confirm，样式与应用一致）
 */
export default function ConfirmModal({
  title = '确认操作',
  message,
  confirmText = '确定',
  cancelText = '取消',
  danger = false,
  onConfirm,
  onCancel,
  busy = false
}: ConfirmModalProps) {
  return (
    <Modal
      title={title}
      onClose={onCancel}
      closeOnMaskClick={true}
      footer={
        <div className="confirm-foot">
          <button className="btn btn-secondary" onClick={onCancel} disabled={busy}>
            {cancelText}
          </button>
          <button
            className={`btn ${danger ? 'btn-danger' : 'btn-primary'}`}
            onClick={onConfirm}
            disabled={busy}
          >
            {busy ? '处理中…' : confirmText}
          </button>
        </div>
      }
    >
      <div className="confirm-message">{message}</div>
    </Modal>
  )
}
