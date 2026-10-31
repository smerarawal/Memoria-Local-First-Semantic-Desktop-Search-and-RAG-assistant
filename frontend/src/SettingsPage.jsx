import { useState, useEffect, useCallback } from 'react'
import { useApi } from './useApi'
import Px from './Px'

export default function SettingsPage({ addToast, onLogout, user }) {
  const { get, post, del } = useApi()
  const [folders, setFolders] = useState([])
  const [st, setSt] = useState(null)
  const [path, setPath] = useState('')
  const [busy, setBusy] = useState(false)
  const [geminiKey, setGeminiKey] = useState(() => localStorage.getItem('memoria_gemini_key') || '')
  const [groqKey, setGroqKey] = useState(() => localStorage.getItem('memoria_groq_key') || '')

  const load = useCallback(async () => {
    try { setFolders(await get('/folders')) } catch {}
    try { setSt(await get('/index/status')) } catch { setSt(null) }
  }, [get])
  useEffect(() => { load(); const id = setInterval(load, 4000); return () => clearInterval(id) }, [load])

  const act = async (fn, ok) => { try { await fn(); ok && addToast(ok); load() } catch (e) { addToast(e.message) } }
  const add = async () => { if (!path.trim()) return; setBusy(true); await act(async () => { await post('/folders', { path: path.trim() }); setPath('') }, 'Folder added'); setBusy(false) }
  const indexNow = () => act(async () => { await post('/index'); }, 'Indexing started')

  const saveGeminiKey = () => {
    const k = geminiKey.trim()
    if (k) {
      localStorage.setItem('memoria_gemini_key', k)
      addToast('Gemini API Key saved!')
    } else {
      localStorage.removeItem('memoria_gemini_key')
      addToast('Gemini API Key cleared.')
    }
  }

  const saveGroqKey = () => {
    const k = groqKey.trim()
    if (k) {
      localStorage.setItem('memoria_groq_key', k)
      addToast('Groq API Key saved!')
    } else {
      localStorage.removeItem('memoria_groq_key')
      addToast('Groq API Key cleared.')
    }
  }

  // Defrag-style map: one cell per file (capped at 600)
  const cells = st ? [
    ...Array(Math.min(st.indexed_files, 600)).fill(''),
    ...Array(Math.min(st.pending_files, 600)).fill('p'),
    ...Array(Math.min(st.failed_files, 600)).fill('f'),
  ].slice(0, 600) : []

  return (
    <div className="body">
      <fieldset>
        <legend>Watched folders</legend>
        <div className="row">
          <input value={path} onChange={e => setPath(e.target.value)} onKeyDown={e => e.key === 'Enter' && add()} placeholder="Full folder path, e.g. C:\Users\me\Documents" />
          <button className="btn" onClick={add} disabled={busy || !path.trim()}>Add</button>
        </div>
        <div className="sunk" style={{ marginTop: 8, maxHeight: 130, overflow: 'auto' }}>
          {folders.length === 0 && <div className="ev">No folders yet.</div>}
          {folders.map(f => (
            <div className="ev row" key={f.folder_id} style={{ alignItems: 'center', gap: 6 }}>
              <Px n="folder" s={1} />
              <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis' }} title={f.path}>
                {f.path}
              </span>
              <span style={{ fontSize: '10px', color: f.enabled ? '#167a3a' : '#888', fontWeight: 600 }}>
                {f.enabled ? '[Active]' : '[Paused]'}
              </span>
              <button
                className="btn"
                style={{ minWidth: 55, padding: '2px 8px', fontSize: '11px' }}
                onClick={() => act(() => post(`/folders/${f.folder_id}/toggle`), f.enabled ? 'Folder indexing paused' : 'Folder indexing resumed')}
                title={f.enabled ? "Stop watching this folder for new files (keeps all already indexed files)" : "Resume watching this folder"}
              >
                {f.enabled ? 'Pause' : 'Resume'}
              </button>
              <button
                className="btn"
                style={{ minWidth: 55, padding: '2px 8px', fontSize: '11px', background: 'var(--coral)' }}
                onClick={() => act(() => del(`/folders/${f.folder_id}`), 'Folder removed')}
              >
                Remove
              </button>
            </div>
          ))}
        </div>
      </fieldset>

      <fieldset>
        <legend>Groq AI (Ultra-low latency RAG)</legend>
        <p style={{ margin: '0 0 8px', fontSize: '11px', opacity: 0.85 }}>
          Recommended for instant document answers (~0.3s latency) using Llama 3.3 70B on Groq LPUs. Get a free key at <a href="https://console.groq.com/keys" target="_blank" rel="noreferrer" style={{ color: 'var(--blue)', textDecoration: 'underline' }}>console.groq.com</a>.
        </p>
        <div className="row">
          <input
            type="password"
            value={groqKey}
            onChange={e => setGroqKey(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && saveGroqKey()}
            placeholder="gsk_... (Groq API Key)"
          />
          <button className="btn" onClick={saveGroqKey}>Save Key</button>
        </div>
        {groqKey && (
          <small style={{ display: 'block', marginTop: 4, color: '#167a3a', fontSize: '10px' }}>
            [Active] Groq API Key configured on this browser
          </small>
        )}
      </fieldset>

      <fieldset>
        <legend>Gemini AI (for Ask Files / RAG &amp; Vision OCR)</legend>
        <p style={{ margin: '0 0 8px', fontSize: '11px', opacity: 0.85 }}>
          Power document Q&amp;A and image OCR using Google Gemini. Get a free key at <a href="https://aistudio.google.com/app/apikey" target="_blank" rel="noreferrer" style={{ color: 'var(--blue)', textDecoration: 'underline' }}>Google AI Studio</a>.
        </p>
        <div className="row">
          <input
            type="password"
            value={geminiKey}
            onChange={e => setGeminiKey(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && saveGeminiKey()}
            placeholder="AIzaSy... (Gemini API Key)"
          />
          <button className="btn" onClick={saveGeminiKey}>Save Key</button>
        </div>
        {geminiKey && (
          <small style={{ display: 'block', marginTop: 4, color: '#167a3a', fontSize: '10px' }}>
            [Active] Gemini API Key configured on this browser
          </small>
        )}
      </fieldset>

      <fieldset>
        <legend>Index map</legend>
        {st ? <>
          <div className="sunk grid">{cells.map((c, i) => <i key={i} className={c} />)}</div>
          <p style={{ margin: '6px 0' }}>
            <i className="dot" style={{ background: '#000080' }} /> indexed {st.indexed_files} &nbsp;
            <i className="dot" style={{ background: '#f2d45c' }} /> pending {st.pending_files} &nbsp;
            <i className="dot" style={{ background: '#d00' }} /> failed {st.failed_files} &nbsp; of {st.total_files}
          </p>
          <div className="row">
            <button className="btn" onClick={indexNow}>Index Now</button>
            {st.watcher_running
              ? <button className="btn" onClick={() => act(() => post('/index/pause'))}>Pause</button>
              : <button className="btn" onClick={() => act(() => post('/index/resume'))}>Resume</button>}
          </div>
        </> : <div className="err">Backend not reachable on localhost:8000.</div>}
      </fieldset>

      <fieldset>
        <legend>Privacy &amp; Architecture</legend>
        Your files are parsed, chunked, and embedded entirely locally on this computer using ONNX &amp; FAISS.
        When using &quot;Ask your files&quot;, only the top retrieved excerpts are sent to your chosen LLM (Groq or Gemini) to formulate the answer.
      </fieldset>

      <fieldset>
        <legend>Account</legend>
        <div className="row" style={{ alignItems: 'center', justifyContent: 'space-between' }}>
          <span style={{ fontSize: '12px' }}>Signed in as <b>{user || 'User'}</b></span>
          {onLogout && (
            <button
              className="btn"
              style={{ background: 'var(--coral)', minWidth: 80, padding: '4px 12px' }}
              onClick={onLogout}
            >
              Sign Out
            </button>
          )}
        </div>
      </fieldset>
    </div>
  )
}
