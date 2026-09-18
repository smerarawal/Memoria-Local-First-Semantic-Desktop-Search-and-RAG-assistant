import { useState } from 'react'

export default function LoginPage({ onLogin }) {
  const [mode, setMode] = useState('signin') // 'signin' or 'create'
  const [name, setName] = useState(() => localStorage.getItem('memoria_name') || '')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  function handleSubmit(e) {
    e.preventDefault()
    setError('')
    if (!name.trim()) { setError('Please enter your name.'); return }
    if (!username.trim()) { setError('Please enter your username/email.'); return }
    if (!password.trim()) { setError('Please enter a password.'); return }
    
    setLoading(true)
    setTimeout(() => {
      localStorage.setItem('memoria_user', username.trim())
      localStorage.setItem('memoria_name', name.trim())
      setLoading(false)
      onLogin(username.trim(), name.trim())
    }, 500)
  }

  return (
    <div className="login-shell">

      {/* Left — ocean image side */}
      <div className="login-left" aria-hidden="true">
        <div className="login-img-text">
          <p className="login-img-quote">Every file<br/>holds a memory.</p>
          <span className="login-img-line" />
        </div>
      </div>

      {/* Right — form side */}
      <div className="login-right">
        <div className="login-inner">

          <div className="login-logo-block">
            <span className="login-logo">Memoria</span>
          </div>

          {/* Mode toggler */}
          <div className="login-mode-toggle">
            <button 
              type="button"
              className={`login-mode-btn ${mode === 'signin' ? 'active' : ''}`}
              onClick={() => setMode('signin')}
            >
              Sign In
            </button>
            <button 
              type="button"
              className={`login-mode-btn ${mode === 'create' ? 'active' : ''}`}
              onClick={() => setMode('create')}
            >
              Create Account
            </button>
          </div>

          <form className="login-form" onSubmit={handleSubmit} noValidate>
            <div className="login-field">
              <label className="login-label" htmlFor="login-name">Your Name</label>
              <input
                id="login-name"
                className="login-input"
                type="text"
                placeholder="e.g. Smera Rawal"
                value={name}
                onChange={e => setName(e.target.value)}
                autoFocus
              />
            </div>

            <div className="login-field">
              <label className="login-label" htmlFor="login-username">Username or Email</label>
              <input
                id="login-username"
                className="login-input"
                type="text"
                autoComplete="username"
                placeholder="username@domain.com"
                value={username}
                onChange={e => setUsername(e.target.value)}
              />
            </div>

            <div className="login-field">
              <label className="login-label" htmlFor="login-password">Password</label>
              <input
                id="login-password"
                className="login-input"
                type="password"
                autoComplete="current-password"
                placeholder="••••••••"
                value={password}
                onChange={e => setPassword(e.target.value)}
              />
            </div>

            {error && <p className="login-error">{error}</p>}

            <button
              className="login-btn"
              type="submit"
              disabled={loading}
              id="login-submit"
            >
              {loading ? 'Processing…' : (mode === 'signin' ? 'Enter' : 'Create')}
            </button>
          </form>

        </div>
      </div>

    </div>
  )
}
