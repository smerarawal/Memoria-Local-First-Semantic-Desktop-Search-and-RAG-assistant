import { useState, useEffect, useCallback } from 'react'
import SearchPage from './SearchPage'
import SettingsPage from './SettingsPage'
import './index.css'

const API = 'http://localhost:8000'

function MemoriaLogo() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ color: '#4f9fff', flexShrink: 0 }}>
      <circle cx="11" cy="11" r="8"/>
      <line x1="21" y1="21" x2="16.65" y2="16.65"/>
    </svg>
  )
}

function Toast({ toasts }) {
  return (
    <div className="toast-container">
      {toasts.map(t => (
        <div key={t.id} className={`toast toast-${t.type}`}>{t.msg}</div>
      ))}
    </div>
  )
}

export default function App() {
  const [page, setPage] = useState('search')
  const [toasts, setToasts] = useState([])
  const [watcherRunning, setWatcherRunning] = useState(null)
  const [indexedCount, setIndexedCount] = useState(null)

  // Poll /index/status lightly for the navbar indicator
  const pollStatus = useCallback(async () => {
    try {
      const res = await fetch(`${API}/index/status`)
      if (res.ok) {
        const d = await res.json()
        setWatcherRunning(d.watcher_running)
        setIndexedCount(d.indexed_files)
      }
    } catch {}
  }, [])

  useEffect(() => {
    pollStatus()
    const id = setInterval(pollStatus, 5000)
    return () => clearInterval(id)
  }, [pollStatus])

  function addToast(msg, type = 'info') {
    const id = Date.now()
    setToasts(prev => [...prev, { id, msg, type }])
    setTimeout(() => setToasts(prev => prev.filter(t => t.id !== id)), 4000)
  }

  return (
    <div className="app-shell">
      <nav className="navbar">
        <div className="navbar-logo">
          <MemoriaLogo />
          Memoria
        </div>

        <div className="navbar-nav">
          <button
            className={`nav-btn ${page === 'search' ? 'active' : ''}`}
            onClick={() => setPage('search')}
            id="nav-search"
          >
            🔍 Search
          </button>
          <button
            className={`nav-btn ${page === 'settings' ? 'active' : ''}`}
            onClick={() => setPage('settings')}
            id="nav-settings"
          >
            ⚙ Settings
          </button>
        </div>

        <div className="navbar-status">
          <span className={`status-dot ${watcherRunning ? '' : 'off'}`} />
          {watcherRunning === null ? 'Connecting…' :
           watcherRunning ? `Monitoring · ${indexedCount ?? 0} files indexed` : 'Monitoring paused'}
        </div>
      </nav>

      <main className="main-content">
        {page === 'search' && <SearchPage addToast={addToast} />}
        {page === 'settings' && <SettingsPage addToast={addToast} />}
      </main>

      <Toast toasts={toasts} />
    </div>
  )
}
