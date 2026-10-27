import { useEffect, useState } from 'react'
import Modal from '../components/Modal'
import { fetchMaterialFile } from '../api/applications'

/**
 * 材料文件预览弹窗：携带令牌下载文件后，用 Blob 地址在 iframe 中渲染 PDF / 图片。
 */
export default function PreviewModal({ appId, material, onClose }) {
  const [url, setUrl] = useState('')
  const [error, setError] = useState('')

  useEffect(() => {
    if (!material?.id) return
    let cancelled = false
    let objectUrl = ''

    setUrl('')
    setError('')
    fetchMaterialFile(appId, material.id)
      .then((blob) => {
        if (cancelled) return
        objectUrl = URL.createObjectURL(blob)
        setUrl(objectUrl)
      })
      .catch((err) => {
        if (!cancelled) setError(err.message || '文件加载失败')
      })

    return () => {
      cancelled = true
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [appId, material])

  if (!material || !material.id) return null

  return (
    <Modal wide title={material.name} onClose={onClose}>
      {error ? (
        <div className="mat-empty">预览失败：{error}</div>
      ) : url ? (
        <iframe src={url} title={material.name} className="preview-frame" />
      ) : (
        <div className="mat-empty">文件加载中…</div>
      )}
      <div className="hint">浏览器内直接预览 PDF / 图片原文件，关闭弹窗返回材料清单。</div>
    </Modal>
  )
}
