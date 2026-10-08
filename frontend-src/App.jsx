import { useState, useEffect, useRef } from 'react'
import SearchPage from './SearchPage'
import SettingsPage from './SettingsPage'
import Px from './Px'
import './index.css'

const API = 'http://localhost:8000'
const G = 160 // wallpaper grid cell (px)

// Procedural 1-bit dithered cloud wallpaper (Bayer 4x4 over fractal noise). Search hits light up grid cells.
function Wallpaper({ lit }) {
  const ref = useRef()
  useEffect(() => {
    const c = ref.current
    const draw = () => {
      const S = 4, w = (c.width = innerWidth), h = (c.height = innerHeight), x = c.getContext('2d')
      const B = [0, 8, 2, 10, 12, 4, 14, 6, 3, 11, 1, 9, 15, 7, 13, 5]
      const hs = (i, j) => { const n = Math.sin(i * 127.1 + j * 311.7) * 43758.5453; return n - Math.floor(n) }
      const vn = (px, py) => {
        const i = Math.floor(px), j = Math.floor(py), fx = px - i, fy = py - j
        const u = fx * fx * (3 - 2 * fx), v = fy * fy * (3 - 2 * fy)
        return (hs(i, j) * (1 - u) + hs(i + 1, j) * u) * (1 - v) + (hs(i, j + 1) * (1 - u) + hs(i + 1, j + 1) * u) * v
      }
      x.fillStyle = '#fff'; x.fillRect(0, 0, w, h)
      x.fillStyle = '#1a5fd0'
      for (let j = 0; j < h / S; j++) for (let i = 0; i < w / S; i++) {
        let n = 0, a = 0.5, f = 0.018
        for (let o = 0; o < 4; o++) { n += a * vn(i * f + 7, j * f * 1.6 + 3); a /= 2; f *= 2 }
        const t = n / 0.9375 + (j * S / h - 0.5) * 0.35
        if (1 - t > (B[(j % 4) * 4 + (i % 4)] + 0.5) / 16) x.fillRect(i * S, j * S, S, S)
      }
      for (const [cx, cy] of lit) {
        x.fillStyle = '#ffad66'; x.fillRect(cx * G, cy * G, G, G)
        x.fillStyle = '#ff0090'; x.fillRect(cx * G, cy * G, G / 3, G / 3)
      }
      x.fillStyle = '#fff'
      for (let gx = 0; gx < w; gx += G) x.fillRect(gx, 0, 1, h)
      for (let gy = 0; gy < h; gy += G) x.fillRect(0, gy, w, 1)
    }
    draw(); addEventListener('resize', draw)
    return () => removeEventListener('resize', draw)
  }, [lit])
  return <canvas ref={ref} className="wall" aria-hidden="true" />
}

function Win({ title, icon, active, z, style, onFocus, onClose, children }) {
  return (
    <div className="win raised" style={{ ...style, zIndex: z }} onMouseDown={onFocus}>
      <div className={'tb' + (active ? '' : ' off')}>
        <Px n={icon} s={1} /><b>{title}</b>
        <button className="tbtn" onClick={onClose} title="Close">x</button>
      </div>
      {children}
    </div>
  )
}

export default function App() {
  const [open, setOpen] = useState({ search: true, settings: false })
  const [top, setTop] = useState('search')
  const [menu, setMenu] = useState(false)
  const [toasts, setToasts] = useState([])
  const [st, setSt] = useState(null)
  const [lit, setLit] = useState([])
  const [now, setNow] = useState(new Date())

  useEffect(() => {
    const poll = async () => { try { const r = await fetch(`${API}/index/status`); if (r.ok) setSt(await r.json()) } catch { setSt(null) } }
    poll(); const a = setInterval(poll, 5000), b = setInterval(() => setNow(new Date()), 30000)
    return () => { clearInterval(a); clearInterval(b) }
  }, [])

  const addToast = (msg) => {
    const id = Date.now() + Math.random()
    setToasts(t => [...t, { id, msg }]); setTimeout(() => setToasts(t => t.filter(x => x.id !== id)), 4000)
  }
  // Light up wallpaper cells: one per hit (max 6), positions seeded by the query text.
  const onHits = (n, seed) => {
    const cols = Math.ceil(innerWidth / G), rows = Math.ceil(innerHeight / G)
    let s = [...seed].reduce((a, c) => (a * 31 + c.charCodeAt(0)) | 0, 7), out = []
    for (let k = 0; k < Math.min(n, 6); k++) { s = (s * 1103515245 + 12345) & 0x7fffffff; out.push([s % cols, (s >> 8) % rows]) }
    setLit(out)
  }
  const show = (id) => { setOpen(o => ({ ...o, [id]: true })); setTop(id); setMenu(false) }
  const hide = (id) => setOpen(o => ({ ...o, [id]: false }))
  const clock = now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })

  return (
    <>
      <Wallpaper lit={lit} />
      {open.search && (
        <Win title="Find: Your Files - Memoria" icon="find" active={top === 'search'} z={top === 'search' ? 3 : 2}
          style={{ left: '4vw', top: 12, width: 'min(980px,92vw)', height: 'calc(100vh - 60px)' }}
          onFocus={() => setTop('search')} onClose={() => hide('search')}>
          <SearchPage addToast={addToast} onHits={onHits} st={st} />
        </Win>
      )}
      {open.settings && (
        <Win title="Memoria Setup" icon="pc" active={top === 'settings'} z={top === 'settings' ? 3 : 2}
          style={{ left: '14vw', top: 40, width: 'min(720px,84vw)', height: 'min(640px,calc(100vh - 90px))' }}
          onFocus={() => setTop('settings')} onClose={() => hide('settings')}>
          <SettingsPage addToast={addToast} />
        </Win>
      )}
      {menu && (
        <div className="menu raised">
          <button onClick={() => show('search')}><Px n="find" />Find Files</button>
          <button onClick={() => show('settings')}><Px n="pc" />Setup</button>
        </div>
      )}
      <div className="taskbar">
        <button className="btn" style={{ fontWeight: 700, minWidth: 80 }} onClick={() => setMenu(m => !m)}>Start</button>
        {open.search && <button className={'btn' + (top === 'search' ? ' on' : '')} onClick={() => setTop('search')}><Px n="find" s={1} />Find</button>}
        {open.settings && <button className={'btn' + (top === 'settings' ? ' on' : '')} onClick={() => setTop('settings')}><Px n="pc" s={1} />Setup</button>}
        <div className="tray" title="Indexer status">
          <span className={'dot' + (st?.watcher_running ? '' : ' off')} />
          <span>{st ? `${st.indexed_files} files` : 'offline'}</span><span>{clock}</span>
        </div>
      </div>
      {toasts.map(t => <div key={t.id} className="toast raised">{t.msg}</div>)}
    </>
  )
}
