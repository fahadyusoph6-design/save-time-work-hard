import { useCallback, useEffect, useMemo, useState } from 'react'
import { api, qs } from '../../api.js'
import { Confirm, Modal } from '../Common.jsx'
import { HistoryFilters, HistoryTable, useBidRows } from '../History.jsx'

const EMPTY_FILTERS = { q: '', date_from: '', date_to: '', resume_id: '', user_id: '', period: '' }

export default function AdminPanel({ notify }) {
  const [tab, setTab] = useState('users')
  const [users, setUsers] = useState([])
  const [resumes, setResumes] = useState([])
  const [historyFilters, setHistoryFilters] = useState(EMPTY_FILTERS)

  const loadUsers = useCallback(() => api('/admin/users').then(setUsers).catch((e) => notify(e.message, 'error')), [notify])
  const loadResumes = useCallback(() => api('/admin/resumes').then(setResumes).catch(() => {}), [])
  useEffect(() => { loadUsers(); loadResumes() }, [loadUsers, loadResumes])

  const openHistory = (filters) => {
    setHistoryFilters({ ...EMPTY_FILTERS, ...filters })
    setTab('history')
  }

  return (
    <div>
      <div className="tabs">
        <button className={tab === 'users' ? 'active' : ''} onClick={() => setTab('users')}>Accounts</button>
        <button className={tab === 'history' ? 'active' : ''} onClick={() => setTab('history')}>Bid history</button>
        <button className={tab === 'stats' ? 'active' : ''} onClick={() => setTab('stats')}>Working history</button>
      </div>
      {tab === 'users' && <UsersTab users={users} reload={loadUsers} notify={notify} openHistory={openHistory} />}
      {tab === 'history' && (
        <HistoryTab
          users={users}
          resumes={resumes}
          filters={historyFilters}
          setFilters={setHistoryFilters}
          notify={notify}
        />
      )}
      {tab === 'stats' && <StatsTab users={users} resumes={resumes} notify={notify} openHistory={openHistory} />}
    </div>
  )
}

// --------------------------------------------------------------------------- accounts

