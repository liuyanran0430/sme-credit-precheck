# 政策问答 Agent 设计方案

> 版本：v2.0（按实际落地实现重写）
> 最后更新：2026-11-09
> 状态：阶段 A（后端问答核心）、阶段 B（前端问答面板）已完成并验证通过

---

## 一、定位与边界

### 1.1 定位

基于知识库 RAG 的**政策问答能力**，面向客户经理与风控人员，回答信贷政策、产品准入、材料审核、规则解释与案例参考类问题。

### 1.2 明确的边界

| 做 | 不做 |
|---|---|
| 基于知识库原文回答，答案强制标注引用 | 通用闲聊、写代码、查天气等无关问题 |
| 无关问题在分类阶段直接拒绝，**不调用 LLM** | 替代 AI 预审的规则判定、评分与结论 |
| 检索不到时明确回答「暂无内容」，不编造 | 跨客户跨申请的数据检索（不做 app_id 维度检索） |
| 单轮问答 + 有限上下文（最多 3 轮历史） | 长对话、多轮任务编排、工具调用 |

核心原则：**只做解释与检索增强，不产生新的业务结论**。

### 1.3 与现有系统的关系

```
AI 预审（analyzer.py）  ──┐
                          ├──> app/rag/kb_retriever.py ──> 四个知识库 collection
政策问答（app/qa/）     ──┘
```

两者共用同一套检索基础设施与 LLM 客户端，但**互不调用**：问答不读申请表、不写申请表、不影响申请状态。

---

## 二、总体架构

### 2.1 模块结构

```
sme-credit-precheck-backend/
└── app/
    ├── qa/                        # 政策问答（全部新增，不改动现有业务模块）
    │   ├── __init__.py            # 统一导出
    │   ├── schemas.py             # 请求/响应 Pydantic 模型
    │   ├── intent.py              # 领域分类 + 意图识别 + 检索计划
    │   ├── prompt.py              # System Prompt、Prompt 拼装、引用后处理
    │   └── service.py             # 主流程编排 + 三级降级 + LLM 调用
    ├── api/
    │   └── qa.py                  # POST /qa/ask、GET /qa/suggestions
    └── rag/
        ├── kb_retriever.py        # 知识库检索（预审与问答共用）
        ├── chroma_store.py        # chroma 向量库实现
        └── memory_store.py        # 内存向量库（测试用）
```

```
sme-credit-precheck-web/src/
├── api/qa.ts                      # askQuestion / fetchSuggestions
├── components/QaPanel.tsx         # 右侧抽屉式问答面板
├── styles/qa.css                  # 面板样式
├── types.ts                       # QaMessage / QaReference / QaResponse
├── components/Sidebar.tsx         # 新增「政策问答」入口
└── App.tsx                        # 抽屉显隐状态
```

### 2.2 数据流

```
用户提问
   │
   ├─[1] 领域分类（纯规则，0 LLM）
   │      └─ 无关 → 直接返回固定提示（不检索、不 embedding、不调 LLM）
   │
   ├─[2] 意图识别 + 检索计划（collection / where / top_k）
   │
   ├─[3] 向量检索（带 where 过滤）
   │      └─ 命中不足 → 去掉 where 重试 → 仍不足 → 关键词兜底读 YAML
   │
   ├─[4] 重排去重（意图关键词加权）
   │
   ├─[5] Prompt 拼装 → LLM 生成（要求逐条标注 [N]）
   │
   ├─[6] 引用后处理（全角归一化 → 剔除无效编号 → 只保留被引用片段）
   │
   └─[7] 返回 answer + references + confidence + used_collections
```

---

## 三、领域分类（先分类，无关问题零 LLM）

### 3.1 为什么用白名单

初版采用「黑名单排除（股票/天气/写代码…）」，实测会误判正常业务问题（如「年营收怎么算」被拒）。现改为**业务领域白名单**：

命中以下任一条件即视为相关：

1. 文本中出现产品名或产品代码（普惠小微经营贷 / 小微快贷 / 经营性抵押贷 / 科技e贷 / AP / AK / AJ / AE）
2. 文本中出现材料类别名（营业执照 / 银行流水 / 财务报表 / 纳税申报表 / 征信授权书）
3. 文本中出现规则编号（正则 `[A-Z]{2}-[HS]\d{2}`，如 `AP-H03`）
4. 文本命中业务术语词表
5. 前端或接口显式传入 `product` / `category` 上下文

