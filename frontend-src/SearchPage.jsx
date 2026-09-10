import { useState, useEffect } from 'react'
import { useApi } from '../useApi'

function fileIcon(ext) {
  const map = { '.pdf': ['PDF', 'icon-pdf'], '.docx': ['DOC', 'icon-docx'], '.txt': ['TXT', 'icon-txt'], '.md': ['MD', 'icon-md'] }
  return map[ext] || ['FILE', 'icon-other']
}

function relevanceBadgeClass(pct) {
  if (pct >= 75) return 'badge-high'
  if (pct >= 50) return 'badge-mid'
  return 'badge-low'
}

export default function SearchPage({ addToast }) {
  const { get } = useApi()
  const [query, setQuery] = useState('')
  const [results, setResults] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [activeFilter, setActiveFilter] = useState('')

  const FILTERS = [
    { label: 'All', value: '' },
    { label: '📄 PDF', value: '.pdf' },
    { label: '📝 DOCX', value: '.docx' },
    { label: '🔤 TXT', value: '.txt' },
    { label: '📋 Markdown', value: '.md' },
  ]

  async function doSearch(q = query, ext = activeFilter) {
    if (!q.trim()) return
    setLoading(true)
    setError(null)
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

  function handleKeyDown(e) {
    if (e.key === 'Enter') doSearch()
  }

  function handleFilterChange(value) {
    setActiveFilter(value)
    if (results) doSearch(query, value)
  }

  function openFile(path) {
    // Copy path to clipboard as a fallback (opening local files from browser requires native app)
    navigator.clipboard?.writeText(path)
    addToast('Path copied to clipboard: ' + path, 'info')
  }

  return (
    <div>
      <div className="search-hero">
        <h1>Search your files by memory</h1>
        <p>Type what you remember — Memoria finds it semantically</p>
      </div>

      <div className="search-box">
        <input
          className="search-input"
          placeholder='e.g. "deep learning assignment" or "my CV"'
          value={query}
          onChange={e => setQuery(e.target.value)}
          onKeyDown={handleKeyDown}
          id="search-input"
          autoFocus
        />
        <button
          className="search-btn"
          onClick={() => doSearch()}
          disabled={loading || !query.trim()}
          id="search-submit"
        >
          {loading ? '...' : 'Search'}
        </button>
      </div>

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

      {loading && <div className="spinner" />}

      {error && <div className="error-box">⚠ {error}</div>}

      {results && !loading && (
        <>
          <div className="results-header">
            <span>{results.total_results} result{results.total_results !== 1 ? 's' : ''} for <strong>"{results.query}"</strong></span>
            <span>{results.total_results > 0 ? 'Ranked by semantic relevance' : ''}</span>
          </div>

          {results.results.length === 0 ? (
            <div className="empty-state">
              <div className="empty-icon">🔍</div>
              <p>No matching files found.</p>
              <p style={{ marginTop: '0.5rem', fontSize: '0.85rem' }}>Try a different query or add more folders in Settings.</p>
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

      {!results && !loading && (
        <div className="empty-state">
          <div className="empty-icon">✨</div>
          <p>Start searching across your indexed files</p>
          <p style={{ marginTop: '0.5rem', fontSize: '0.85rem' }}>Add folders in Settings, then search by meaning — not filenames</p>
        </div>
      )}
    </div>
  )
}
