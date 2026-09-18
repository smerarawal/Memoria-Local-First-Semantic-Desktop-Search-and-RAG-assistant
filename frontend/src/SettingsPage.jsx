import { useState, useEffect, useCallback } from 'react'
import { useApi } from './useApi'

export default function SettingsPage({ addToast, user }) {
  const { get, post, del } = useApi()
  const [folders, setFolders] = useState([])
  const [status, setStatus] = useState(null)
  const [newPath, setNewPath] = useState('')
  const [adding, setAdding] = useState(false)
  const [indexing, setIndexing] = useState(false)
  const [userName, setUserName] = useState(() => localStorage.getItem('memoria_name') || '')

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
      await post('/folders', { path: newPath.trim() })
      setNewPath('')
      await loadFolders()
      addToast('Folder added', 'success')
    } catch (e) { addToast(e.message, 'error') }
    finally { setAdding(false) }
  }

  async function removeFolder(id, path) {
    try {
      await del(`/folders/${id}`)
      await loadFolders()
      addToast(`Removed: ${path}`, 'info')
    } catch (e) { addToast(e.message, 'error') }
  }

  async function triggerIndex() {
    setIndexing(true)
    try {
      await post('/index/trigger')
      addToast('Indexing started', 'info')
      setTimeout(loadStatus, 1500)
    } catch (e) { addToast(e.message, 'error') }
    finally { setIndexing(false) }
  }

  async function pauseWatcher() {
    try { await post('/index/pause'); await loadStatus() } catch (e) { addToast(e.message, 'error') }
  }
  async function resumeWatcher() {
    try { await post('/index/resume'); await loadStatus() } catch (e) { addToast(e.message, 'error') }
  }

  return (
    <div className="settings-shell">

      {/* Left — content area */}
      <div className="settings-content">

        {/* Natural page heading */}
        <div className="settings-page-title">
          <p className="settings-eyebrow">Configuration</p>
          <h2 className="settings-title">Settings</h2>
        </div>

        <div className="settings-grid">
          {/* Account Info */}
          <div className="settings-card">
            <h3 className="settings-card-title">Account</h3>
            {userName && (
              <p style={{ color: 'var(--text-1)', fontSize: '0.92rem', marginBottom: '0.3rem', fontFamily: "'Fraunces', serif" }}>
                Name: <strong style={{ color: '#fff', fontWeight: 400 }}>{userName}</strong>
              </p>
            )}
            <p style={{ color: 'var(--text-2)', fontSize: '0.85rem' }}>
              Logged in as: <strong style={{ color: '#fff' }}>{user}</strong>
            </p>
          </div>

          {/* Folder Manager */}
          <div className="settings-card">
            <h3 className="settings-card-title">Indexed Folders</h3>

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
                <p className="folder-empty">No folders added yet</p>
              )}
              {folders.map(f => (
                <div className="folder-item" key={f.folder_id}>
                  <span className="folder-item-icon" aria-hidden="true" />
                  <span className="folder-item-path" title={f.path}>{f.path}</span>
                  <button
                    className="folder-item-delete"
                    onClick={() => removeFolder(f.folder_id, f.path)}
                    title="Remove folder"
                  >
                    ✕
                  </button>
                </div>
              ))}
            </div>
          </div>

          {/* Status + Controls */}
          <div>
            <div className="settings-card" style={{ marginBottom: '1rem' }}>
              <h3 className="settings-card-title">Index Status</h3>

              {status ? (
                <>
                  <div className="stat-grid">
                    <div className="stat-item">
                      <div className="stat-value">{status.total_files}</div>
                      <div className="stat-label">Total files</div>
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
                      <div className="stat-label">Watched folders</div>
                    </div>
                  </div>

                  {status.pending_files > 0 && (
                    <div className="indexing-hint">
                      <strong>{status.pending_files} file{status.pending_files > 1 ? 's' : ''}</strong> being embedded in the background.
                    </div>
                  )}

                  <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap', marginTop: '1rem' }}>
                    <button className="btn btn-ghost" onClick={triggerIndex} disabled={indexing} id="index-now-btn">
                      {indexing ? 'Indexing…' : 'Index Now'}
                    </button>
                    {status.watcher_running ? (
                      <button className="btn btn-danger" onClick={pauseWatcher} id="pause-btn">Pause Monitoring</button>
                    ) : (
                      <button className="btn btn-primary" onClick={resumeWatcher} id="resume-btn">Resume Monitoring</button>
                    )}
                  </div>

                  {status.failed_files > 0 && (
                    <div className="error-box" style={{ marginTop: '0.75rem' }}>
                      {status.failed_files} file(s) failed to index. Check permissions or file format.
                    </div>
                  )}
                </>
              ) : (
                <div className="spinner" />
              )}
            </div>

            {/* Privacy */}
            <div className="settings-card">
              <h3 className="settings-card-title">Privacy</h3>
              <div className="privacy-banner">
                <strong className="privacy-title">100% Local Processing</strong>
                <p className="privacy-body">
                  Your files are read, chunked, and embedded on this device.
                  Nothing is sent to any external service.
                  The embedding model runs entirely offline via ONNX Runtime.
                </p>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Right — space image panel (clean, no text overlay) */}
      <div className="settings-image-panel" aria-hidden="true">
        <div className="settings-image-inner" />
      </div>

    </div>
  )
}
