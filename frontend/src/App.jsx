import { useState, useEffect, useCallback, useMemo } from 'react'
import SearchPage from './SearchPage'
import SettingsPage from './SettingsPage'
import LoginPage from './LoginPage'
import './index.css'

const API = 'http://localhost:8000'

/* ── Neural network background ─────────────────────────────────
   Seeded nodes + edges computed at module load — never re-randomizes.
   Uses SVG animateMotion for signal pulses traveling along edges.
── */

// Generate stable node positions (seeded LCG)
const NN_NODES = Array.from({ length: 42 }, (_, i) => {
  const a = (i * 6271 + 3847) % 10000
  const b = (i * 9431 + 1237) % 10000
  return {
    id: i,
    x: 3 + (a % 94),          // % of viewBox width
    y: 3 + (b % 94),          // % of viewBox height
    r: 0.4 + ((a * b % 100) / 100) * 0.7,
    pulseDur: `${3.5 + (a % 35) / 10}s`,
    pulseDelay: `${-((b % 50) / 10)}s`,
  }
})

// Connect nodes that are within threshold distance
const CONNECT_DIST = 22
const NN_EDGES = []
for (let i = 0; i < NN_NODES.length; i++) {
  for (let j = i + 1; j < NN_NODES.length; j++) {
    const dx = NN_NODES[i].x - NN_NODES[j].x
    const dy = NN_NODES[i].y - NN_NODES[j].y
    const d = Math.sqrt(dx * dx + dy * dy)
    if (d < CONNECT_DIST) {
      NN_EDGES.push({
        id: `e${i}-${j}`,
        x1: NN_NODES[i].x, y1: NN_NODES[i].y,
        x2: NN_NODES[j].x, y2: NN_NODES[j].y,
        // Closer edges are slightly more visible
        op: +(Math.max(0.05, 0.16 - d * 0.006)).toFixed(3),
      })
    }
  }
}

// Pick edges spaced apart for signal animations
const NN_SIGNALS = NN_EDGES.filter((_, i) => i % 6 === 0).slice(0, 10)

function NeuralBg() {
  return (
    <svg className="neural-bg" viewBox="0 0 100 100"
      preserveAspectRatio="xMidYMid slice" aria-hidden="true">
      {/* Edges — thin lines between nearby nodes */}
      {NN_EDGES.map(e => (
        <line key={e.id}
          x1={e.x1} y1={e.y1} x2={e.x2} y2={e.y2}
          stroke="#7a8870" strokeOpacity={e.op} strokeWidth="0.1"
        />
      ))}

      {/* Signal pulses — warm cream dots */}
      {NN_SIGNALS.map((e, i) => (
        <circle key={`sig-${i}`} r="0.35" fill="rgba(200,185,145,0.5)">
          <animateMotion
            path={`M ${e.x1} ${e.y1} L ${e.x2} ${e.y2}`}
            dur={`${7 + i * 2.3}s`}
            begin={`${-(i * 1.7)}s`}
            repeatCount="indefinite"
          />
        </circle>
      ))}

      {/* Nodes — glowing dots with pulse */}
      {NN_NODES.map(n => (
        <g key={n.id}>
          {/* Soft halo */}
          <circle cx={n.x} cy={n.y} r={n.r * 4}
            fill="rgba(160,150,110,0.025)" />
          {/* Core */}
          <circle cx={n.x} cy={n.y} r={n.r}
            fill="rgba(190,178,145,0.28)">
            <animate attributeName="opacity"
              values="0.1;0.3;0.1"
              dur={n.pulseDur} begin={n.pulseDelay}
              repeatCount="indefinite" />
            <animate attributeName="r"
              values={`${n.r};${n.r * 1.25};${n.r}`}
              dur={n.pulseDur} begin={n.pulseDelay}
              repeatCount="indefinite" />
          </circle>
        </g>
      ))}
    </svg>
  )
}

/* Cinematic left vignette — dark gradient that lets bg image breathe on the right */
function VignetteOverlay() {
  return <div className="vignette-overlay" aria-hidden="true" />
}

