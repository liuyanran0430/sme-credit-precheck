import type { QaReference } from '../../types'

interface Props {
  references: Array<QaReference & { kind?: 'policy' | 'business' }>
  expanded: boolean
  onToggle: () => void
  /** 是否展示「业务数据 / 政策」来源标签（授信助手使用） */
  showKind?: boolean
}

/** 引用列表：折叠面板 + 来源 + 规则编号 + 摘录，两个面板共用。 */
export default function CitationList({ references, expanded, onToggle, showKind }: Props) {
  if (references.length === 0) return null
  return (
    <div className="qa-refs">
      <button type="button" className="qa-refs-toggle" onClick={onToggle}>
        📎 {references.length} 条引用
        <span className={`qa-refs-caret${expanded ? ' open' : ''}`}>▾</span>
      </button>
      {expanded && (
        <div className="qa-refs-list">
          {references.map((ref) => (
            <div key={ref.index} className="qa-ref-item">
              <span className="qa-ref-num">[{ref.index}]</span>
              <div className="qa-ref-body">
                <div className="qa-ref-meta">
                  {showKind && ref.kind && (
                    <span className={`asst-ref-kind ${ref.kind}`}>
                      {ref.kind === 'business' ? '业务数据' : '政策'}
                    </span>
                  )}
                  {ref.source}
                  {ref.rule_id && <span className="qa-ref-rule">{ref.rule_id}</span>}
                </div>
                <div className="qa-ref-excerpt">{ref.excerpt}</div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
