import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import '../styles/adminDashboard.css'

// JWT admin se guarda en localStorage (no third-party). Expiración 24h igual que el token.
const LS_KEY = 'abv_admin_jwt'
const LS_EXP = 'abv_admin_jwt_exp'

// =================================================================
// BACKEND_URL: calcula la URL base del backend Python (Servicio 1).
// Usa EXACTAMENTE la misma estrategia que src/services/imageProcessor.js
// PRIORIDAD 1: VITE_BACKEND_URL  (configurar en Railway Servicio 2 FRONTEND Static)
// PRIORIDAD 2: VITE_PROCESS_URL
// PRIORIDAD 3: VITE_RAILWAY_URL
// PRIORIDAD 4: string vacío = localhost proxy (dev) o mismo dominio producción SI
//             hay rewrite rules.
// =================================================================
export const BACKEND_URL = (
  import.meta.env.VITE_BACKEND_URL ||
  import.meta.env.VITE_PROCESS_URL ||
  import.meta.env.VITE_RAILWAY_URL ||
  ''
).replace(/\/+$/, '')

export const apiUrl = (path = '') => {
  const p = path.startsWith('/') ? path : '/' + path
  return BACKEND_URL + p
}

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
  const [password, setPassword] = useState('Fiesta2026!Valle')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [debugInfo, setDebugInfo] = useState(null)
  const [diagnostico, setDiagnostico] = useState(null)
  const [diagnosticando, setDiagnosticando] = useState(false)

  const diagnosticarBackend = async () => {
    setDiagnosticando(true)
    setDiagnostico(null)
    const base = BACKEND_URL || window.location.origin
    const urls = [
      { k: 'HEALTH (cors)', u: `${base.replace(/\/+$/, '')}/health`, m: 'cors' },
      { k: 'HEALTH (no-cors)', u: `${base.replace(/\/+$/, '')}/health`, m: 'no-cors' },
      { k: 'CORSTEST (cors)', u: `${base.replace(/\/+$/, '')}/cors-test`, m: 'cors' },
      { k: 'CORSTEST (no-cors)', u: `${base.replace(/\/+$/, '')}/cors-test`, m: 'no-cors' },
    ]
    const resumen = {}
    for (const t of urls) {
      try {
        const res = await fetch(t.u, { method: 'GET', mode: t.m })
        let bodyPreview = ''
        try {
          if (t.m === 'cors') {
            const txt = await res.text()
            bodyPreview = txt.slice(0, 160)
          }
        } catch {}
        resumen[t.k] = { status: res.status, ok: res.ok, type: res.type, bodyPreview }
      } catch (e) {
        resumen[t.k] = {
          status: 'EXC',
          error: e?.message || String(e),
          explicacion:
            t.m === 'cors'
              ? 'Failed to fetch modo cors = el backend NO respondió (caído / dominio incorrecto / puerto cerrado) O el header Access-Control-Allow-Origin NO fue enviado por CORS bloqueado por Railway WAF. Prueba modo no-cors abajo.'
              : 'Failed to fetch modo no-cors = el backend está TOTALMENTE caído (502/503 Railway), el dominio NO EXISTE o hay firewall bloqueando. Esto NO es un problema de CORS.'
        }
      }
    }

    // Heuristica conclusión
    let conclusion = ''
    const c = resumen
    if (c['HEALTH (no-cors)']?.error) {
      conclusion =
        '🔴 DIAGNÓSTICO: BACKEND PYTHON ESTÁ CAÍDO EN RAILWAY. No responde ni siquiera a no-cors. SOLUCIÓN: (1) Railway Dashboard → Servicio1 Python → Ver Logs / Redeploy Latest. (2) Asegúrate que quede Healthy (checkmark verde). (3) Probá la URL /health directamente en una pestaña.'
    } else if (c['HEALTH (cors)']?.error && c['HEALTH (no-cors)']?.ok) {
      conclusion =
        '🟡 DIAGNÓSTICO: BACKEND ESTÁ UP PERO CORS ESTÁ BLOQUEADO. Modo no-cors funciona pero cors FALLA = el navegador bloquea por header Access-Control-Allow-Origin. SOLUCIÓN: (1) Hacer REDEPLOY del Backend Python SHA nuevo (ya agregué expose_headers y max_age). (2) Asegúrate de NO usar allow_credentials=True con allow_origins=* (está en False ya).'
    } else if (c['HEALTH (cors)']?.ok) {
      conclusion =
        '🟢 DIAGNÓSTICO: BACKEND ESTÁ UP + CORS OK. Si el login sigue fallando = el problema NO es red ni CORS, es la lógica AUTH. Soluciones: (1) abre /api/promo/debug/reseed-admin en el dominio backend para insertar admin ilv1921. (2) Abre /api/promo/debug/health para verificar tablas existen.'
    } else if (c['CORSTEST (cors)']?.ok) {
      conclusion = '🟢 BACKEND UP + CORS OK. Revisa credenciales y que admin ilv1921 exista con /api/promo/debug/reseed-admin.'
    } else {
      conclusion = '🟡 INDEFINIDO: Revisa los resultados abajo y envíame screenshot.'
    }

    setDiagnostico({ base, resumen, conclusion })
    setDiagnosticando(false)
  }

  const handleSubmit = async (e) => {
    e.preventDefault()
    setError('')
    setDebugInfo(null)
    if (!username || !password) {
      setError('Ingresa usuario y contraseña')
      return
    }
    const URL = apiUrl('/api/admin/login')
    setLoading(true)
    try {
      const res = await fetch(URL, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          username: String(username || '').trim(),
          password: String(password || ''),
        }),
      })
      const txt = await res.text()
      let data = {}
      try { data = JSON.parse(txt) } catch { data = { _raw: txt.slice(0, 200) } }

      if (res.ok && data.access_token) {
        guardarJWT(data.access_token, data.expires_in || 86400)
        navigate('/admin/dashboard', { replace: true })
      } else {
        // AQUI ESTABA EL BUG PRINCIPAL: FastAPI envía data.detail NO data.message
        const detalleReal = data.detail || data.error || data.message || data._raw || 'Sin detalle del servidor'
        const msg = `HTTP ${res.status} — ${detalleReal}`
        setError(msg)
        setDebugInfo({
          url_peticion: URL,
          status_code: res.status,
          status_text: res.statusText,
          backend_url_configurado: BACKEND_URL || '(vacio = mismo dominio, revisar rewrite railway servicio 2)',
          enviado: { username: username.trim(), password_len: (password || '').length },
          respuesta_servidor: data,
          proximo_paso:
            res.status === 404
              ? '⚠️ STATUS 404 = Endpoint NO está en este dominio. CONFIGURA VITE_BACKEND_URL en Railway Servicio 2 (Frontend) con el dominio del Servicio 1 (Python). Luego redeploy Frontend.'
              : res.status === 401
                ? data?.detail === 'Credenciales inválidas'
                  ? '⚠️ STATUS 401 credenciales = Admin no existe en DB. Carga /api/promo/debug/reseed-admin en el backend para insertar ilv1921/Fiesta2026!Valle.'
                  : data?.detail || '⚠️ STATUS 401 genérico = token u otro. Reinicia login.'
                : res.status >= 500
                  ? '⚠️ STATUS 5XX = Backend Python está caído o error en startup. Revisa logs Railway Servicio 1.'
                  : '⚠️ Error inesperado, revisa los datos técnicos.'
        })
      }
    } catch (err) {
      const msg = `Error de conexión: ${err?.message || String(err)}`
      setError(msg)
      setDebugInfo({
        url_peticion: URL,
        backend_url_configurado: BACKEND_URL || '(vacio)',
        error: msg,
        proximo_paso: BACKEND_URL
          ? '⚠️ Revisa que el dominio VITE_BACKEND_URL sea correcto (https://...) y que Railway Servicio 1 backend esté UP.'
          : '⚠️ NO hay VITE_BACKEND_URL configurada en Railway Servicio 2 = Frontend Static no sabe dónde está el Python. Agrega la variable!'
      })
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="screen admin-login-screen">
      <div className="screen-bg admin-login-bg" />

      <div className="screen-content anim-in" style={{ alignItems: 'center', justifyContent: 'center' }}>
        <form className="admin-login-card" onSubmit={handleSubmit} noValidate style={{ width: 640, maxWidth: '96vw' }}>
          <h1>Panel de Administración ILV 1921</h1>

          {error && <div className="admin-login-toast-error" style={{ whiteSpace: 'pre-wrap', lineHeight: 1.5 }}>{error}</div>}

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
              placeholder="Fiesta2026!Valle"
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

          <button
            type="button"
            className="admin-login-btn"
            disabled={diagnosticando}
            style={{
              marginTop: 10,
              background: diagnosticando ? '#334155' : 'linear-gradient(135deg, #065f46 0%, #047857 100%)',
              border: 'none',
              fontSize: 15,
            }}
            onClick={diagnosticarBackend}
          >
            {diagnosticando ? '🔧 DIAGNOSTICANDO CONEXIÓN BACKEND...' : '🔧 DIAGNOSTICAR CONEXIÓN BACKEND (1 clic)'}
          </button>

          <div
            style={{
              marginTop: 14,
              textAlign: 'left',
              fontSize: 12.5,
              color: '#cbd5e1',
              background: 'rgba(15, 23, 42, 0.55)',
              padding: '10px 12px',
              borderRadius: 10,
              lineHeight: 1.7,
              border: '1px solid rgba(148, 163, 184, 0.2)',
            }}
          >
            <div><b style={{ color: '#fbbf24' }}>📋 PASOS RÁPIDOS PRIMERO (sin tocar código):</b></div>
            <div>1️⃣ ABRÍ NUEVA PESTAÑA → <b>{BACKEND_URL || '(mismo dominio, configura VITE_BACKEND_URL!)'}/health</b> → DEBE MOSTRAR JSON <code style={{ color: '#86efac' }}>{'{ok:true}'}</code></div>
            <div>2️⃣ ABRÍ → <b>{BACKEND_URL || '(...)'}/cors-test</b> → DEBE MOSTRAR JSON <code style={{ color: '#86efac' }}>cors: OK</code></div>
            <div>3️⃣ ABRÍ → <b>{BACKEND_URL || '(...)'}/api/promo/debug/reseed-admin</b> → reinserta admin ilv1921</div>
            <div>4️⃣ VOLVÉ a <b>/admin</b> y click INGRESAR.</div>
          </div>

          {diagnostico && (
            <div
              style={{
                marginTop: 14,
                padding: '14px 16px',
                borderRadius: 12,
                background:
                  diagnostico.conclusion.includes('🔴')
                    ? 'rgba(127, 29, 29, 0.72)'
                    : diagnostico.conclusion.includes('🟡')
                      ? 'rgba(146, 64, 14, 0.72)'
                      : 'rgba(6, 78, 59, 0.72)',
                border: '1px solid rgba(226, 232, 240, 0.25)',
                fontSize: 12.5,
                color: '#e2e8f0',
                lineHeight: 1.6,
                fontFamily: 'ui-monospace, Consolas, monospace',
                textAlign: 'left',
                whiteSpace: 'pre-wrap',
                wordBreak: 'break-all',
              }}
            >
              <div style={{ fontSize: 14, color: '#fde68a', fontWeight: 700, marginBottom: 8 }}>
                🔧 RESULTADO DIAGNÓSTICO:
              </div>
              <div style={{ marginBottom: 10 }}>{diagnostico.conclusion}</div>
              <div>
                <b style={{ color: '#93c5fd' }}>Dominio backend probado (base):</b> {diagnostico.base}
              </div>
              {Object.entries(diagnostico.resumen).map(([k, v]) => (
                <div key={k} style={{ marginTop: 4 }}>
                  <b style={{ color: '#bae6fd' }}>{k}:</b> {JSON.stringify(v, null, 0)}
                </div>
              ))}
            </div>
          )}

          {debugInfo && (
            <div
              style={{
                marginTop: 16,
                padding: '14px 16px',
                borderRadius: 12,
                background: 'rgba(15, 23, 42, 0.72)',
                border: '1px solid rgba(148, 163, 184, 0.25)',
                fontSize: 12,
                color: '#cbd5e1',
                lineHeight: 1.6,
                fontFamily: 'ui-monospace, Consolas, monospace',
                textAlign: 'left',
                whiteSpace: 'pre-wrap',
                wordBreak: 'break-all',
              }}
            >
              <b style={{ color: '#fbbf24' }}>🔧 INFO TÉCNICA DEPLOY:</b>
              {'\n'}
              {Object.entries(debugInfo).map(([k, v]) => (
                <div key={k}>
                  <b style={{ color: '#93c5fd' }}>{k}:</b>{' '}
                  {typeof v === 'object' ? JSON.stringify(v, null, 0) : String(v)}
                </div>
              ))}
            </div>
          )}
        </form>
      </div>
    </div>
  )
}
