import { test, expect } from '@playwright/test'
import { appRow, json, listPayload, LIST_URL, mockAuthMe, mockFallback, seedToken } from './helpers'

test.describe('必填与格式校验', () => {
  test('登录表单未填写时提示错误，填写后可正常登录', async ({ page }) => {
    await mockFallback(page)
    await page.route(LIST_URL, (route) => json(route, listPayload([appRow()], { precheck: 1 })))
    await page.route('**/api/v1/auth/login', (route) =>
      json(route, {
        access_token: 'e2e-mock-token',
        user: { username: 'manager', full_name: '张晓峰', role: 'manager' },
      })
    )

    await page.goto('/')
    await page.getByRole('button', { name: '登录', exact: true }).click()
    await expect(page.locator('.login-error')).toHaveText('请输入用户名和密码')

    await page.getByLabel(/用户名/).fill('manager')
    await page.getByRole('button', { name: '登录', exact: true }).click()
    await expect(page.locator('.login-error')).toHaveText('请输入用户名和密码')

    await page.getByLabel(/密码/).fill('123456')
    await page.getByRole('button', { name: '登录', exact: true }).click()
    await expect(page.getByRole('heading', { name: '申请列表' })).toBeVisible()
    await expect(page.getByText('客户经理：张晓峰')).toBeVisible()
  })

  test('新建申请逐项校验必填项、信用代码格式与文件格式', async ({ page }) => {
    await mockFallback(page)
    await seedToken(page)
    await mockAuthMe(page)
    await page.route(LIST_URL, (route) => json(route, listPayload([appRow()], { precheck: 1 })))

    const created = appRow({
      app_no: 'AP00000009',
      company_name: '测试企业有限公司',
      credit_code: '91310000MA1FL0009X',
      amount: 100,
      status: 'precheck',
    })
    await page.route('**/api/v1/applications', (route) => {
      if (route.request().method() !== 'POST') return route.fallback()
      return json(route, created)
    })
    await page.route('**/api/v1/applications/AP00000009/materials/upload', (route) =>
      json(route, { request_id: 'upload-1', app_no: 'AP00000009' })
    )
    await page.route('**/api/v1/applications/AP00000009/materials', (route) =>
      json(route, [{ id: 1, file_name: '营业执照.pdf', category: 'business_license', status: 'ok' }])
    )
    await page.route('**/api/v1/applications/AP00000009', (route) => json(route, created))

    await page.goto('/')
    await expect(page.getByRole('heading', { name: '申请列表' })).toBeVisible()

    await page.getByRole('button', { name: '＋ 提交申请' }).click()
    const submit = page.getByRole('button', { name: '提交申请', exact: true })
    const companyInput = page.getByPlaceholder('请输入企业全称，例如：上海德信精密机械有限公司')
    const creditInput = page.getByPlaceholder('请输入18位统一社会信用代码')
    const amountInput = page.getByPlaceholder('请输入贷款金额，例如：120')
    const fileInput = page.locator('.modal input[type="file"]')

    // 企业名称必填
    await submit.click()
    await expect(page.getByText('请输入企业名称')).toBeVisible()
    await expect(companyInput).toBeVisible()

    // 信用代码必填
    await companyInput.fill('测试企业有限公司')
    await submit.click()
    await expect(page.getByText('请输入统一社会信用代码')).toBeVisible()

    // 信用代码格式校验（必须 18 位数字或大写字母）
    await creditInput.fill('123456')
    await submit.click()
    await expect(page.getByText('请输入18位统一社会信用代码（数字或大写字母）')).toBeVisible()

    // 贷款金额必填
    await creditInput.fill('91310000MA1FL0009X')
    await submit.click()
    await expect(page.getByText('请输入正确的贷款金额')).toBeVisible()

    // 申请材料必填
    await amountInput.fill('100')
    await submit.click()
    await expect(page.getByText('请至少上传一份申请材料')).toBeVisible()

    // 文件格式校验：txt 被拒绝，不加入上传列表
    await fileInput.setInputFiles({
      name: '说明.txt',
      mimeType: 'text/plain',
      buffer: Buffer.from('hello'),
    })
    await expect(page.getByText('仅支持 PDF / JPG / PNG 格式文件')).toBeVisible()
    await expect(page.locator('.modal').getByText('说明.txt')).toHaveCount(0)

    // 合法 PDF 可加入上传列表
    await fileInput.setInputFiles({
      name: '营业执照.pdf',
      mimeType: 'application/pdf',
      buffer: Buffer.from('%PDF-1.4'),
    })
    await expect(page.locator('.modal').getByText('营业执照.pdf')).toBeVisible()

    // 全部校验通过后创建成功
    await submit.click()
    await expect(page).toHaveURL(/\/detail\/AP00000009$/)
  })
})