业务术语词表按六组维护（见 `intent.py: _DOMAIN_TERMS`）：

| 分组 | 示例词 |
|---|---|
| 业务主体 | 信贷、贷款、授信、借款、普惠、小微、企业、商户、个体、客户、经营 |
| 产品与要素 | 产品、额度、利率、期限、还款、逾期、负债、担保、抵押、质押、保证、征信、评级 |
| 政策与制度 | 政策、制度、规定、办法、指引、合规、监管 |
| 材料 | 材料、清单、流水、对账、报表、财报、资产负债表、利润表、纳税、税务、发票、营业执照、授权书、验资、工商、登记、合同、订单、开户、账户、回款、进账 |
| 财务指标 | 营收、营业收入、收入、利润、净利润、资产、净资产、成本、成立年限、注册资本、法定代表人、股东、行业 |
| 流程与规则 | 准入、预审、复核、风控、审批、申请、补件、退回、驳回、规则、硬规则、弱规则、评分、等级、阈值、条件 |
| 案例与问答 | 案例、先例、常见问题、faq、解释 |

### 3.2 无关问题的响应

```
我仅回答与信贷政策相关制度问题，请说明你要咨询的信贷政策、产品、材料和复核规则
```

- 文案可通过 `.env` 的 `QA_OUT_OF_SCOPE_MSG` 覆盖
- 响应中 `confidence = 0.0`、`references = []`、`fallback_used = false`
- 实测耗时 **0.0–0.1ms**，且单测断言 `_retrieve_with_fallback` 与 `get_client` 均未被调用

---

## 四、意图识别与检索计划

### 4.1 五类意图 + 兜底

| 意图 | kind | 触发关键词（节选） | 检索 collection | 过滤条件 |
|---|---|---|---|---|
| 产品准入 | `product_admission` | 准入、条件、要求、门槛、能不能、可不可以、额度、年限、评分、等级 | `kb_policy` → `kb_rule_config` | `where={"product": <产品名>}` |
| 材料审核 | `material_review` | 材料、清单、流水、报表、营业执照、征信、纳税、发票、签章、有效期、缺件 | `kb_material_review` | `where={"category": <类别编码>}` |
| 规则解释 | `rule_explain` | 规则、编号、什么意思、为什么、原因、依据、解释、条款 | `kb_rule_config` → `kb_policy` | `where={"rule_id": <编号>}` |
| 案例参考 | `case_ref` | 案例、先例、之前、有没有类似、常见问题、FAQ | `kb_cases` | 无（按产品过滤，若有） |
| 操作指引 | `operation_guide` | 怎么做、如何、流程、步骤、在哪、入口、提交、上传 | `kb_policy` + `kb_material_review` | 按上下文过滤 |
| 通用兜底 | `general` | 已通过领域分类但未命中细分关键词 | 四个 collection 全搜 | 按上下文过滤 |

### 4.2 意图置信度

关键词得分按命中数量累加，产品/材料/规则编号精确命中额外加权，最终归一化到 `[0, 1]`。置信度参与最终答案置信度计算（占 60% 权重）。

---

## 五、检索与降级

### 5.1 三级降级链

```
第 1 级：按意图检索 + where 元数据过滤（product / category / rule_id）
   ↓ 命中 < 2
第 2 级：同 collection 去掉 where 再检索
   ↓ 仍为空
第 3 级：关键词兜底（直接读 knowledge_base 下的 YAML/Markdown，按规则编号/产品名匹配）
   ↓ 仍为空
返回「知识库中暂无相关内容，请联系风控运营团队补充。」
```

`fallback_used = true` 表示走了第 2 级及之后，前端据此显示「已启用降级策略」提示（**仅在有引用时显示**，避免与「暂无内容」同时出现）。

### 5.2 索引不可用时的短路

`kb_retriever` 在检索前先查 collection 的 `count`：

