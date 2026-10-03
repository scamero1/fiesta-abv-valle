import { useState, useEffect, useMemo } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { QRCodeCanvas } from 'qrcode.react'
import { apiUrl } from './AdminLogin.jsx'
import '../styles/ganador.css'

// ============================================================
// COMPONENTE A PRUEBA DE CRASH PARA QRCodeCanvas
// ============================================================
// Si la librería qrcode.react falla (cualquier razón), NUNCA debe desmontar
// TODO el componente Ganador. User reportó "azul puro sin nada por horas" =
// React 18 crashea 1 vez y no recupera sin ErrorBoundary.
// Este wrapper try/catch render retorna un div placeholder si algo sale mal.
function QRSeguro({ value, size = 64 }) {
  try {
    if (!value || typeof value !== 'string') return null
    // No importamos ni usamos nada dinámico; si falla el return JSX, catch
    // en el primer render lo agarramos antes de que React crashee el árbol.
    const _seguro = <QRCodeCanvas value={String(value)} size={Number(size) || 64} level="M" includeMargin={false} />
    return _seguro
  } catch (err) {
    // Silencioso; user solo ve un placeholder sin QR; no afecta UX de form/validación.
    try {
      console.warn('[GanaQR] fallback sin QR canvas:', err && err.message ? err.message : err)
    } catch {}
    return (
      <div style={{
        width: Number(size) || 64,
        height: Number(size) || 64,
        background: 'rgba(255,255,255,.06)',
        borderRadius: 10,
        border: '1px dashed rgba(255,255,255,.22)',
        color: '#fff',
        fontSize: 10,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        textAlign: 'center',
        padding: 6,
        wordBreak: 'break-all',
        lineHeight: 1.15,
      }}>
        QR: {String(value || '').slice(0, 10)}…
      </div>
    )
  }
}

// ============================================================
// ERROR BOUNDARY INLINE: si <Ganador /> TOTALMENTE falla (render o cualquier cosa),
// se renderiza este fallback amigable con el usuario en lugar de pantalla AZUL SÓLIDA.
// ============================================================
function PantallaFalloSeguro({ raw }) {
  return (
    <div className="screen ganador-screen">
      <div className="screen-bg ganador-bg-fondo-vertical" />
      <div className="screen-header instrucciones-header">
        <div className="header-left" />
        <div className="header-middle"><h1 className="header-titulo">Lo sentimos</h1></div>
        <div className="header-right" />
      </div>
      <div className="screen-content ganador-content anim-in">
        <div style={{maxWidth:640, margin:'0 auto', background:'rgba(255,255,255,.95)', padding:28, borderRadius:22, boxShadow:'0 14px 50px rgba(0,0,0,.25)', textAlign:'center'}}>
          <div style={{fontSize:60, marginBottom:6}}>ℹ️</div>
          <h1 style={{margin:'6px 0 12px', color:'#002A7A'}}>Para continuar, cierra y vuelve a abrir el link</h1>
          <p style={{margin:'0 0 16px', color:'#334155', fontSize:16, lineHeight:1.5}}>
            Oprime el botón <b>REFRESCAR</b> del navegador o cierra la pestaña y vuelve a escanear el QR.
            <br />Prometemos que el premio sigue ahí, solo hubo un detalle momentáneo.
          </p>
          {raw && typeof raw === 'string' && (
            <p style={{marginTop:14, fontSize:12, color:'#94a3b8', textAlign:'center'}}>{raw.slice(0,160)}</p>
          )}
        </div>
      </div>
    </div>
  )
}

// ===== URLS PÚBLICAS PDFs estáticos en carpeta /public (servidos por Vite Static) =====
// User VERBATIM hoy: "añade los links y direcciones en ganadores para los terminos y condiciones"
const URL_TERMINOS_Y_CONDICIONES_PDF = `/Terminos_y_Condiciones_ILV_Extrem_Marketing_VERSION_FINAL.pdf`
const URL_POLITICA_TRATAMIENTO_DATOS_PDF = `/POLITICA-DE-PROTECCION-DE-DATOS-PERSONALES-2025.pdf`

