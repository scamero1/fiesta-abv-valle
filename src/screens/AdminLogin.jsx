import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import '../styles/adminDashboard.css'

// JWT admin se guarda en localStorage (no third-party). Expiración 24h igual que el token.
const LS_KEY = 'abv_admin_jwt'
const LS_EXP = 'abv_admin_jwt_exp'

function guardarJWT(token, expires_in = 86400) {
  localStorage.setItem(LS_KEY, token)
  const expiraEnMs = Date.now() + (Math.min(expires_in, 86400) * 1000)
  localStorage.setItem(LS_EXP, String(expiraEnMs))
}

export function leerJWTValido() {
  const tok = localStorage.getItem(LS_KEY)
  const exp = Number(localStorage.getItem(LS_EXP) || 0)
  if (!tok || !exp || Date.now() > exp) {
    localStorage.removeItem(LS_KEY); localStorage.removeItem(LS_EXP)
    return null
  }
  return tok
}
export function borrarJWT() { localStorage.removeItem(LS_KEY); localStorage.removeItem(LS_EXP) }

export default function AdminLogin() {
  const navigate = useNavigate()
  const [username, setUsername] = useState('ilv1921')
  const [password, setPassword] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const handleSubmit = async (e) => {
    e.preventDefault()
    setError('')
    if (!username || !password) {
      setError('Ingresa usuario y contraseña')
      return
    }
    setLoading(true)
    try {
      const res = await fetch('/api/admin/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password }),
      })
      const data = await res.json().catch(() => ({}))
      if (res.ok && data.access_token) {
        guardarJWT(data.access_token, data.expires_in || 86400)
        navigate('/admin/dashboard', { replace: true })
      } else {
        setError(data.message || data.error || 'Credenciales inválidas')
      }
    } catch {
      setError('Error de conexión. Revisa tu red e intenta de nuevo.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="screen admin-login-screen">
      <div className="screen-bg admin-login-bg" />

      <div className="screen-content anim-in" style={{ alignItems: 'center', justifyContent: 'center' }}>
        <form className="admin-login-card" onSubmit={handleSubmit} noValidate>
          <h1>Panel de Administración ILV 1921</h1>

          {error && <div className="admin-login-toast-error">{error}</div>}

          <div className="campo">
            <label htmlFor="admin-user">Usuario</label>
            <input
              id="admin-user"
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              placeholder="ilv1921"
              autoComplete="username"
              disabled={loading}
            />
          </div>

          <div className="campo">
            <label htmlFor="admin-pass">Contraseña</label>
            <input
              id="admin-pass"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="•••••••••••••••"
              autoComplete="current-password"
              disabled={loading}
            />
          </div>

          <button
            type="submit"
            className={`admin-login-btn ${loading ? 'is-loading' : ''}`}
            disabled={loading}
          >
            {loading ? (
              <>
                <span className="spinner" />
                INGRESANDO...
              </>
            ) : (
              'INGRESAR'
            )}
          </button>
        </form>
      </div>
    </div>
  )
}
