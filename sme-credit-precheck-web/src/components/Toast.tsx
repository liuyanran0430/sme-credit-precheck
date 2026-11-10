import { useApp } from '../context/AppContext'

/**
 * Toast 提示容器
 */
export default function Toast() {
  const { toasts } = useApp()
  return (
    <div className="toast-container">
      {toasts.map((t) => (
        <div key={t.id} className="toast show">
          {t.msg}
        </div>
      ))}
    </div>
  )
}
