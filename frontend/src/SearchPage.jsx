import { useState } from 'react'
import { useApi } from './useApi'
import Px from './Px'

const EXT = [['All files', ''], ['PDF', '.pdf'], ['Word', '.docx'], ['Text', '.txt'], ['Markdown', '.md']]

// Segmented progress-block score bar (capped: backend scores can exceed 100%)
const Bar = ({ pct }) => {
  const n = Math.min(10, Math.max(0, Math.round(pct / 10)))
  return <span className="bar">{Array.from({ length: 10 }, (_, i) => <i key={i} className={'blk' + (i < n ? ' on' : '')} />)}</span>
}

export default function SearchPage({ addToast, onHits, st }) {
  const { get, post } = useApi()
  const [mode, setMode] = useState('search')
  const [q, setQ] = useState('')
  const [ext, setExt] = useState('')
  const [res, setRes] = useState(null)
  const [rag, setRag] = useState(null)
  const [sel, setSel] = useState(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)
  const [quickKey, setQuickKey] = useState('')

  const reset = () => { setRes(null); setRag(null); setSel(null); setErr(null) }
  const copy = (p) => { navigator.clipboard?.writeText(p); addToast('Path copied: ' + p) }

  const openFile = async (path, file_id) => {
    try {
      await post('/files/open', { path, file_id })
      const name = path ? path.split(/[/\\]/).pop() : 'file'
      addToast('Opening ' + name + ' in default app...')
    } catch (e) {
      addToast('Could not open file: ' + e.message)
    }
  }

  const revealFile = async (path, file_id) => {
    try {
      await post('/files/reveal', { path, file_id })
      addToast('Revealing file in Explorer...')
    } catch (e) {
      addToast('Could not reveal: ' + e.message)
    }
  }

  async function go(extArg = ext) {
    if (!q.trim() || busy) return
    setBusy(true); reset()
    try {
      if (mode === 'search') {
        const p = new URLSearchParams({ q, top_k: 15 })
        if (extArg) p.set('extension', extArg)
        const d = await get('/search?' + p)
        setRes(d); setSel(d.results[0] ?? null); onHits(d.results.length, q)
      } else {
        const apiKey = localStorage.getItem('memoria_gemini_key') || quickKey.trim() || ''
        const d = await post('/rag', { query: q, top_k: 5, api_key: apiKey })
        setRag(d); onHits(d.sources.length, q)
      }
    } catch (e) { setErr(e.message); addToast((mode === 'search' ? 'Search' : 'Ask') + ' failed: ' + e.message) }
    finally { setBusy(false) }
  }

  return (
    <>
      <div className="body">
        <div className="tabs">
          <button className={'tab' + (mode === 'search' ? ' on' : '')} onClick={() => { setMode('search'); reset() }}>Find by meaning</button>
          <button className={'tab' + (mode === 'ask' ? ' on' : '')} onClick={() => { setMode('ask'); reset() }}>Ask your files (Gemini)</button>
        </div>

        <div className="row">
          <label htmlFor="q">{mode === 'search' ? 'Named:' : 'Question:'}</label>
          <input id="q" autoFocus value={q} onChange={e => setQ(e.target.value)} onKeyDown={e => e.key === 'Enter' && go()}
            placeholder={mode === 'search' ? 'e.g. game theory assignment' : 'e.g. What do my notes say about Shapley values?'} />
          {mode === 'search' && (
            <select value={ext} onChange={e => { setExt(e.target.value); if (res) go(e.target.value) }} title="File type">
              {EXT.map(([l, v]) => <option key={v} value={v}>{l}</option>)}
            </select>
          )}
          <button className="btn" onClick={() => go()} disabled={busy || !q.trim()}>{busy ? 'Working...' : mode === 'search' ? 'Find Now' : 'Ask Gemini'}</button>
        </div>

        {err && <div className="err">{err}</div>}

        {mode === 'search' && res && (res.results.length === 0
          ? <div className="sunk pv">No files match. Try different words, or add folders in Setup.</div>
          : <>
            <div className="sunk lv">
              <table>
                <thead><tr><th>Name (click to open)</th><th>Score</th><th>Type</th><th>Pages</th><th>Actions</th></tr></thead>
                <tbody>
                  {res.results.map(r => (
                    <tr key={r.file_id} className={sel?.file_id === r.file_id ? 'sel' : ''} onClick={() => setSel(r)} onDoubleClick={() => openFile(r.path, r.file_id)} title="Click to preview, double-click to open">
                      <td onClick={(e) => { e.stopPropagation(); openFile(r.path, r.file_id) }} style={{ cursor: 'pointer' }} title="Click to open file in default app">
                        <Px n="doc" s={1} /> <span style={{ textDecoration: 'underline' }}>{r.filename}</span>
                      </td>
                      <td><Bar pct={r.relevance_pct} /> {Math.min(100, r.relevance_pct)}%</td>
                      <td>{r.extension.replace('.', '').toUpperCase()}</td>
                      <td>{r.matched_pages.slice(0, 4).join(', ')}{r.matched_pages.length > 4 ? '...' : ''}</td>
                      <td>
                        <button className="btn" style={{ padding: '2px 8px', fontSize: '11px', marginRight: 4 }} onClick={(e) => { e.stopPropagation(); openFile(r.path, r.file_id) }} title="Open in default app">Open</button>
                        <button className="btn" style={{ padding: '2px 8px', fontSize: '11px', background: 'var(--blue2)' }} onClick={(e) => { e.stopPropagation(); revealFile(r.path, r.file_id) }} title="Show in File Explorer">Folder</button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {sel && (
              <div className="sunk pv" style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                  <b>{sel.filename}</b> <span style={{ opacity: 0.7 }}>(page {sel.top_page})</span>
                  <button className="btn" style={{ padding: '2px 10px', fontSize: '11px' }} onClick={() => openFile(sel.path, sel.file_id)}>Open File</button>
                  <button className="btn" style={{ padding: '2px 10px', fontSize: '11px', background: 'var(--blue2)' }} onClick={() => revealFile(sel.path, sel.file_id)}>Show in Explorer</button>
                  <button className="btn" style={{ padding: '2px 10px', fontSize: '11px', background: 'rgba(22,64,107,0.3)', boxShadow: 'none' }} onClick={() => copy(sel.path)}>Copy Path</button>
                </div>
                <div style={{ opacity: 0.9 }}>{sel.top_chunk_text}</div>
              </div>
            )}
          </>)}

        {mode === 'ask' && rag && (
          <>
            <div className="sunk ans">{rag.answer}</div>
            
            {/* Quick Gemini key prompt if missing */}
            {rag.model === 'none' && rag.answer.toLowerCase().includes('gemini') && (
              <div className="err" style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                <span style={{ fontSize: '11px' }}>Quick key:</span>
                <input
                  type="password"
                  placeholder="Paste Gemini API Key here & press Enter"
                  value={quickKey}
                  onChange={e => setQuickKey(e.target.value)}
                  onKeyDown={e => {
                    if (e.key === 'Enter' && quickKey.trim()) {
                      localStorage.setItem('memoria_gemini_key', quickKey.trim())
                      addToast('Gemini key saved!')
                      go()
                    }
                  }}
                  style={{ flex: 1, padding: '4px 8px' }}
                />
                <button className="btn" style={{ padding: '4px 10px' }} onClick={() => {
                  if (quickKey.trim()) {
                    localStorage.setItem('memoria_gemini_key', quickKey.trim())
                    addToast('Gemini key saved!')
                    go()
                  }
                }}>Save</button>
              </div>
            )}

            {rag.sources.length > 0 && (
              <fieldset style={{ flex: 1, minHeight: 100, overflow: 'auto' }}>
                <legend>Evidence (click any source to open)</legend>
                <div className="sunk" style={{ margin: -2 }}>
                  {rag.sources.map((s, i) => (
                    <div className="ev" key={i} onClick={() => openFile(s.path)} style={{ cursor: 'pointer' }} title="Click to open this file in default app">
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                        <b>[{i + 1}] {s.filename}</b>{s.page != null && ` - p.${s.page}`} <Bar pct={s.score * 100} />
                        <button className="btn" style={{ padding: '2px 8px', fontSize: '10px', marginLeft: 'auto' }} onClick={(e) => { e.stopPropagation(); openFile(s.path) }}>Open</button>
                      </div>
                      <small>{s.snippet}</small>
                    </div>
                  ))}
                </div>
              </fieldset>
            )}
          </>
        )}

        {!res && !rag && !err && !busy && (
          <div className="sunk pv" style={{ maxHeight: 'none' }}>
            {mode === 'search'
              ? 'Type what you remember, not the filename. Results are ranked by meaning. Click any file to open it in your default app.'
              : 'Ask a question. Memoria retrieves excerpts from your indexed files and Gemini produces an accurate, cited answer.'}
          </div>
        )}
      </div>
      <div className="status">
        <span>{busy ? 'Working...' : res ? `${res.total_results} file(s) found` : rag ? `Answered by ${rag.model}` : 'Ready'}</span>
        <span>{st ? `${st.indexed_files} indexed - watcher ${st.watcher_running ? 'on' : 'paused'}` : 'backend offline'}</span>
        <span>AI: Gemini 1.5 Flash</span>
      </div>
    </>
  )
}