- `count == 0` → 只输出一次 WARNING（「知识库索引为空…本次跳过 RAG 检索」），**不触发 embedding 调用**，直接返回空结果
- embedding 或检索抛异常 → 记录 WARNING 并进入 300 秒冷却期（`KB_RAG_COOLDOWN_SECONDS`），冷却期内直接跳过，不反复打接口

该机制保证：**索引没建或 Key 没配时，问答功能表现为「暂无内容」，而不是报错或卡顿。**

### 5.3 结果重排

在向量相似度基础上叠加意图关键词命中加权（每个命中 +0.05），再按 `id` 去重，取 `QA_MAX_HITS`（默认 5）条。

### 5.4 数据隔离

问答只检索通用知识库，**不带 app_id 维度**，不触碰任何客户材料与申请数据，天然不存在跨客户泄漏风险。

---

## 六、Prompt 与引用后处理

### 6.1 System Prompt 约束

1. 只能依据提供的知识库片段回答，不得引入片段外的内容
2. 每句结论后必须标注来源编号，如 `[1]`、`[2]`
3. 片段不足以回答时，明确说明「知识库中未收录」，不得猜测
4. 区分「硬规则（直接拒绝）」与「弱规则（影响评分）」时须原样表述
5. 涉及金额、比例、期限等数值必须与片段完全一致
6. 回答使用简体中文，条理清晰，不超过 500 字
7. 不得输出任何客户敏感信息

### 6.2 引用后处理

LLM 实际输出常出现全角引用 `【2】`，因此：

```python
_FULLWIDTH_CITATION_RE = re.compile(r"【(\d{1,2})】")

def normalize_citations(text: str) -> str:
    """把全角引用【N】统一成半角[N]。"""
    return _FULLWIDTH_CITATION_RE.sub(r"[\1]", text)
```

处理顺序：

1. `normalize_citations` 全角 → 半角
2. 扫描 answer 中所有 `[N]`，剔除越界编号
3. **只保留被实际引用的片段**构造 `references`（未被引用的命中不出现在引用列表）
4. 按 `QA_MAX_ANSWER_CHARS`（默认 1500）截断
5. 前端渲染时再做一次全角兼容（`/(?:\[|【)(\d{1,2})(?:\]|】)/`），把编号转成上标

### 6.3 LLM 失败兜底

LLM 调用异常时，不返回 500，而是把命中的前 3 条原文摘要拼接后返回，并在答案中标明「以下为知识库原文摘录」。主流程不中断。

### 6.4 置信度

```
confidence = 0.6 × 意图置信度 + 0.4 × 命中片段平均相似度
```

无引用时统一为 `0.0`。

---

## 七、API 契约

### 7.1 提问

```
POST /api/v1/qa/ask
Authorization: Bearer <token>       # manager / risk 两种角色均可
Content-Type: application/json
```

请求：

```json
{
  "question": "普惠小微经营贷对成立年限有什么要求？",
  "product": "普惠小微经营贷",
  "category": null,
  "chat_history": [
    { "role": "user", "content": "..." },
    { "role": "assistant", "content": "..." }
  ]
}
```

| 字段 | 必填 | 说明 |
|---|---|---|
| `question` | 是 | 问题文本，最长 500 字 |
| `product` | 否 | 产品上下文，前端在申请详情页自动注入 |
| `category` | 否 | 材料类别上下文 |
| `chat_history` | 否 | 历史对话，服务端只取最近 `QA_MAX_HISTORY_TURNS`（默认 3）轮 |

响应：

```json
{
  "answer": "普惠小微经营贷要求企业成立年限不少于 2 年 [1]，同时近 12 个月流水进账需覆盖年营收的 70% [2]。",
  "references": [
    {
      "index": 1,
      "collection": "kb_rule_config",
      "source": "03_规则配置/准入规则/rule_普惠小微经营贷.yaml",
      "rule_id": "AP-H02",
      "product": "普惠小微经营贷",
      "excerpt": "规则 AP-H02（企业成立年限）… 判定条件：成立年限 >= 2"
    }
  ],
  "confidence": 0.78,
  "used_collections": ["kb_policy", "kb_rule_config"],
  "fallback_used": false,
  "model": "deepseek-chat",
  "request_id": "qa-20261109-xxxx"
}
```

### 7.2 推荐问题

```
GET /api/v1/qa/suggestions
```

