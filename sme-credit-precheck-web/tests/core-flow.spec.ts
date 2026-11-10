import { test, expect } from '@playwright/test'
import { appRow, json, listPayload, LIST_URL, mockAuthMe, mockFallback, seedToken } from './helpers'

const CREATED_APP_NO = 'AP00000009'

test.describe('核心业务流程', () => {
  test('提交申请 → 材料检查进度 → 自动流转待 AI 预审', async ({ page }) => {
    await mockFallback(page)
    await seedToken(page)
    await mockAuthMe(page)

    await page.route(LIST_URL, (route) => json(route, listPayload([appRow()], { precheck: 1 })))

    const created = appRow({
      app_no: CREATED_APP_NO,
      company_name: '测试企业有限公司',
      credit_code: '91310000MA1FL0009X',
      amount: 100,
      status: 'check',
      ai_summary: null,
      conclusion: null,
    })

    await page.route('**/api/v1/applications', (route) => {
      const method = route.request().method()
      if (method !== 'POST') return route.fallback()
      return json(route, created)
    })

    await page.route(`**/api/v1/applications/${CREATED_APP_NO}/materials/upload`, (route) =>
      json(route, { request_id: 'upload-1', app_no: CREATED_APP_NO })
    )

    // 材料检查进度：首次返回待抽取，之后返回已抽取
    let materialPolls = 0
    await page.route(`**/api/v1/applications/${CREATED_APP_NO}/materials`, (route) => {
      materialPolls += 1
      return json(route, [
        {
          id: 1,
          file_name: '营业执照.pdf',
          category: 'business_license',
          status: materialPolls === 1 ? 'pending' : 'ok',
          created_at: '2026-11-07T10:00:00',
        },
      ])
    })

    // 申请状态：材料检查完成后由 check 自动流转为 precheck
    let statusPolls = 0
    await page.route(`**/api/v1/applications/${CREATED_APP_NO}`, (route) => {
      statusPolls += 1
      return json(route, { ...created, status: statusPolls <= 2 ? 'check' : 'precheck' })
    })

    await page.goto('/')
    await expect(page.getByRole('heading', { name: '申请列表' })).toBeVisible()

    // 填写并提交申请
    await page.getByRole('button', { name: '＋ 提交申请' }).click()
    await expect(page.getByRole('heading', { name: '提交新申请' })).toBeVisible()

    await page
      .getByPlaceholder('请输入企业全称，例如：上海德信精密机械有限公司')
      .fill('测试企业有限公司')
    await page.getByPlaceholder('请输入18位统一社会信用代码').fill('91310000MA1FL0009X')
    await page.getByPlaceholder('请输入贷款金额，例如：120').fill('100')
    await page.locator('.modal select').selectOption('小微快贷')
    await page.locator('.modal input[type="file"]').setInputFiles({
      name: '营业执照.pdf',
      mimeType: 'application/pdf',
      buffer: Buffer.from('%PDF-1.4'),
    })

    await page.getByRole('button', { name: '提交申请', exact: true }).click()

    // 进入详情页并展示材料检查进度
    await expect(page).toHaveURL(new RegExp(`/detail/${CREATED_APP_NO}$`))
    await expect(page.locator('.processing-banner')).toContainText('材料检查中')
    await expect(page.locator('.processing-banner')).toContainText('已处理 1 / 1')

    // 材料检查完成后自动流转为「待 AI 预审」，进度提示消失
    await expect(page.locator('h1 .tag')).toContainText('待 AI 预审', { timeout: 15000 })
    await expect(page.locator('.processing-banner')).toHaveCount(0)

    // 材料清单展示已抽取的分类
    await expect(page.getByText('营业执照', { exact: true }).first()).toBeVisible()
  })
})
