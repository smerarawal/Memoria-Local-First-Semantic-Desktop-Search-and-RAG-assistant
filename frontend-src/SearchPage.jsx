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

  const reset = () => { setRes(null); setRag(null); setSel(null); setErr(null) }
  const copy = (p) => { navigator.clipboard?.writeText(p); addToast('Path copied: ' + p) }

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
        const d = await post('/rag', { query: q, top_k: 5 })
        setRag(d); onHits(d.sources.length, q)
      }
    } catch (e) { setErr(e.message); addToast((mode === 'search' ? 'Search' : 'Ask') + ' failed: ' + e.message) }
    finally { setBusy(false) }
  }

  const cloud = rag?.model?.includes('cloud')
  return (
    <>
      <div className="body">
        <div className="tabs">
          <button className={'tab' + (mode === 'search' ? ' on' : '')} onClick={() => { setMode('search'); reset() }}>Find by meaning</button>
          <button className={'tab' + (mode === 'ask' ? ' on' : '')} onClick={() => { setMode('ask'); reset() }}>Ask your files</button>
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
          <button className="btn" onClick={() => go()} disabled={busy || !q.trim()}>{busy ? 'Working...' : mode === 'search' ? 'Find Now' : 'Ask'}</button>
        </div>

        {err && <div className="err">{err}</div>}

        {mode === 'search' && res && (res.results.length === 0
          ? <div className="sunk pv">No files match. Try different words, or add folders in Setup.</div>
          : <>
            <div className="sunk lv">
              <table>
                <thead><tr><th>Name</th><th>Score</th><th>Type</th><th>Pages</th><th>Path</th></tr></thead>
                <tbody>
                  {res.results.map(r => (
                    <tr key={r.file_id} className={sel?.file_id === r.file_id ? 'sel' : ''} onClick={() => setSel(r)} onDoubleClick={() => copy(r.path)}>
                      <td><Px n="doc" s={1} /> {r.filename}</td>
                      <td><Bar pct={r.relevance_pct} /> {Math.min(100, r.relevance_pct)}%</td>
                      <td>{r.extension.replace('.', '').toUpperCase()}</td>
                      <td>{r.matched_pages.slice(0, 4).join(', ')}{r.matched_pages.length > 4 ? '...' : ''}</td>
                      <td>{r.path}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {sel && <div className="sunk pv" title="Double-click a row to copy its path"><b>{sel.filename}</b> (p.{sel.top_page}){'\n'}{sel.top_chunk_text}</div>}
          </>)}

        {mode === 'ask' && rag && (
          <>
            <div className="sunk ans">{rag.answer}</div>
            {rag.sources.length > 0 && (
              <fieldset style={{ flex: 1, minHeight: 100, overflow: 'auto' }}>
                <legend>Evidence (citations [n] refer to these)</legend>
                <div className="sunk" style={{ margin: -2 }}>
                  {rag.sources.map((s, i) => (
                    <div className="ev" key={i} onDoubleClick={() => copy(s.path)}>
                      <b>[{i + 1}] {s.filename}</b>{s.page != null && ` - p.${s.page}`} <Bar pct={s.score * 100} />
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
              ? 'Type what you remember, not the filename. Results are ranked by meaning.'
              : 'Ask a question. Memoria retrieves passages from your files and answers with citations.'}
          </div>
        )}
      </div>
      <div className="status">
        <span>{busy ? 'Working...' : res ? `${res.total_results} file(s) found` : rag ? `Answered by ${rag.model}` : 'Ready'}</span>
        <span>{st ? `${st.indexed_files} indexed - watcher ${st.watcher_running ? 'on' : 'paused'}` : 'backend offline'}</span>
        <span>{cloud ? 'Network: Google (cloud)' : 'Network: none'}</span>
      </div>
    </>
  )
}
