# 小微企业授信智能预审系统 — 后端

基于 **FastAPI + SQLAlchemy + MySQL** 构建的授信申请智能预审后端服务，提供认证、申请管理、材料上传与 OCR、AI 预审（规则引擎 + LLM 辅助字段抽取）、人工复核、风控复核、PDF 预审报告导出等能力。

## ✨ 核心能力

| 模块 | 说明 |
|---|---|
| 认证 | JWT 登录态，角色权限：客户经理 / 风控人员 / 管理员 |
| 申请管理 | 创建、编辑、删除、分页查询；申请编号按贷款类型独立递增 |
| 材料上传 | 多文件上传、OCR 识别（PyMuPDF + RapidOCR）、AI 自动分类（LangChain + OpenAI 兼容接口） |
| AI 预审 | 材料完整性 + 一致性校验 + 产品准入规则逐条匹配；每款产品一套独立 YAML 规则文件；分段耗时日志 |
| 人工复核 | 核验清单、决策结论（通过 / 退回补件 / 否决），状态流转 |
| 风控复核 | 独立风控队列、决策（通过 / 退回补件 / 拒绝）；补件来源区分（manual / risk） |
| AI预审报告导出 | PyMuPDF 生成，落库缓存避免重复生成 |
| 统一日志 | 按天滚动文件（`logs/app-YYYY-MM-DD.log`）+ 控制台双输出，协程安全的业务上下文注入，敏感脱敏（信用代码 / 金额 / OCR 文本） |
| LLM 封装 | `app/llm/` — 统一接口（chat / structured / embed），LangChain OpenAI 兼容实现 + Stub fallback |
| RAG 向量库 | `app/rag/` — 统一接口（upsert / query / delete），InMemory（零依赖）+ Chroma（持久化）双实现 |

## 🧰 技术栈

| 分类 | 依赖 |
|---|---|
| Web | FastAPI ≥ 0.115, Uvicorn ≥ 0.30 |
| ORM | SQLAlchemy ≥ 2.0 |
| 数据库 | MySQL 8.0 + PyMySQL |
| 校验 | Pydantic ≥ 2.7 |
| 认证 | PyJWT ≥ 2.8, python-dotenv |
| OCR / 文档 | RapidOCR ≥ 3.0, PyMuPDF ≥ 1.24 |
| LLM / 分类 / 封装 | LangChain ≥ 0.3, LangChain-OpenAI ≥ 0.2（OpenAI 兼容接口，支持 DeepSeek / 通义 / Ollama） |
| 向量库 | ChromaDB（可选，不配则用内置 InMemoryStore） |
| 迁移 | Alembic |
| 测试 | pytest ≥ 8.2, httpx |

## 🏗️ 分层架构

```
api/            路由层       只收发请求 + 参数校验 + 调 services，零 SQL
  └── deps.py   依赖注入     get_db / get_current_user / get_application_or_404
repositories/   数据层       数据库读写唯一入口（Application / Material / Report / Review / User）
services/       业务层       流程编排 + 规则引擎（analyzer / classifier / extractor / report_pdf / init_db）
llm/            LLM 层       chat / structured / embed 统一接口 + LangChain / Stub 实现 + 单例工厂
rag/            RAG 层       upsert / query / delete 统一接口 + InMemory / Chroma 实现 + 单例工厂
models/         ORM 模型     Base / SessionLocal + 业务模型 + 枚举 + Mixin
schemas/        Pydantic     请求 / 响应 / DTO
core/           基础设施     config / security / logging / exceptions
```

**关键设计约束**：
- **repositories 是 DB 唯一入口** — api/services 层禁止直接 `db.scalar/execute/add`
- **llm 和 rag 解耦** — VectorStore 不 import LLMClient，调用方自己 embed 完传向量进去
- **跨层零循环 import** — llm/rag 只 import core/config，不 import models/services/api

## 📁 项目目录