function UsersTab({ users, reload, notify, openHistory }) {
  const blank = { username: '', email: '', display_name: '', password: '' }
  const [form, setForm] = useState(blank)
  const [editing, setEditing] = useState(null)
  const [deleting, setDeleting] = useState(null)
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }))

  const create = async (e) => {
    e.preventDefault()
    try {
      await api('/admin/users', { method: 'POST', body: form })
      notify(`Account ${form.username} created`)
      setForm(blank)
      reload()
    } catch (err) { notify(err.message, 'error') }
  }

  const saveEdit = async () => {
    try {
      await api(`/admin/users/${editing.id}`, { method: 'PUT', body: editing })
      notify('Account updated')
      setEditing(null)
      reload()
    } catch (err) { notify(err.message, 'error') }
  }

  const remove = async () => {
    try {
      await api(`/admin/users/${deleting.id}`, { method: 'DELETE' })
      notify('Account deleted')
      setDeleting(null)
      reload()
    } catch (err) { notify(err.message, 'error') }
  }

  return (
    <div className="stack">
      <form className="card" onSubmit={create}>
        <div className="card-head"><h2>Create account</h2></div>
        <div className="row" style={{ alignItems: 'flex-end' }}>
          <label className="field" style={{ flex: '1 1 150px' }}><span>Username</span><input required value={form.username} onChange={set('username')} /></label>
          <label className="field" style={{ flex: '1 1 200px' }}><span>E-mail (login)</span><input required type="email" value={form.email} onChange={set('email')} /></label>
          <label className="field" style={{ flex: '1 1 150px' }}><span>Name</span><input value={form.display_name} onChange={set('display_name')} /></label>
          <label className="field" style={{ flex: '1 1 150px' }}><span>Password</span><input required minLength={6} value={form.password} onChange={set('password')} /></label>
          <button className="primary">Create</button>
        </div>
      </form>

      <div className="card">
        <div className="card-head"><h2>Accounts</h2><span className="muted small">{users.length}</span></div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Username</th><th>E-mail</th><th>Name</th><th>Role</th><th>Status</th>
                <th>Bids</th><th>Default resumes</th><th>Last bid</th><th />
              </tr>
            </thead>
            <tbody>
              {users.map((u) => (
                <tr key={u.id}>
                  <td><b>{u.username}</b></td>
                  <td>{u.email || <span className="muted">—</span>}</td>
                  <td>{u.display_name}</td>
                  <td>{u.role === 'admin' ? <span className="pill accent">admin</span> : 'user'}</td>
                  <td>{u.disabled ? <span className="pill bad">disabled</span> : <span className="pill ok">active</span>}</td>
                  <td>{u.bid_count}</td>
                  <td>{u.resume_count}</td>
                  <td className="small">{u.last_bid || '—'}</td>
                  <td className="actions">
                    <button className="small" onClick={() => openHistory({ user_id: String(u.id) })}>History</button>
                    <button className="small" onClick={() => setEditing({ ...u, email: u.email || '', password: '', disabled: Boolean(u.disabled) })}>Edit</button>
                    {u.role !== 'admin' && <button className="small danger" onClick={() => setDeleting(u)}>Delete</button>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {editing && (
        <Modal
          title={`Edit ${editing.username}`}
          onClose={() => setEditing(null)}
          footer={<><button onClick={() => setEditing(null)}>Cancel</button><button className="primary" onClick={saveEdit}>Save</button></>}
        >
          <div className="stack">
            <div className="grid-2">
              <label className="field"><span>Username</span><input value={editing.username} onChange={(e) => setEditing({ ...editing, username: e.target.value })} /></label>
              <label className="field"><span>E-mail</span><input value={editing.email} onChange={(e) => setEditing({ ...editing, email: e.target.value })} /></label>
              <label className="field"><span>Name</span><input value={editing.display_name} onChange={(e) => setEditing({ ...editing, display_name: e.target.value })} /></label>
              <label className="field"><span>New password (leave empty to keep)</span><input value={editing.password} onChange={(e) => setEditing({ ...editing, password: e.target.value })} /></label>
            </div>
            {editing.role !== 'admin' && (
              <label className="check">
                <input type="checkbox" checked={editing.disabled} onChange={(e) => setEditing({ ...editing, disabled: e.target.checked })} />
                Disable this account (blocks login)
              </label>
            )}
          </div>
        </Modal>
      )}
      {deleting && (
        <Confirm
          danger
          title="Delete account"
          confirmLabel="Delete"
          message={`Delete ${deleting.username}? Their bid history and default resume list are deleted too (saved .docx files stay on disk).`}
          onClose={() => setDeleting(null)}
          onConfirm={remove}
        />
      )}
    </div>
  )
}

// --------------------------------------------------------------------------- history

function HistoryTab({ users, resumes, filters, setFilters, notify }) {
  const { rows, loading, reload } = useBidRows('/admin/bids', filters, notify)
  const userResumes = filters.user_id ? resumes.filter((r) => String(r.user_id) === filters.user_id) : resumes

  return (
    <div className="card">
      <div className="card-head">
        <h2>Bid history</h2>
        {filters.period && (
          <span className="pill accent">
            {filters.period}
            <button className="ghost small" onClick={() => setFilters((f) => ({ ...f, period: '' }))}>✕</button>
          </span>
        )}
        <span className="muted small">{loading ? 'Loading…' : `${rows.length} bids`}</span>
      </div>
      <HistoryFilters filters={filters} setFilters={setFilters} resumes={userResumes}>
        <select
          style={{ flex: '1 1 200px', width: 'auto' }}
          value={filters.user_id}
          onChange={(e) => setFilters((f) => ({ ...f, user_id: e.target.value, resume_id: '' }))}
        >
          <option value="">All users</option>
          {users.map((u) => <option key={u.id} value={u.id}>{u.username}{u.email ? ` — ${u.email}` : ''}</option>)}
        </select>
      </HistoryFilters>
      <HistoryTable rows={rows} showUser notify={notify} onChanged={reload} />
    </div>
  )
}

// --------------------------------------------------------------------------- working history

function StatsTab({ users, resumes, notify, openHistory }) {
  const [period, setPeriod] = useState('day')
  const [userId, setUserId] = useState('')
  const [resumeId, setResumeId] = useState('')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const [data, setData] = useState([])

  useEffect(() => {
    api(`/admin/stats${qs({ period, user_id: userId, resume_id: resumeId, date_from: dateFrom, date_to: dateTo })}`)
      .then(setData)
      .catch((e) => notify(e.message, 'error'))
  }, [period, userId, resumeId, dateFrom, dateTo, notify])

  const groups = useMemo(() => {
    const map = new Map()
    data.forEach((r) => {
      if (!map.has(r.period)) map.set(r.period, { period: r.period, total: 0, users: [] })
      const g = map.get(r.period)
      g.total += r.count
      g.users.push(r)
    })
    return [...map.values()]
  }, [data])
  const max = Math.max(1, ...groups.map((g) => g.total))
  const total = groups.reduce((s, g) => s + g.total, 0)
  const userResumes = userId ? resumes.filter((r) => String(r.user_id) === userId) : resumes

  return (
    <div className="card">
      <div className="card-head">
        <h2>Working history</h2>
        <div className="seg">
          <button className={period === 'day' ? 'active' : ''} onClick={() => setPeriod('day')}>By date</button>
          <button className={period === 'month' ? 'active' : ''} onClick={() => setPeriod('month')}>By month</button>
        </div>
        <div className="spacer" />
        <span className="muted small">{total} bids in {groups.length} {period === 'day' ? 'days' : 'months'}</span>
      </div>
      <div className="row" style={{ marginBottom: 12 }}>
        <select style={{ width: 'auto', flex: '1 1 200px' }} value={userId} onChange={(e) => { setUserId(e.target.value); setResumeId('') }}>
          <option value="">All users</option>
          {users.map((u) => <option key={u.id} value={u.id}>{u.username}{u.email ? ` — ${u.email}` : ''}</option>)}
        </select>
        <select style={{ width: 'auto', flex: '1 1 200px' }} value={resumeId} onChange={(e) => setResumeId(e.target.value)}>
          <option value="">All default resumes</option>
          {userResumes.map((r) => <option key={r.id} value={r.id}>{r.label} ({r.username})</option>)}
        </select>
        <input type="date" style={{ width: 'auto' }} value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} />
        <span className="muted">–</span>
        <input type="date" style={{ width: 'auto' }} value={dateTo} onChange={(e) => setDateTo(e.target.value)} />
      </div>
      {!groups.length ? <div className="empty">No work recorded for this selection.</div> : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr><th>{period === 'day' ? 'Date' : 'Month'}</th><th>Bids</th><th style={{ width: '25%' }} /><th>By user</th><th /></tr>
            </thead>
            <tbody>
              {groups.map((g) => (
                <tr key={g.period}>
                  <td style={{ whiteSpace: 'nowrap' }}><b>{g.period}</b></td>
                  <td>{g.total}</td>
                  <td><div className="bar" style={{ width: `${(g.total / max) * 100}%` }} /></td>
                  <td>
                    <div className="row" style={{ gap: 6 }}>
                      {g.users.map((u) => (
                        <button
                          key={u.user_id}
                          className="small"
                          title={u.email || ''}
                          onClick={() => openHistory({ period: g.period, user_id: String(u.user_id), resume_id: resumeId })}
                        >
                          {u.username}{u.email ? ` (${u.email})` : ''}: <b>{u.count}</b>
                        </button>
                      ))}
                    </div>
                  </td>
                  <td className="actions">
                    <button className="small" onClick={() => openHistory({ period: g.period, user_id: userId, resume_id: resumeId })}>View bids</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
