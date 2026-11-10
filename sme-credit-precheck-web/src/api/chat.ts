import { authHeaders, readError, handleUnauthorized } from './http'
import type { AssistantResponse, QaMessage, QaResponse } from '../types'

const API = '/api/v1'

export type ChatRoute = 'qa' | 'assistant'

export interface ChatRequestPayload {
  question: string
  app_id?: number | null
  product?: string | null
  category?: string | null
  chat_history?: QaMessage[] | null
}

export interface ChatResponsePayload {
  route: ChatRoute
  qa: QaResponse | null
  assistant: AssistantResponse | null
}

export interface SuggestionResponsePayload {
  questions: string[]
}

/** 统一问答入口：后端按问题自动分流政策问答 / 授信助手 */
export async function askChat(payload: ChatRequestPayload): Promise<ChatResponsePayload> {
  const resp = await fetch(`${API}/chat/dispatch`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify(payload),
    cache: 'no-store'
  })
  if (resp.status === 401) {
    handleUnauthorized()
    throw new Error('登录已过期')
  }
  if (!resp.ok) {
    const msg = await readError(resp)
    throw new Error(msg)
  }
  return resp.json() as Promise<ChatResponsePayload>
}

/** 推荐问题气泡（静态） */
export async function fetchSuggestions(): Promise<string[]> {
  const resp = await fetch(`${API}/qa/suggestions`, {
    headers: authHeaders(),
    cache: 'no-store'
  })
  if (resp.status === 401) {
    handleUnauthorized()
    throw new Error('登录已过期')
  }
  if (!resp.ok) {
    const msg = await readError(resp)
    throw new Error(msg)
  }
  const data = (await resp.json()) as SuggestionResponsePayload
  return data.questions || []
}
