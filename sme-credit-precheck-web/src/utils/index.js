/**
 * 通用工具函数
 */

// 格式化金额（保留两位小数）
export const fmt = (n) => Number(n).toFixed(2)

// 格式化文件大小
export function formatSize(bytes) {
  if (!bytes) return '—'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(0) + ' KB'
  return (bytes / 1024 / 1024).toFixed(1) + ' MB'
}

// 将后端材料记录转换为前端材料项
export function normalizeMaterial(row) {
  return {
    id: row.id,
    name: row.file_name || '未命名文件',
    category: row.category || 'other',
    ver: row.version || 'v1.0',
    update: row.created_at ? String(row.created_at).slice(0, 10) : '—',
    status: row.status || 'pending',
    confidence: row.confidence ?? null,
    reason: row.reason || '',
    files: 1
  }
}

// 材料状态文本
export function matStatusText(m) {
  if (m.status === 'ok') return '已抽取'
  if (m.status === 'low') return '低置信'
  if (m.status === 'none') return '暂无文件'
  return '待抽取'
}

// 申请状态对应的步骤索引（审批环节暂无入口，已审批停留在审批节点显示数字 6）
export const STEP_IDX = { check: 1, supplement: 1, manual: 3, pending: 3, risk: 4, rejected: 3, approved: 5 }

// 步骤定义
export const STEPS = ['已提交', '材料检查', 'AI 预审', '人工复核', '风控复核', '审批']