```
sme-credit-precheck-backend/
├── app/
│   ├── main.py                     # FastAPI 入口（lifespan、CORS、路由注册、启动自动建表）
│   │
│   ├── core/                       # 跨领域基础设施（不依赖任何业务层）
│   │   ├── config.py               # pydantic-settings 环境变量加载（含 LLM/RAG 配置）
│   │   ├── security.py             # JWT 签发/验签 + 密码哈希
│   │   ├── exceptions.py           # BusinessException 统一业务异常
│   │   └── logging.py              # 按天滚动文件 + 控制台双输出、LogContext 上下文注入、敏感脱敏
│   │
│   ├── api/                        # 路由层（扁平结构，无 v1/ 嵌套）
│   │   ├── router.py               # api_router 拼装入口
│   │   ├── deps.py                 # Depends：get_db / get_current_user / get_application_or_404
│   │   ├── auth.py                 # POST /auth/login、GET /auth/me
│   │   ├── applications.py         # 申请 CRUD + 分页 + 级联删除
│   │   ├── materials.py            # 材料上传 / 分类 / 修改 / 删除（含 OCR + AI 自动分类）
│   │   ├── reports.py              # AI 预审查询 / 触发 / PDF 导出
│   │   ├── reviews.py              # 人工复核提交
│   │   └── risk.py                 # 风控复核队列 / 决策（独立权限路由）
│   │
│   ├── repositories/               # 数据访问层 — DB 读写唯一入口
│   │   ├── application.py          # ApplicationRepository：list_paginated / create / delete_cascade / next_app_no
│   │   ├── material.py             # MaterialRepository：list_by_app / get_by_id_and_app / update_fields
│   │   ├── report.py               # ReportRepository：upsert_for_app（commit=False 支持跨表同事务）
│   │   ├── review.py               # ReviewRepository：create_manual / create_risk / list_risk_queue
│   │   └── user.py                 # UserRepository：get_by_username / get_by_id
│   │
│   ├── services/                   # 业务流程编排
│   │   ├── init_db.py              # 启动自动建表（Base.metadata.create_all）
│   │   ├── analyzer.py             # AI 预审核心：completeness / consistency / rule_matching / 状态流转
│   │   ├── classifier.py           # 材料 AI 分类
│   │   ├── extractor.py            # OCR 文本提取
│   │   ├── report_pdf.py           # PDF 报告生成（PyMuPDF + 缓存）
│   │   └── rule_config.py          # YAML 规则文件加载
│   │
│   ├── llm/                        # LLM 调用封装
│   │   ├── base.py                 # LLMClient 抽象基类 + LLMResponse 数据结构
│   │   ├── langchain_client.py     # LangChain ChatOpenAI 实现（chat / structured / embed）
│   │   ├── stub_client.py          # 无 API Key 时 fallback（确定性占位回复）
│   │   └── factory.py              # get_client() 单例工厂
│   │
│   ├── rag/                        # 向量库封装
│   │   ├── base.py                 # VectorStore 抽象基类 + Document / QueryResult
│   │   ├── memory_store.py         # 进程内 dict + cosine 相似度（零依赖，默认）
│   │   ├── chroma_store.py         # ChromaDB 实现（pip install chromadb 即用）
│   │   └── factory.py              # get_vector_store() 单例工厂
│   │
│   ├── models/                     # SQLAlchemy ORM 模型
│   │   ├── base.py                 # Base = declarative_base()
│   │   ├── __init__.py             # 集中 import 所有模型（让 Alembic / init_db 发现全库表）
│   │   ├── session.py              # engine + SessionLocal（SQLAlchemy 连接池工厂）
│   │   ├── application.py          # Application 表
│   │   ├── material.py             # Material 表
│   │   ├── report.py               # AiReport 表
│   │   ├── review.py               # ManualReview + RiskReview 表
│   │   ├── user.py                 # User 表
│   │   ├── enums.py                # 枚举（申请状态 / 复核结论 / 材料分类等）
│   │   └── mixins.py               # 公共 Mixin（created_at / updated_at 等）
│   │
│   └── schemas/                    # Pydantic 请求 / 响应 DTO
│       ├── application.py          # 申请创建 / 更新 / 查询参数
│       ├── material.py             # 材料上传 / 更新 / 分类
│       ├── report.py               # AI 预审查询 / 结论
│       ├── review.py               # 人工复核 / 风控复核提交
│       ├── user.py                 # 登录 / Token 响应
│       ├── ai_analysis.py          # AI 预审分段结果
│       ├── ai_classification.py    # AI 材料分类结果
│       ├── ai_errors.py            # AI 预审错误项 DTO
│       └── common.py               # 通用分页 / 状态等 schema
│
├── alembic/                        # Alembic 迁移（生产环境推荐用迁移管理版本）
│   ├── env.py
│   ├── script.py.mako
│   └── versions/                   # 迁移版本文件（空目录有 .gitkeep）
├── rules/                          # 【已废弃】原运行时规则目录，规则现从 knowledge_base/03_规则配置/准入规则/ 读取
│   ├── README_规则说明.yaml
├── scripts/
│   ├── create_user.py              # 批量创建测试账号
│   └── export_openapi.py           # 导出 openapi.json
├── tests/
│   ├── conftest.py                 # logging 隔离 fixture
│   ├── test_health.py              # 健康检查 + DB 连通性
│   ├── test_logging_unit.py        # LogContext / 脱敏 / Formatter 单元测试
│   ├── test_logging_integration.py # setup_logging / handler / 文件输出集成测试
│   └── test_logging_endpoints.py   # 登录 / 申请 / 预审 / 复核 / PDF 日志端到端
├── .env.example                    # 环境变量模板
├── requirements.txt                # 生产依赖
├── requirements-dev.txt            # 开发依赖（pytest / httpx）
└── alembic.ini
```

