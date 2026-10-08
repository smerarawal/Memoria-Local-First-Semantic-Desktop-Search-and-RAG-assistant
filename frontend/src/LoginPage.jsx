import { useState } from 'react'
import { GoogleLogin } from '@react-oauth/google'

// Decode the JWT payload Google returns (no library needed — it's just base64)
function decodeJwt(token) {
  try {
    const base64 = token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/')
    return JSON.parse(atob(base64))
  } catch {
    return {}
  }
}

export default function LoginPage({ onLogin }) {
  const [showForm, setShowForm] = useState(false)
  const [name, setName]         = useState(() => localStorage.getItem('memoria_name') || '')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError]       = useState('')
  const [loading, setLoading]   = useState(false)

  // ── Google OAuth success ──────────────────────────────────────────
  function onGoogleSuccess(response) {
    const payload = decodeJwt(response.credential)
    const displayName = payload.name || payload.email || 'User'
    const email       = payload.email || 'google-user'
    localStorage.setItem('memoria_user', email)
    localStorage.setItem('memoria_name', displayName)
    localStorage.setItem('memoria_avatar', payload.picture || '')
    onLogin(email, displayName)
  }

  function onGoogleError() {
    setError('Google sign-in failed. Make sure you have set VITE_GOOGLE_CLIENT_ID.')
  }

  // ── Manual form submit ────────────────────────────────────────────
  function submit(e) {
    e.preventDefault()
    setError('')
    if (!name.trim())     { setError('Please enter your name.'); return }
    if (!username.trim()) { setError('Please enter your username.'); return }
    if (!password.trim()) { setError('Please enter a password.'); return }
    setLoading(true)
    setTimeout(() => {
      localStorage.setItem('memoria_user', username.trim())
      localStorage.setItem('memoria_name', name.trim())
      setLoading(false)
      onLogin(username.trim(), name.trim())
    }, 400)
  }

  return (
    <div className="lp-shell">
      <div className="lp-card">

        {/* ── Left — tree-moon illustration ── */}
        <div className="lp-left" aria-hidden="true">
          <div className="lp-left-overlay">
            <p className="lp-tagline">every file<br />holds a memory.</p>
            <span className="lp-brand">memoria_</span>
          </div>
        </div>

        {/* ── Right — auth form ── */}
        <div className="lp-right">
        <div className="lp-form-wrap">

          <div className="lp-header">
            <h1 className="lp-title">memoria_</h1>
            <p className="lp-sub">Your local AI memory. Private by design.</p>
          </div>

          {/* Google sign-in — primary CTA */}
          <div className="lp-google-wrap">
            <GoogleLogin
              onSuccess={onGoogleSuccess}
              onError={onGoogleError}
              theme="outline"
              size="large"
              text="signin_with"
              shape="rectangular"
              width="100%"
            />
          </div>

          {/* Divider */}
          <div className="lp-divider">
            <span className="lp-divider-line" />
            <span className="lp-divider-text">or continue manually</span>
            <span className="lp-divider-line" />
          </div>

          {/* Manual form — collapsed by default */}
          {!showForm ? (
            <button className="lp-show-form-btn" onClick={() => setShowForm(true)}>
              Use username &amp; password ↓
            </button>
          ) : (
            <form onSubmit={submit} noValidate>
              <label className="lp-label">Name
                <input className="lp-input" type="text" placeholder="Your name"
                  value={name} onChange={e => setName(e.target.value)} autoFocus />
              </label>
              <label className="lp-label">Username or email
                <input className="lp-input" type="text" placeholder="username@domain.com"
                  autoComplete="username"
                  value={username} onChange={e => setUsername(e.target.value)} />
              </label>
              <label className="lp-label">Password
                <input className="lp-input" type="password" placeholder="••••••••"
                  autoComplete="current-password"
                  value={password} onChange={e => setPassword(e.target.value)} />
              </label>
              {error && <p className="lp-error">{error}</p>}
              <button className="lp-btn" type="submit" disabled={loading}>
                {loading ? 'One moment…' : 'Enter →'}
              </button>
            </form>
          )}

          {error && !showForm && <p className="lp-error">{error}</p>}

          <p className="lp-privacy">
            🔒 All your files stay on this machine. Memoria never uploads your documents.
          </p>

        </div>
      </div>
    </div>
  </div>
)
}
