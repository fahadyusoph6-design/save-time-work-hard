import { useCallback, useEffect, useState } from 'react'
import { api, getToken, setToken } from './api.js'
import Login from './components/Login.jsx'
import Dashboard from './components/Dashboard.jsx'
import BidWorkspace from './components/BidWorkspace.jsx'
import AdminPanel from './components/admin/AdminPanel.jsx'

export default function App() {
  const [user, setUser] = useState(null)
  const [booting, setBooting] = useState(true)
  const [view, setView] = useState('dashboard') // dashboard | bid | admin
  const [bidSeed, setBidSeed] = useState(null) // { resume_html, resume_text } when reusing a history resume
  const [toast, setToast] = useState(null)

  const notify = useCallback((message, kind = 'info') => {
    setToast({ message, kind, id: Date.now() })
  }, [])

  useEffect(() => {
    if (!toast) return undefined
    const t = setTimeout(() => setToast(null), toast.kind === 'error' ? 6000 : 3500)
    return () => clearTimeout(t)
  }, [toast])

  useEffect(() => {
    if (!getToken()) { setBooting(false); return }
    api('/me').then(setUser).catch(() => setToken(null)).finally(() => setBooting(false))
  }, [])

  useEffect(() => {
    const onLogout = () => { setToken(null); setUser(null) }
    window.addEventListener('stwh-logout', onLogout)
    return () => window.removeEventListener('stwh-logout', onLogout)
  }, [])

  const logout = async () => {
    try { await api('/auth/logout', { method: 'POST' }) } catch { /* already gone */ }
    setToken(null)
    setUser(null)
    setView('dashboard')
  }

  const startBid = (seed = null) => {
    setBidSeed(seed)
    setView('bid')
  }

  if (booting) return null
  if (!user) {
    return <Login onLogin={(u) => { setUser(u); setView('dashboard') }} />
  }

  return (
    <>
      <header className="topbar">
        <div className="brand">
          <div className="brand-mark">ST</div>
          <h1>Save time, Work hard</h1>
        </div>
        <nav>
          <button className={view !== 'admin' ? 'active' : ''} onClick={() => setView('dashboard')}>Dashboard</button>
          {user.role === 'admin' && (
            <button className={view === 'admin' ? 'active' : ''} onClick={() => setView('admin')}>Admin</button>
          )}
        </nav>
        <div className="spacer" />
        <span className="who">{user.display_name || user.username}{user.email ? ` · ${user.email}` : ''}</span>
        <button onClick={logout}>Log out</button>
      </header>
      <main>
        {view === 'dashboard' && (
          <Dashboard user={user} onUserChange={setUser} onStartBid={startBid} notify={notify} />
        )}
        {view === 'bid' && (
          <BidWorkspace
            user={user}
            seed={bidSeed}
            notify={notify}
            onDone={() => { setBidSeed(null); setView('dashboard') }}
          />
        )}
        {view === 'admin' && user.role === 'admin' && <AdminPanel notify={notify} />}
      </main>
      {toast && <div key={toast.id} className={`toast ${toast.kind}`}>{toast.message}</div>}
    </>
  )
}
