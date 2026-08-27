import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api, localDate, qs, uploadFile } from '../api.js'
import { Confirm, DocxView, Modal } from './Common.jsx'
import { HistoryFilters, HistoryTable, useBidRows } from './History.jsx'

export default function Dashboard({ user, onUserChange, onStartBid, notify }) {
  const [resumes, setResumes] = useState([])
  const [filters, setFilters] = useState({ q: '', date_from: '', date_to: '', jobsite: '', resume_id: '' })
  const { rows, loading, reload } = useBidRows('/bids', filters, notify)
  const [allRows, setAllRows] = useState([])

  const loadResumes = useCallback(
    () => api('/resumes').then(setResumes).catch((e) => notify(e.message, 'error')),
    [notify],
  )
  useEffect(() => { loadResumes() }, [loadResumes])
  useEffect(() => { api('/bids').then(setAllRows).catch(() => {}) }, [rows])

  const today = localDate()
  const stats = useMemo(() => ({
    today: allRows.filter((b) => b.bid_date === today).length,
    month: allRows.filter((b) => b.bid_date.startsWith(today.slice(0, 7))).length,
    total: allRows.length,
  }), [allRows, today])
  const jobsites = useMemo(
    () => [...new Set(allRows.map((b) => b.jobsite_name).filter(Boolean))].sort(),
    [allRows],
  )

  const active = resumes.find((r) => r.id === user.active_resume_id)

  return (
    <div className="dash">
      <aside className="stack">
        <ProfileCard user={user} onUserChange={onUserChange} notify={notify} />
        <DefaultResumes
          user={user}
          resumes={resumes}
          reload={loadResumes}
          onUserChange={onUserChange}
          notify={notify}
        />
      </aside>

      <section className="stack">
        <div className="card hero">
          <div>
            <h2 style={{ fontSize: 20 }}>Hi {user.display_name || user.username} 👋</h2>
            <div className="muted small" style={{ marginTop: 4 }}>
              {active
                ? <>Default resume: <b>{active.label}</b></>
                : 'Add and select a default resume to start bidding.'}
            </div>
          </div>
          <div className="stats">
            <div className="stat"><b>{stats.today}</b><span>Today</span></div>
            <div className="stat"><b>{stats.month}</b><span>This month</span></div>
            <div className="stat"><b>{stats.total}</b><span>Total</span></div>
          </div>
          <div className="spacer" />
          <button className="primary big" disabled={!resumes.length} onClick={() => onStartBid(null)}>
            Start bid
          </button>
        </div>

        <div className="card">
          <div className="card-head">
            <h2>Bid history</h2>
            <span className="muted small">{loading ? 'Loading…' : `${rows.length} result${rows.length === 1 ? '' : 's'}`}</span>
          </div>
          <HistoryFilters filters={filters} setFilters={setFilters} resumes={resumes} jobsites={jobsites} />
          <HistoryTable rows={rows} notify={notify} onChanged={reload} onUseResume={onStartBid} />
        </div>
      </section>
    </div>
  )
}

function ProfileCard({ user, onUserChange, notify }) {
  const [name, setName] = useState(user.display_name)
  const [pw, setPw] = useState(null)

  const saveName = async () => {
    try {
      onUserChange(await api('/me', { method: 'PUT', body: { display_name: name } }))
      notify('Name saved')
    } catch (e) { notify(e.message, 'error') }
  }
  const savePw = async () => {
    try {
      await api('/me/password', { method: 'PUT', body: pw })
      notify('Password changed')
      setPw(null)
    } catch (e) { notify(e.message, 'error') }
  }

  return (
    <div className="card stack">
      <h2>Profile</h2>
      <label className="field">
        <span>Name</span>
        <div className="row" style={{ flexWrap: 'nowrap' }}>
          <input value={name} onChange={(e) => setName(e.target.value)} />
          <button disabled={!name.trim() || name === user.display_name} onClick={saveName}>Save</button>
        </div>
      </label>
      <div className="small muted">{user.email || user.username}</div>
      <div><button className="small" onClick={() => setPw({ old_password: '', new_password: '' })}>Change password</button></div>
      {pw && (
        <Modal
          title="Change password"
          onClose={() => setPw(null)}
          footer={<><button onClick={() => setPw(null)}>Cancel</button><button className="primary" onClick={savePw}>Save</button></>}
        >
          <div className="stack">
            <label className="field"><span>Current password</span>
              <input type="password" value={pw.old_password} onChange={(e) => setPw({ ...pw, old_password: e.target.value })} />
            </label>
            <label className="field"><span>New password</span>
              <input type="password" value={pw.new_password} onChange={(e) => setPw({ ...pw, new_password: e.target.value })} />
            </label>
          </div>
        </Modal>
      )}
    </div>
  )
}

