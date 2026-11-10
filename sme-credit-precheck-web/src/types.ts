/**
 * 全局共享类型定义
 *
 * 分为两类：
 * 1. 后端原始数据结构（*Row）—— 字段名与接口返回保持一致，全部可选以兼容历史数据；
 * 2. 前端归一化结构（Application / Material 等）—— 供组件直接消费。
 */

export type Role = 'manager' | 'risk' | 'admin'

export interface User {
  username?: string
  full_name: string
  role: Role
}

/** 申请状态 */
export type ApplicationStatus =
  | 'check'
  | 'precheck'
  | 'supplement'
  | 'manual'
  | 'risk'
  | 'approved'
  | 'rejected'

/** 预审结论 */
export type ConclusionKey = 'pass' | 'attention' | 'forbidden' | 'manual'

/** 补件来源：manual=人工复核退回，risk=风控退回 */
export type SupplementSource = 'manual' | 'risk'

/** 后台处理阶段：checking=材料检查中，analyzing=AI 预审中 */
export type ProcessingStage = 'checking' | 'analyzing'

/**
 * 后端返回的申请记录（GET /applications、POST /applications 等）
 */
export interface ApplicationRow {
  id?: number
  app_no: string
  company_name?: string
  credit_code?: string | null
  amount?: number
  product?: string
  status?: ApplicationStatus
  manager_name?: string | null
  ai_summary?: string | null
  supplement_note?: string | null
  supplement_source?: SupplementSource | null
  risk_returned?: boolean | null
  conclusion?: ConclusionKey | null
  created_at?: string | null
  sla_deadline?: string | null
  can_precheck?: boolean
  precheck_disabled_reason?: string | null
  [key: string]: unknown
}

/**
 * 前端归一化后的申请对象（normalizeApplication 的输出）
 */
export interface Application {
  id: string
  dbId?: number
  company: string
  creditCode: string
  amount: number
  product: string
  status: ApplicationStatus
  manager: string
  summary: string
  supplementNote: string
  supplementSource: SupplementSource | null
  riskReturned: boolean
  conclusion: ConclusionKey | null
  submittedAt?: string | null
  slaDeadline?: string | null
  createdAt?: string | null
  ai: string
  dti: number | null
  gap: number | null
  passRate: number | null
  sla: string
  slaLevel: string
  submitDate: string
  upgradeReason: string
  archived: boolean
  canPrecheck: boolean
  precheckDisabledReason: string | null
}

/** 后端返回的材料记录 */
export interface MaterialRow {
  id: number
  file_name?: string | null
  category?: string | null
  version?: string | null
  created_at?: string | null
  status?: string | null
  confidence?: number | null
  reason?: string | null
  [key: string]: unknown
}

/** 前端归一化后的材料项 */
export interface Material {
  id: number
  name: string
  category: string
  ver: string
  update: string
  status: string
  confidence: number | null
  reason: string
  files: number
}

/** 材料分类配置项 */
export interface MaterialCategory {
  key: string
  label: string
  icon: string
}

/** 申请状态展示配置 */
export interface StatusMeta {
  label: string
  cls: string
}

/** 全量状态统计（不受筛选条件影响） */
export type StatusCounts = Record<string, number>

/** 一致性校验结果状态 */
export type ConsistencyStatus = 'pass' | 'fail' | 'uncertain'

export interface ConsistencyValue {
  source: string
  value: string
}

export interface ConsistencyCheck {
  check_item: string
  status: ConsistencyStatus
  severity: string
  values?: ConsistencyValue[]
  suggestion?: string | null
}

export interface Consistency {
  checks?: ConsistencyCheck[]
  [key: string]: unknown
}

export interface CompletenessCategory {
  category: string
  label: string
  count: number
  required: boolean
  satisfied: boolean
  requirement?: string | null
}

export interface CompletenessIssue {
  type?: string
  message: string
}

export interface Completeness {
  categories?: CompletenessCategory[]
  issues?: CompletenessIssue[]
  missing?: string[]
  [key: string]: unknown
}

export type RuleResultStatus = 'pass' | 'fail' | 'uncertain'
export type RuleKind = 'hard' | 'soft'

export interface RuleEvidence {
  source?: string
  detail?: string
  [key: string]: unknown
}

export interface RuleItem {
  rule_id: string
  rule_name: string
  kind: RuleKind
  result: RuleResultStatus
  actual?: string | null
  expected?: string | null
  detail?: string | null
  /** 知识库政策依据原文（RAG 检索，仅用于解释） */
  basis?: string | null
  /** 字段缺失时的材料审核要点提示（RAG 兜底） */
  hint?: string | null
  evidence?: RuleEvidence | null
}

