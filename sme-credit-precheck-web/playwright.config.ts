/**
 * Playwright 端到端测试配置（TypeScript）
 *
 * 默认只启动前端 Vite dev server（端口 5173）。测试通过 page.route 对
 * /api/v1/** 返回确定性的 Mock 数据，不依赖真实后端与数据库。
 *
 * 若本地已启动 MySQL + 后端（端口 8001），可设置 E2E_WITH_BACKEND=1 让
 * Playwright 同时托管后端，用于真实链路冒烟：
 *   PowerShell: $env:E2E_WITH_BACKEND=1; npx playwright test
 *
 * 运行方式：
 *   npx playwright test                              # 跑全部
 *   npx playwright test tests/core-flow.spec.ts      # 跑单个
 *   npx playwright show-report                       # 查看报告
 *
 * 失败产物（截图 / 轨迹 / 录屏）保留在 test-results/ 目录。
 */

import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { defineConfig, type PlaywrightTestConfig } from '@playwright/test'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const rootDir = path.resolve(__dirname, '..')
const backendDir = path.resolve(rootDir, 'sme-credit-precheck-backend')

const withBackend = process.env.E2E_WITH_BACKEND === '1'
// Windows 和 Unix 的可执行文件后缀差异
const pythonCmd = process.platform === 'win32' ? 'python.exe' : 'python'
const pythonBin = path.join(backendDir, '.venv', 'Scripts', pythonCmd)

const frontendServer = {
  command: 'npm run dev',
  port: 5173,
  cwd: __dirname,
  reuseExistingServer: true,
  timeout: 60000,
  // BROWSER=none 阻止 Vite 自动打开浏览器，避免测试时多开页面
  env: { ...(process.env as Record<string, string>), BROWSER: 'none' },
}

const backendServer = {
  command: `"${pythonBin}" -m uvicorn app.main:app --host 127.0.0.1 --port 8001`,
  port: 8001,
  cwd: backendDir,
  reuseExistingServer: true,
  timeout: 60000,
}

const config: PlaywrightTestConfig = {
  testDir: './tests',
  fullyParallel: false, // 串行执行，失败定位更清晰
  workers: 1,
  retries: 0,
  reporter: [['list'], ['html', { open: 'never' }]],

  // 失败产物统一输出，便于复盘
  outputDir: 'test-results',

  use: {
    baseURL: 'http://localhost:5173',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
    navigationTimeout: 15000,
    actionTimeout: 8000,
  },

  expect: { timeout: 10000 },

  projects: [
    {
      name: 'chromium',
      use: {
        browserName: 'chromium',
        viewport: { width: 1280, height: 800 },
        ignoreHTTPSErrors: true,
      },
    },
  ],

  webServer: withBackend ? [backendServer, frontendServer] : [frontendServer],
}

export default defineConfig(config)
