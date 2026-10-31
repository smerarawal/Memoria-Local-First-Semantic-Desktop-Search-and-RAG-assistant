import { useState, useEffect, useRef } from 'react'
import { useApi } from './useApi'
import Px from './Px'
import FormattedAnswer from './FormattedAnswer'

const EXT = [['All files', ''], ['PDF', '.pdf'], ['Word', '.docx'], ['PowerPoint', '.pptx'], ['Text', '.txt'], ['Markdown', '.md'], ['Images (PNG/JPG)', '.png']]

// Segmented progress-block score bar (capped: backend scores can exceed 100%)
const Bar = ({ pct }) => {
  const n = Math.min(10, Math.max(0, Math.round(pct / 10)))
  return <span className="bar">{Array.from({ length: 10 }, (_, i) => <i key={i} className={'blk' + (i < n ? ' on' : '')} />)}</span>
}

export default function SearchPage({ addToast, onHits, st }) {
  const { get, post } = useApi()
  const [mode, setMode] = useState('search')
  const [provider, setProvider] = useState(() => localStorage.getItem('memoria_provider') || 'auto')
  const [q, setQ] = useState('')
  const [ext, setExt] = useState('')
  const [res, setRes] = useState(null)
  const [rag, setRag] = useState(null)
  const [sel, setSel] = useState(null)
  const [busy, setBusy] = useState(false)
  const [elapsed, setElapsed] = useState(0)
  const [err, setErr] = useState(null)
  const timerRef = useRef(null)

  useEffect(() => {
    if (busy) {
      setElapsed(0)
      const t0 = Date.now()
      timerRef.current = setInterval(() => {
        setElapsed((Date.now() - t0) / 1000)
      }, 100)
    } else {
      if (timerRef.current) clearInterval(timerRef.current)
    }
    return () => {
      if (timerRef.current) clearInterval(timerRef.current)
    }
  }, [busy])

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
        const apiKey = localStorage.getItem('memoria_gemini_key') || ''
        const groqKey = localStorage.getItem('memoria_groq_key') || ''
        const defaultModel = provider === 'groq' ? 'Groq Llama 3.3 70B' : provider === 'gemini' ? 'Gemini Flash' : 'Auto (Groq / Gemini)'
        setRag({ answer: '', sources: [], model: defaultModel, streaming: true })

        try {
          const resp = await fetch('http://localhost:8000/rag/stream', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              query: q,
              top_k: 5,
              api_key: apiKey,
              groq_api_key: groqKey,
              provider: provider,
            }),
          })

          if (!resp.ok) {
            throw new Error(`HTTP ${resp.status}`)
          }

          const reader = resp.body.getReader()
          const decoder = new TextDecoder()
          let buffer = ''
          let currentAnswer = ''
          let sourcesList = []
          let modelName = defaultModel
          let finalMetrics = null

          while (true) {
            const { value, done } = await reader.read()
            if (done) break
            buffer += decoder.decode(value, { stream: true })
            const lines = buffer.split('\n\n')
            buffer = lines.pop()

            for (const block of lines) {
              const eventMatch = block.match(/^event:\s*(\w+)/m)
              const dataMatch = block.match(/^data:\s*(.+)$/m)
              if (!dataMatch) continue

              const eventType = eventMatch ? eventMatch[1] : 'token'
              try {
                const data = JSON.parse(dataMatch[1])
                if (eventType === 'init') {
                  sourcesList = data.sources || []
                  setRag(prev => ({ ...prev, sources: sourcesList }))
                  onHits(sourcesList.length, q)
                } else if (eventType === 'heartbeat') {
                  // Server is alive, LLM processing
                } else if (eventType === 'token') {
                  currentAnswer += data.token
                  setRag(prev => ({ ...prev, answer: currentAnswer, streaming: true }))
                } else if (eventType === 'done') {
                  modelName = data.model || modelName
                  finalMetrics = data.metrics
                  setRag(prev => ({
                    ...prev,
                    answer: currentAnswer,
                    sources: sourcesList,
                    model: modelName,
                    metrics: finalMetrics,
                    streaming: false,
                  }))
                }
              } catch (_) {
                // Ignore parse errors on partial chunks
              }
            }
          }
        } catch (_) {
          // Fallback to standard POST /rag
          const d = await post('/rag', {
            query: q,
            top_k: 5,
            api_key: apiKey,
            groq_api_key: groqKey,
            provider: provider,
          })
          setRag(d)
          onHits(d.sources.length, q)
        }
      }
    } catch (e) {
      setErr(e.message)
      addToast((mode === 'search' ? 'Search' : 'Ask') + ' failed: ' + e.message)
    } finally {
      setBusy(false)
    }
  }

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
            placeholder={mode === 'search' ? 'e.g. game theory assignment' : 'e.g. what internships did i do in my summer?'} />
          {mode === 'search' && (
            <select value={ext} onChange={e => { setExt(e.target.value); if (res) go(e.target.value) }} title="File type">
              {EXT.map(([l, v]) => <option key={v} value={v}>{l}</option>)}
            </select>
          )}
          {mode === 'ask' && (
            <select
              value={provider}
              onChange={e => {
                setProvider(e.target.value)
                localStorage.setItem('memoria_provider', e.target.value)
              }}
              title="Select LLM Engine"
            >
              <option value="auto">Auto (Groq ~0.3s / Gemini fallback)</option>
              <option value="groq">Groq (Llama 3.3 70B)</option>
              <option value="gemini">Gemini (Google 1.5)</option>
            </select>
          )}
          <button className="btn" onClick={() => go()} disabled={busy || !q.trim()}>{busy ? `Working... (${elapsed.toFixed(1)}s)` : mode === 'search' ? 'Find Now' : provider === 'groq' ? 'Ask Groq' : provider === 'gemini' ? 'Ask Gemini' : 'Ask AI'}</button>
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

        {mode === 'ask' && busy && (!rag || !rag.answer) && (
          <div className="sunk ans" style={{ padding: '16px', display: 'flex', flexDirection: 'column', gap: 10 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, fontSize: '13px', fontWeight: 600 }}>
              <span style={{ display: 'inline-block', width: 12, height: 12, border: '2px solid var(--blue)', borderTopColor: 'transparent', borderRadius: '50%', animation: 'spin 0.8s linear infinite' }} />
              <span>{rag?.sources?.length > 0 ? `Retrieved ${rag.sources.length} matching excerpts · Synthesizing detailed response...` : 'Searching document index...'}</span>
              <span style={{ opacity: 0.65, fontSize: '12px', fontVariantNumeric: 'tabular-nums', marginLeft: 'auto' }}>({elapsed.toFixed(1)}s)</span>
            </div>
            {rag?.sources?.length > 0 && (
              <div style={{ fontSize: '12px', opacity: 0.85, background: 'rgba(255,255,255,0.03)', padding: '8px 12px', borderRadius: 4, borderLeft: '3px solid var(--blue)' }}>
                <b>Direct excerpt from {rag.sources[0].filename}:</b> <i>"{rag.sources[0].snippet.slice(0, 160)}..."</i>
              </div>
            )}
          </div>
        )}

        {mode === 'ask' && rag && rag.answer && (
          <div className="sunk ans">
            <FormattedAnswer content={rag.answer} />
            {rag.streaming && <span style={{ display: 'inline-block', width: 8, height: 14, background: 'var(--blue)', marginLeft: 4, animation: 'blink 1s infinite' }}>▌</span>}
          </div>
        )}

        {mode === 'ask' && rag && rag.sources && rag.sources.length > 0 && (
          <fieldset style={{ flex: 1, minHeight: 100, overflow: 'auto' }}>
            <legend>Evidence ({rag.sources.length} matching excerpts)</legend>
                <div className="sunk" style={{ margin: -2 }}>
                  {rag.sources.map((s, i) => {
                    const isImage = s.extension && ['.png', '.jpg', '.jpeg', '.webp', '.gif', '.bmp'].includes(s.extension.toLowerCase())
                    return (
                      <div className="ev" key={i} onClick={() => openFile(s.path)} style={{ cursor: 'pointer' }} title="Click to open this file in default app">
                        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                          <b>[{i + 1}] {s.filename}</b>{s.page != null && ` - p.${s.page}`} <Bar pct={s.score * 100} />
                          {isImage && <span style={{ fontSize: '10px', background: 'rgba(70,130,255,0.2)', padding: '1px 6px', borderRadius: 3 }}>[Image]</span>}
                          <button className="btn" style={{ padding: '2px 8px', fontSize: '10px', marginLeft: 'auto' }} onClick={(e) => { e.stopPropagation(); openFile(s.path) }}>Open</button>
                        </div>
                        {isImage && s.file_id && (
                          <div style={{ margin: '6px 0', textAlign: 'center' }}>
                            <img
                              src={`http://localhost:8000/files/${s.file_id}/thumbnail`}
                              alt={s.filename}
                              style={{ maxWidth: 200, maxHeight: 150, borderRadius: 4, border: '1px solid rgba(255,255,255,0.15)' }}
                              onError={e => { e.target.style.display = 'none' }}
                            />
                          </div>
                        )}
                        <small>{isImage && s.snippet?.startsWith('IMAGE_DESCRIPTION:') ? s.snippet.replace('IMAGE_DESCRIPTION: ', '') : s.snippet}</small>
                      </div>
                    )
                  })}
                </div>
              </fieldset>
            )}

        {!res && !rag && !err && !busy && (
          <div className="sunk pv" style={{ maxHeight: 'none' }}>
            {mode === 'search'
              ? 'Type what you remember, not the filename. Results are ranked by meaning. Click any file to open it in your default app.'
              : 'Ask a question. Memoria retrieves excerpts from your indexed files and produces an accurate, cited answer.'}
          </div>
        )}
      </div>
      <div className="status">
        <span>
          {busy
            ? `Working... (${elapsed.toFixed(1)}s)`
            : res
            ? `${res.total_results} file(s) found`
            : rag
            ? (rag.metrics
                ? `${(rag.metrics.total_ms / 1000).toFixed(1)}s (retrieval: ${rag.metrics.search_ms}ms · LLM: ${(rag.metrics.llm_ms / 1000).toFixed(1)}s) · ${rag.model}`
                : `Answered by ${rag.model}`)
            : 'Ready'}
        </span>
        <span>{st ? `${st.indexed_files} indexed - watcher ${st.watcher_running ? 'on' : 'paused'}` : 'backend offline'}</span>
        <span>AI: {rag?.model || (provider === 'gemini' ? 'Gemini Flash' : 'Groq Llama 3.3')}</span>
      </div>
    </>
  )
}
