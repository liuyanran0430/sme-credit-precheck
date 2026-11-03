/**
 * 返回上一步数据保留 — 刷新登录态、浏览器后退、侧栏导航
 */
import { test, expect } from '@playwright/test'

async function loginAs(page, username = 'manager', password = '123456') {
  await page.goto('/login')
  await page.getByPlaceholder('请输入用户名').fill(username)
  await page.getByPlaceholder('请输入密码').fill(password)
  await page.getByRole('button', { name: '登录' }).click()
  await expect(page).toHaveURL('/', { timeout: 10000 })
}

test.describe('数据保留', () => {
  test('刷新页面后登录态保留 — localStorage token 持久化', async ({ page }) => {
    await loginAs(page)
    // reload 会触发 AuthContext useEffect 从 localStorage 恢复 token 并调 fetchMe
    await page.reload()
    await expect(page).toHaveURL('/', { timeout: 10000 })
    await expect(page.locator('.app-sidebar')).toBeVisible()
  })

  test('从列表点进详情 → 浏览器后退 → 回到列表', async ({ page }) => {
    await loginAs(page)
    await expect(page.locator('.list-table tbody tr')).not.toHaveCount(0, { timeout: 10000 })
    await page.locator('.list-table tbody .id-link').first().click()
    await expect(page).toHaveURL(/\/detail\//, { timeout: 8000 })
    await page.goBack()
    await expect(page).toHaveURL('/', { timeout: 8000 })
  })

  test('侧栏导航后退出按钮始终可见', async ({ page }) => {
    await loginAs(page)
    const nav = (name) => page.locator('.app-sidebar .nav-item', { hasText: name }).first()

    await nav('申请详情').click()
    await expect(page.locator('.sidebar-logout')).toBeVisible()

    await nav('AI 预审报告').click()
    await expect(page.locator('.sidebar-logout')).toBeVisible()

    await nav('人工复核').click()
    await expect(page.locator('.sidebar-logout')).toBeVisible()
  })
})