## 🚀 快速开始（Windows）

### 前置条件

| 依赖 | 版本 | 说明 |
|---|---|---|
| Python | 3.11+ | **必须用 `.venv\Scripts\python.exe`**，Windows 下 `python3` 是应用商店占位符 |
| MySQL | 8.0+ | 服务名默认 `MySQL`，如 `MySQL80` 可在 `start-all.bat` 第一个参数传入 |
| pip | — | 虚拟环境内自动安装依赖 |

### 一键启动（推荐）

在项目根目录执行，自动完成 MySQL 启动 / 虚拟环境创建 / 依赖安装 / 后端 & 前端启动。

```bat
:: 项目根目录 e:\AI全栈\workspace\sme-credit-precheck
start-all.bat
```

脚本会：
1. 检测 MySQL 服务并启动
2. 创建 `sme-credit-precheck-backend\.venv` 并安装依赖
3. 端口占用检测 + 后端 Uvicorn（`app.main:app --reload --port 8000`）
4. 端口占用检测 + 前端 Vite（`--port 5173`）
5. 自动打开 `http://localhost:5173`

停止服务：`stop-all.bat`（默认不关闭 MySQL）。

### 手动分步启动

**Step 1 — 配置环境变量**

```bat
copy sme-credit-precheck-backend\.env.example sme-credit-precheck-backend\.env
:: 然后编辑 .env，重点改 DATABASE_URL 和 AUTH_SECRET_KEY
```

最少需要改这 4 项：

```env
DATABASE_URL=mysql+pymysql://root:你的密码@127.0.0.1:3306/sme_credit?charset=utf8mb4
AUTH_SECRET_KEY=随便写个32位以上的随机字符串
OPENAI_API_KEY=你的LLM Key（材料分类用，支持 OpenAI / DeepSeek / 通义 / Ollama）
LLM_MODEL=gpt-4o-mini
```

**LLM / RAG 可选配置**（不配即 fallback）：

```env
# LLM — 不配 API Key 自动用 StubClient（确定性占位回复）
LLM_PROVIDER=langchain-openai
LLM_BASE_URL=https://api.openai.com/v1        # 换 Ollama: http://localhost:11434/v1
LLM_MODEL=gpt-4o-mini                        # 换 Ollama: qwen2.5

# RAG — 默认 InMemoryStore（零依赖），配 chroma 启用磁盘持久化
VECTOR_STORE_BACKEND=memory
VECTOR_STORE_PERSIST_DIR=data/chroma
VECTOR_STORE_COLLECTION=credit_rules
```

**Step 2 — 创建虚拟环境 & 安装依赖**

```bat
cd sme-credit-precheck-backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
pip install -r requirements-dev.txt   :: 只在开发 / 跑测试时需要
```

