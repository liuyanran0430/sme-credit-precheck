# 小微企业授信智能预审系统 — 前端

基于 **React 18 + Vite + React Router** 构建的单页应用，提供客户经理端（申请管理 / 材料上传 / AI 预审报告 / 人工复核 / 风控队列）全部界面。

## ✨ 核心能力

| 模块 | 说明 |
|---|---|
| 登录 | 用户名密码 + JWT，localStorage 持久化 token |
| 申请列表 | 分页 / 状态筛选 / 操作（编辑 / 删除 / AI 预审摘要 / 状态流转按钮） |
| 申请详情 | 节点式进度条、AI 预审摘要侧栏、实时状态指示、操作列 |
| 材料管理 | 多文件上传、实时 AI 分类、修改分类弹窗、删除后自动重跑预审 |
| AI 预审报告 | 分段展示（完整性 / 一致性 / 准入规则 / 风险信号 / 冲突），支持 PDF 导出 |
| 人工复核 | 核验区 + 决策区，三态核验项（无异议 / 误报排除 / 确认补件），状态流转建议 |
| 风控复核 | 待办队列、选中件摘要（符合项 / 存疑项 / 冲突项实时统计）、决策弹窗（通过 / 退回补件 / 拒绝） |
| 统一日志 | 后端 HTTP 请求拦截器，请求失败 Toast 全局提示 |

## 🧰 技术栈

| 分类 | 依赖 |
|---|---|
| 框架 | React 18 + TypeScript（strict） |
| 路由 | React Router DOM 6 |
| 构建 | Vite 5 + @vitejs/plugin-react |
| HTTP | fetch（自封装拦截器） |
| 样式 | 原生 CSS Modules / 分离 CSS（无 Tailwind） |

## 📁 项目目录

```
sme-credit-precheck-web/
├── index.html                      # Vite 入口 HTML
├── vite.config.ts                  # Vite 配置（代理 /api → http://127.0.0.1:8000）
├── tsconfig.json                   # TypeScript 配置（strict / noEmit）
├── playwright.config.ts            # Playwright 端到端测试配置
├── package.json
├── src/
│   ├── main.tsx                    # React 挂载点 + Router + Context 注入
│   ├── App.tsx                     # App 根组件（含 Sidebar + 路由布局）
│   ├── types.ts                    # 全局共享 TypeScript 类型
│   ├── api/                        # HTTP 请求层
│   │   ├── http.ts                 # fetch 封装 + 401 拦截 + Toast 全局提示
│   │   ├── auth.ts                 # 登录 / me
│   │   └── applications.ts         # 申请 / 材料 / 报告 / 复核 / 风控全部 endpoint
│   ├── components/                 # 通用组件
│   │   ├── Sidebar.tsx             # 左侧导航（登录 / 申请列表 / AI 预审报告 / 人工复核 / 风控复核）
│   │   ├── Stepper.tsx             # 节点式进度条
│   │   ├── Modal.tsx               # 通用模态框
│   │   ├── ConfirmModal.tsx        # 带确认按钮的二次确认弹窗
│   │   ├── Toast.tsx               # 轻量 Toast（定位全局错误提示）
│   │   └── ReportSections.tsx      # AI 预审报告分节渲染组件
│   ├── modals/                     # 业务弹窗
│   │   ├── NewAppModal.tsx         # 新建申请
│   │   ├── EditAppModal.tsx        # 编辑申请
│   │   ├── UploadModal.tsx         # 材料多文件上传
│   │   ├── CategoryModal.tsx       # 查看 / 修改材料分类（左侧放大图标 + AI 依据悬停）
│   │   ├── PreviewModal.tsx        # 材料文件内联预览
│   │   ├── PackageModal.tsx        # 「查看预审报告和材料清单」双栏弹窗
│   │   └── ProcessModal.tsx        # 风控复核决策 / 状态流转弹窗
│   ├── views/                      # 路由页面
│   │   ├── LoginView.tsx           # 登录页
│   │   ├── ListView.tsx            # 申请列表（表格 + 筛选）
│   │   ├── DetailView.tsx          # 申请详情（左侧进度条 + 中间主卡 + 右侧 AI 摘要）
│   │   ├── ReportView.tsx          # AI 预审报告完整页
│   │   ├── ReviewView.tsx          # 人工复核页（核验区 + 决策区两层结构）
│   │   └── RiskView.tsx            # 风控复核队列页
│   ├── context/                    # React Context
│   │   ├── AuthContext.tsx         # 登录态（token / user / login / logout）
│   │   └── AppContext.tsx          # 全局加载 / Toast 调度
│   ├── constants/index.ts          # 状态标签颜色 / 操作按钮文案映射等常量
│   ├── utils/index.ts              # 工具函数（日期格式化 / 脱敏展示 / 枚举映射）
│   └── styles/                     # 全局样式
│       ├── variables.css           # CSS 变量（主题色 / 间距 / 字号）
│       ├── layout.css              # 布局（侧边栏 + 主内容）
│       ├── login.css
│       ├── list.css
│       ├── detail.css
│       ├── report.css
│       ├── review.css
│       └── risk.css
└── dist/                           # 构建输出目录（npm run build 产物）
```

