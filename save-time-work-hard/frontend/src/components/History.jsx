import { useEffect, useState } from 'react'
import { api, KNOWN_JOBSITES, qs } from '../api.js'
import { BidResumeModal, Confirm, JdModal, Modal, useDebounced } from './Common.jsx'

/** Search/filter bar shared by the user dashboard and the admin history. */
export function HistoryFilters({ filters, setFilters, resumes, jobsites, children }) {
  const set = (k) => (e) => setFilters((f) => ({ ...f, [k]: e.target.value }))
  return (
    <div className="row" style={{ marginBottom: 12 }}>
      <input
        style={{ flex: '2 1 220px', width: 'auto' }}
        placeholder="Search job title, company, jobsite, filename, JD…"
        value={filters.q}
        onChange={set('q')}
      />
      {children}
      {jobsites && (
        <select style={{ flex: '1 1 130px', width: 'auto' }} value={filters.jobsite} onChange={set('jobsite')}>
          <option value="">All jobsites</option>
          {jobsites.map((s) => <option key={s}>{s}</option>)}
        </select>
      )}
      {resumes && (
        <select style={{ flex: '1 1 150px', width: 'auto' }} value={filters.resume_id} onChange={set('resume_id')}>
          <option value="">All default resumes</option>
          {resumes.map((r) => <option key={r.id} value={r.id}>{r.label}{r.username ? ` (${r.username})` : ''}</option>)}
        </select>
      )}
      <input type="date" style={{ width: 'auto' }} value={filters.date_from} onChange={set('date_from')} title="From date" />
      <span className="muted">–</span>
      <input type="date" style={{ width: 'auto' }} value={filters.date_to} onChange={set('date_to')} title="To date" />
      <button
        className="ghost small"
        onClick={() => setFilters((f) => Object.fromEntries(Object.keys(f).map((k) => [k, ''])))}
      >
        Clear
      </button>
    </div>
  )
}

