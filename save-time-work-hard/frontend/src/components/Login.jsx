import { useState } from 'react'
import { api, setToken } from '../api.js'

export default function Login({ onLogin }) {
  const [identifier, setIdentifier] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const submit = async (e) => {
    e.preventDefault()
    setBusy(true)
    setError('')
    try {
      const res = await api('/auth/login', { method: 'POST', body: { identifier, password } })
      setToken(res.token)
      onLogin(res.user)
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="login-page">
      <form className="card login-card stack" onSubmit={submit}>
        <div className="brand">
          <div className="brand-mark">ST</div>
          <h1>Save time, Work hard</h1>
          <span className="muted small">Sign in to start bidding</span>
        </div>
        <label className="field">
          <span>E-mail</span>
          <input
            autoFocus
            autoComplete="username"
            value={identifier}
            onChange={(e) => setIdentifier(e.target.value)}
            placeholder="you@example.com"
            required
          />
        </label>
        <label className="field">
          <span>Password</span>
          <input
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />
        </label>
        {error && <div className="alert">{error}</div>}
        <button className="primary" disabled={busy}>{busy ? 'Signing in…' : 'Log in'}</button>
        <span className="muted small" style={{ textAlign: 'center' }}>
          Accounts are created by the administrator.
        </span>
      </form>
    </div>
  )
}