返回 6 条静态问题气泡，覆盖产品准入、材料审核、规则解释、案例参考四类，帮助用户快速上手。

### 7.3 异常与开关

| 场景 | 行为 |
|---|---|
| `QA_ENABLED=false` | 直接返回「政策问答功能当前未启用」 |
| 问题为无关问题 | 200 + 固定提示语，`confidence=0` |
| 知识库无命中 | 200 + 「知识库中暂无相关内容…」 |
| LLM 异常 | 200 + 命中原文摘录，仅 WARNING 日志 |
| 未登录 | 401（复用现有鉴权） |

---

## 八、配置项

`.env` 中与问答相关的配置：

| 配置 | 默认值 | 说明 |
|---|---|---|
| `QA_ENABLED` | `true` | 问答功能总开关 |
| `QA_MAX_HITS` | `5` | 参与 Prompt 的最大片段数 |
| `QA_MAX_HISTORY_TURNS` | `3` | 保留的历史对话轮数 |
| `QA_MAX_ANSWER_CHARS` | `1500` | 答案最大字符数 |
| `QA_OUT_OF_SCOPE_MSG` | 见 §3.2 | 无关问题提示语 |
| `QA_NO_RESULT_MSG` | 知识库中暂无相关内容… | 无命中提示语 |
| `KB_RAG_ENABLED` | `true` | 知识库检索总开关（预审与问答共用） |
| `KB_RAG_TOP_K` | `3` | 预审场景的检索条数 |
| `KB_RAG_BASIS_MAX_CHARS` | `300` | 预审报告政策依据的截断长度 |
| `KB_RAG_COOLDOWN_SECONDS` | `300` | 检索失败后的冷却时间 |
| `VECTOR_STORE_BACKEND` | `chroma` | 向量库后端（memory / chroma / milvus） |
| `VECTOR_STORE_PERSIST_DIR` | `data/chroma` | 持久化目录，相对后端目录解析 |
| `EMBEDDING_MODEL` | `BAAI/bge-m3` | Embedding 模型 |
| `EMBEDDING_DIMENSIONS` | `0` | **0 表示不传 dimensions 参数** |
| `EMBEDDING_API_KEY` | — | Embedding 独立密钥（不能复用 DeepSeek 的 Key） |
| `EMBEDDING_BASE_URL` | `https://api.siliconflow.cn/v1` | Embedding 服务地址 |

---

## 九、知识库与索引

### 9.1 四个 collection

| collection | 来源目录 | 块数 | 关键 metadata |
|---|---|---|---|
| `kb_policy` | `01_信贷政策/**/*.md` | 46 | source、product、product_code、section、rule_id、kind |
| `kb_material_review` | `02_材料审核标准/**/*.md` | 43 | source、category、check_item、section、rule_id |
| `kb_rule_config` | `03_规则配置/**/*.yaml` | 73 | source、product、version、rule_id、kind |
| `kb_cases` | `04_案例与FAQ/**/*.md` | 10 | source、case_type、product |

合计 172 块，由 `scripts/rebuild_vector_index.py` 生成。

### 9.2 重建步骤

```powershell
# 1. 先停后端，避免 chroma 并发访问
# 2. 在项目根目录执行
sme-credit-precheck-backend\.venv\Scripts\python.exe scripts\rebuild_vector_index.py --reset
# 3. 重启后端
```

脚本参数：`--dry-run` 只统计不写库、`--collection <name>` 只重建单个、`--batch-size` 控制 embedding 批量。

---

## 十、前端实现

### 10.1 交互形态

右侧抽屉面板（宽 420px，768px 以下全屏），从申请详情页与任意页面均可打开，不打断当前操作。

| 元素 | 行为 |
|---|---|
| 侧边栏「政策问答」 | 打开抽屉 |
| 顶部上下文条 | 在申请详情页自动显示「当前产品：普惠小微经营贷」，可一键清除 |
| 推荐问题气泡 | 点击直接提问 |
| 输入框 | Enter 发送，Shift+Enter 换行 |
| 引用卡片 | 折叠展示「来源文件 / 规则编号 / 原文摘录」，点击展开 |
| 降级标签 | 仅在 `fallback_used && references.length > 0` 时显示 |

### 10.2 上下文注入

