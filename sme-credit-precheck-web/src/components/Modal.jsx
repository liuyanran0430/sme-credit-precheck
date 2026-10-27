/**
 * 通用弹窗组件
 */
export default function Modal({ title, onClose, children, footer, wide }) {
  return (
    <div className="modal-mask" onClick={onClose}>
      <div className={wide ? 'modal modal-wide' : 'modal'} onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <h3>{title}</h3>
          <button className="btn btn-ghost btn-sm" onClick={onClose}>
            ✕
          </button>
        </div>
        <div className="modal-body">{children}</div>
        {footer ? <div className="modal-foot">{footer}</div> : null}
      </div>
    </div>
  )
}
