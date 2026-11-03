/**
 * 核心业务流程 — 登录 → 列表 → 新建申请 → 提交 → 进入详情页
 *
 * 依赖后端真实运行、已有测试账号（manager/123456）
 * 注意：会真实创建一条申请数据到数据库
 */
import { test, expect } from '@playwright/test'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))

// 最小 1x1 白色 PNG
const MIN_PNG = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==',
  'base64'
)

async function loginAs(page, username = 'manager', password = '123456') {
  await page.goto('/login')
  await page.getByPlaceholder('请输入用户名').fill(username)
  await page.getByPlaceholder('请输入密码').fill(password)
  await page.getByRole('button', { name: '登录' }).click()
  await expect(page).toHaveURL('/', { timeout: 10000 })
}

test.describe('核心业务流程', () => {
  test('新建申请完整流程 — 提交表单 → 跳转详情', async ({ page }) => {
    await loginAs(page)

    // 1. 打开新建申请弹窗（ListView 顶部的 "＋ 提交申请" 按钮）
    await page.getByRole('button', { name: /提交申请/ }).first().click()
    await expect(page.locator('.modal')).toBeVisible()
    await expect(page.locator('.modal-head h3')).toHaveText('提交新申请')

    // 2. 填写表单
    const modal = page.locator('.modal')
    await modal.locator('input').nth(0).fill('Playwright 测试企业有限公司')
    await modal.locator('input').nth(1).fill('91310000MA1FL0TEST')
    await modal.locator('input').nth(2).fill('88.88')
    await modal.locator('select').selectOption('普惠小微经营贷')

    // 3. 上传材料
    const tmpPng = path.resolve(__dirname, '..', '.pw-test-file.png')
    fs.writeFileSync(tmpPng, MIN_PNG)
    await modal.locator('input[type="file"]').setInputFiles(tmpPng)

    // 4. 提交（弹窗内的 "提交申请" 按钮 — 用 exact 精确匹配，避开 "＋ 提交申请"）
    await page.getByRole('button', { name: '提交申请', exact: true }).click()

    // 5. 跳转到详情页
    await expect(page).toHaveURL(/\/detail\/AP\d+/, { timeout: 15000 })
    await expect(page.locator('.app-sidebar')).toBeVisible()

    // 清理临时文件
    try { fs.unlinkSync(tmpPng) } catch {}
  })
})
