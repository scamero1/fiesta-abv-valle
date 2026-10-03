import { useState } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import { apiUrl } from './AdminLogin.jsx'
import '../styles/ganador.css'

const URL_TERMINOS_Y_CONDICIONES_PDF = `/Terminos_y_Condiciones_ILV_Extrem_Marketing_VERSION_FINAL.pdf`
const URL_POLITICA_TRATAMIENTO_DATOS_PDF = `/POLITICA-DE-PROTECCION-DE-DATOS-PERSONALES-2025.pdf`

export default function RegistroGanador() {
  const navigate = useNavigate()
  const location = useLocation()
  const state = location.state || {}
  const qr_uuid = state.qr_uuid || ''

  const [form, setForm] = useState({
    nombres_apellidos: '',
    celular: '',
    telefono_fijo: '',
    confirmar_celular: '',
    correo_electronico: '',
    direccion: '',
    barrio: '',
    municipio: '',
    ciudad: '',
  })

  const [errores, setErrores] = useState({})
  const [loading, setLoading] = useState(false)

  const actualizarCampo = (campo, valor) => {
    setForm((prev) => ({ ...prev, [campo]: valor }))
    if (errores[campo]) {
      setErrores((prev) => {
        const next = { ...prev }
        delete next[campo]
        return next
      })
    }
  }

  const validarForm = () => {
    const e = {}

    if (!form.nombres_apellidos || form.nombres_apellidos.trim().length < 2) {
      e.nombres_apellidos = 'Ingresa tu nombre completo (mínimo 2 caracteres)'
    } else if (form.nombres_apellidos.length > 80) {
      e.nombres_apellidos = 'Máximo 80 caracteres'
    }

    if (!/^[0-9]{10}$/.test(form.celular)) {
      e.celular = 'Celular debe ser 10 dígitos numéricos'
    }

    if (form.telefono_fijo && !/^[0-9]{7,10}$/.test(form.telefono_fijo)) {
      e.telefono_fijo = 'Teléfono fijo debe ser 7-10 dígitos'
    }

    if (form.celular && form.confirmar_celular !== form.celular) {
      e.confirmar_celular = 'Los celulares no coinciden'
    } else if (!/^[0-9]{10}$/.test(form.confirmar_celular)) {
      e.confirmar_celular = 'Confirma tu celular (10 dígitos)'
    }

    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(form.correo_electronico)) {
      e.correo_electronico = 'Ingresa un correo electrónico válido'
    }

    if (!form.direccion || form.direccion.trim().length < 10) {
      e.direccion = 'Dirección mínimo 10 caracteres'
    } else if (form.direccion.length > 120) {
      e.direccion = 'Máximo 120 caracteres'
    }

    if (!form.barrio || form.barrio.trim().length < 3) {
      e.barrio = 'Barrio mínimo 3 caracteres'
    } else if (form.barrio.length > 60) {
      e.barrio = 'Máximo 60 caracteres'
    }

    if (!form.municipio || !form.municipio.trim()) {
      e.municipio = 'Ingresa el municipio'
    }

    if (!form.ciudad || !form.ciudad.trim()) {
      e.ciudad = 'Ingresa la ciudad'
    }

    setErrores(e)
    return Object.keys(e).length === 0
  }

  const handleSubmit = async (e) => {
    e.preventDefault()
    if (!validarForm()) return
    if (!qr_uuid) {
      setErrores((prev) => ({
        ...prev,
        _generico: 'Código QR no válido. Regresa a la pantalla anterior.',
      }))
      return
    }

    setLoading(true)
    try {
      const body = {
        qr_uuid,
        acepta_terminos_at_iso: state.acepta_terminos_at_iso || state.acepta_terminos_at || new Date().toISOString(),
        acepta_habeas_at_iso: state.acepta_habeas_at_iso || state.acepta_habeas_at || new Date().toISOString(),
        nombres_apellidos: form.nombres_apellidos.trim(),
        celular: form.celular || null,
        telefono_fijo: form.telefono_fijo || null,
        celular_confirmacion: form.confirmar_celular || form.celular_confirmacion || null,
        correo_electronico: form.correo_electronico.trim().toLowerCase(),
        direccion: form.direccion.trim(),
        barrio: form.barrio ? form.barrio.trim() : null,
        municipio: form.municipio ? form.municipio.trim() : null,
        ciudad: form.ciudad.trim(),
      }

      const res = await fetch(apiUrl('/api/promo/registro'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })

      const textRaw = await res.text().catch(() => '')
      let data = {}
      try { data = textRaw ? JSON.parse(textRaw) : {} } catch (_e) { data = { _raw: textRaw.slice(0, 1200) } }

      const formatearErrorPydantic = () => {
        const arr = (data && Array.isArray(data.detail)) ? data.detail : null
        if (arr && arr.length) {
          const lineas = arr.map((er, i) => {
            try {
              const loc = Array.isArray(er.loc) ? er.loc.join(' > ') : String(er.loc || '')
              const msg = String(er.msg || er.message || er || 'error sin mensaje')
              const ty = String(er.type || '')
              return `${i+1}) [${loc || ty || 'body'}] ${msg}`.trim()
            } catch {
              return String(er)
            }
          })
          return lineas.join(' · ')
        }
        if (data && typeof data.detail === 'string') return data.detail
        if (data && typeof data.message === 'string') return data.message
        if (data && typeof data.error === 'string') return data.error
        if (data && data._raw) return String(data._raw).slice(0, 280)
        return 'No se pudo completar el registro. Intenta nuevamente.'
      }

      if (res.ok && (data.registro_id || data.id)) {
        navigate(`/ganador/gracias/${data.registro_id || data.id}`)
      } else {
        const txt = formatearErrorPydantic()
        setErrores((prev) => ({
          ...prev,
          _generico: `HTTP ${res.status} — ${String(txt).slice(0, 480)}`,
          _detalleTecnico: data,
        }))
        // Debug temporal panel F12:
        try { console.warn('[RegistroGanador] error HTTP '+res.status+':', data, 'body enviado:', body) } catch {}
      }
    } catch (err) {
      setErrores((prev) => ({
        ...prev,
        _generico: 'Error de conexión. Revisa tu red e intenta de nuevo.',
      }))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="screen ganador-screen">
      <div className="screen-bg ganador-bg-fondo-vertical" />

      <div className="screen-header instrucciones-header">
        <div className="header-left" />
        <div className="header-middle">
          <h1 className="header-titulo">Completa tus datos</h1>
        </div>
        <div className="header-right" />
      </div>

      <div className="screen-content ganador-content anim-in" style={{ justifyContent: 'flex-start', alignItems: 'center' }}>
        <div
          style={{
            width: '100%',
            maxWidth: 'min(96%, 720px)',
            marginBottom: 'clamp(12px, 2.2svh, 20px)',
            background: 'rgba(255,255,255,.96)',
            border: '1.5px solid rgba(0,71,186,.35)',
            borderRadius: '14px',
            padding: 'clamp(12px, 1.9svh, 18px) clamp(16px, 2.6svw, 24px)',
            boxShadow: '0 12px 30px rgba(0,0,0,.18)',
            color: '#001f4d',
            fontSize: 'clamp(.88rem, 1.65svw, 1rem)',
            lineHeight: '1.55',
            textAlign: 'center',
          }}
        >
          📄 Documentos legales disponibles:&nbsp;
          <a href={URL_TERMINOS_Y_CONDICIONES_PDF} target="_blank" rel="noreferrer noopener" className="ganador-link-pdf" style={{fontWeight:800,marginLeft:4}} title="Abrir Términos y Condiciones (PDF nueva pestaña)">
            TÉRMINOS Y CONDICIONES
          </a>
          &nbsp;·&nbsp;
          <a href={URL_POLITICA_TRATAMIENTO_DATOS_PDF} target="_blank" rel="noreferrer noopener" className="ganador-link-pdf" style={{fontWeight:800}} title="Abrir Política de Protección de Datos Personales (PDF nueva pestaña)">
            POLÍTICA TRATAMIENTO DE DATOS (Habeas Data)
          </a>
        </div>

        <form className="registro-form" onSubmit={handleSubmit} noValidate>
          {errores._generico && (
            <div className="registro-error full" style={{ background: 'rgba(228,0,43,0.15)', padding: '10px 14px', borderRadius: '10px', color: '#fff', fontWeight: 600 }}>
              ⚠ {errores._generico}
            </div>
          )}

          <div className="registro-campo full">
            <label htmlFor="f-nombres">Nombres y Apellidos<span className="req">*</span></label>
            <input
              id="f-nombres"
              type="text"
              value={form.nombres_apellidos}
              onChange={(e) => actualizarCampo('nombres_apellidos', e.target.value)}
              minLength={2}
              maxLength={80}
              required
              placeholder="Ej: María Fernanda Rodríguez"
            />
            {errores.nombres_apellidos && <span className="registro-error">{errores.nombres_apellidos}</span>}
          </div>

          <div className="registro-campo">
            <label htmlFor="f-celular">Celular<span className="req">*</span></label>
            <input
              id="f-celular"
              type="tel"
              value={form.celular}
              onChange={(e) => actualizarCampo('celular', e.target.value.replace(/\D/g, '').slice(0, 10))}
              pattern="[0-9]{10}"
              placeholder="3001234567"
              required
            />
            {errores.celular && <span className="registro-error">{errores.celular}</span>}
          </div>

          <div className="registro-campo">
            <label htmlFor="f-confirmar-celular">Confirmar Celular<span className="req">*</span></label>
            <input
              id="f-confirmar-celular"
              type="tel"
              value={form.confirmar_celular}
              onChange={(e) => actualizarCampo('confirmar_celular', e.target.value.replace(/\D/g, '').slice(0, 10))}
              pattern="[0-9]{10}"
              placeholder="3001234567"
              required
            />
            {errores.confirmar_celular && <span className="registro-error">{errores.confirmar_celular}</span>}
          </div>

          <div className="registro-campo">
            <label htmlFor="f-tel-fijo">Teléfono Fijo</label>
            <input
              id="f-tel-fijo"
              type="tel"
              value={form.telefono_fijo}
              onChange={(e) => actualizarCampo('telefono_fijo', e.target.value.replace(/\D/g, '').slice(0, 10))}
              pattern="[0-9]{7,10}"
              placeholder="6011234567 (opcional)"
            />
            {errores.telefono_fijo && <span className="registro-error">{errores.telefono_fijo}</span>}
          </div>

          <div className="registro-campo">
            <label htmlFor="f-correo">Correo Electrónico<span className="req">*</span></label>
            <input
              id="f-correo"
              type="email"
              value={form.correo_electronico}
              onChange={(e) => actualizarCampo('correo_electronico', e.target.value)}
              placeholder="correo@ejemplo.com"
              required
            />
            {errores.correo_electronico && <span className="registro-error">{errores.correo_electronico}</span>}
          </div>

          <div className="registro-campo full">
            <label htmlFor="f-direccion">Dirección<span className="req">*</span></label>
            <input
              id="f-direccion"
              type="text"
              value={form.direccion}
              onChange={(e) => actualizarCampo('direccion', e.target.value)}
              minLength={10}
              maxLength={120}
              placeholder="Cra / Calle / Carrera # ## - ##, Apt"
              required
            />
            {errores.direccion && <span className="registro-error">{errores.direccion}</span>}
          </div>

          <div className="registro-campo">
            <label htmlFor="f-barrio">Barrio<span className="req">*</span></label>
            <input
              id="f-barrio"
              type="text"
              value={form.barrio}
              onChange={(e) => actualizarCampo('barrio', e.target.value)}
              minLength={3}
              maxLength={60}
              placeholder="Ej: Chapinero"
              required
            />
            {errores.barrio && <span className="registro-error">{errores.barrio}</span>}
          </div>

          <div className="registro-campo">
            <label htmlFor="f-municipio">Municipio<span className="req">*</span></label>
            <input
              id="f-municipio"
              type="text"
              value={form.municipio}
              onChange={(e) => actualizarCampo('municipio', e.target.value)}
              placeholder="Ej: Bogotá"
              required
            />
            {errores.municipio && <span className="registro-error">{errores.municipio}</span>}
          </div>

          <div className="registro-campo full">
            <label htmlFor="f-ciudad">Ciudad<span className="req">*</span></label>
            <input
              id="f-ciudad"
              type="text"
              value={form.ciudad}
              onChange={(e) => actualizarCampo('ciudad', e.target.value)}
              placeholder="Bogotá D.C. / Medellín / Cali / ..."
              required
            />
            {errores.ciudad && <span className="registro-error">{errores.ciudad}</span>}
          </div>

          <button
            type="submit"
            className={`btn-primario btn-cta-red registro-btn-submit ${loading ? 'is-loading' : ''}`}
            disabled={loading}
          >
            {loading ? (
              <>
                <span className="spinner" />
                Registrando...
              </>
            ) : (
              <>📦 REGISTRAR Y RECLAMAR MI PREMIO</>
            )}
          </button>
        </form>
      </div>
    </div>
  )
}
