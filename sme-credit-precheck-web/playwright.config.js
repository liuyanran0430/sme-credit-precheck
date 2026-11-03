/**
 * Playwright 端到端测试配置（ESM）
 *
 * webServer 会自动启动前后端（reuseExistingServer: true 表示端口已占用则复用）：
 *   - 后端：FastAPI（端口 8000，复用已有实例）
 *   - 前端：Vite dev server（端口 5173）
 *
 * 运行方式：
 *   npx playwright test                       # 跑全部
 *   npx playwright test tests/page-load.spec.js   # 跑单个
 *   npx playwright show-report                # 看报告
 */

import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const rootDir = path.resolve(__dirname, '..')
const backendDir = path.resolve(rootDir, 'sme-credit-precheck-backend')

// Windows 和 Unix 的可执行文件后缀差异
const pythonCmd = process.platform === 'win32' ? 'python.exe' : 'python'
const pythonBin = path.join(backendDir, '.venv', 'Scripts', pythonCmd)

export default {
  testDir: './tests',
  fullyParallel: false, // 串行执行，避免后端数据冲突
  workers: 1,
  reporter: [['list'], ['html', { open: 'never' }]],

  use: {
    baseURL: 'http://localhost:5173',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
    navigationTimeout: 15000,
    actionTimeout: 8000,
  },

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

  // 自动启动前后端（reuseExistingServer: true 意味着如果 8000/5173 已被占用就直接用）
  webServer: [
    {
      command: `"${pythonBin}" -m uvicorn app.main:app --host 127.0.0.1 --port 8000`,
      port: 8000,
      cwd: backendDir,
      reuseExistingServer: true,
      timeout: 30000,
    },
    {
      command: 'npm run dev',
      port: 5173,
      cwd: __dirname,
      reuseExistingServer: true,
      timeout: 30000,
      env: { ...process.env, BROWSER: 'none' },
    },
  ],
}
