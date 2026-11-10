/**
 * React 错误边界：捕获子组件渲染异常，避免白屏。
 * 记录错误到 logger 并展示友好降级 UI。
 */

import { Component } from 'react'
import type { CSSProperties, ErrorInfo, ReactNode } from 'react'
import { logger } from '../utils/logger'

interface ErrorBoundaryProps {
  children: ReactNode
}

interface ErrorBoundaryState {
  hasError: boolean
  error: Error | null
}

export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  constructor(props: ErrorBoundaryProps) {
    super(props)
    this.state = { hasError: false, error: null }
  }

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { hasError: true, error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    logger.error('React 渲染异常', error, { componentStack: info.componentStack })
  }

  handleReset = () => {
    this.setState({ hasError: false, error: null })
  }

  render() {
    if (this.state.hasError) {
      return (
        <div style={styles.container}>
          <div style={styles.card}>
            <h2 style={styles.title}>页面出错了</h2>
            <p style={styles.desc}>抱歉，当前页面发生了异常。</p>
            {this.state.error?.message && (
              <pre style={styles.error}>{this.state.error.message}</pre>
            )}
            <button style={styles.btn} onClick={this.handleReset}>
              重试
            </button>
            <button style={styles.btn} onClick={() => window.location.reload()}>
              刷新页面
            </button>
          </div>
        </div>
      )
    }
    return this.props.children
  }
}

const styles: Record<string, CSSProperties> = {
  container: {
    minHeight: '100vh',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    background: '#f8fafc'
  },
  card: {
    background: '#fff',
    padding: '32px 40px',
    borderRadius: '10px',
    boxShadow: '0 4px 12px rgba(0,0,0,0.08)',
    maxWidth: 480,
    textAlign: 'center'
  },
  title: { margin: '0 0 12px', color: '#1e293b' },
  desc: { margin: '0 0 16px', color: '#64748b' },
  error: {
    background: '#f1f5f9',
    padding: 12,
    borderRadius: 6,
    color: '#dc2626',
    fontSize: 13,
    textAlign: 'left',
    overflowX: 'auto'
  },
  btn: {
    margin: '8px 6px 0',
    padding: '8px 20px',
    border: 'none',
    borderRadius: 6,
    background: '#2563eb',
    color: '#fff',
    cursor: 'pointer',
    fontSize: 14
  }
}