**Step 3 — 启动后端（自动建表）**

```bat
.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

开发模式首次启动自动 `create_all()` 建表（`services/init_db.py`）。生产环境推荐走 Alembic 迁移：

```bash
alembic upgrade head
```

启动成功后：
- API 根：`http://127.0.0.1:8000`
- Swagger 文档：`http://127.0.0.1:8000/docs`
- ReDoc：`http://127.0.0.1:8000/redoc`

**Step 4 — 初始化测试账号**

```bat
:: 客户经理 + 风控人员
.venv\Scripts\python.exe scripts\create_user.py
```

### 运行测试

```bat
cd sme-credit-precheck-backend
.venv\Scripts\python.exe -m pytest tests/ -v
```

### 查看日志

```powershell
Get-Content logs\app-$(Get-Date -Format yyyy-MM-dd).log -Tail 50 -Wait
```

## 🌐 API 路由速查

| 前缀 | 鉴权 | 说明 |
|---|---|---|
| `/api/auth/*` | 免鉴 | 登录 / me |
| `/api/applications/*` | 需登录 | 申请 CRUD |
| `/api/applications/{app_no}/materials/*` | 需登录 | 材料上传 / 分类 / 修改 / 删除 |
| `/api/applications/{app_no}/report/*` | 需登录 | AI 预审查询 / 触发 / PDF 导出 |
| `/api/applications/{app_no}/reviews/*` | 需登录 | 人工复核记录查询 + 提交 |
| `/api/risk/{app_no}/decision` | 需登录 | 风控复核提交（**仅 risk / admin**） |
| `/api/risk/queue` | 需 risk / admin | 风控待办队列 |
| `/api/risk/{app_no}/reviews` | 需登录 | 风控复核记录（**独立只读路由**） |

## 🔐 日志系统

后端内置统一日志基础设施（58 条测试覆盖）：

| 特性 | 实现 |
|---|---|
| 协程安全 | `contextvars.ContextVar`（不是 `threading.local`），FastAPI async endpoint 不串上下文 |
| 自动注入 | `with LogContext(app_no=..., user=...)` 包裹业务代码，所有 logger 自动带 ctx |
| 双输出 | 控制台（开发看）+ 按天滚动文件（午夜切新文件，保留 30 天） |
| 敏感脱敏 | `mask_credit_code`、`mask_amount`、不记录完整 OCR 文本 |
| AI 预审分段耗时 | completeness → consistency → rule_matching → risk_summary → conflicts → summary |

## 🧪 LLM / RAG 快速上手

```python
from app.llm import get_client
from app.rag import get_vector_store, Document

# LLM —— chat / structured / embed 三接口全有
client = get_client()                               # LangChainClient 单例
reply = client.chat("小微企业经营贷要求是什么？")
vector = client.embed(["年报必须盖章的规定"])[0]

# RAG —— 调用方自己 embed 完传向量进去（解耦 LLM 和 VectorStore）
vs = get_vector_store()                             # InMemoryStore 单例
vs.upsert([
    Document(id="r1", text="...规则原文...", vector=vector, metadata={"type": "rule"}),
], collection="credit_rules")

# 相似度查询
results = vs.query(client.embed(["经营贷对年报的要求"])[0], top_k=3, collection="credit_rules")
```

## 🔧 常见问题

**Q: `python3` 命令不可用？**
A: Windows 下 `python3` 是应用商店占位符，直接用 `.venv\Scripts\python.exe` 或 `python`。

**Q: MySQL 已连接但建表失败？**
A: 确认 MySQL 版本 ≥ 8.0、字符集 utf8mb4、用户权限（CREATE / INSERT / UPDATE / DELETE）。

**Q: LLM 没配会不会报错？**
A: OCR（RapidOCR 本地）+ 规则匹配（纯 YAML）不依赖 LLM；仅材料分类用 LangChain。没配 API Key 自动 fallback StubClient（确定性占位回复），分类会兜底为 `other`。

**Q: 测试里 `test_health.py` 报 `ConnectionResetError`？**
A: MySQL 服务可能短暂掉线，重启 `net start MySQL` 即可。
