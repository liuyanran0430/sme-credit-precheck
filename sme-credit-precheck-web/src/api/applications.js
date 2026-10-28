import { authHeaders, handleUnauthorized, readError } from './http'

const API_PREFIX = '/api/v1'

/** 统一请求封装：自动携带访问令牌，401 时清理登录态 */
async function request(url, options = {}) {
  const response = await fetch(url, {
    ...options,
    headers: authHeaders(options.headers)
  })
  if (response.status === 401) {
    handleUnauthorized()
    throw new Error('登录已过期，请重新登录')
  }
  if (!response.ok) {
    throw new Error(await readError(response))
  }
  return response
}

/**
 * 获取申请列表（后端已按 id 倒序返回）。
 */
export async function fetchApplications({ page = 1, pageSize = 100 } = {}) {
  const response = await request(
    `${API_PREFIX}/applications?page=${page}&page_size=${pageSize}`
  )
  const data = await response.json()
  return Array.isArray(data.items) ? data.items : []
}

/**
 * 提交新申请，落库后返回完整申请记录。
 */
export async function createApplication(payload) {
  const response = await request(`${API_PREFIX}/applications`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  })
  return response.json()
}

/**
 * 查询单个申请的最新详情（用于同步状态与进度）。
 */
export async function fetchApplication(appNo) {
  const response = await request(
    `${API_PREFIX}/applications/${encodeURIComponent(appNo)}`
  )
  return response.json()
}

/**
 * 修改申请基础信息（企业名称、信用代码、贷款类型、申请金额）。
 * 后端在字段发生变化时自动重新生成 AI 预审报告。
 */
export async function updateApplication(appNo, payload) {
  const response = await request(
    `${API_PREFIX}/applications/${encodeURIComponent(appNo)}`,
    {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    }
  )
  return response.json()
}

/**
 * 查询申请材料清单。
 */
export async function fetchMaterials(appNo) {
  const response = await request(
    `${API_PREFIX}/applications/${encodeURIComponent(appNo)}/materials`
  )
  const data = await response.json()
  return Array.isArray(data) ? data : []
}

/**
 * 查询最新 AI 预审报告，尚未生成时返回 null。
 */
export async function fetchReport(appNo) {
  const response = await fetch(
    `${API_PREFIX}/applications/${encodeURIComponent(appNo)}/report`,
    { headers: authHeaders() }
  )
  if (response.status === 404) return null
  if (response.status === 401) {
    handleUnauthorized()
    throw new Error('登录已过期，请重新登录')
  }
  if (!response.ok) throw new Error(await readError(response))
  return response.json()
}

/**
 * 查询某申请的人工复核记录（按提交时间倒序）。
 */
export async function fetchManualReviews(appNo) {
  const response = await request(
    `${API_PREFIX}/applications/${encodeURIComponent(appNo)}/reviews`
  )
  return response.json()
}

/**
 * 查询某申请的风控复核记录（按提交时间倒序）。
 */
export async function fetchRiskReviews(appNo) {
  const response = await request(
    `${API_PREFIX}/risk/${encodeURIComponent(appNo)}/reviews`
  )
  return response.json()
}

/**
 * 触发 AI 预审（材料分类完成后调用），返回最新预审报告。
 */
export async function generateReport(appNo) {
  const response = await request(
    `${API_PREFIX}/applications/${encodeURIComponent(appNo)}/report/generate`,
    { method: 'POST' }
  )
  return response.json()
}

/**
 * 导出 AI 预审报告 PDF（浏览器直接下载）。
 */
export async function exportReport(appNo) {
  const response = await request(
    `${API_PREFIX}/applications/${encodeURIComponent(appNo)}/report/export`
  )
  const blob = await response.blob()
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = `AI预审报告_${appNo}.pdf`
  document.body.appendChild(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(url)
}

/**
 * 提交人工复核结果（逐项采纳/修改/驳回）。
 */
export async function submitManualReview(appNo, payload) {
  const response = await request(
    `${API_PREFIX}/applications/${encodeURIComponent(appNo)}/reviews`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    }
  )
  return response.json()
}

/**
 * 提交风控复核决策：通过/有条件通过 → 已审批；退回补件 → 待补件。
 */
export async function submitRiskDecision(appNo, payload) {
  const response = await request(
    `${API_PREFIX}/risk/${encodeURIComponent(appNo)}/decision`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    }
  )
  return response.json()
}

/**
 * 上传申请材料，返回已创建的材料记录。
 */
export async function uploadMaterials(appNo, files) {
  const formData = new FormData()
  files.forEach((file) => formData.append('files', file))

  const response = await request(
    `${API_PREFIX}/applications/${encodeURIComponent(appNo)}/materials/upload`,
    { method: 'POST', body: formData }
  )
  return response.json()
}

/**
 * 删除申请及其所有关联数据（AI 报告、复核记录、材料与上传文件）。
 */
export async function deleteApplication(appNo) {
  await request(`${API_PREFIX}/applications/${encodeURIComponent(appNo)}`, {
    method: 'DELETE'
  })
}

/**
 * 材料文件原始地址（内联返回 PDF / 图片）。
 */
export function materialFileUrl(appNo, materialId) {
  return `${API_PREFIX}/applications/${encodeURIComponent(appNo)}/materials/${materialId}/file`
}

/**
 * 携带令牌下载材料文件，返回 Blob（用于弹窗内预览）。
 */
export async function fetchMaterialFile(appNo, materialId) {
  const response = await request(materialFileUrl(appNo, materialId))
  return response.blob()
}

/**
 * 人工修正材料类别，返回更新后的材料记录。
 */
export async function updateMaterialCategory(appNo, materialId, category) {
  const response = await request(
    `${API_PREFIX}/applications/${encodeURIComponent(appNo)}/materials/${materialId}`,
    {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ category })
    }
  )
  return response.json()
}

/**
 * 删除材料记录及其上传文件。
 */
export async function deleteMaterial(appNo, materialId) {
  await request(
    `${API_PREFIX}/applications/${encodeURIComponent(appNo)}/materials/${materialId}`,
    { method: 'DELETE' }
  )
}