`App.tsx` 维护 `showQa` 状态；进入 `/detail/:id` 时，从已加载的申请列表取出该申请的 `product`，通过 props 传入 `QaPanel`，问答时自动带上 `product` 字段，使「这个产品成立年限要求是什么」这类指代问题也能正确路由到对应产品规则。

### 10.3 渲染

- 答案按空行分段渲染，`- ` 开头转列表
- 引用编号渲染为 `sup` 上标，点击滚动定位到对应引用卡片
- 历史对话只发送最近 6 条（对应后端 3 轮）

---

## 十一、验证结果

### 11.1 单元测试

`tests/test_qa_agent.py`，**42 个用例全部通过**（纯 mock，不依赖 MySQL）：

| 分组 | 覆盖内容 |
|---|---|
| 领域分类 | 无关问题 4 类、业务术语 5 类不误判、闲聊+业务关键词时业务优先 |
| 意图识别 | 五类意图 + 规则编号 / 产品 / 材料上下文、检索计划 where 生成 |
| Schema | 字段校验、长度上限、未知字段拒绝 |
| Prompt | 上下文拼装、历史截断、引用编号校验、全角归一化、答案截断 |
| Service | 范围外短路（断言不检索不调 LLM）、无命中、LLM 异常兜底、三级降级、开关关闭 |

### 11.2 端到端实测（真实 chroma 索引 + 真实 LLM）

| 问题 | 引用数 | 命中来源 |
|---|---|---|
| 企业成立不满 2 年能做什么产品？ | 5 | rule_经营性抵押贷.yaml、科技e贷.md、普惠小微经营贷.md |
| 普惠小微经营贷对成立年限有什么要求？ | 5 | rule_普惠小微经营贷.yaml |
| 银行流水需要覆盖几个月？ | 3 | 02_材料审核标准/银行流水审核要点.md |
| AP-H03 不满足会怎么样？ | 4 | rule_普惠小微经营贷.yaml（rule_id 精确命中） |
| 你好 / 今天天气怎么样 / 帮我写代码 | 0 | 分类阶段直接拒绝，0ms，0 LLM 调用 |

### 11.3 构建

前端 `npm run build`（`tsc --noEmit && vite build`）通过。

---

## 十二、已知约束与避坑

| 问题 | 现象 | 处理 |
|---|---|---|
| bge-m3 不支持 `dimensions` | embedding 返回 400，code 20015，索引写入 0 条，问答全量降级 | `EMBEDDING_DIMENSIONS=0`，仅当 `> 0` 时才传该参数 |
| DeepSeek 无 embedding 接口 | 复用 LLM Key 必然失败 | `EMBEDDING_API_KEY` / `EMBEDDING_BASE_URL` 独立配置（SiliconFlow） |
| chroma 并发访问 | `Error creating hnsw segment reader: Nothing found on disk` | 重建索引前先停后端；不要与运行中的服务同时写同一目录 |
| LLM 输出全角引用 | 引用全部被判为无效，前端引用卡片空白 | 后端 `normalize_citations` 归一化，前端正则同时兼容全角 |
| 索引为空仍调用 embedding | 每次提问都打一次 embedding 接口，耗时且浪费配额 | `_index_has_data` 先查 count，为 0 只告警一次并跳过 |
| 黑名单式分类误伤 | 「年营收怎么算」被判为无关问题 | 改为业务领域白名单（§3.1） |
| 降级标签误导 | 「暂无内容」和「已启用降级策略」同时出现 | 仅在有引用时展示降级标签 |

---

## 十三、后续演进（阶段 C）

1. **真实数据验证**：替换 `.env` 中 `EMBEDDING_API_KEY` 为真实密钥 → 重建索引 → 用 30 条真实业务问题做召回率与引用准确率评测
2. **Prompt 调优**：基于评测集的错误样本迭代 System Prompt，重点治理「引用编号错配」「跨产品串味」
3. **流式输出**：`/qa/ask` 增加 SSE 版本，改善首字延迟
4. **问题埋点**：记录未被知识库覆盖的高频问题，反哺知识库建设
5. **多轮追问**：在 `chat_history` 基础上支持指代消解（「那它呢」→ 沿用上一轮产品）

以上均属增强项，不影响当前已交付功能的可用性。
