/**
 * 接口失败提示 — 用 Playwright route mock 后端返回 500 / 401
 */
import { test, expect } from '@playwright/test'

test.describe('接口失败提示', () => {
  test('登录接口 500 — 显示错误提示', async ({ page }) => {
    await page.route(/\/auth\/login/, async (route) => {
      await route.fulfill({
        status: 500,
        contentType: 'application/json',
        body: JSON.stringify({ detail: '数据库连接失败，请稍后重试' }),
      })
    })

    await page.goto('/login')
    await page.getByPlaceholder('请输入用户名').fill('manager')
    await page.getByPlaceholder('请输入密码').fill('123456')
    await page.getByRole('button', { name: '登录' }).click()
    await expect(page.locator('.login-error')).toContainText(/数据库|失败/)
  })

  test('申请列表接口 500 — 页面正常渲染 + 无崩溃', async ({ page }) => {
    // Mock API 失败，验证前端能处理（不崩溃、显示空态）
    await page.route(/\/applications(\?|$)/, async (route) => {
      await route.fulfill({
        status: 500,
        contentType: 'application/json',
        body: JSON.stringify({ detail: '后端服务异常' }),
      })
    })

    await page.goto('/login')
    await page.getByPlaceholder('请输入用户名').fill('manager')
    await page.getByPlaceholder('请输入密码').fill('123456')
    await page.getByRole('button', { name: '登录' }).click()
    await expect(page).toHaveURL('/', { timeout: 10000 })
    // 列表页面还在渲染（没白屏崩溃），侧栏可见
    await expect(page.locator('.app-sidebar')).toBeVisible()
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('申请列表')
  })

  test('401 过期 token — 自动跳转登录页', async ({ page }) => {
    await page.addInitScript(() => localStorage.setItem('sme_token', 'fake-invalid-token'))

    await page.route(/\/auth\/me/, async (route) => {
      await route.fulfill({
        status: 401,
        contentType: 'application/json',
        body: JSON.stringify({ detail: '登录已过期' }),
      })
    })

    await page.goto('/')
    await expect(page).toHaveURL('/login', { timeout: 8000 })
  })
})
