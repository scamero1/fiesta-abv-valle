import { useState, useEffect } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { QRCodeCanvas } from 'qrcode.react'
import { apiUrl } from './AdminLogin.jsx'
import '../styles/ganador.css'

export default function Ganador() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const qr_uuid = searchParams.get('qr') || ''

  const [aceptaTerminos, setAceptaTerminos] = useState(false)
  const [aceptaHabeas, setAceptaHabeas] = useState(false)
  const [terminosTs, setTerminosTs] = useState('')
  const [habeasTs, setHabeasTs] = useState('')

  // ===== FLUJO NUEVO: Step Visual 0 = Solo imagen PIEZA (8 segundos AUTO) / Step 1 = checks + botón ACEPTAR =====
  // User VERBATIM pedido #1 (1er flujo SHA 787034c): "le da click en la imagen y pasa a terminos"
  // User VERBATIM pedido #2 (SHA 12a7dd7): "NO SIRVE tocar cualquiera parte, SOLO darle al botón dibujado abajo"
  // User VERBATIM pedido #3 (SHA af8a64f ACTUAL):
  //   "Pieza NO LE DE CLICK; solo 8 segundos AUTO → políticas para aceptar → formulario"
  // ==== IMPLEMENTACIÓN: NINGÚN CLICK, SOLO ESPERA 8s ====
  const [stepVisual, setStepVisual] = useState(0)
  const [piezaCountdown, setPiezaCountdown] = useState(null)
  const avanzarATerminos = () => {
    if (qrEstado !== 'listo') return
    setPiezaCountdown(null)
    setStepVisual(1)
  }

  // ============== FIX INMEDIATO PANTALLA AZUL USER ==============
  // ROOT CAUSE (SHA af8a64f): fetch validar es ASYNC → useEffect reseteo step 0 depende solo de qr_uuid,
  // NO de la TRANSICIÓN qrEstado → 'listo'. Si stepVisual llegaba a 1 antes por StrictMode doble render /
  // hot reload / navegación back, al volver a montar qr_uuid NO cambia → stepVisual se quedó en 1.
  // Resultado: (qrEstado listo + stepVisual 1) = claseFondo Vertical = "pantalla de azul se queda".
  // SOLUCIÓN: useEffect SÓLO que escucha cuando qrEstado CAMBIA a 'listo' → FORZA stepVisual=0.
  useEffect(() => {
    if (qrEstado === 'listo') {
      setStepVisual(0)
      setPiezaCountdown(null)
      setAceptaTerminos(false)
      setAceptaHabeas(false)
      setTerminosTs('')
      setHabeasTs('')
    }
  }, [qrEstado])

  // Countdown auto 8s en Pieza (listo + stepVisual=0). Cuando llega a 0 → avanzarATerminos → políticas
  useEffect(() => {
    if (qrEstado === 'listo' && stepVisual === 0) {
      setPiezaCountdown(8)
      let restantes = 8
      let cancelado = false
      const idInt = setInterval(() => {
        if (cancelado) { clearInterval(idInt); return }
        restantes = restantes - 1
        if (restantes <= 0) {
          clearInterval(idInt)
          avanzarATerminos()
          return
        }
        setPiezaCountdown(restantes)
      }, 1000)
      return () => { cancelado = true; clearInterval(idInt) }
    } else {
      setPiezaCountdown(null)
    }
    // ✅ NO incluir qr_uuid en dep array!
    // Solo se reinicia el interval cuando cambia qrEstado listo/no-listo o stepVisual.
    // Incluir qr_uuid era bug SHA af8a64f: reiniciaba interval de 8s al hacer cualquier cosa.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [qrEstado, stepVisual])

  // Reseteamos stepVisual a 0 SI el QR uuid cambia (nuevo link en la misma pestaña)
  // => mantenemos este por seguridad al cambiar URL mismo componente
  useEffect(() => {
    setStepVisual(0)
    setPiezaCountdown(null)
    setAceptaTerminos(false)
    setAceptaHabeas(false)
    setTerminosTs('')
    setHabeasTs('')
  }, [qr_uuid])

  // ===== VALIDACION QR AL ABRIR LINK (ANTES DE MOSTRAR NADA) =====
  // User idea: 1 QR = 1 solo ganador. Si ya fue registrado, link se bloquea.
  // Estados: validando | listo | ya_usado | inhabilitado | no_existe | error_red
  const [qrEstado, setQrEstado] = useState('validando')
  const [qrInfo, setQrInfo] = useState(null)   // payload endpoint /api/promo/qr/validar

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

  const puedeContinuar = !!(qr_uuid && qrEstado === 'listo' && aceptaTerminos && aceptaHabeas)

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
      <div className="ganador-qr-wrap" title={`QR: ${qr_uuid || 'sin-qr'}`}>
        <QRCodeCanvas value={qr_uuid || 'no-qr'} size={64} level="M" includeMargin={false} />
      </div>
      {notaPie && <div className="ganador-bloqueo-nota">{notaPie}</div>}
    </div>
  )

  const renderContenido = () => {
    switch (qrEstado) {
      case 'validando':
        return <PantallaBloqueo icono="🔍" colorTitulo="color-blue" titulo="Validando código QR..." mensaje="Estamos confirmando que tu código QR está listo para reclamar el premio. Espera unos segundos." notaPie="Si esta pantalla dura más de 10s, cierra y vuelve a abrir el link." />
      case 'ya_usado':
        return <PantallaBloqueo
          icono="✖️"
          colorTitulo="color-red"
          titulo={(qrInfo && qrInfo.mensaje_titulo) || 'QR ya utilizado — Premio ya reclamado'}
          mensaje={(qrInfo && qrInfo.mensaje) || 'Este código QR ya fue utilizado para registrar un ganador. Solo se permite un solo ganador por QR. Pide un código QR nuevo en el puesto del evento.'}
          notaPie="Nota: La promotora del evento te entregará un QR nuevo gratuito para que vuelvas a participar y ganes."
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
                <QRCodeCanvas value={qr_uuid} size={64} level="M" includeMargin={false} />
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
                  <b>He leído y acepto los TÉRMINOS Y CONDICIONES de la promoción</b>
                  <div className="ganador-check-detalle">
                    Premio 1 botella Fiesta, ganador por orden de llegada, entrega en Bogotá D.C.,
                    ILV 1921 se reserva derecho de admisión, mayor de edad 18+, licor no se devuelve.
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
                  <b>Autorizo el TRATAMIENTO DE DATOS PERSONALES de acuerdo a la Ley 1581/2012 y política Habeas Data ILV 1921</b>
                  <div className="ganador-check-detalle">
                    Uso de datos solo para entrega del premio, no se comparten terceros.
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

      {/* ===== CONTADOR COUNTDOWN 8 SEGUNDOS (SOLO PIEZA stepVisual=0 / listo) =====
           User VERBATIM HOY: "que la persona NO LE DE CLICK, solo se muestre 8 segundos y luego pase"
           NO BOTÓN INVISIBLE. SÓLO contador grande centrado: 8..7..6..5..4..3..2..1 → AUTO step 1. */}
      {qrEstado === 'listo' && stepVisual === 0 && piezaCountdown !== null && (
        <div className="ganador-step0-countdown-wrapper">
          <div className="ganador-step0-countdown-titulo">Continuando en</div>
          <div className="ganador-step0-countdown-numero">
            {piezaCountdown}
            <span className="ganador-step0-countdown-seg">seg</span>
          </div>
          <div className="ganador-step0-countdown-barra-fondo">
            <div
              className="ganador-step0-countdown-barra-llena"
              style={{ width: `${((8 - piezaCountdown + 1) / 8) * 100}%` }}
            />
          </div>
          <div className="ganador-step0-countdown-leyenda">
            Aceptar políticas y completar registro 👇
          </div>
        </div>
      )}

      {/* HEADER: Se oculta solo en Step 0 (cuando queremos que la imagen esté 100% limpia y solo se vea el botón dibujado original de la pieza) */}
      {(qrEstado !== 'listo' || stepVisual >= 1) && (
        <div className="screen-header instrucciones-header">
          <div className="header-left" />
          <div className="header-middle">
            <h1 className="header-titulo">{tituloHeader()}</h1>
          </div>
          <div className="header-right" />
        </div>
      )}

      {/* CONTENIDO: Se oculta solo en Step 0 (solo imagen + botón invisible sobre botón dibujado) */}
      {(qrEstado !== 'listo' || stepVisual >= 1) && renderContenido()}
    </div>
  )
}
