import type { ReactNode } from 'react'

/** 段落排版 + [N] 引用上标（兼容后端归一化前的全角【N】）。 */
export function RichText({ text }: { text: string }) {
  const lines = text
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean)
  if (lines.length === 0) return null
  return (
    <>
      {lines.map((line, i) => (
        <p key={i}>{renderInline(line)}</p>
      ))}
    </>
  )
}

const CITATION_RE = /(?:\[|【)(\d{1,2})(?:\]|】)/g

function renderInline(line: string): ReactNode[] {
  const parts: ReactNode[] = []
  let last = 0
  let match: RegExpExecArray | null
  CITATION_RE.lastIndex = 0
  while ((match = CITATION_RE.exec(line)) !== null) {
    if (match.index > last) parts.push(line.slice(last, match.index))
    parts.push(
      <sup key={match.index} className="qa-cite">
        [{match[1]}]
      </sup>
    )
    last = CITATION_RE.lastIndex
  }
  if (last < line.length) parts.push(line.slice(last))
  return parts
}
