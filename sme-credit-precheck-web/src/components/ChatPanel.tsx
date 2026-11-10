import { useEffect, useRef, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { askChat, fetchSuggestions } from '../api/chat'
import type { ChatRoute } from '../api/chat'
import { useApp } from '../context/AppContext'
import { useAuth } from '../context/AuthContext'
import type {
  AssistantAction,
  AssistantResponse,
  AssistantToolCall,
  QaMessage,
  QaResponse
} from '../types'
import ChatBubble from './chat/ChatBubble'
import CitationList from './chat/CitationList'

interface Props {
  /** 预填并打开新建申请弹窗（不自动提交） */
  onPrefillNewApp: (payload: Record<string, unknown>) => void
}

interface ChatEntry {
  id: string
  role: 'user' | 'assistant'
  content: string
  loading?: boolean
  error?: boolean
  route?: ChatRoute
  qa?: QaResponse
  assistant?: AssistantResponse
  refsExpanded?: boolean
  toolsExpanded?: boolean
}

interface AppContextInfo {
  dbId?: number
  appNo: string
  product: string
}

/** 快捷动作：业务办理类问题（政策类问题在推荐气泡中） */
interface QuickAction {
  icon: string
  label: string
  question: string
  needApp?: boolean
}

const MANAGER_QUICK_ACTIONS: QuickAction[] = [
  { icon: '📦', label: '选产品', question: '目前有哪些信贷产品？' },
  { icon: '🎯', label: '查准入', question: '年营收 800 万、成立 3 年、资产负债率 60%、申请 100 万，能申请普惠小微经营贷吗？' },
  { icon: '📌', label: '我的待办', question: '我名下有哪些待办申请？' },
  { icon: '🧾', label: '补件指导', question: '这笔申请缺什么材料？', needApp: true }
]

const RISK_QUICK_ACTIONS: QuickAction[] = [
  { icon: '🗂️', label: '复核队列', question: '当前有哪些待我复核的申请？' },
  { icon: '⚠️', label: '风险汇总', question: '列出当前待复核申请中的高风险信号' },
  { icon: '🔍', label: '冲突核查', question: '待复核申请中有哪些规则冲突或信息不一致？' },
  { icon: '📜', label: '政策依据', question: 'AP-H03 这条规则的政策依据是什么？' }
]

function quickActionsFor(role: string | undefined): QuickAction[] {
  return role === 'risk' ? RISK_QUICK_ACTIONS : MANAGER_QUICK_ACTIONS
}

/** 进入页面时由侧边栏路由 state 携带的申请上下文与预填问题 */
interface ChatRouteState {
  appId?: number
  appNo?: string
  product?: string
  question?: string
}

/**
 * 智能问答页面：占满主内容区，一个输入框由后端自动分流政策问答 / 授信助手；
 * 答案在同一对话流中渲染，引用、动作与工具轨迹按分流结果展示。
 */
export default function ChatPanel({ onPrefillNewApp }: Props) {
  const location = useLocation()
  const navigate = useNavigate()
  const { toast } = useApp()
  const { user } = useAuth()
  const isRisk = user?.role === 'risk'
  const quickActions = quickActionsFor(user?.role)
  const routeState = location.state as ChatRouteState | null
  const appCtx: AppContextInfo | null = routeState?.appId
    ? {
        dbId: routeState.appId,
        appNo: routeState.appNo || '',
        product: routeState.product || ''
      }
    : null

  const [entries, setEntries] = useState<ChatEntry[]>([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [suggestions, setSuggestions] = useState<string[]>([])
  const scrollRef = useRef<HTMLDivElement | null>(null)

  // 进入页面时拉一次推荐问题
  useEffect(() => {
    fetchSuggestions()
      .then((list) => setSuggestions(list))
      .catch(() => {})
  }, [])

  // 从详情页/报告页带问题跳转过来时预填输入框（每次 state 变化执行一次）
  useEffect(() => {
    const q = routeState?.question?.trim()
    if (q) setInput(q)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [location.state])

  useEffect(() => {
    const el = scrollRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [entries])

  const submit = async (raw?: string) => {
    const q = (raw ?? input).trim()
    if (!q || loading) return
    setInput('')

    // 最多带最近 10 条历史（5 轮），由后端再截断
    const history: QaMessage[] = entries
      .filter((e) => !e.loading)
      .slice(-10)
      .map((e) => ({ role: e.role, content: e.content }))

    const userEntry: ChatEntry = { id: crypto.randomUUID(), role: 'user', content: q }
    const botId = crypto.randomUUID()
    const botEntry: ChatEntry = { id: botId, role: 'assistant', content: '', loading: true }
    setEntries((prev) => [...prev, userEntry, botEntry])
    setLoading(true)

    try {
      const resp = await askChat({
        question: q,
        app_id: appCtx?.dbId ?? null,
        product: appCtx?.product || null,
        chat_history: history
      })
      setEntries((prev) =>
        prev.map((e) =>
          e.id === botId
            ? {
                ...e,
                loading: false,
                route: resp.route,
                qa: resp.qa ?? undefined,
                assistant: resp.assistant ?? undefined,
                content: resp.qa?.answer ?? resp.assistant?.answer ?? ''
              }
            : e
        )
      )
    } catch (err) {
      const msg = err instanceof Error ? err.message : '网络错误'
      setEntries((prev) =>
        prev.map((e) =>
          e.id === botId
            ? { ...e, loading: false, error: true, content: `抱歉，调用失败：${msg}` }
            : e
        )
      )
    } finally {
      setLoading(false)
    }
  }

  const clickQuick = (action: QuickAction) => {
    if (action.needApp && !appCtx) {
      toast('请先打开一笔申请详情，或直接输入申请编号')
      return
    }
    submit(action.question)
  }

  const toggle = (id: string, key: 'refsExpanded' | 'toolsExpanded') => {
    setEntries((prev) => prev.map((e) => (e.id === id ? { ...e, [key]: !e[key] } : e)))
  }

  const handleAction = (action: AssistantAction) => {
    if (action.type === 'navigate' && action.target) {
      navigate(action.target)
      return
    }
    if (action.type === 'prefill_new_app') {
      onPrefillNewApp(action.payload || {})
    }
  }

  const resetSession = () => {
    if (loading) return
    setEntries([])
    setInput('')
  }

  return (
    <section className="chat-page">
      <header className="qa-head">
        <div className="qa-title">
          <span className="qa-title-icon">{isRisk ? '🛡️' : '💬'}</span>
          <span>{isRisk ? '风控预审助手' : '智能问答'}</span>
        </div>
        <div className="qa-head-actions">
          <button
            className="qa-refresh"
            onClick={resetSession}
            disabled={loading || entries.length === 0}
            aria-label="刷新会话"
            title="刷新会话"
          >
            ↻ <span>刷新会话</span>
          </button>
        </div>
      </header>

      {appCtx && (
        <div className="qa-ctx-banner">
          {isRisk
            ? `🛡️ 当前关联申请「${appCtx.appNo}」，回答将围绕该笔申请的风险信号、预审结论与复核关注点展开`
            : `ℹ️ 当前查看申请「${appCtx.appNo}」，回答将围绕该笔申请展开`}
        </div>
      )}

      <div ref={scrollRef} className="qa-body">
        {entries.length === 0 && (
          <div className="qa-empty">
            <div className="qa-empty-title">
              {isRisk ? '我是你的风控预审助手' : '我是你的授信办理助手'}
            </div>
            <div className="qa-empty-tip">
              {isRisk
                ? '我可以帮你汇总待复核申请的风险信号、规则冲突与预审结论，并引用政策依据；最终复核结论以你的人工判断为准，我不会替你做任何修改或提交。'
                : '政策规则、产品准入、材料标准，以及你名下申请的进度、预审结论与补件要求，都可以直接问我；涉及新建申请时只预填弹窗，不会替你提交或修改任何数据'}
            </div>
            <div className="asst-quick-grid">
              {quickActions.map((action) => (
                <button
                  key={action.label}
                  type="button"
                  className="asst-quick-card"
                  onClick={() => clickQuick(action)}
                >
                  <span className="asst-quick-icon">{action.icon}</span>
                  <span>{action.label}</span>
                </button>
              ))}
            </div>
            {suggestions.length > 0 && (
              <div className="qa-suggestions">
                {suggestions.map((q) => (
                  <button
                    key={q}
                    type="button"
                    className="qa-suggestion"
                    onClick={() => setInput(q)}
                  >
                    {q}
                  </button>
                ))}
              </div>
            )}
          </div>
        )}

        {entries.map((e) => {
          const references = e.assistant?.references ?? e.qa?.references ?? []
          const actions = e.assistant?.actions.filter((a) => a.type !== 'open_qa') ?? []
          const toolCalls = e.assistant?.tool_calls ?? []
          return (
            <div key={e.id} className="qa-msg-group">
              <ChatBubble
                role={e.role}
                content={e.content}
                loading={e.loading}
                error={e.error}
                loadingText="正在分析问题…"
              />

              {actions.length > 0 && !e.loading && (
                <div className="asst-actions">
                  {actions.map((a, i) => (
                    <button
                      key={`${a.type}-${i}`}
                      type="button"
                      className="asst-action-btn"
                      onClick={() => handleAction(a)}
                    >
                      {a.label}
                    </button>
                  ))}
                </div>
              )}

              {!e.loading && (
                <CitationList
                  references={references}
                  expanded={Boolean(e.refsExpanded)}
                  onToggle={() => toggle(e.id, 'refsExpanded')}
                  showKind={Boolean(e.assistant)}
                />
              )}

              {toolCalls.length > 0 && !e.loading && (
                <div className="asst-tools">
                  <button
                    type="button"
                    className="qa-refs-toggle"
                    onClick={() => toggle(e.id, 'toolsExpanded')}
                  >
                    🔧 已查询 {toolCalls.length} 项业务数据
                    <span className={`qa-refs-caret${e.toolsExpanded ? ' open' : ''}`}>▾</span>
                  </button>
                  {e.toolsExpanded && (
                    <div className="asst-tool-list">
                      {toolCalls.map((call: AssistantToolCall, i) => (
                        <div key={`${call.name}-${i}`} className="asst-tool-item">
                          <span>{call.name}</span>
                          <span className={call.ok ? 'ok' : 'fail'}>
                            {call.ok ? `成功 · ${call.latency_ms}ms` : call.error || '失败'}
                          </span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}

              {e.qa?.fallback_used && e.qa.references.length > 0 && !e.loading && (
                <div className="qa-fallback-tag">已启用降级策略（知识库命中较少）</div>
              )}
            </div>
          )
        })}
      </div>

      <footer className="qa-foot">
        <div className="qa-input-wrap">
          <textarea
            className="qa-input"
            rows={1}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault()
                submit()
              }
            }}
            placeholder={
              appCtx
                ? isRisk
                  ? `问问「${appCtx.appNo}」的风险信号、预审结论或复核关注点…`
                  : `问问「${appCtx.appNo}」的进度、预审或补件，也可咨询政策…`
                : isRisk
                  ? '问问待复核申请的风险情况，或咨询政策依据…'
                  : '问问政策规则，或你的申请进度…'
            }
          />
          <button
            type="button"
            className="qa-send"
            onClick={() => submit()}
            disabled={loading || !input.trim()}
          >
            {loading ? '…' : '发送'}
          </button>
        </div>
        <div className="qa-composer-tip">Enter 发送 · Shift + Enter 换行 · 回答仅供辅助决策</div>
      </footer>
    </section>
  )
}
