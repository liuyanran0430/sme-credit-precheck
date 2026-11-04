/**
 * 前端日志工具：分级输出 + 生产环境控制。
 *
 * 使用方式：
 *   import { logger } from '@/utils/logger'
 *   logger.info('用户登录', { username })
 *   logger.error('加载申请失败', error, { appNo })
 *   logger.error('AI 预审失败', error, { appNo, request_id })
 *
 * 调用 LLM 相关接口的日志在 extra 中传入 request_id 后，
 * 输出行与上报内容都会带上 request_id，可与后端日志、llm_runs 对齐。
 *
 * 日志级别：debug < info < warn < error
 * - 开发环境：全部输出
 * - 生产环境：只输出 warn 及以上（debug/info 静默）
 */

const LEVELS = { debug: 10, info: 20, warn: 30, error: 40 }

// 批量上报配置
const UPLOAD_ENDPOINT = '/api/v1/frontend-logs'
const FLUSH_INTERVAL = 2000 // 防抖 2 秒
const MAX_BUFFER_SIZE = 10 // 满 10 条立即上报

const _logBuffer = []
let _flushTimer = null

// 生产环境默认只输出 warn/error；可通过 localStorage 临时打开 debug
function getMinLevel() {
  const stored = localStorage.getItem('log_level')
  if (stored && LEVELS[stored]) return LEVELS[stored]
  return import.meta.env.PROD ? LEVELS.warn : LEVELS.debug
}

function format(level, message, extra) {
  const requestId = extra && typeof extra === 'object' ? extra.request_id : undefined
  const ts = new Date().toISOString()
  const parts = [`[${ts}]`, level.toUpperCase()]
  if (requestId) parts.push(`request_id=${requestId}`)
  parts.push(message)
  if (extra !== undefined) {
    try {
      parts.push(typeof extra === 'object' ? JSON.stringify(extra) : String(extra))
    } catch {
      parts.push('[unserializable]')
    }
  }
  return parts.join(' | ')
}

function serializeError(error) {
  if (!error) return undefined
  if (error instanceof Error) {
    return { name: error.name, message: error.message, stack: error.stack }
  }
  if (typeof error === 'object') {
    try {
      return JSON.parse(JSON.stringify(error))
    } catch {
      return String(error)
    }
  }
  return String(error)
}

function flushBuffer() {
  if (_flushTimer) {
    clearTimeout(_flushTimer)
    _flushTimer = null
  }
  if (!_logBuffer.length) return

  const entries = _logBuffer.splice(0, _logBuffer.length)
  const payload = JSON.stringify({ entries })

  // 优先用 fetch；页面卸载场景由 sendBeacon 兜底
  fetch(UPLOAD_ENDPOINT, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: payload,
    keepalive: true,
  }).catch((err) => {
    // 上报失败仅打 console，不能再调 logger，否则死循环
    console.error('[frontend-logger] 上报失败:', err)
  })
}

function scheduleFlush() {
  if (_flushTimer) return
  _flushTimer = setTimeout(flushBuffer, FLUSH_INTERVAL)
}

function enqueue(level, message, error, extra) {
  if (LEVELS[level] < LEVELS.warn) return

  const requestId = extra && typeof extra === 'object' ? extra.request_id : undefined
  const entry = {
    timestamp: new Date().toISOString(),
    level,
    message,
    request_id: requestId || null,
    extra: {},
  }

  const errInfo = serializeError(error)
  if (errInfo) entry.extra.error = errInfo
  if (extra !== undefined) {
    if (requestId) {
      // request_id 已提升为独立字段，context 中不再重复
      const rest = { ...extra }
      delete rest.request_id
      if (Object.keys(rest).length) entry.extra.context = rest
    } else {
      entry.extra.context = extra
    }
  }

  if (!Object.keys(entry.extra).length) entry.extra = null

  _logBuffer.push(entry)
  if (_logBuffer.length >= MAX_BUFFER_SIZE) {
    flushBuffer()
  } else {
    scheduleFlush()
  }
}

// 页面卸载前强制 flush，避免丢失日志
if (typeof window !== 'undefined') {
  window.addEventListener('pagehide', () => {
    if (!_logBuffer.length) return
    const payload = JSON.stringify({ entries: _logBuffer.splice(0) })
    try {
      navigator.sendBeacon(UPLOAD_ENDPOINT, new Blob([payload], { type: 'application/json' }))
    } catch {
      // sendBeacon 不可用时忽略，不影响页面关闭
    }
  })
}

function log(level, message, error, extra) {
  if (LEVELS[level] < getMinLevel()) return

  const text = format(level, message, extra)

  switch (level) {
    case 'error':
      console.error(text, error ?? '')
      break
    case 'warn':
      console.warn(text, error ?? '')
      break
    case 'info':
      console.info(text)
      break
    default:
      console.debug(text)
  }

  enqueue(level, message, error, extra)
}

export const logger = {
  debug: (message, extra) => log('debug', message, undefined, extra),
  info: (message, extra) => log('info', message, undefined, extra),
  warn: (message, error, extra) => log('warn', message, error, extra),
  error: (message, error, extra) => log('error', message, error, extra),
}

/** 临时把日志级别调到 debug（仅当前会话） */
export function enableDebugLogs() {
  localStorage.setItem('log_level', 'debug')
}

/** 恢复默认日志级别 */
export function resetLogLevel() {
  localStorage.removeItem('log_level')
}