function CornerSmoke() {
  return (
    <div className="corner-smoke" aria-hidden="true">
      <div className="smoke-l" />
      <div className="smoke-l" />
      <div className="smoke-l" />
      <div className="smoke-l" />
      <div className="smoke-l" />
      <div className="smoke-l" />
    </div>
  )
}

/* Geometric corner accent */
function CornerGeo() {
  return (
    <svg className="corner-geo" viewBox="0 0 420 420"
      fill="none" aria-hidden="true">
      {/* Concentric quarter-circle arcs — warm cream */}
      <circle cx="420" cy="0" r="120"
        stroke="rgba(180,165,130,0.06)" strokeWidth="1"/>
      <circle cx="420" cy="0" r="190"
        stroke="rgba(160,148,115,0.045)" strokeWidth="1"/>
      <circle cx="420" cy="0" r="260"
        stroke="rgba(148,135,105,0.032)" strokeWidth="1"/>
      <circle cx="420" cy="0" r="330"
        stroke="rgba(135,122,95,0.022)" strokeWidth="0.75"/>
      <circle cx="420" cy="0" r="400"
        stroke="rgba(120,110,85,0.015)" strokeWidth="0.75"/>
      {/* Radial lines from corner */}
      <line x1="420" y1="0" x2="0" y2="0"
        stroke="rgba(175,160,125,0.05)" strokeWidth="0.75"/>
      <line x1="420" y1="0" x2="420" y2="420"
        stroke="rgba(175,160,125,0.05)" strokeWidth="0.75"/>
      {/* Corner anchor — warm gold dot */}
      <circle cx="420" cy="0" r="2"
        fill="rgba(200,180,130,0.2)"/>
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
  const [user, setUser] = useState(() => localStorage.getItem('memoria_user'))
  const [page, setPage] = useState('search')
  const [toasts, setToasts] = useState([])
  const [watcherRunning, setWatcherRunning] = useState(null)
  const [indexedCount, setIndexedCount] = useState(null)

  // All hooks must run unconditionally — before any early returns
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
    if (!user) return          // only poll when logged in
    pollStatus()
    const id = setInterval(pollStatus, 5000)
    return () => clearInterval(id)
  }, [pollStatus, user])       // re-run when user logs in

  function addToast(msg, type = 'info') {
    const id = Date.now()
    setToasts(prev => [...prev, { id, msg, type }])
    setTimeout(() => setToasts(prev => prev.filter(t => t.id !== id)), 4000)
  }

  // Show login page if not authenticated
  if (!user) {
    return <LoginPage onLogin={u => setUser(u)} />
  }

  return (
    <div className="app-shell">
      <CornerGeo />

      <nav className="navbar">
        <div className="navbar-logo">
          <span className="navbar-logo-text">Memoria</span>
        </div>

        <div className="navbar-nav">
          <button
            className={`nav-btn ${page === 'search' ? 'active' : ''}`}
            onClick={() => setPage('search')}
            id="nav-search"
          >
            Search
          </button>
          <button
            className={`nav-btn ${page === 'settings' ? 'active' : ''}`}
            onClick={() => setPage('settings')}
            id="nav-settings"
          >
            Settings
          </button>
        </div>

        <div className="navbar-status">
          <span className={`status-dot ${watcherRunning ? '' : 'off'}`} />
          {watcherRunning === null ? 'connecting' :
           watcherRunning ? `${indexedCount ?? 0} files indexed` : 'paused'}
        </div>
      </nav>

      <main className="main-content">
        {page === 'search' && <SearchPage addToast={addToast} user={user} />}
        {page === 'settings' && <SettingsPage addToast={addToast} user={user} />}
      </main>

      {/* Bottom right user menu */}
      <div className="bottom-right-menu">
        <button className="icon-menu-btn" onClick={() => setPage('settings')} title="Profile">
          <img src="/profile.png" alt="profile" className="menu-icon" />
          <span>Profile</span>
        </button>
        <button
          className="icon-menu-btn"
          onClick={() => { localStorage.removeItem('memoria_user'); setUser(null) }}
          title="Logout"
        >
          <img src="/vortex.png" alt="logout" className="menu-icon vortex-spin" />
          <span>Logout</span>
        </button>
      </div>

      <Toast toasts={toasts} />
    </div>
  )
}
