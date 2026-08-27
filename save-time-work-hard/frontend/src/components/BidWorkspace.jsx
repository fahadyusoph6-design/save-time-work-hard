import { useEffect, useMemo, useRef, useState } from 'react'
import { api, cleanFilename, dirname, KNOWN_JOBSITES, localDate, localTime, sanitizeHtml, saveBlob } from '../api.js'
import { Confirm, DocxView, Modal, useDebounced } from './Common.jsx'
import { HistoryFilters, useBidRows } from './History.jsx'

const FIELDS = ['job_title', 'company_name', 'jobsite_name']

export default function BidWorkspace({ user, seed, notify, onDone }) {
  const [resumes, setResumes] = useState([])
  const [resumeId, setResumeId] = useState(user.active_resume_id || '')
  const editor = useRef(null)
  const [hasResume, setHasResume] = useState(false)
  const [loadedFrom, setLoadedFrom] = useState(seed?.from || '')
  const [jdText, setJdText] = useState('')
  const [jobUrl, setJobUrl] = useState('')
  const [fields, setFields] = useState({
    bid_date: localDate(), bid_time: localTime(), job_title: '', company_name: '', jobsite_name: '', filename: '',
  })
  const touched = useRef(new Set())
  const [suggestions, setSuggestions] = useState({ jobsites: [], companies: [] })
  const [busy, setBusy] = useState(false)
  const [preview, setPreview] = useState(null) // stable loader fn
  const [picker, setPicker] = useState(false)
  const [overwrite, setOverwrite] = useState(null) // conflict message
  const [leaving, setLeaving] = useState(false)

  useEffect(() => {
    api('/resumes').then((list) => {
      setResumes(list)
      setResumeId((id) => (list.some((r) => r.id === Number(id)) ? Number(id) : (list[0]?.id ?? '')))
    }).catch((e) => notify(e.message, 'error'))
    api('/bids/suggestions').then(setSuggestions).catch(() => {})
  }, [notify])

  const loadResume = (html, text) => {
    if (!editor.current) return
    if (html) editor.current.innerHTML = sanitizeHtml(html)
    else editor.current.innerText = text || ''
    setHasResume(Boolean(editor.current.innerText.trim()))
  }

  useEffect(() => {
    if (seed) loadResume(seed.resume_html, seed.resume_text)
  }, [seed])

  // Autofill job title / company / jobsite from the JD and URL (unless the user edited them).
  const jdKey = useDebounced(`${jdText}\u0000${jobUrl}`, 500)
  useEffect(() => {
    const [jd_text, job_url] = jdKey.split('\u0000')
    if (!jd_text.trim() && !job_url.trim()) return
    api('/jd/parse', { method: 'POST', body: { jd_text, job_url } }).then((parsed) => {
      setFields((f) => {
        const next = { ...f }
        FIELDS.forEach((k) => { if (!touched.current.has(k) && parsed[k]) next[k] = parsed[k] })
        return next
      })
    }).catch(() => {})
  }, [jdKey])

  // Default filename follows name/company/title until the user types their own.
  const autoName = cleanFilename(
    [user.display_name || user.username, fields.company_name, fields.job_title].filter(Boolean).join('_'),
  )
  const filename = touched.current.has('filename') ? fields.filename : autoName

  const setField = (k) => (e) => {
    touched.current.add(k)
    const value = e.target.value
    setFields((f) => ({ ...f, [k]: value }))
  }

  const resume = resumes.find((r) => r.id === Number(resumeId))
  const saveDir = resume ? dirname(resume.path) : ''
  const jobsiteOptions = useMemo(
    () => [...new Set([...suggestions.jobsites, ...KNOWN_JOBSITES])],
    [suggestions.jobsites],
  )

  const content = () => ({
    default_resume_id: Number(resumeId),
    resume_html: editor.current?.innerHTML || '',
    resume_text: editor.current?.innerText || '',
  })

  const check = () => {
    if (!resume) { notify('Select a default resume first', 'error'); return false }
    if (!editor.current?.innerText.trim()) { notify('Paste the resume text first', 'error'); return false }
    return true
  }

  const openPreview = () => {
    if (!check()) return
    const body = content()
    setPreview(() => () => api('/bids/preview', { method: 'POST', body, blob: true }))
  }

  const submit = async (force = false) => {
    if (!check()) return
    if (!filename.trim()) { notify('Enter a filename', 'error'); return }
    setBusy(true)
    try {
      const bid = await api('/bids', {
        method: 'POST',
        body: {
          ...content(),
          jd_text: jdText,
          job_url: jobUrl,
          job_title: fields.job_title,
          company_name: fields.company_name,
          jobsite_name: fields.jobsite_name,
          bid_date: fields.bid_date,
          bid_time: fields.bid_time,
          filename,
          overwrite: force,
        },
      })
      const blob = await api(`/bids/${bid.id}/file`, { blob: true })
      saveBlob(blob, bid.filename)
      notify(`Saved ${bid.file_path}`)
      onDone()
    } catch (e) {
      if (e.status === 409) setOverwrite(e.message)
      else notify(e.message, 'error')
    } finally {
      setBusy(false)
    }
  }

  const cancel = () => {
    if (hasResume || jdText.trim()) setLeaving(true)
    else onDone()
  }

  return (
    <div className="workspace">
      <div className="stack">
        <div className="card">
          <div className="card-head">
            <h2>Resume</h2>
            <span className="muted small">Paste styled resume text (from Word, Google Docs, a web page…)</span>
            <div className="spacer" />
            {loadedFrom && <span className="pill accent">from {loadedFrom}</span>}
            <button className="small" onClick={() => setPicker(true)}>Select from history</button>
            <button className="small ghost" onClick={() => { loadResume('', ''); setLoadedFrom('') }}>Clear</button>
          </div>
          <div
            ref={editor}
            className="editor"
            contentEditable
            suppressContentEditableWarning
            data-placeholder="Paste the resume here (Ctrl+V)…"
            onInput={() => setHasResume(Boolean(editor.current.innerText.trim()))}
          />
        </div>

        <div className="card stack">
          <div className="card-head" style={{ marginBottom: 0 }}>
            <h2>Job description</h2>
          </div>
          <label className="field">
            <span>Job posting URL</span>
            <input value={jobUrl} onChange={(e) => setJobUrl(e.target.value)} placeholder="https://www.linkedin.com/jobs/view/…" />
          </label>
          <label className="field">
            <span>JD</span>
            <textarea rows={12} value={jdText} onChange={(e) => setJdText(e.target.value)} placeholder="Paste the job description…" />
          </label>
        </div>
      </div>

      <div className="card stack sticky">
        <h2>Bid details</h2>
        <label className="field">
          <span>Default resume (style)</span>
          <select value={resumeId} onChange={(e) => setResumeId(Number(e.target.value))}>
            {resumes.map((r) => <option key={r.id} value={r.id}>{r.label}{r.exists ? '' : ' (missing)'}</option>)}
          </select>
        </label>
        <div className="grid-2">
          <label className="field"><span>Date</span><input type="date" value={fields.bid_date} onChange={setField('bid_date')} /></label>
          <label className="field"><span>Time</span><input type="time" value={fields.bid_time} onChange={setField('bid_time')} /></label>
        </div>
        <label className="field"><span>Job title</span><input value={fields.job_title} onChange={setField('job_title')} /></label>
        <label className="field">
          <span>Company</span>
          <input list="company-list" value={fields.company_name} onChange={setField('company_name')} />
          <datalist id="company-list">{suggestions.companies.map((c) => <option key={c} value={c} />)}</datalist>
        </label>
        <label className="field">
          <span>Jobsite</span>
          <input list="jobsite-options" value={fields.jobsite_name} onChange={setField('jobsite_name')} />
          <datalist id="jobsite-options">{jobsiteOptions.map((s) => <option key={s} value={s} />)}</datalist>
        </label>
        <label className="field">
          <span>Filename</span>
          <div className="fname">
            <input
              value={filename}
              onChange={(e) => { touched.current.add('filename'); setFields((f) => ({ ...f, filename: e.target.value })) }}
            />
            <span>.docx</span>
          </div>
        </label>
        <div className="savepath">
          <div className="small muted">Saved on the server, in the default resume’s folder</div>
          <div className="mono">{saveDir || '—'}</div>
        </div>
        <button disabled={busy} onClick={openPreview}>Preview resume</button>
        <button className="primary big" disabled={busy || !resume} onClick={() => submit(false)}>
          {busy ? 'Saving…' : 'Download and Save'}
        </button>
        <button className="ghost" onClick={cancel}>Cancel</button>
      </div>

      {preview && (
        <Modal
          wide
          title={`Preview — ${filename}.docx`}
          onClose={() => setPreview(null)}
          footer={(
            <>
              <button onClick={() => setPreview(null)}>Back to editing</button>
              <button className="primary" disabled={busy} onClick={() => { setPreview(null); submit(false) }}>Download and Save</button>
            </>
          )}
        >
          <DocxView load={preview} />
        </Modal>
      )}
      {picker && (
        <HistoryPicker
          notify={notify}
          onClose={() => setPicker(false)}
          onPick={(bid) => { loadResume(bid.resume_html, bid.resume_text); setLoadedFrom(bid.filename); setPicker(false) }}
        />
      )}
      {overwrite && (
        <Confirm
          title="File already exists"
          message={`${overwrite}. Replace it?`}
          confirmLabel="Replace"
          danger
          onClose={() => setOverwrite(null)}
          onConfirm={() => { setOverwrite(null); submit(true) }}
        />
      )}
      {leaving && (
        <Confirm
          title="Discard this bid?"
          message="The pasted resume and JD will be lost."
          confirmLabel="Discard"
          danger
          onClose={() => setLeaving(false)}
          onConfirm={onDone}
        />
      )}
    </div>
  )
}

