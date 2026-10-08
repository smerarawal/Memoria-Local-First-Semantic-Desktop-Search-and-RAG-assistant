import { useState, useEffect, useCallback } from 'react'
import { useApi } from './useApi'
import Px from './Px'

export default function SettingsPage({ addToast }) {
  const { get, post, del } = useApi()
  const [folders, setFolders] = useState([])
  const [st, setSt] = useState(null)
  const [path, setPath] = useState('')
  const [busy, setBusy] = useState(false)

  const load = useCallback(async () => {
    try { setFolders(await get('/folders')) } catch {}
    try { setSt(await get('/index/status')) } catch { setSt(null) }
  }, [get])
  useEffect(() => { load(); const id = setInterval(load, 4000); return () => clearInterval(id) }, [load])

  const act = async (fn, ok) => { try { await fn(); ok && addToast(ok); load() } catch (e) { addToast(e.message) } }
  const add = async () => { if (!path.trim()) return; setBusy(true); await act(async () => { await post('/folders', { path: path.trim() }); setPath('') }, 'Folder added'); setBusy(false) }
  // NOTE: the old UI called POST /index/trigger, which does not exist. The real route is POST /index.
  const indexNow = () => act(async () => { await post('/index'); }, 'Indexing started')

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
            <div className="ev row" key={f.folder_id}>
              <Px n="folder" s={1} /><span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis' }} title={f.path}>{f.path}</span>
              <button className="btn" style={{ minWidth: 60 }} onClick={() => act(() => del(`/folders/${f.folder_id}`), 'Folder removed')}>Remove</button>
            </div>
          ))}
        </div>
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
        <legend>Privacy</legend>
        Files are read, chunked and embedded on this machine. Questions are answered by a local Ollama model.
        A cloud model is used only if you set MEMORIA_ALLOW_CLOUD=1, and the status bar then says so.
      </fieldset>
    </div>
  )
}