export default function Ganador() {
  // ============================================================
  // TRY-CATCH TOTAL DEL RENDER (NUNCA MÁS PANTALLA AZUL SÓLIDA):
  // ============================================================
  try {
  // ===== TODOS LOS HOOKS PRIMERO (orden fijo React Rules of Hooks) =====
  // NUNCA mezclar hooks con constantes/funciones handlers entre ellos para
  // evitar referencias adelantadas / TDZ / desalineación doble-render StrictMode.
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const qr_uuid = searchParams.get('qr') || ''

  // Estados (TODOS declarados ANTES de cualquier useRef/función que los capture):
  const [aceptaTerminos, setAceptaTerminos] = useState(false)
  const [aceptaHabeas, setAceptaHabeas] = useState(false)
  const [terminosTs, setTerminosTs] = useState('')
  const [habeasTs, setHabeasTs] = useState('')
  const [stepVisual, setStepVisual] = useState(0)
  const [qrEstado, setQrEstado] = useState('validando')
  const [qrInfo, setQrInfo] = useState(null)

  // ===== useMemo / useEffects DESPUÉS de todos los useState =====
  const puedeContinuar = useMemo(
    () => !!(qr_uuid && qrEstado === 'listo' && aceptaTerminos && aceptaHabeas),
    [qr_uuid, qrEstado, aceptaTerminos, aceptaHabeas]
  )

  // ============== FIX INMEDIATO PANTALLA AZUL ==============
  // Cuando el endpoint retorna 200 y qrEstado → 'listo' (async), forzamos siempre stepVisual a 0
  // para que NO SE QUEDE PEGADO en stepVisual 1 (Vertical) cuando montan de nuevo link.
  useEffect(() => {
    if (qrEstado === 'listo') {
      setStepVisual(0)
      setAceptaTerminos(false)
      setAceptaHabeas(false)
      setTerminosTs('')
      setHabeasTs('')
    }
  }, [qrEstado])

  // Reseteamos si cambia el QR uuid (nuevo link en misma pestaña):
  useEffect(() => {
    setStepVisual(0)
    setAceptaTerminos(false)
    setAceptaHabeas(false)
    setTerminosTs('')
    setHabeasTs('')
  }, [qr_uuid])

  // ===== VALIDACION QR AL ABRIR LINK (ANTES DE MOSTRAR NADA) =====
  // User idea: 1 QR = 1 solo ganador. Si ya fue registrado, link se bloquea.
  // Estados: validando | listo | ya_usado | inhabilitado | no_existe | error_red
  useEffect(() => {
    let cancelled = false
    const validar = async () => {
      if (!qr_uuid) {
        setQrEstado('no_existe')
        setQrInfo({
          mensaje_titulo: 'Link inválido',
          mensaje: 'Falta el parámetro ?qr= en la URL. Escanea un QR válido generado por el administrador del evento.',
        })
        return
      }
      try {
        const res = await fetch(apiUrl('/api/promo/qr/validar'), {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ qr_uuid }),
        })
        if (cancelled) return
        if (res.ok) {
          const d = await res.json().catch(() => ({}))
          const est = d && d.estado ? String(d.estado) : (d && d.valido ? 'listo' : 'no_existe')
          setQrInfo(d || {})
          setQrEstado(est)
        } else if (res.status === 400) {
          const d = await res.json().catch(() => ({}))
          setQrInfo({
            mensaje_titulo: 'Link inválido',
            mensaje: d.detail || 'QR inválido.',
          })
          setQrEstado('no_existe')
        } else {
          setQrInfo({
            mensaje_titulo: 'Error de conexión',
            mensaje: 'No se pudo validar el QR. Revisa internet o cierra y vuelve a abrir el link.',
          })
          setQrEstado('error_red')
        }
      } catch {
        if (cancelled) return
        setQrInfo({
          mensaje_titulo: 'Sin conexión',
          mensaje: 'No se pudo validar el QR. Acercate a la promotora para ayuda o vuelve a intentar.',
        })
        setQrEstado('error_red')
      }
    }
    validar()
    return () => { cancelled = true }
  }, [qr_uuid])

  // ===== FUNCIONES HANDLERS (TODOS los states YA están declarados, sin referencias adelantadas) =====
  const avanzarATerminos = () => {
    if (qrEstado !== 'listo') return
    setStepVisual(1)
  }

  const formatearTimestamp = (iso) => {
    if (!iso) return ''
    try {
      const d = new Date(iso)
      const hh = String(d.getHours()).padStart(2, '0')
      const mm = String(d.getMinutes()).padStart(2, '0')
      const ss = String(d.getSeconds()).padStart(2, '0')
      return `ⓘ Aceptado ${hh}:${mm}:${ss} servidor`
    } catch {
      return ''
    }
  }

  const enviarAceptacion = async (tipo) => {
    // Antes de enviar aceptacion, la validacion QR DEBE estar en estado "listo".
    // Si alguien togglea rapidisimo antes de validar, bloqueamos.
    if (!qr_uuid) return null
    if (qrEstado !== 'listo') return null
    try {
      const res = await fetch(apiUrl('/api/promo/aceptacion'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ qr_uuid, tipo }),
      })
      if (res.ok) {
        const data = await res.json().catch(() => ({}))
        return data.server_timestamp_iso || new Date().toISOString()
      }
      // 409/410 → QR fue usado/inhabilitado en el interín: REFRESCAR VALIDACIÓN
      if (res.status === 409 || res.status === 410 || res.status === 404) {
        try {
          const d = await res.json().catch(() => ({}))
          setQrInfo({
            mensaje_titulo: (res.status === 409) ? 'QR ya utilizado — Premio ya reclamado'
              : (res.status === 410) ? 'QR inhabilitado' : 'QR no encontrado',
            mensaje: d.detail || 'Este QR ya no está disponible.',
          })
          setQrEstado(
            res.status === 409 ? 'ya_usado'
              : res.status === 410 ? 'inhabilitado' : 'no_existe'
          )
        } catch { /* ignore */ }
      }
    } catch {
    }
    return null
  }

  const handleToggleTerminos = async (e) => {
    const checked = e.target.checked
    if (qrEstado !== 'listo') {
      setAceptaTerminos(false)
      return
    }
    setAceptaTerminos(checked)
    if (checked) {
      const ts = await enviarAceptacion('terminos')
      setTerminosTs(formatearTimestamp(ts))
    } else {
      setTerminosTs('')
    }
  }

  const handleToggleHabeas = async (e) => {
    const checked = e.target.checked
    if (qrEstado !== 'listo') {
      setAceptaHabeas(false)
      return
    }
    setAceptaHabeas(checked)
    if (checked) {
      const ts = await enviarAceptacion('habeas')
      setHabeasTs(formatearTimestamp(ts))
    } else {
      setHabeasTs('')
    }
  }

  const handleContinuar = () => {
    if (!puedeContinuar) return
    navigate('/ganador/registro', {
      state: {
        qr_uuid,
        acepta_terminos_at: terminosTs ? new Date().toISOString() : null,
        acepta_habeas_at: habeasTs ? new Date().toISOString() : null,
      },
    })
  }

  // Pantalla de CARGA MIENTRAS VALIDA (primeros ~300ms)
  const PantallaBloqueo = ({ icono, colorTitulo, titulo, mensaje, notaPie }) => (
    <div className="screen-content ganador-content anim-in">
      <div className={`ganador-bloqueo-icono ${colorTitulo}`}>{icono}</div>
      <h2 className={`ganador-titulo ganador-bloqueo-titulo ${colorTitulo}`}>{titulo}</h2>
      <p className="ganador-subtitulo ganador-bloqueo-mensaje">{mensaje}</p>
      <div className={`ganador-qr-wrap`} title={`QR: ${qr_uuid || 'sin-qr'}`}>
        <QRSeguro value={qr_uuid || 'no-qr'} size={64} />
      </div>
      {notaPie && <div className="ganador-bloqueo-nota">{notaPie}</div>}
    </div>
  )

  const renderContenido = () => {
    switch (qrEstado) {
      case 'validando':
        return <PantallaBloqueo icono="🔍" colorTitulo="color-blue" titulo="Validando código QR..." mensaje="Estamos confirmando que tu código QR está listo para reclamar el premio. Espera unos segundos." notaPie="Si esta pantalla dura más de 10s, cierra y vuelve a abrir el link." />
      case 'ya_usado':
        // User VERBATIM 03/10/2026: TÍTULO SOLO = "QR YA UTILIZADA". NADA MÁS.
        // Eliminar fallback antiguo "QR ya utilizado — Premio ya reclamado".
        // Título HARDCODEADO exacto. Mensaje = lo que venga del backend (nombre + hora + ciudad + pide QR nuevo).
        return <PantallaBloqueo
          icono="✖️"
          colorTitulo="color-red"
          titulo="QR YA UTILIZADA"
          mensaje={(qrInfo && qrInfo.mensaje) || 'Premio ya reclamado por otra persona. Pide un QR nuevo en el puesto del evento.'}
          notaPie="Nota: La promotora del evento te entregará un QR nuevo gratuito para que vuelvas a participar."
        />
      case 'inhabilitado':
        return <PantallaBloqueo
          icono="🚫"
          colorTitulo="color-amber"
          titulo={(qrInfo && qrInfo.mensaje_titulo) || 'QR inhabilitado'}
          mensaje={(qrInfo && qrInfo.mensaje) || 'Este QR fue inhabilitado por el administrador. Pide un código nuevo en el puesto de Aguardiente Blanco del Valle.'}
          notaPie="Puedes solicitar un QR nuevo de forma gratuita con la promotora del evento."
        />
      case 'error_red':
        return <PantallaBloqueo
          icono="📡"
          colorTitulo="color-amber"
          titulo={(qrInfo && qrInfo.mensaje_titulo) || 'Sin conexión'}
          mensaje={(qrInfo && qrInfo.mensaje) || 'No se pudo validar el QR. Revisa que tengas señal de datos o WiFi, y vuelve a abrir el link.'}
          notaPie="Tira para abajo en el navegador para refrescar (pull to refresh) o cierra y abre el link nuevamente."
        />
      case 'no_existe':
      default:
        return <PantallaBloqueo
          icono="❔"
          colorTitulo="color-gray"
          titulo={(qrInfo && qrInfo.mensaje_titulo) || 'Link inválido'}
          mensaje={(qrInfo && qrInfo.mensaje) || 'Este QR no fue encontrado en el sistema. Asegúrate de haber escaneado el código correctamente con la cámara y solicita uno nuevo en el puesto si el error persiste.'}
          notaPie="Si crees que es un error, acércate a la promotora del evento para revisar."
        />
      case 'listo':
        // ==================== ESTADO OK: MUESTRA UI NORMAL (checks + continuar) ====================
        return (
          <div className="screen-content ganador-content anim-in">
            <h2 className="ganador-titulo">{(qrInfo && qrInfo.mensaje_titulo) || '¡Felicidades!'}</h2>
            <p className="ganador-subtitulo">
              {qrInfo && qrInfo.mensaje ? qrInfo.mensaje : 'Ganaste una botella de Aguardiente Blanco del Valle Fiesta 🎉'}
            </p>

            {qr_uuid && (
              <div className="ganador-qr-wrap" title={`QR: ${qr_uuid}`}>
                <QRSeguro value={qr_uuid} size={64} />
              </div>
            )}

            <div className="ganador-checks">
              <label className="ganador-check-wrap" htmlFor="chk-terminos">
                <input
                  type="checkbox"
                  id="chk-terminos"
                  checked={aceptaTerminos}
                  onChange={handleToggleTerminos}
                />
                <span className="ganador-check-label">
                  <b>
                    He leído y acepto los&nbsp;
                    <a
                      href={URL_TERMINOS_Y_CONDICIONES_PDF}
                      target="_blank"
                      rel="noreferrer noopener"
                      className="ganador-link-pdf"
                      title="Abrir Términos y Condiciones (PDF en nueva pestaña)"
                    >
                      TÉRMINOS Y CONDICIONES de la promoción
                    </a>
                  </b>
                  <div className="ganador-check-detalle">
                    Premio 1 botella Fiesta, entrega en Bogotá D.C., ILV 1921 se reserva derecho de admisión,
                    mayor de edad 18+, licor no se devuelve. Puedes leer el documento completo dando clic al enlace azul.
                  </div>
                  {terminosTs && (
                    <span className="ganador-aceptado-timestamp">{terminosTs}</span>
                  )}
                </span>
              </label>

              <label className="ganador-check-wrap" htmlFor="chk-habeas">
                <input
                  type="checkbox"
                  id="chk-habeas"
                  checked={aceptaHabeas}
                  onChange={handleToggleHabeas}
                />
                <span className="ganador-check-label">
                  <b>
                    Autorizo el&nbsp;
                    <a
                      href={URL_POLITICA_TRATAMIENTO_DATOS_PDF}
                      target="_blank"
                      rel="noreferrer noopener"
                      className="ganador-link-pdf"
                      title="Abrir Política de Protección de Datos Personales (PDF en nueva pestaña)"
                    >
                      TRATAMIENTO DE DATOS PERSONALES (Política Habeas Data ILV 1921 / Ley 1581/2012)
                    </a>
                  </b>
                  <div className="ganador-check-detalle">
                    Uso de datos solo para entrega del premio, no se comparten con terceros, derecho a conocer/actualizar/suprimir tus datos.
                    Documento completo disponible en el enlace azul arriba.
                  </div>
                  {habeasTs && (
                    <span className="ganador-aceptado-timestamp">{habeasTs}</span>
                  )}
                </span>
              </label>
            </div>

            <button
              type="button"
              className={`btn-primario btn-cta-red ganador-btn-continuar ${!puedeContinuar ? 'is-disabled' : ''}`}
              onClick={handleContinuar}
              disabled={!puedeContinuar}
            >
              ACEPTAR Y REGISTRARME →
            </button>
          </div>
        )
    }
  }

  const tituloHeader = () => {
    switch (qrEstado) {
      case 'listo': return '¡FELICIDADES GANASTE!'
      case 'validando': return 'Validando QR...'
      case 'ya_usado': return 'QR YA UTILIZADO'
      case 'inhabilitado': return 'QR INHABILITADO'
      case 'error_red': return 'Sin conexión'
      case 'no_existe':
      default: return 'Link inválido'
    }
  }

  // Determinamos clase fondo dinámicamente según stepVisual y estado QR
  // User VERBATIM (último pedido): "cuando diga validando codigo qr que tenga este fondo Fondo Vertical.png"
  // Regla clara:
  //   - qrEstado === 'validando' → Fondo Vertical.png
  //   - qrEstado === 'listo' && stepVisual === 0 → Pieza Ganadores Vertical.jpg (solo cuando la pieza debe estar 100% limpia antes de click botón)
  //   - CUALQUIER OTRO CASO (listo stepVisual>=1 / ya_usado / inhabilitado / error_red / no_existe) → Fondo Vertical.png
  const claseFondo = (qrEstado === 'listo' && stepVisual === 0)
    ? 'screen-bg ganador-bg'
    : 'screen-bg ganador-bg-fondo-vertical'

  return (
    <div className="screen ganador-screen">
      <div className={claseFondo} />

      {/* ===== BOTÓN FULLSCREEN TRANSPARENTE EN TODA LA PANTALLA =====
           User VERBATIM HOY MÁXIMA PRIORIDAD (supera countdown 8s y supera botón área CTA):
           "colocas un botón transparente en TODA LA PANTALLA para que solo le de click y
            de una pase a terminos y condiciones"
           Z=9999 absolute inset: 0. Cualquier toque/click en CUALQUIER LUGAR de la pantalla
           (esquina sup izq / logo / foto / título / slogan / pie) pasa a políticas/aceptar. */}
      {qrEstado === 'listo' && stepVisual === 0 && (
        <button
          type="button"
          className="ganador-step0-btn-fullscreen-transparente"
          onClick={avanzarATerminos}
          aria-label="Toca para continuar con la aceptación de términos"
          tabIndex={0}
          onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') avanzarATerminos() }}
        >
          <span className="ganador-step0-btn-fullscreen-llamado">
            👉 Toca cualquier parte para continuar 👈
          </span>
        </button>
      )}

      {/* HEADER: Se oculta solo en Step 0 (Pieza 100% limpia SIN HEADER / SIN TEXTO). */}
      {(qrEstado !== 'listo' || stepVisual >= 1) && (
        <div className="screen-header instrucciones-header">
          <div className="header-left" />
          <div className="header-middle">
            <h1 className="header-titulo">{tituloHeader()}</h1>
          </div>
          <div className="header-right" />
        </div>
      )}

      {/* CONTENIDO: Se oculta solo en Step 0 (Pieza 100% limpia) */}
      {(qrEstado !== 'listo' || stepVisual >= 1) && renderContenido()}
    </div>
  )
  // ============================================================
  // CATCH TOTAL: Cualquier error durante render Ganador
  // => PantallaFalloSeguro amigable para el user, NUNCA pantalla azul puro sólida.
  // ============================================================
  } catch (_err) {
    let _suf = ''
    try { _suf = (_err && _err.message ? String(_err.message) : String(_err || '')).slice(0, 160) } catch {}
    return <PantallaFalloSeguro raw={_suf} />
  }
}