export interface RuleResults {
  score?: number
  level?: string
  level_label?: string
  total_count?: number
  pass_count?: number
  uncertain_count?: number
  hard_fail_count?: number
  soft_fail_count?: number
  rules?: RuleItem[]
}

export type RiskLevel = 'high' | 'medium' | 'low'

export interface RiskSignal {
  signal_id: string
  category: string
  title: string
  level: RiskLevel
  suggestion?: string | null
  evidence?: RuleEvidence | null
}

export interface ConflictItem {
  type: string
  reason: string
  value?: string
  source?: string
  field?: string
  confidence?: number
  rules?: string[]
}

/** AI 预审报告 */
export interface Report {
  id?: number
  app_no?: string
  conclusion?: ConclusionKey
  summary?: string | null
  /** AI 解读文本（LLM 转述预审快照，随报告重新生成而覆盖） */
  interpretation_text?: string | null
  pass_rate?: number | null
  version?: string | null
  rule_version?: string | null
  created_at?: string | null
  completeness?: Completeness | null
  consistency?: Consistency | null
  rule_results?: RuleResults | null
  risk_signals?: RiskSignal[] | null
  conflicts?: ConflictItem[] | null
  [key: string]: unknown
}

/** 人工复核 / 风控复核记录 */
export interface ReviewRecord {
  reviewer?: string
  decision?: string
  comment?: string | null
  [key: string]: unknown
}

/** 异步任务提交响应 */
export interface TaskSubmitResponse {
  request_id: string
  app_no: string
}

/** 异步任务状态 */
export interface TaskStatus {
  request_id: string
  task_type?: string
  app_no?: string
  status: 'running' | 'done' | 'failed'
  error?: string | null
}

/** 申请列表接口返回 */
export interface ApplicationListResult {
  items: ApplicationRow[]
  total: number
  statusCounts: StatusCounts
}

export interface FetchApplicationsParams {
  page?: number
  pageSize?: number
  status?: string
  product?: string
  keyword?: string
}

export interface CreateApplicationPayload {
  company_name: string
  credit_code: string
  amount: number
  product: string
}

export type UpdateApplicationPayload = Partial<CreateApplicationPayload>

/** 人工复核提交项 */
export interface ManualReviewItemPayload {
  item_id: number
  action: string
  comment: string | null
}

export interface ManualReviewPayload {
  reviewer: string
  items: ManualReviewItemPayload[]
  decision: string
  comment: string | null
  supplement_note: string | null
}

/** 风控逐项风险复核结果 */
export interface RiskReviewItemPayload {
  signal_id: string
  title: string
  action: 'confirm' | 'exclude'
  comment?: string | null
}

export interface RiskDecisionPayload {
  decision: string
  opinion: string
  items?: RiskReviewItemPayload[] | null
}

/** 提示消息 */
export interface ToastItem {
  id: number
  msg: string
}

/** 表单中选中的待上传文件 */
export interface SelectedFile {
  file: File
  name: string
  size: number
}

/** ============ 政策问答 Agent ============ */

export interface QaMessage {
  role: 'user' | 'assistant'
  content: string
}

export interface QaReference {
  index: number
  collection: string
  source: string
  rule_id?: string | null
  product?: string | null
  excerpt: string
}

export interface QaResponse {
  answer: string
  references: QaReference[]
  confidence: number
  used_collections: string[]
  fallback_used: boolean
  model: string
  request_id: string
  /** 个人化业务问题引导：提示改用授信助手 */
  hint?: string | null
}

/** ============ 授信助手 Agent ============ */

/** 引用类型：policy=知识库原文，business=业务数据 */
export type AssistantReferenceKind = 'policy' | 'business'

export interface AssistantReference extends QaReference {
  kind: AssistantReferenceKind
}

/** 授信助手预填新建申请弹窗的字段（仅回填，提交仍由用户完成） */
export interface NewAppPrefill {
  company_name?: string
  amount?: string
  product?: string
}

/** 回答中的动作按钮：只跳转或预填，不直接执行业务写操作 */
export interface AssistantAction {
  label: string
  type: 'navigate' | 'open_qa' | 'prefill_new_app'
  target?: string | null
  payload?: Record<string, unknown> | null
}

/** 工具调用轨迹 */
export interface AssistantToolCall {
  name: string
  ok: boolean
  latency_ms: number
  args: Record<string, unknown>
  error?: string | null
}

export interface AssistantResponse {
  answer: string
  references: AssistantReference[]
  actions: AssistantAction[]
  tool_calls: AssistantToolCall[]
  confidence: number
  model: string
  request_id: string
}
