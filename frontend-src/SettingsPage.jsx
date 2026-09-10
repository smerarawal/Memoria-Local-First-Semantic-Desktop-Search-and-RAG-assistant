import { useState, useEffect, useCallback } from 'react'
import { useApi } from '../useApi'

export default function SettingsPage({ addToast }) {
  const { get, post, del } = useApi()
  const [folders, setFolders] = useState([])
  const [status, setStatus] = useState(null)
  const [newPath, setNewPath] = useState('')
  const [adding, setAdding] = useState(false)
  const [indexing, setIndexing] = useState(false)

  const loadFolders = useCallback(async () => {
    try { setFolders(await get('/folders')) } catch {}
  }, [get])

  const loadStatus = useCallback(async () => {
    try { setStatus(await get('/index/status')) } catch {}
  }, [get])

  useEffect(() => {
    loadFolders()
    loadStatus()
    const id = setInterval(() => { loadFolders(); loadStatus() }, 4000)
    return () => clearInterval(id)
  }, [loadFolders, loadStatus])

  async function addFolder() {
    if (!newPath.trim()) return
    setAdding(true)
    try {
      const res = await post('/folders', { path: newPath.trim() })
      addToast(`Added folder: ${res.new_files} new file(s) found`, 'success')
      setNewPath('')
      loadFolders()
      loadStatus()
    } catch (e) {
      addToast(e.message, 'error')
    } finally {
      setAdding(false)
    }
  }

  async function removeFolder(id, path) {
    try {
      await del(`/folders/${id}`)
      addToast(`Removed: ${path}`, 'info')
      loadFolders()
      loadStatus()
    } catch (e) {
      addToast(e.message, 'error')
    }
  }

  async function triggerIndex() {
    setIndexing(true)
    try {
      const res = await post('/index')
      addToast(res.message, 'success')
      loadStatus()
    } catch (e) {
      addToast(e.message, 'error')
    } finally {
      setIndexing(false)
    }
  }

  async function pauseWatcher() {
    try {
      await post('/index/pause')
      addToast('File monitoring paused', 'info')
      loadStatus()
    } catch (e) { addToast(e.message, 'error') }
  }

  async function resumeWatcher() {
    try {
      await post('/index/resume')
      addToast('File monitoring resumed', 'success')
      loadStatus()
    } catch (e) { addToast(e.message, 'error') }
  }

  return (
    <div>
      <h2 style={{ fontSize: '1.4rem', fontWeight: 700, marginBottom: '1.5rem', letterSpacing: '-0.02em' }}>
        Settings
      </h2>

      <div className="settings-grid">
        {/* ── Folder Manager ── */}
        <div className="settings-card">
          <h3>📁 Indexed Folders</h3>

          <div className="folder-input-row">
            <input
              className="text-input"
              placeholder="Paste full folder path…"
              value={newPath}
              onChange={e => setNewPath(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && addFolder()}
              id="folder-path-input"
            />
            <button
              className="btn btn-primary"
              onClick={addFolder}
              disabled={adding || !newPath.trim()}
              id="add-folder-btn"
            >
              {adding ? '…' : '+ Add'}
            </button>
          </div>

          <div className="folder-list">
            {folders.length === 0 && (
              <p style={{ fontSize: '0.82rem', color: 'var(--text-muted)', textAlign: 'center', padding: '1rem' }}>
                No folders added yet
              </p>
            )}
            {folders.map(f => (
              <div className="folder-item" key={f.folder_id}>
                <span style={{ fontSize: '1rem' }}>📂</span>
                <span className="folder-item-path" title={f.path}>{f.path}</span>
                <button
                  className="folder-item-delete"
                  onClick={() => removeFolder(f.folder_id, f.path)}
                  title="Remove folder"
                >✕</button>
              </div>
            ))}
          </div>
        </div>

        {/* ── Status + Controls ── */}
        <div>
          <div className="settings-card" style={{ marginBottom: '1rem' }}>
            <h3>📊 Index Status</h3>

            {status ? (
              <>
                <div className="stat-grid">
                  <div className="stat-item">
                    <div className="stat-value">{status.total_files}</div>
                    <div className="stat-label">Total Files</div>
                  </div>
                  <div className="stat-item">
                    <div className="stat-value">{status.indexed_files}</div>
                    <div className="stat-label">Indexed</div>
                  </div>
                  <div className="stat-item">
                    <div className="stat-value">{status.pending_files}</div>
                    <div className="stat-label">Pending</div>
                  </div>
                  <div className="stat-item">
                    <div className="stat-value">{status.watched_folders}</div>
                    <div className="stat-label">Watched Folders</div>
                  </div>
                </div>

                <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
                  <button
                    className="btn btn-ghost"
                    onClick={triggerIndex}
                    disabled={indexing}
                    id="index-now-btn"
                  >
                    {indexing ? '⏳ Indexing…' : '⚡ Index Now'}
                  </button>

                  {status.watcher_running ? (
                    <button className="btn btn-danger" onClick={pauseWatcher} id="pause-btn">
                      ⏸ Pause Monitoring
                    </button>
                  ) : (
                    <button className="btn btn-primary" onClick={resumeWatcher} id="resume-btn">
                      ▶ Resume Monitoring
                    </button>
                  )}
                </div>

                {status.failed_files > 0 && (
                  <div className="error-box" style={{ marginTop: '0.75rem' }}>
                    ⚠ {status.failed_files} file(s) failed to index. Check file permissions or format.
                  </div>
                )}
              </>
            ) : (
              <div className="spinner" />
            )}
          </div>

          {/* ── Privacy Banner ── */}
          <div className="settings-card">
            <h3>🔒 Privacy</h3>
            <div className="privacy-banner">
              <span className="privacy-icon">🖥️</span>
              <div>
                <strong style={{ color: 'var(--success)', display: 'block', marginBottom: '0.25rem' }}>100% Local Processing</strong>
                Your files are read, chunked, and embedded on this device.
                No document content is sent to any external service.
                The embedding model (all-MiniLM-L6-v2) runs entirely locally via PyTorch.
                Ollama LLM queries (RAG, coming next) also run on-device.
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
