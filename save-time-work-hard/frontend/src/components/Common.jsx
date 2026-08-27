import { useEffect, useRef, useState } from 'react'
import { renderAsync } from 'docx-preview'
import { api, saveBlob } from '../api.js'

export function Modal({ title, onClose, children, footer, wide = false, actions }) {
  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])
  return (
    <div className="modal-backdrop" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose() }}>
      <div className={`modal ${wide ? 'wide' : ''}`} role="dialog" aria-modal="true">
        <div className="modal-head">
          <h2>{title}</h2>
          {actions}
          <button className="ghost" onClick={onClose} aria-label="Close">✕</button>
        </div>
        <div className="modal-body">{children}</div>
        {footer && <div className="modal-foot">{footer}</div>}
      </div>
    </div>
  )
}

/** Renders a .docx Blob (or a promise of one) with Word-like styling. */
export function DocxView({ load }) {
  const host = useRef(null)
  const [state, setState] = useState('loading')
  const [error, setError] = useState('')

  useEffect(() => {
    let cancelled = false
    setState('loading')
    load()
      .then((blob) => {
        if (cancelled || !host.current) return null
        host.current.innerHTML = ''
        return renderAsync(blob, host.current, undefined, {
          inWrapper: true, ignoreLastRenderedPageBreak: true, breakPages: true, experimental: true,
        }).then(() => { if (!cancelled) setState('ready') })
      })
      .catch((e) => { if (!cancelled) { setError(e.message); setState('error') } })
    return () => { cancelled = true }
  }, [load])

  return (
    <>
      {state === 'loading' && <div className="muted">Rendering…</div>}
      {state === 'error' && <div className="alert">{error}</div>}
      <div className="docx-host" ref={host} style={{ display: state === 'ready' ? 'block' : 'none' }} />
    </>
  )
}

export function BidResumeModal({ bid, onClose, notify }) {
  const load = useRef(() => api(`/bids/${bid.id}/file`, { blob: true })).current
  const download = async () => {
    try { saveBlob(await load(), bid.filename) } catch (e) { notify(e.message, 'error') }
  }
  return (
    <Modal
      wide
      title={bid.filename}
      onClose={onClose}
      actions={<button onClick={download}>Download</button>}
    >
      <p className="small muted mono" style={{ marginTop: 0 }}>{bid.file_path}</p>
      <DocxView load={load} />
    </Modal>
  )
}

export function JdModal({ bid, onClose }) {
  const [full, setFull] = useState(null)
  useEffect(() => { api(`/bids/${bid.id}`).then(setFull) }, [bid.id])
  return (
    <Modal title={`JD — ${bid.job_title || 'Untitled'}${bid.company_name ? ` @ ${bid.company_name}` : ''}`} onClose={onClose}>
      {bid.job_url && (
        <p style={{ marginTop: 0 }}>
          <a href={bid.job_url} target="_blank" rel="noreferrer">{bid.job_url}</a>
        </p>
      )}
      {!full ? <div className="muted">Loading…</div>
        : full.jd_text ? <div className="jd-text">{full.jd_text}</div>
          : <div className="muted">No JD was saved for this bid.</div>}
    </Modal>
  )
}

export function Confirm({ title, message, confirmLabel = 'Confirm', danger = false, onConfirm, onClose, children }) {
  return (
    <Modal
      title={title}
      onClose={onClose}
      footer={(
        <>
          <button onClick={onClose}>Cancel</button>
          <button className={danger ? 'danger' : 'primary'} onClick={onConfirm}>{confirmLabel}</button>
        </>
      )}
    >
      <p style={{ marginTop: 0 }}>{message}</p>
      {children}
    </Modal>
  )
}

export function useDebounced(value, delay = 350) {
  const [v, setV] = useState(value)
  useEffect(() => {
    const t = setTimeout(() => setV(value), delay)
    return () => clearTimeout(t)
  }, [value, delay])
  return v
}