## 🚀 快速开始（Windows）

### 前置条件

| 依赖 | 版本 |
|---|---|
| Node.js | 18+ |
| npm | 9+ |
| 后端 | FastAPI 服务已启动在 `http://127.0.0.1:8000` |

### 一键启动（推荐）

在项目根目录执行（后端也要自动起）：

```bat
start-all.bat
```

### 手动启动

**Step 1 — 安装依赖**

```bat
cd sme-credit-precheck-web
npm install
```

`node_modules` 装好后就不用每次都装了。

**Step 2 — 确保后端已启动**

前端开发服务器通过 Vite 代理转发 `/api` → `http://127.0.0.1:8000`。
后端没起的话登录、拉列表全部 404 + Toast 报错。

```bat
cd sme-credit-precheck-backend
.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

**Step 3 — 启动前端开发服务器**

```bat
cd sme-credit-precheck-web
npm run dev
```

启动成功后自动打开：`http://localhost:5173`

### 构建生产包

```bat
npm run typecheck    # tsc --noEmit 类型检查
npm run build        # 类型检查 + 产物输出到 dist/
npm run preview      # 本地预览构建产物（http://localhost:4173）
```

部署时把 `dist/` 丢到 Nginx / Apache / 任意静态服务器即可，记得配置 `/api` 反向代理到后端。

### 后端地址变更怎么办？

改 `vite.config.ts`：

```ts
proxy: {
  '/api': {
    target: 'http://127.0.0.1:8000',   // ← 改这里
    changeOrigin: true
  }
}
```

## 🔐 角色权限

| 角色 | 说明 | 能看到什么 |
|---|---|---|
| 客户经理 | `manager` | 登录后默认进入申请列表；可新建 / 编辑 / 删除申请、上传材料、提交人工复核 |
| 风控人员 | `risk` | 登录后默认进入风控待办队列；可查看风控待办、提交风控决策 |
| 管理员 | `admin` | 超级权限，保留位 |

登录态由后端 JWT 下发后前端存在 `localStorage['token']`，所有请求自动带 `Authorization: Bearer xxx`。

## 🎨 设计要点

| 特性 | 实现 |
|---|---|
| 错误处理 | 所有 HTTP 请求失败（非 2xx）通过 `http.ts` 拦截器统一抛 Toast；401 自动跳登录 |
| 状态标签 | `constants/index.ts` 里维护，浅色底圆角胶囊（符合绿 / 不符合红 / 存疑琥珀） |
| AI 摘要 | 申请详情页右侧面板；不重复调预审接口，直接拉已落库的 report snapshot |
| 修改分类弹窗 | 左侧放大 44px 图标；右侧展示 AI 分类依据（截断 + hover tooltip）；分区把「其他」顶到最前 |
| 双栏弹窗 | 预审报告和材料清单各一 Scroll 容器，内容不会被弹窗裁切 |
| 补件来源区分 | 待补件状态旁显示来源标签（人工 / 风控），补齐后自动清空来源标记 |

## 🔧 常见问题

**Q: `npm install` 太慢？**
A: 切国内镜像：`npm config set registry https://registry.npmmirror.com`。

**Q: 前端能打开但登录一直转圈？**
A: 确认后端启动成功（`http://127.0.0.1:8000/docs` 能打开）。Vite 代理失败时浏览器 Network 面板 `/api/v1/auth/login` 会显示 502 / ECONNREFUSED。

**Q: 端口被占用？**
A: 改 `vite.config.ts` 的 `server.port`，或者 `npm run dev -- --port 5174`。

**Q: 构建后直接打开 `dist/index.html` 白屏？**
A: 浏览器 file:// 协议下 React Router 不生效。用 `npm run preview` 或挂到 Nginx 上。
