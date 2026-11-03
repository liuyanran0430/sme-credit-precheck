/**
 * 必填 & 格式校验 — 登录页 + 新建申请表单的校验提示
 */
import { test, expect } from '@playwright/test'

async function loginAs(page, username = 'manager', password = '123456') {
  await page.addInitScript(() => localStorage.clear())
  await page.goto('/login')
  await page.getByPlaceholder('请输入用户名').fill(username)
  await page.getByPlaceholder('请输入密码').fill(password)
  await page.getByRole('button', { name: '登录' }).click()
  await expect(page).toHaveURL('/', { timeout: 10000 })
}

test.describe('登录页校验', () => {
  test('用户名密码为空 — 前端提示', async ({ page }) => {
    await page.goto('/login')
    await page.getByRole('button', { name: '登录' }).click()
    await expect(page.locator('.login-error')).toContainText('请输入用户名和密码')
  })

  test('密码错误 — 后端返回错误', async ({ page }) => {
    await page.goto('/login')
    await page.getByPlaceholder('请输入用户名').fill('manager')
    await page.getByPlaceholder('请输入密码').fill('wrong-password')
    await page.getByRole('button', { name: '登录' }).click()
    await expect(page.locator('.login-error')).toBeVisible({ timeout: 8000 })
  })
})

test.describe('新建申请表单校验', () => {
  test('企业名称为空', async ({ page }) => {
    await loginAs(page)
    await page.getByRole('button', { name: '提交申请' }).first().click()

    // 只填后面的，留空企业名
    await page.locator('.modal input').nth(1).fill('91310000MA1FL0TEST')
    await page.locator('.modal input').nth(2).fill('100')
    await page.getByRole('button', { name: '提交申请' }).last().click()

    await expect(page.locator('.toast')).toContainText('请输入企业名称')
  })

  test('信用代码位数不对', async ({ page }) => {
    await loginAs(page)
    await page.getByRole('button', { name: '提交申请' }).first().click()

    await page.locator('.modal input').nth(0).fill('测试企业')
    await page.locator('.modal input').nth(1).fill('12345') // 只有 5 位
    await page.locator('.modal input').nth(2).fill('100')
    await page.getByRole('button', { name: '提交申请' }).last().click()

    await expect(page.locator('.toast')).toContainText('18位统一社会信用代码')
  })

  test('金额为负数或零', async ({ page }) => {
    await loginAs(page)
    await page.getByRole('button', { name: '提交申请' }).first().click()

    await page.locator('.modal input').nth(0).fill('测试企业')
    await page.locator('.modal input').nth(1).fill('91310000MA1FL0TEST')
    await page.locator('.modal input').nth(2).fill('-50')
    await page.getByRole('button', { name: '提交申请' }).last().click()

    await expect(page.locator('.toast')).toContainText('请输入正确的贷款金额')
  })

  test('不上传材料 — 拦截提交', async ({ page }) => {
    await loginAs(page)
    await page.getByRole('button', { name: '提交申请' }).first().click()

    await page.locator('.modal input').nth(0).fill('测试企业')
    await page.locator('.modal input').nth(1).fill('91310000MA1FL0TEST')
    await page.locator('.modal input').nth(2).fill('100')
    // 不上传文件直接提交
    await page.getByRole('button', { name: '提交申请' }).last().click()

    await expect(page.locator('.toast')).toContainText('请至少上传一份申请材料')
  })
})
