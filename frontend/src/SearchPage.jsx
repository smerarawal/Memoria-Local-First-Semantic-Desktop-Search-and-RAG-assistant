import { useState } from 'react'
import { useApi } from './useApi'

function fileIcon(ext) {
  const map = { '.pdf': ['PDF', 'icon-pdf'], '.docx': ['DOC', 'icon-docx'], '.txt': ['TXT', 'icon-txt'], '.md': ['MD', 'icon-md'] }
  return map[ext] || ['FILE', 'icon-other']
}

function relevanceBadgeClass(pct) {
  if (pct >= 75) return 'badge-high'
  if (pct >= 50) return 'badge-mid'
  return 'badge-low'
}

export default function SearchPage({ addToast, user }) {
  const { get, post } = useApi()
  const [query, setQuery] = useState('')
  const [mode, setMode] = useState('search') // 'search' | 'ask'
  const [results, setResults] = useState(null)
  const [ragResult, setRagResult] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [activeFilter, setActiveFilter] = useState('')
  const [displayName, setDisplayName] = useState(() => localStorage.getItem('memoria_name') || '')
  const [nameInput, setNameInput] = useState('')
  const [nameFocused, setNameFocused] = useState(false)

  function saveName(e) {
    if (e.key === 'Enter' && nameInput.trim()) {
      const n = nameInput.trim()
      localStorage.setItem('memoria_name', n)
      setDisplayName(n)
      setNameInput('')
    }
  }

  const FILTERS = [
    { label: 'All',      value: '' },
    { label: 'PDF',      value: '.pdf' },
    { label: 'DOCX',     value: '.docx' },
    { label: 'TXT',      value: '.txt' },
    { label: 'Markdown', value: '.md' },
  ]

  async function doSearch(q = query, ext = activeFilter) {
    if (!q.trim()) return
    setLoading(true)
    setError(null)
    setRagResult(null)
    try {
      const params = new URLSearchParams({ q, top_k: 15 })
      if (ext) params.set('extension', ext)
      const data = await get(`/search?${params}`)
      setResults(data)
    } catch (e) {
      setError(e.message)
      addToast('Search failed: ' + e.message, 'error')
    } finally {
      setLoading(false)
    }
  }

  async function doAsk(q = query) {
    if (!q.trim()) return
    setLoading(true)
    setError(null)
    setResults(null)
    try {
      const data = await post('/rag', { query: q, top_k: 5 })
      setRagResult(data)
    } catch (e) {
      setError(e.message)
      addToast('Ask failed: ' + e.message, 'error')
    } finally {
      setLoading(false)
    }
  }

  function handleSubmit() {
    if (mode === 'search') doSearch()
    else doAsk()
  }

  function handleKeyDown(e) {
    if (e.key === 'Enter') handleSubmit()
  }

  function handleFilterChange(value) {
    setActiveFilter(value)
    if (results) doSearch(query, value)
  }

  function openFile(path) {
    navigator.clipboard?.writeText(path)
    addToast('Path copied: ' + path, 'info')
  }

  function switchMode(m) {
    setMode(m)
    setResults(null)
    setRagResult(null)
    setError(null)
  }

  return (
    <div>
      <div className="search-hero">
        <h1>Find what you<br/><em>remember</em></h1>
        {/* Name personalisation */}
        {displayName ? (
          <p className="hero-name-tag">
            {displayName}
            <button className="hero-name-reset" onClick={() => { localStorage.removeItem('memoria_name'); setDisplayName('') }} title="Change name">✕</button>
          </p>
        ) : (
          <div className={`hero-name-wrap ${nameFocused ? 'focused' : ''}`}>
            <span className="hero-name-label">What shall I call you?</span>
            <input
              className="hero-name-input"
              type="text"
              value={nameInput}
              onChange={e => setNameInput(e.target.value)}
              onFocus={() => setNameFocused(true)}
              onBlur={() => setNameFocused(false)}
              onKeyDown={saveName}
              placeholder="your name"
              id="hero-name-input"
            />
          </div>
        )}
      </div>

      {/* Mode toggle */}
      <div className="mode-toggle">
        <button
          className={`mode-btn ${mode === 'search' ? 'active' : ''}`}
          onClick={() => switchMode('search')}
        >Search</button>
        <span className="mode-divider" />
        <button
          className={`mode-btn ${mode === 'ask' ? 'active' : ''}`}
          onClick={() => switchMode('ask')}
        >Ask</button>
      </div>

      <div className="search-box">
        <input
          className="search-input"
          placeholder={mode === 'search'
            ? 'e.g. "game theory assignment" or "my CV"'
            : 'e.g. "What does my game theory paper say about Shapley values?"'}
          value={query}
          onChange={e => setQuery(e.target.value)}
          onKeyDown={handleKeyDown}
          id="search-input"
          autoFocus
        />
        <button
          className="search-btn"
          onClick={handleSubmit}
          disabled={loading || !query.trim()}
          id="search-submit"
        >
          {loading ? '...' : mode === 'search' ? 'Search' : 'Ask'}
        </button>
      </div>

      {/* Filter row — only in search mode */}
      {mode === 'search' && (
        <div className="filter-row">
          {FILTERS.map(f => (
            <button
              key={f.value}
              className={`chip ${activeFilter === f.value ? 'active' : ''}`}
              onClick={() => handleFilterChange(f.value)}
            >
              {f.label}
            </button>
          ))}
        </div>
      )}

      {loading && <div className="spinner" />}
      {error && <div className="error-box">{error}</div>}

      {/* ── RAG answer ── */}
      {ragResult && !loading && (
        <div className="rag-result">
          <p className="rag-model-label">{ragResult.model}</p>
          <p className="rag-answer">{ragResult.answer}</p>

          {ragResult.sources.length > 0 && (
            <>
              <p className="rag-sources-label">Sources</p>
              {ragResult.sources.map((s, i) => {
                const [label, iconClass] = fileIcon(s.path?.split('.').pop() ? '.' + s.path.split('.').pop() : '')
                return (
                  <div key={i} className="result-card" onClick={() => openFile(s.path)} title={`Click to copy: ${s.path}`}>
                    <div className="result-top">
                      <div className={`file-icon ${iconClass}`}>{label}</div>
                      <div className="result-info">
                        <div className="result-filename">{s.filename}</div>
                        <div className="result-path">{s.path}</div>
                      </div>
                    </div>
                    {s.snippet && <p className="result-snippet">"{s.snippet}"</p>}
                  </div>
                )
              })}
            </>
          )}
        </div>
      )}

      {/* ── Search results ── */}
      {results && !loading && (
        <>
          <div className="results-header">
            <span>{results.total_results} result{results.total_results !== 1 ? 's' : ''} for <strong>"{results.query}"</strong></span>
            <span>{results.total_results > 0 ? 'Ranked by relevance' : ''}</span>
          </div>

          {results.results.length === 0 ? (
            <div className="empty-state">
              <div className="empty-dots">
                {[4,7,5,9,4,6,3].map((s,i) => (
                  <div key={i} className="empty-dot" style={{width:s,height:s}} />
                ))}
              </div>
              <p className="empty-label">Nothing matched</p>
              <p style={{ fontSize: '0.8rem', color: 'var(--text-2)', marginTop: '0.4rem' }}>Try rephrasing, or add folders in Settings.</p>
            </div>
          ) : (
            results.results.map(r => {
              const [label, iconClass] = fileIcon(r.extension)
              const badgeClass = relevanceBadgeClass(r.relevance_pct)
              return (
                <div
                  className="result-card"
                  key={r.file_id}
                  onClick={() => openFile(r.path)}
                  title={`Click to copy path: ${r.path}`}
                >
                  <div className="result-top">
                    <div className={`file-icon ${iconClass}`}>{label}</div>
                    <div className="result-info">
                      <div className="result-filename">{r.filename}</div>
                      <div className="result-path">{r.path}</div>
                    </div>
                    <span className={`relevance-badge ${badgeClass}`}>
                      {r.relevance_pct}%
                    </span>
                  </div>

                  {r.top_chunk_text && (
                    <p className="result-snippet">"{r.top_chunk_text}"</p>
                  )}

                  {r.matched_pages.length > 0 && (
                    <div className="result-pages">
                      {r.matched_pages.slice(0, 6).map(p => (
                        <span className="page-tag" key={p}>p.{p}</span>
                      ))}
                      {r.matched_pages.length > 6 && (
                        <span className="page-tag">+{r.matched_pages.length - 6} more</span>
                      )}
                    </div>
                  )}
                </div>
              )
            })
          )}
        </>
      )}

      {/* ── Landing state ── */}
      {!results && !ragResult && !loading && (
        <div className="landing-state">
          <div className="capability-row">
            <div className="capability-item">
              <span className="capability-num">PDF · DOCX · TXT · MD</span>
              <span className="capability-label">Supported formats</span>
            </div>
            <div className="capability-divider" />
            <div className="capability-item">
              <span className="capability-num">Semantic</span>
              <span className="capability-label">Search by meaning</span>
            </div>
            <div className="capability-divider" />
            <div className="capability-item">
              <span className="capability-num">RAG</span>
              <span className="capability-label">Ask your documents</span>
            </div>
          </div>

          <div className="example-queries">
            <span className="example-label">Try</span>
            {[
              'machine learning notes',
              'invoice from last month',
              'project proposal',
              'resume draft',
            ].map(q => (
              <button
                key={q}
                className="example-chip"
                onClick={() => { setQuery(q); doSearch(q) }}
              >
                {q}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
