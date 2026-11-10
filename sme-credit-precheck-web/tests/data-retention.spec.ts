import { test, expect } from '@playwright/test'
import { appRow, json, listPayload, LIST_URL, mockAuthMe, mockFallback, seedToken } from './helpers'

const APP_NO = 'AP00000003'

const reportFixture = {
  app_no: APP_NO,
  version: 'v1.0',
  conclusion: 'manual',
  pass_rate: 0.86,
  rule_results: {
    score: 72,
    level: 'B',
    total_count: 8,
    pass_count: 7,
    uncertain_count: 1,
    hard_fail_count: 0,
    soft_fail_count: 0,
    rules: [],
  },
  conflicts: [
    {
      type: 'rule_conflict',
      reason: '营业执照经营范围与所申请产品不匹配',
      confidence: 0.72,
      rules: ['R-PRODUCT-01'],
    },
  ],
  risk_signals: [],
  completeness: { categories: [], missing: [], issues: [] },
}

test.describe('返回上一步后数据保留', () => {
  test('人工复核填写内容存草稿后离开再返回可恢复', async ({ page }) => {
    await mockFallback(page)
    await seedToken(page)
    await mockAuthMe(page)
    await page.route(LIST_URL, (route) =>
      json(
        route,
        listPayload([appRow({ app_no: APP_NO, status: 'manual' })], { manual: 1 })
      )
    )
    await page.route(`**/api/v1/applications/${APP_NO}/report`, (route) =>
      json(route, reportFixture)
    )

    await page.goto(`/review/${APP_NO}`)
    await expect(page.getByRole('heading', { name: /人工复核：\s*AP00000003/ })).toBeVisible()

    // 核验区：选择一个核验动作并填写理由（单选框被样式隐藏，点击其 label 触发）
    const conflictChoice = page.locator('.review-card .seg label', { hasText: '确认冲突存在' })
    const conflictRadio = conflictChoice.locator('input')
    await conflictChoice.click()
    const reason = '已核对原始凭证，确认经营范围确实与产品不匹配'
    await page.locator('.review-card textarea').fill(reason)

    // 决策区：人工覆盖为「退回补件」并填写补件说明
    const supplementChoice = page.locator('.decision-seg label', { hasText: '退回补件' })
    await supplementChoice.click()
    const supplementNote = '请补充最新的营业执照副本'
    const noteInput = page.getByPlaceholder('补件说明（将展示在申请详情页，必填）…')
    await noteInput.fill(supplementNote)

    // 等待自动保存草稿
    await expect(page.locator('.decision-saved')).toContainText('自动保存草稿')

    // 离开复核页：先回申请列表，再从侧边栏重新进入人工复核
    await page.getByRole('button', { name: '申请列表' }).click()
    await expect(page.getByRole('heading', { name: '申请列表' })).toBeVisible()
    await page.getByRole('button', { name: '人工复核' }).click()

    // 重新进入后应恢复到同一申请，且已填内容完整保留
    await expect(page.getByRole('heading', { name: /人工复核：\s*AP00000003/ })).toBeVisible()
    await expect(conflictRadio).toBeChecked()
    await expect(page.locator('.review-card textarea')).toHaveValue(reason)
    await expect(supplementChoice.locator('input')).toBeChecked()
    await expect(noteInput).toHaveValue(supplementNote)
    await expect(page.locator('.decision-saved')).toContainText('自动保存草稿')
  })
})