export function HistoryTable({ rows, showUser = false, notify, onChanged, onUseResume }) {
  const [previewing, setPreviewing] = useState(null)
  const [jd, setJd] = useState(null)
  const [editing, setEditing] = useState(null)
  const [deleting, setDeleting] = useState(null)
  const [deleteFile, setDeleteFile] = useState(false)

  const useResume = async (bid) => {
    try {
      const full = await api(`/bids/${bid.id}`)
      onUseResume({ resume_html: full.resume_html, resume_text: full.resume_text, from: full.filename })
    } catch (e) { notify(e.message, 'error') }
  }

  const doDelete = async () => {
    try {
      await api(`/bids/${deleting.id}${qs({ delete_file: deleteFile })}`, { method: 'DELETE' })
      notify('Bid deleted')
      setDeleting(null)
      onChanged()
    } catch (e) { notify(e.message, 'error') }
  }

  if (!rows.length) return <div className="empty">No bids found.</div>

  return (
    <>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              {showUser && <th>User</th>}
              <th>Date</th>
              <th>Time</th>
              <th>Job title</th>
              <th>Company</th>
              <th>Jobsite</th>
              <th>Resume file</th>
              <th>Default resume</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {rows.map((b) => (
              <tr key={b.id}>
                {showUser && (
                  <td>
                    <div>{b.username}</div>
                    <div className="small muted">{b.email || '—'}</div>
                  </td>
                )}
                <td style={{ whiteSpace: 'nowrap' }}>{b.bid_date}</td>
                <td>{b.bid_time}</td>
                <td>{b.job_title || <span className="muted">—</span>}</td>
                <td>{b.company_name || <span className="muted">—</span>}</td>
                <td>
                  {b.job_url
                    ? <a href={b.job_url} target="_blank" rel="noreferrer">{b.jobsite_name || 'link'}</a>
                    : (b.jobsite_name || <span className="muted">—</span>)}
                </td>
                <td title={b.file_path}>
                  <span className={`pill ${b.file_exists ? '' : 'bad'}`} title={b.file_exists ? b.file_path : 'File moved or deleted — it will be rebuilt on download'}>
                    {b.filename}
                  </span>
                </td>
                <td className="small">{b.default_resume_label || <span className="muted">—</span>}</td>
                <td className="actions">
                  <button className="small" onClick={() => setPreviewing(b)}>Resume</button>
                  <button className="small" onClick={() => setJd(b)}>JD</button>
                  <button className="small" onClick={() => setEditing(b)}>Edit</button>
                  {onUseResume && <button className="small" onClick={() => useResume(b)} title="Start a new bid with this resume">Reuse</button>}
                  <button className="small danger" onClick={() => { setDeleteFile(false); setDeleting(b) }}>Delete</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {previewing && <BidResumeModal bid={previewing} notify={notify} onClose={() => setPreviewing(null)} />}
      {jd && <JdModal bid={jd} onClose={() => setJd(null)} />}
      {editing && (
        <BidEditModal
          bid={editing}
          notify={notify}
          onClose={() => setEditing(null)}
          onSaved={() => { setEditing(null); onChanged() }}
        />
      )}
      {deleting && (
        <Confirm
          danger
          title="Delete bid"
          confirmLabel="Delete"
          message={`Delete the history entry for "${deleting.job_title || deleting.filename}"?`}
          onClose={() => setDeleting(null)}
          onConfirm={doDelete}
        >
          <label className="check">
            <input type="checkbox" checked={deleteFile} onChange={(e) => setDeleteFile(e.target.checked)} />
            Also delete {deleting.filename} from disk
          </label>
        </Confirm>
      )}
    </>
  )
}

function BidEditModal({ bid, onClose, onSaved, notify }) {
  const [form, setForm] = useState(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    api(`/bids/${bid.id}`).then((b) => setForm({
      bid_date: b.bid_date,
      bid_time: b.bid_time,
      job_title: b.job_title,
      company_name: b.company_name,
      jobsite_name: b.jobsite_name,
      job_url: b.job_url,
      jd_text: b.jd_text,
      filename: b.filename.replace(/\.docx$/i, ''),
    })).catch((e) => notify(e.message, 'error'))
  }, [bid.id, notify])

  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }))
  const save = async () => {
    setBusy(true)
    try {
      await api(`/bids/${bid.id}`, { method: 'PUT', body: form })
      notify('Bid updated')
      onSaved()
    } catch (e) {
      notify(e.message, 'error')
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal
      title="Edit bid"
      onClose={onClose}
      footer={(
        <>
          <button onClick={onClose}>Cancel</button>
          <button className="primary" disabled={!form || busy} onClick={save}>Save</button>
        </>
      )}
    >
      {!form ? <div className="muted">Loading…</div> : (
        <div className="stack">
          <div className="grid-2">
            <label className="field"><span>Date</span><input type="date" value={form.bid_date} onChange={set('bid_date')} /></label>
            <label className="field"><span>Time</span><input type="time" value={form.bid_time} onChange={set('bid_time')} /></label>
            <label className="field"><span>Job title</span><input value={form.job_title} onChange={set('job_title')} /></label>
            <label className="field"><span>Company</span><input value={form.company_name} onChange={set('company_name')} /></label>
            <label className="field">
              <span>Jobsite</span>
              <input list="jobsite-list" value={form.jobsite_name} onChange={set('jobsite_name')} />
              <datalist id="jobsite-list">{KNOWN_JOBSITES.map((s) => <option key={s} value={s} />)}</datalist>
            </label>
            <label className="field"><span>Job URL</span><input value={form.job_url} onChange={set('job_url')} /></label>
          </div>
          <label className="field">
            <span>Filename (renames the file on disk)</span>
            <div className="fname"><input value={form.filename} onChange={set('filename')} /><span>.docx</span></div>
          </label>
          <label className="field"><span>JD</span><textarea rows={8} value={form.jd_text} onChange={set('jd_text')} /></label>
        </div>
      )}
    </Modal>
  )
}

export function useBidRows(path, filters, notify, extra = {}) {
  const debouncedQ = useDebounced(filters.q)
  const [rows, setRows] = useState([])
  const [loading, setLoading] = useState(true)
  const [tick, setTick] = useState(0)
  const params = { ...filters, q: debouncedQ, ...extra }
  const key = JSON.stringify(params)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    api(`${path}${qs(JSON.parse(key))}`)
      .then((r) => { if (!cancelled) setRows(r) })
      .catch((e) => notify(e.message, 'error'))
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [path, key, tick, notify])

  return { rows, loading, reload: () => setTick((t) => t + 1) }
}
