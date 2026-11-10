import { test, expect } from '@playwright/test'
import { appRow, json, listPayload, LIST_URL, mockAuthMe, mockFallback, seedToken } from './helpers'

test.describe('接口失败提示与重试', () => {
  test('登录接口失败给出提示，重试后成功进入列表', async ({ page }) => {
    await mockFallback(page)
    await page.route(LIST_URL, (route) => json(route, listPayload([appRow()], { precheck: 1 })))

    let failFirst = true
    await page.route('**/api/v1/auth/login', (route) => {
      if (failFirst) {
        failFirst = false
        return json(route, { detail: '用户名或密码错误' }, 500)
      }
      return json(route, {
        access_token: 'e2e-mock-token',
        user: { username: 'manager', full_name: '张晓峰', role: 'manager' },
      })
    })

    await page.goto('/')
    await page.getByLabel(/用户名/).fill('manager')
    await page.getByLabel(/密码/).fill('123456')
    await page.getByRole('button', { name: '登录', exact: true }).click()

    // 失败提示保留在登录表单内，页面不跳转
    await expect(page.locator('.login-error')).toHaveText('用户名或密码错误')
    await expect(page.getByRole('button', { name: '登录', exact: true })).toBeEnabled()

    // 重试后进入申请列表
    await page.getByRole('button', { name: '登录', exact: true }).click()
    await expect(page.getByRole('heading', { name: '申请列表' })).toBeVisible()
    await expect(page.getByText('AP00000001')).toBeVisible()
  })

  test('申请列表接口失败给出提示，切换筛选后重试成功', async ({ page }) => {
    await mockFallback(page)
    await seedToken(page)
    await mockAuthMe(page)

    let listCalls = 0
    await page.route(LIST_URL, (route) => {
      listCalls += 1
      // 未选择筛选条件时的请求（应用初始化 + 列表首次加载）全部失败
      if (!route.request().url().includes('status=')) {
        return json(route, { detail: '申请列表服务暂时不可用' }, 500)
      }
      return json(route, listPayload([appRow()], { precheck: 1 }))
    })

    await page.goto('/')

    // 首次加载失败：toast 提示，表格为空
    await expect(page.getByText('申请列表服务暂时不可用')).toBeVisible()
    await expect(page.getByText('没有符合条件的申请')).toBeVisible()

    // 切换状态筛选触发重新请求，本次成功加载
    await page.getByRole('combobox').first().selectOption('precheck')
    await expect(page.getByText('AP00000001')).toBeVisible()
    await expect(page.getByText('共 1 条', { exact: true })).toBeVisible()
    expect(listCalls).toBeGreaterThan(1)
  })

  test('提交申请接口失败保留表单并给出提示，重试后创建成功', async ({ page }) => {
    await mockFallback(page)
    await seedToken(page)
    await mockAuthMe(page)
    await page.route(LIST_URL, (route) => json(route, listPayload([])))

    let createCalls = 0
    await page.route('**/api/v1/applications', (route) => {
      const method = route.request().method()
      if (method !== 'POST') return route.fallback()
      createCalls += 1
      if (createCalls === 1) {
        return json(route, { detail: '创建申请失败，请稍后重试' }, 500)
      }
      return json(
        route,
        appRow({
          app_no: 'AP00000009',
          company_name: '测试企业有限公司',
          credit_code: '91310000MA1FL0009X',
          amount: 100,
          status: 'precheck',
        })
      )
    })
    await page.route('**/api/v1/applications/AP00000009/materials/upload', (route) =>
      json(route, { request_id: 'upload-1', app_no: 'AP00000009' })
    )
    await page.route('**/api/v1/applications/AP00000009/materials', (route) =>
      json(route, [{ id: 1, file_name: '营业执照.pdf', category: 'business_license', status: 'ok' }])
    )
    await page.route('**/api/v1/applications/AP00000009', (route) =>
      json(
        route,
        appRow({
          app_no: 'AP00000009',
          company_name: '测试企业有限公司',
          credit_code: '91310000MA1FL0009X',
          amount: 100,
          status: 'precheck',
        })
      )
    )

    await page.goto('/')
    await expect(page.getByRole('heading', { name: '申请列表' })).toBeVisible()

    await page.getByRole('button', { name: '＋ 提交申请' }).click()
    await expect(page.getByRole('heading', { name: '提交新申请' })).toBeVisible()

    await page
      .getByPlaceholder('请输入企业全称，例如：上海德信精密机械有限公司')
      .fill('测试企业有限公司')
    await page.getByPlaceholder('请输入18位统一社会信用代码').fill('91310000MA1FL0009X')
    await page.getByPlaceholder('请输入贷款金额，例如：120').fill('100')
    await page.locator('input[type="file"]').setInputFiles({
      name: '营业执照.pdf',
      mimeType: 'application/pdf',
      buffer: Buffer.from('%PDF-1.4'),
    })

    await page.getByRole('button', { name: '提交申请', exact: true }).click()

    // 失败提示，弹窗保留且已填内容不丢失
    await expect(page.getByText('创建申请失败，请稍后重试')).toBeVisible()
    await expect(page.getByRole('heading', { name: '提交新申请' })).toBeVisible()
    await expect(
      page.getByPlaceholder('请输入企业全称，例如：上海德信精密机械有限公司')
    ).toHaveValue('测试企业有限公司')

    // 重试后创建成功并进入详情页
    await page.getByRole('button', { name: '提交申请', exact: true }).click()
    await expect(page).toHaveURL(/\/detail\/AP00000009$/)
    await expect(page.getByText('测试企业有限公司')).toBeVisible()
  })
})
