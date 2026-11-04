import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import App from './App'
import { ErrorBoundary } from './components/ErrorBoundary'
import { logger } from './utils/logger'
import './index.css'

// 全局未捕获异常
window.addEventListener('error', (event) => {
  logger.error('全局未捕获异常', event.error || event.message, {
    filename: event.filename,
    lineno: event.lineno,
    colno: event.colno,
  })
})

// 全局未处理的 Promise rejection
window.addEventListener('unhandledrejection', (event) => {
  logger.error('未处理的 Promise rejection', event.reason)
})

createRoot(document.getElementById('root')).render(
  <ErrorBoundary>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </ErrorBoundary>
)