function DefaultResumes({ user, resumes, reload, onUserChange, notify }) {
  const [form, setForm] = useState(null) // { id?, label, path }
  const [preview, setPreview] = useState(null)
  const [removing, setRemoving] = useState(null)

  const activate = async (r) => {
    try {
      await api(`/resumes/${r.id}/activate`, { method: 'PUT' })
      onUserChange({ ...user, active_resume_id: r.id })
    } catch (e) { notify(e.message, 'error') }
  }

  const save = async () => {
    try {
      let saved
      if (form.mode === 'upload' && form.file) {
        saved = await uploadFile(
          `/resumes/upload${qs({ filename: form.file.name, label: form.label, resume_id: form.id || '' })}`,
          form.file,
        )
      } else {
        saved = await api(form.id ? `/resumes/${form.id}` : '/resumes', {
          method: form.id ? 'PUT' : 'POST',
          body: { label: form.label, path: form.path },
        })
      }
      if (!user.active_resume_id) onUserChange({ ...user, active_resume_id: saved.id })
      setForm(null)
      reload()
      notify('Default resume saved')
    } catch (e) { notify(e.message, 'error') }
  }

  const remove = async () => {
    try {
      await api(`/resumes/${removing.id}`, { method: 'DELETE' })
      if (user.active_resume_id === removing.id) onUserChange({ ...user, active_resume_id: null })
      setRemoving(null)
      reload()
    } catch (e) { notify(e.message, 'error') }
  }

  return (
    <div className="card stack">
      <div className="card-head" style={{ marginBottom: 0 }}>
        <h2>Default resumes</h2>
        <div className="spacer" />
        <button className="small" onClick={() => setForm({ label: '', path: '', mode: 'upload', file: null })}>+ Add</button>
      </div>
      {!resumes.length && (
        <div className="note">
          Upload the .docx resume whose style should be applied. Resumes you create are saved next to it.
        </div>
      )}
      {resumes.map((r) => (
        <div key={r.id} className={`resume-item ${r.id === user.active_resume_id ? 'active' : ''}`}>
          <label className="check" style={{ fontWeight: 600 }}>
            <input
              type="radio"
              name="active-resume"
              checked={r.id === user.active_resume_id}
              onChange={() => activate(r)}
            />
            {r.label}
          </label>
          <div className="mono muted">{r.uploaded ? `Uploaded: ${r.path.split(/[\\/]/).pop()}` : r.path}</div>
          <div className="row">
            {r.exists ? <span className="pill ok">found</span> : <span className="pill bad">file missing</span>}
            <span className="pill">{r.bid_count} bids</span>
            <div className="spacer" style={{ flex: 1 }} />
            <button className="small" disabled={!r.exists} onClick={() => setPreview(r)}>Preview</button>
            <button className="small" onClick={() => setForm({ id: r.id, label: r.label, path: r.path, mode: r.uploaded ? 'upload' : 'path', file: null })}>Edit</button>
            <button className="small danger" onClick={() => setRemoving(r)}>✕</button>
          </div>
        </div>
      ))}

      {form && (
        <Modal
          title={form.id ? 'Edit default resume' : 'Add default resume'}
          onClose={() => setForm(null)}
          footer={(
            <>
              <button onClick={() => setForm(null)}>Cancel</button>
              <button
                className="primary"
                disabled={form.mode === 'upload' ? !form.file && !form.id : !form.path.trim()}
                onClick={save}
              >
                Save
              </button>
            </>
          )}
        >
          <div className="stack">
            {!form.id && (
              <div className="seg" style={{ alignSelf: 'flex-start' }}>
                <button className={form.mode === 'upload' ? 'active' : ''} onClick={() => setForm({ ...form, mode: 'upload' })}>Upload file</button>
                <button className={form.mode === 'path' ? 'active' : ''} onClick={() => setForm({ ...form, mode: 'path' })}>Path on server</button>
              </div>
            )}
            <label className="field"><span>Label</span>
              <input value={form.label} placeholder="e.g. Software Engineer – main" onChange={(e) => setForm({ ...form, label: e.target.value })} />
            </label>
            {form.mode === 'upload' ? (
              <>
                <label className="field">
                  <span>{form.id ? 'Replace with a new version (optional)' : '.docx file'}</span>
                  <input
                    type="file"
                    accept=".docx,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                    onChange={(e) => setForm({ ...form, file: e.target.files[0] || null })}
                  />
                </label>
                <div className="small muted">
                  The file is stored on the server in your own folder. Resumes you create are saved in that same folder
                  and download to this computer.
                </div>
              </>
            ) : (
              <>
                <label className="field"><span>Full path to the .docx file on the server PC (or a shared folder)</span>
                  <input
                    className="mono"
                    value={form.path}
                    placeholder="\\server\Resumes\My Resume.docx"
                    onChange={(e) => setForm({ ...form, path: e.target.value })}
                  />
                </label>
                <div className="small muted">
                  The path must be reachable from the PC running the app — a local path there, or a shared network folder.
                  Generated resumes are saved in that file’s folder. Tip: in File Explorer, Ctrl+Shift+C copies a file’s path.
                </div>
              </>
            )}
          </div>
        </Modal>
      )}
      {preview && <DefaultPreview resume={preview} onClose={() => setPreview(null)} />}
      {removing && (
        <Confirm
          danger
          title="Remove default resume"
          confirmLabel="Remove"
          message={`Remove "${removing.label}" from the list? The file on disk and the bid history are kept.`}
          onClose={() => setRemoving(null)}
          onConfirm={remove}
        />
      )}
    </div>
  )
}

function DefaultPreview({ resume, onClose }) {
  const load = useRef(() => api(`/resumes/${resume.id}/file`, { blob: true })).current
  return (
    <Modal wide title={resume.label} onClose={onClose}>
      <DocxView load={load} />
    </Modal>
  )
}
