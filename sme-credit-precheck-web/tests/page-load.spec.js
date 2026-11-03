/**
 * 页面正常加载 — 验证核心路由能渲染、基础 UI 组件存在
 */
import { test, expect } from '@playwright/test'

// Playwright 默认每个 test 有独立 browser context，localStorage 本来就是空的
// 不需要手动清理

async function loginAs(page, username = 'manager', password = '123456') {
  await page.goto('/login')
  await page.getByPlaceholder('请输入用户名').fill(username)
  await page.getByPlaceholder('请输入密码').fill(password)
  await page.getByRole('button', { name: '登录' }).click()
  await expect(page).toHaveURL('/', { timeout: 10000 })
}

test.describe('页面加载', () => {
  test('未登录访问任意页面自动跳转 /login', async ({ page }) => {
    await page.goto('/')
    await expect(page).toHaveURL('/login')
    await page.goto('/detail/AP00000001')
    await expect(page).toHaveURL('/login')
    await page.goto('/risk')
    await expect(page).toHaveURL('/login')
  })

  test('登录页正常渲染 — 品牌区 + 表单区 + 角色标签', async ({ page }) => {
    await page.goto('/login')
    await expect(page.locator('.login-logo')).toHaveText('🏦')
    await expect(page.getByRole('heading', { level: 1 })).toContainText('小微企业授信智能预审系统')
    await expect(page.locator('.login-roles .login-role')).toHaveCount(3)
    await expect(page.getByRole('heading', { level: 2 })).toHaveText('账号登录')
    await expect(page.getByPlaceholder('请输入用户名')).toBeVisible()
    await expect(page.getByPlaceholder('请输入密码')).toBeVisible()
    await expect(page.getByRole('button', { name: '登录' })).toBeVisible()
  })

  test('客户经理登录后进入申请列表', async ({ page }) => {
    await loginAs(page)
    await expect(page.locator('.app-sidebar')).toBeVisible()
    await expect(page.getByText('客户经理：')).toBeVisible()
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('申请列表')
  })

  test('风控人员登录后进入风控队列', async ({ page }) => {
    await page.goto('/login')
    await page.getByPlaceholder('请输入用户名').fill('risk')
    await page.getByPlaceholder('请输入密码').fill('123456')
    await page.getByRole('button', { name: '登录' }).click()
    await expect(page).toHaveURL('/risk', { timeout: 10000 })
    await expect(page.getByRole('heading', { level: 1 })).toContainText('风控')
  })

  test('侧栏导航项正确渲染 — 申请列表 / 详情 / 报告 / 复核', async ({ page }) => {
    await loginAs(page)

    const sidebar = page.locator('.app-sidebar')
    await expect(sidebar).toBeVisible()

    // 侧栏必须有 4 个 nav-item 按钮
    await expect(sidebar.locator('.nav-item')).toHaveCount(4)
    await expect(sidebar.locator('.nav-item', { hasText: '申请列表' })).toBeVisible()
    await expect(sidebar.locator('.nav-item', { hasText: '申请详情' })).toBeVisible()
    await expect(sidebar.locator('.nav-item', { hasText: /AI.*预审报告/ })).toBeVisible()
    await expect(sidebar.locator('.nav-item', { hasText: '人工复核' })).toBeVisible()
  })
})
