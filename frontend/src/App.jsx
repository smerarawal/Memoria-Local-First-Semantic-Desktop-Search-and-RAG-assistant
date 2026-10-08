import { useState, useEffect, useRef } from 'react'
import SearchPage from './SearchPage'
import SettingsPage from './SettingsPage'
import LoginPage from './LoginPage'
import './index.css'

const API = 'http://localhost:8000'
const RAMP = ['·', '+', '*', '=', '2', 'e', '/']

// ASCII canvas — samples tulip-ascii.jpg; warm zones → coral glyphs, cool → blue
function SkyAscii() {
  const ref = useRef()
  useEffect(() => {
    const c = ref.current, img = new Image()
    const draw = () => {
      const cell = 18
      c.width = innerWidth; c.height = innerHeight
      const cols = Math.ceil(innerWidth / cell), rows = Math.ceil(innerHeight / cell)
      const o = document.createElement('canvas'); o.width = cols; o.height = rows
      const ox = o.getContext('2d', { willReadFrequently: true })
      const k = Math.max(cols / img.width, rows / img.height)
      const dw = img.width * k, dh = img.height * k
      ox.drawImage(img, (cols - dw) / 2, (rows - dh) / 2, dw, dh)
      const d = ox.getImageData(0, 0, cols, rows).data
      const ctx = c.getContext('2d')
      ctx.clearRect(0, 0, c.width, c.height)
      ctx.font = `${cell}px ui-monospace,Consolas,monospace`
      ctx.textBaseline = 'top'
      for (let j = 0; j < rows; j++) {
        for (let i = 0; i < cols; i++) {
          const p = (j * cols + i) * 4
          const l = (d[p] * 0.3 + d[p+1] * 0.59 + d[p+2] * 0.11) / 255
          if (l > 0.55) {
            const t = Math.min(1, (l - 0.55) / 0.4)
            const idx = Math.min(RAMP.length - 1, Math.floor(t * RAMP.length))
            const warm = d[p] > d[p+2] + 20
            ctx.fillStyle = warm
              ? `rgba(240,112,122,${0.22 + 0.6 * t})`
              : `rgba(28,111,214,${0.18 + 0.5 * t})`
            ctx.fillText(RAMP[idx], i * cell, j * cell)
          }
        }
      }
    }
    img.onload = draw
    img.src = '/tulip-ascii.jpg'
    addEventListener('resize', draw)
    return () => removeEventListener('resize', draw)
  }, [])
  return <canvas ref={ref} className="sky" aria-hidden="true" />
}

export default function App() {
  const [user, setUser] = useState(() => localStorage.getItem('memoria_user') || null)
  const [name, setName] = useState(() => localStorage.getItem('memoria_name') || '')
  const [tab, setTab]   = useState('find')
  const [st, setSt]     = useState(null)
  const [toasts, setToasts] = useState([])

  useEffect(() => {
    if (!user) return
    const poll = async () => {
      try { const r = await fetch(`${API}/index/status`); if (r.ok) setSt(await r.json()) }
      catch { setSt(null) }
    }
    poll()
    const id = setInterval(poll, 5000)
    return () => clearInterval(id)
  }, [user])

  const addToast = (msg) => {
    const id = Date.now() + Math.random()
    setToasts(t => [...t, { id, msg }])
    setTimeout(() => setToasts(t => t.filter(x => x.id !== id)), 4000)
  }

  const handleLogin = (u, n) => {
    setUser(u)
    setName(n)
    setTab('find')
  }

  const handleLogout = () => {
    localStorage.removeItem('memoria_user')
    localStorage.removeItem('memoria_name')
    setUser(null)
    setName('')
    setSt(null)
    setTab('find')
    addToast('Signed out.')
  }

  // Show login page (still render the background)
  if (!user) {
    return (
      <>
        <SkyAscii />
        <LoginPage onLogin={handleLogin} />
        {toasts.map(t => <div key={t.id} className="toast">{t.msg}</div>)}
      </>
    )
  }

  return (
    <>
      <SkyAscii />
      <main className="shell">
        <header className="top">
          <div className="logo">memoria<span>_</span></div>
          <nav>
            <button className={'nav' + (tab === 'find'  ? ' on' : '')} onClick={() => setTab('find')}>find</button>
            <button className={'nav' + (tab === 'setup' ? ' on' : '')} onClick={() => setTab('setup')}>setup</button>
          </nav>
          <div className="chip">
            <span className={'dot' + (st?.watcher_running ? '' : ' off')} />
            {st ? `${st.indexed_files} files` : 'offline'}
          </div>
          {/* User info + logout */}
          <div className="top-user">
            <span className="top-username">{name || user}</span>
            <button className="logout-btn" onClick={handleLogout} title="Sign out">
              sign out ↩
            </button>
          </div>
        </header>
        <section className="panel">
          {tab === 'find'
            ? <SearchPage addToast={addToast} onHits={() => {}} st={st} />
            : <SettingsPage addToast={addToast} />}
        </section>
      </main>
      {toasts.map(t => <div key={t.id} className="toast">{t.msg}</div>)}
    </>
  )
}
