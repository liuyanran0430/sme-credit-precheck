/**
 * E2E 测试公共工具：Mock 数据、登录态注入、接口兜底。
 *
 * 约定：先注册兜底路由（未配置的接口返回 404），再注册具体业务路由；
 * Playwright 路由按注册顺序倒序匹配，因此后注册的规则优先生效。
 */

import type { Page, Route } from '@playwright/test'

export const MOCK_USER = {
  username: 'manager',
  full_name: '张晓峰',
  role: 'manager',
}

/** 构造一条申请列表 / 详情数据 */
export function appRow(overrides: Record<string, unknown> = {}) {
  return {
    id: 1,
    app_no: 'AP00000001',
    company_name: '上海德信精密机械有限公司',
    credit_code: '91310000MA1FL0001X',
    amount: 120,
    product: '普惠小微经营贷',
    status: 'precheck',
    manager_name: '张晓峰',
    created_at: '2026-11-01T09:30:00',
    ai_summary: null,
    conclusion: null,
    supplement_note: null,
    supplement_source: null,
    can_precheck: true,
    precheck_disabled_reason: null,
    ...overrides,
  }
}

/** 统一 JSON 响应 */
export function json(route: Route, data: unknown, status = 200) {
  return route.fulfill({
    status,
    contentType: 'application/json',
    body: JSON.stringify(data),
  })
}

/** 未配置的接口统一返回 404，避免请求透传到代理后端 */
export async function mockFallback(page: Page) {
  await page.route('**/api/v1/**', (route) =>
    json(route, { detail: 'E2E: 该接口未配置 Mock' }, 404)
  )
}

/** 注入本地登录令牌（应用启动时据此恢复登录态） */
export async function seedToken(page: Page) {
  await page.addInitScript(() => {
    window.localStorage.setItem('sme_token', 'e2e-mock-token')
  })
}

/** Mock 当前登录用户接口 */
export async function mockAuthMe(page: Page, user = MOCK_USER) {
  await page.route('**/api/v1/auth/me', (route) => json(route, user))
}

/** 列表接口 URL 正则（仅匹配列表，不匹配单条详情） */
export const LIST_URL = /\/api\/v1\/applications(\?.*)?$/

/** 应用列表响应体 */
export function listPayload(items: unknown[], statusCounts: Record<string, number> = {}) {
  return {
    items,
    total: items.length,
    status_counts: {
      check: 0,
      precheck: 0,
      supplement: 0,
      manual: 0,
      risk: 0,
      ...statusCounts,
    },
  }
}

/** 常用 PDF 上传文件（内容内联，避免依赖外部 fixture 文件） */
export function pdfFile(name = '营业执照.pdf') {
  return {
    name,
    mimeType: 'application/pdf',
    buffer: Buffer.from('%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n<<>>\n%%EOF'),
  }
}
