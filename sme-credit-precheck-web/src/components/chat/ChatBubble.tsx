import { RichText } from './RichText'

interface Props {
  role: 'user' | 'assistant'
  content: string
  loading?: boolean
  error?: boolean
  loadingText?: string
}

/** 单条消息气泡：加载态 / 错误态 / 正文，两个面板共用。 */
export default function ChatBubble({ role, content, loading, error, loadingText }: Props) {
  return (
    <div className={`qa-msg qa-${role}${error ? ' error' : ''}`}>
      <div className="qa-msg-bubble">
        {loading ? <span className="qa-thinking">{loadingText || '正在思考…'}</span> : <RichText text={content} />}
      </div>
    </div>
  )
}