function HistoryPicker({ onClose, onPick, notify }) {
  const [filters, setFilters] = useState({ q: '', date_from: '', date_to: '', jobsite: '', resume_id: '' })
  const { rows, loading } = useBidRows('/bids', filters, notify)
  const [selected, setSelected] = useState(null)
  const [full, setFull] = useState(null)
  const previewHost = useRef(null)

  useEffect(() => {
    if (!selected) return
    setFull(null)
    api(`/bids/${selected}`).then(setFull).catch((e) => notify(e.message, 'error'))
  }, [selected, notify])

  useEffect(() => {
    if (previewHost.current && full) previewHost.current.innerHTML = sanitizeHtml(full.resume_html)
    if (previewHost.current && full && !full.resume_html) previewHost.current.innerText = full.resume_text
  }, [full])

  return (
    <Modal
      wide
      title="Select resume from history"
      onClose={onClose}
      footer={(
        <>
          <button onClick={onClose}>Cancel</button>
          <button className="primary" disabled={!full} onClick={() => onPick(full)}>Use this resume</button>
        </>
      )}
    >
      <HistoryFilters filters={filters} setFilters={setFilters} />
      <div className="grid-2" style={{ alignItems: 'start' }}>
        <div className="table-wrap" style={{ maxHeight: '55vh', overflow: 'auto' }}>
          {loading ? <div className="muted">Loading…</div> : !rows.length ? <div className="empty">No bids found.</div> : (
            <table>
              <tbody>
                {rows.map((b) => (
                  <tr
                    key={b.id}
                    onClick={() => setSelected(b.id)}
                    style={{ cursor: 'pointer', background: selected === b.id ? 'var(--accent-soft)' : undefined }}
                  >
                    <td>
                      <div><b>{b.job_title || '—'}</b>{b.company_name ? ` · ${b.company_name}` : ''}</div>
                      <div className="small muted">{b.bid_date} {b.bid_time} · {b.jobsite_name || 'no jobsite'} · {b.filename}</div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
        <div>
          {!selected && <div className="empty">Pick a bid to see its resume.</div>}
          {selected && !full && <div className="muted">Loading…</div>}
          <div
            ref={previewHost}
            className="editor"
            style={{ minHeight: 0, maxHeight: '55vh', display: full ? 'block' : 'none', fontSize: 12.5 }}
          />
        </div>
      </div>
    </Modal>
  )
}
