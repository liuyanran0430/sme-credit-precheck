/**
 * 通用弹窗组件
 *
 * props:
 *   title             弹窗标题（ReactNode）
 *   onClose           关闭回调（点击 X、取消按钮，或 closeOnMaskClick=true 时点击遮罩）
 *   children          弹窗内容
 *   footer            底部操作区（ReactNode，不传则无底部）
 *   wide              宽版（max-width 1100px）
 *   xlarge            超宽版（max-width 1400px）
 *   closeOnMaskClick  是否允许点击遮罩关闭（默认 false，防止表单填写到一半误触丢失数据）
 */

import type { ReactNode } from 'react'

interface ModalProps {
  title: ReactNode
  onClose: () => void
  children: ReactNode
  footer?: ReactNode
  wide?: boolean
  xlarge?: boolean
  closeOnMaskClick?: boolean
}

export default function Modal({
  title,
  onClose,
  children,
  footer,
  wide,
  xlarge,
  closeOnMaskClick = false
}: ModalProps) {
  const cls = xlarge ? 'modal modal-xlarge' : wide ? 'modal modal-wide' : 'modal'
  return (
    <div className="modal-mask" onClick={closeOnMaskClick ? onClose : undefined}>
      <div className={cls} onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <h3>{title}</h3>
          <button className="btn btn-ghost btn-sm" onClick={onClose} aria-label="关闭">
            ✕
          </button>
        </div>
        <div className="modal-body">{children}</div>
        {footer ? <div className="modal-foot">{footer}</div> : null}
      </div>
    </div>
  )
}
