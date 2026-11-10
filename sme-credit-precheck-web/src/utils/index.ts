/**
 * 通用工具函数
 */

import type { Material, MaterialRow } from '../types'

// 格式化金额（保留两位小数）
export const fmt = (n: number | string | null | undefined): string => Number(n).toFixed(2)

// 格式化文件大小
export function formatSize(bytes?: number | null): string {
  if (!bytes) return '—'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(0) + ' KB'
  return (bytes / 1024 / 1024).toFixed(1) + ' MB'
}

// 将后端材料记录转换为前端材料项
export function normalizeMaterial(row: MaterialRow): Material {
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
export function matStatusText(m: { status?: string }): string {
  if (m.status === 'ok') return '已抽取'
  if (m.status === 'low') return '低置信'
  if (m.status === 'none') return '暂无文件'
  return '待抽取'
}

// 申请状态对应的步骤索引（审批环节暂无入口，已审批停留在审批节点显示数字 6）
// 步骤定义：0=已提交 1=材料检查 2=AI 预审 3=人工复核 4=风控复核 5=审批
export const STEP_IDX: Record<string, number> = {
  check: 1, // 待材料检查 → 步骤1 进行中
  precheck: 2, // 待 AI 预审 → 步骤2 进行中（材料检查完成，等用户点按钮）
  supplement: 1, // 待补件 → 步骤1（补完材料需重新检查/抽取）
  manual: 3, // 待人工核验 → 步骤3 进行中
  risk: 4, // 待风控复核 → 步骤4 进行中
  rejected: 3, // 已否决 → 停在人工复核节点（被拒）
  approved: 5 // 已审批 → 步骤5 完成
}

// 步骤定义
export const STEPS: string[] = ['已提交', '材料检查', 'AI 预审', '人工复核', '风控复核', '审批']
