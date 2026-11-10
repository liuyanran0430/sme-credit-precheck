import { test, expect } from '@playwright/test'
import {
  appRow,
  json,
  listPayload,
  LIST_URL,
  mockAuthMe,
  mockFallback,
  seedToken,
} from './helpers'

test.describe('页面正常加载', () => {
  test('未登录时登录页完整渲染', async ({ page }) => {
    await mockFallback(page)
    await page.goto('/')

    // 品牌区与角色说明
    await expect(
      page.getByRole('heading', { name: '小微企业授信智能预审系统' })
    ).toBeVisible()
    await expect(page.getByText('客户经理', { exact: true })).toBeVisible()
    await expect(page.getByText('风控人员', { exact: true })).toBeVisible()
    await expect(page.getByText('管理员', { exact: true })).toBeVisible()

    // 表单控件可交互
    await expect(page.getByLabel(/用户名/)).toBeVisible()
    await expect(page.getByLabel(/密码/)).toBeVisible()
    await expect(page.getByRole('button', { name: '登录' })).toBeEnabled()
    await expect(page.getByText('登录后按账号角色进入对应工作台')).toBeVisible()
  })

  test('已登录时申请列表正常加载并展示数据', async ({ page }) => {
    await mockFallback(page)
    await seedToken(page)
    await mockAuthMe(page)
    await page.route(LIST_URL, (route) =>
      json(
        route,
        listPayload(
          [
            appRow(),
            appRow({
              id: 2,
              app_no: 'AK00000002',
              company_name: '苏州云启软件有限公司',
              credit_code: '91320500MA1ABCDE2Y',
              amount: 80,
              product: '小微快贷',
              status: 'manual',
            }),
          ],
          { precheck: 1, manual: 1 }
        )
      )
    )

    await page.goto('/')

    // 页面标题与客户经理信息
    await expect(page.getByRole('heading', { name: '申请列表' })).toBeVisible()
    await expect(page.getByText('客户经理：张晓峰')).toBeVisible()

    // 表头完整
    for (const header of [
      '申请编号',
      '企业名称',
      '统一社会信用代码',
      '信用贷类型',
      '申请金额',
      '当前状态',
      '操作',
    ]) {
      await expect(page.getByRole('columnheader', { name: header })).toBeVisible()
    }

    // 列表行真实数据
    await expect(page.getByText('AP00000001')).toBeVisible()
    await expect(page.getByText('上海德信精密机械有限公司')).toBeVisible()
    await expect(page.getByText('120.00 万元')).toBeVisible()
    await expect(page.getByText('苏州云启软件有限公司')).toBeVisible()

    // 状态统计条按后端返回的 status_counts 渲染
    const stats = page.locator('.stats-bar')
    await expect(stats).toContainText('待 AI 预审')
    await expect(stats).toContainText('待人工核验')
    await expect(page.getByText('共 2 条', { exact: true })).toBeVisible()
  })
})
