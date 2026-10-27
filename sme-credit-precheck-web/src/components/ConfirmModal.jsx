import Modal from './Modal'

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
}) {
  return (
    <Modal
      title={title}
      onClose={onCancel}
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
