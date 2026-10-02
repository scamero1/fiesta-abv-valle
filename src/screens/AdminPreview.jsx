import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { QRCodeCanvas } from 'qrcode.react'
import '../styles/ganador.css'
import '../styles/adminDashboard.css'

// ==============================================================
// ADMIN PREVIEW: MUESTRA CÓMO SE VEN LAS 3 PANTALLAS DEL FLUJO GANADOR
// (solo admin, URL manual /admin/preview)
// Idea user: "añade o coloca en admin un link de vista previa de como se ve todo"
// - Fondo: Pieza Ganadores Vertical.jpg (oficial del evento)
// - Modo celular: botón "Toggle portrait/landscape" para previsualizar
// - TODO CENTRADO (estética sobria minimalista)
// ==============================================================

const MOCK_UUID = '00000000-0000-0000-0000-000000000PREVIEW'
const MOCK_REGISTRO = {
  posicion: 123,
  nombres: 'María Fernanda Rodríguez Pérez',
  celular: '3001234567',
  correo: 'maria@ejemplo.com',
  direccion: 'Cra 74a #51a-87, Barrio La Soledad, Chapinero',
  barrio: 'La Soledad',
  municipio: 'Bogotá',
  ciudad: 'Bogotá D.C.',
  fecha: '02/10/2026 10:15 AM (hora Bogotá)',
}

function PantallaFelicitaciones() {
  return (
    <div className="screen-content ganador-content anim-in">
      <h2 className="ganador-titulo">¡Felicidades!</h2>
      <p className="ganador-subtitulo">
        Ganaste una botella de Aguardiente Blanco del Valle Fiesta 🎉
      </p>
      <div className="ganador-qr-wrap" title={`Mock Preview QR: ${MOCK_UUID}`}>
        <QRCodeCanvas value={MOCK_UUID} size={64} level="M" includeMargin={false} />
      </div>
      <div className="ganador-checks">
        <label className="ganador-check-wrap" htmlFor="mp-chk1">
          <input type="checkbox" id="mp-chk1" defaultChecked disabled />
          <span className="ganador-check-label">
            <b>He leído y acepto los TÉRMINOS Y CONDICIONES de la promoción</b>
            <div className="ganador-check-detalle">
              Premio 1 botella Fiesta, ganador por orden de llegada, entrega en Bogotá D.C.,
              ILV 1921 se reserva derecho de admisión, mayor de edad 18+, licor no se devuelve.
            </div>
            <span className="ganador-aceptado-timestamp">ⓘ Aceptado 10:14:32 servidor</span>
          </span>
        </label>
        <label className="ganador-check-wrap" htmlFor="mp-chk2">
          <input type="checkbox" id="mp-chk2" defaultChecked disabled />
          <span className="ganador-check-label">
            <b>Autorizo el TRATAMIENTO DE DATOS PERSONALES de acuerdo a la Ley 1581/2012 y política Habeas Data ILV 1921</b>
            <div className="ganador-check-detalle">
              Uso de datos solo para entrega del premio, no se comparten terceros.
            </div>
            <span className="ganador-aceptado-timestamp">ⓘ Aceptado 10:14:35 servidor</span>
          </span>
        </label>
      </div>
      <button type="button" className="btn-primario btn-cta-red ganador-btn-continuar">
        ACEPTAR Y REGISTRARME →
      </button>
    </div>
  )
}

function PantallaRegistro() {
  const campo = (label, id, val, full, placeholder, tipo = 'text') => (
    <div className={`registro-campo${full ? ' full' : ''}`}>
      <label htmlFor={id}>{label} <span className="req">*</span></label>
      <input id={id} type={tipo} defaultValue={val} placeholder={placeholder} readOnly />
      <div className="registro-error" />
    </div>
  )
  return (
    <div className="screen-content ganador-content anim-in">
      <h2 className="ganador-titulo">Completa tus datos</h2>
      <p className="ganador-subtitulo">
        Llena la información para reclamar tu premio. Los campos con <span className="req">*</span> son obligatorios.
      </p>
      <div className="registro-form">
        {campo('Nombres y Apellidos', 'mp-nom', MOCK_REGISTRO.nombres, true, 'Ej: Ana María Gutiérrez')}
        {campo('Celular', 'mp-cel', MOCK_REGISTRO.celular, false, '3001234567', 'tel')}
        {campo('Confirmar Celular', 'mp-cel2', MOCK_REGISTRO.celular, false, 'Repite el celular', 'tel')}
        {campo('Teléfono Fijo (opcional)', 'mp-fij', '', false, '601 123 4567', 'tel')}
        {campo('Correo Electrónico', 'mp-cor', MOCK_REGISTRO.correo, true, 'correo@ejemplo.com', 'email')}
        {campo('Dirección Completa', 'mp-dir', MOCK_REGISTRO.direccion, true, 'Carrera / Calle / # / Interior / Barrio')}
        {campo('Barrio', 'mp-bar', MOCK_REGISTRO.barrio, false, 'Ej: La Soledad')}
        {campo('Municipio', 'mp-mun', MOCK_REGISTRO.municipio, false, 'Ej: Bogotá')}
        {campo('Ciudad', 'mp-cid', MOCK_REGISTRO.ciudad, false, 'Ej: Bogotá D.C.')}
        <div className="registro-campo full" style={{ display: 'flex', alignItems: 'center', gap: 12, color: '#fff', fontSize: '.92rem' }}>
          <label style={{ margin: 0, color: '#fff', fontSize: '.95rem' }}>
            📍 Dirección Bogotá D.C. — modalidad: <b>DOMICILIO (ENTREGA A DOMICILIO BOGOTÁ)</b>
          </label>
        </div>
        <button type="button" className="btn-primario btn-cta-red registro-btn-submit">
          ✅ FINALIZAR Y RECLAMAR PREMIO
        </button>
      </div>
    </div>
  )
}

function PantallaAgradecimiento() {
  return (
    <div className="screen-content ganador-content anim-in">
      <div className="agradecimiento-card">
        <div className="agradecimiento-icon ok">🎉</div>
        <h1>¡FELICITACIONES!</h1>
        <p className="agradecimiento-mensaje">
          Eres el ganador <b>#{MOCK_REGISTRO.posicion}</b> de una <b>Botella Aguardiente Blanco del Valle Fiesta</b>.
          <br />
          {MOCK_REGISTRO.nombres.split(' ')[0]}, tu premio será entregado en <b>{MOCK_REGISTRO.direccion.split(',')[0]}, {MOCK_REGISTRO.ciudad}</b> en los próximos días hábiles.
          <br /><br />
          <b>Celular de contacto:</b> {MOCK_REGISTRO.celular}<br />
          <b>Correo:</b> {MOCK_REGISTRO.correo}<br />
          <b>Fecha registro (Bogotá):</b> {MOCK_REGISTRO.fecha}
        </p>
        <div className="agradecimiento-botones">
          <button type="button" className="btn-primario btn-cta-red">Volver al inicio</button>
        </div>
      </div>
    </div>
  )
}

export default function AdminPreview() {
  const navigate = useNavigate()
  // step: 1 = Felicitaciones (Substeps: -1 = Validando QR mock / 0 = Imagen Botón Pieza / 1 = Checks Términos Fondo Vertical)
  // step 2 = Registro / step 3 = Agradecimiento
  const [step, setStep] = useState(1)
  const [orientation, setOrientation] = useState('auto')

  // Substep para la pantalla FELICITACIONES
  //   -1 = Estado "Validando código QR..." (mock para preview estado inicial con Fondo Vertical)
  //    0 = Solo imagen Pieza (8 segundos AUTO → pasa a políticas/aceptar; NO HAY CLICK)
  //    1 = Checks términos + botón ACEPTAR (con Fondo Vertical.png)
  const [felSubstep, setFelSubstep] = useState(-1)

  // Countdown 8s PIEZA step1 felSubstep=0 (igual que Ganador real pedido HOY)
  // User VERBATIM HOY: "Pieza NO le de click; solo 8 segundos y pase a políticas"
  const [felCountdown, setFelCountdown] = useState(null)

  // Toggle debug: ya no existe el botón invisible (SHA 12a7dd7 SUPERPUESTO por el countdown).
  // Se reutiliza el switch como "Mostrar overlay countdown 8s"; default true.
  const [debugShowBtnArea, setDebugShowBtnArea] = useState(true)

  // Resetear Substep a -1 (Validando mock default) si cambiamos Step a 1
  useEffect(() => {
    if (step === 1) setFelSubstep(-1)
  }, [step])

  // Countdown 8s auto en PIEZA (step 1 felSubstep=0). Cuando llega a 0 → felSubstep=1 (políticas).
  useEffect(() => {
    if (step === 1 && felSubstep === 0) {
      setFelCountdown(8)
      let restantes = 8
      const idInt = setInterval(() => {
        restantes = restantes - 1
        if (restantes <= 0) {
          clearInterval(idInt)
          setFelCountdown(null)
          setFelSubstep(1)
          return
        }
        setFelCountdown(restantes)
      }, 1000)
      return () => clearInterval(idInt)
    } else {
      setFelCountdown(null)
    }
  }, [step, felSubstep])

  // Forzamos TCL o Móvil portrait con Wrapper CSS
  useEffect(() => {
    const el = document.getElementById('preview-device-frame')
    if (!el) return
    if (orientation === 'tcl-landscape') {
      el.style.width = 'min(100%, 1280px)'
      el.style.aspectRatio = '1280 / 800'
      el.style.margin = '0 auto'
      el.style.maxHeight = 'calc(100svh - 90px)'
    } else if (orientation === 'movil-portrait') {
      el.style.width = 'min(420px, 96vw)'
      el.style.aspectRatio = '9 / 19.5'
      el.style.margin = '0 auto'
      el.style.maxHeight = 'calc(100svh - 90px)'
      el.style.borderRadius = 28
      el.style.overflow = 'hidden'
      el.style.border = '3px solid #0f172a'
      el.style.boxShadow = '0 20px 60px rgba(0,0,0,.25)'
    } else {
      el.style.width = '100%'
      el.style.aspectRatio = ''
      el.style.margin = ''
      el.style.maxHeight = ''
      el.style.borderRadius = ''
      el.style.overflow = ''
      el.style.border = ''
      el.style.boxShadow = ''
    }
  }, [orientation])

  const tituloHeaderFrame = () => step === 1 ? '¡FELICIDADES GANASTE!' : step === 2 ? 'Completa tus datos' : '✅ Registro Exitoso'

  // Clase fondo DINÁMICA alineada EXACTA con Ganador.jsx real SHA 12a7dd7+:
  // - felSubstep === -1 (Validando mock) → Fondo Vertical.png
  // - felSubstep === 0 (listo + stepVisual=0) → Pieza Ganadores Vertical.jpg
  // - felSubstep >= 1 (listo + stepVisual=1 / bloqueos) → Fondo Vertical.png
  const claseFondoPreview = (step === 1 && felSubstep === 0)
    ? 'screen-bg ganador-bg'
    : 'screen-bg ganador-bg-fondo-vertical'

  // Clase botón debug: si toggle true agregamos la clase debug-show-btn-area
  const claseBtnStep0 = 'ganador-step0-btn-cta' + (debugShowBtnArea ? ' debug-show-btn-area' : '')

  return (
    <div className="admin-preview-pagina">
      {/* Barra de control preview */}
      <div className="admin-preview-controls">
        <div className="admin-preview-controls-left">
          <button type="button" className="admin-btn sm ghost" onClick={() => navigate('/admin/dashboard')}>← Volver al Panel</button>
          <span className="admin-preview-titulo">👀 Vista previa — Promoción "FIESTA"</span>
          {step === 1 && (
            <span className="admin-preview-subinfo" style={{color:'#475569',fontSize:'.85rem',marginLeft:12}}>
              Substep actual: <b>{felSubstep === -1 ? '⌛ Validando QR (mock estado inicial)' : felSubstep === 0 ? '① Imagen Pieza · countdown 8s auto → políticas (NO hay click)' : '② Fondo Vertical.png + Checks términos + botón ACEPTAR'}</b>
              <span style={{marginLeft:10,display:'inline-flex',gap:6}}>
                {felSubstep > -1 && <button type="button" className="admin-btn xs ghost" onClick={() => setFelSubstep(-1)}>⏮ Volver a Validando</button>}
                {felSubstep === -1 && <button type="button" className="admin-btn xs" onClick={() => setFelSubstep(0)}>⏩ Simular QR OK → Imagen (contador 8s)</button>}
                {felSubstep === 0 && <button type="button" className="admin-btn xs" onClick={() => { setFelCountdown(null); setFelSubstep(1) }}>⏩ Saltar 8s → Términos</button>}
                {felSubstep === 1 && <button type="button" className="admin-btn xs ghost" onClick={() => setFelSubstep(0)}>↩️ Volver a imagen (reinicia countdown)</button>}
              </span>
              <label style={{display:'inline-flex',alignItems:'center',gap:6,marginLeft:14,color: debugShowBtnArea ? '#b45309' : '#64748b', fontWeight: debugShowBtnArea ? 700 : 500, fontSize: '.85rem', cursor: 'pointer'}}>
                <input type="checkbox" style={{width:16,height:16,accentColor:'#facc15'}} checked={debugShowBtnArea} onChange={(e) => setDebugShowBtnArea(e.target.checked)} />
                Mostrar overlay countdown 8s
              </label>
            </span>
          )}
        </div>
        <div className="admin-preview-controls-right">
          <div className="admin-preview-steps">
            <button type="button" className={`admin-btn sm ${step === 1 ? 'primary' : 'ghost'}`} onClick={() => setStep(1)}>① Felicitaciones</button>
            <button type="button" className={`admin-btn sm ${step === 2 ? 'primary' : 'ghost'}`} onClick={() => setStep(2)}>② Registro</button>
            <button type="button" className={`admin-btn sm ${step === 3 ? 'primary' : 'ghost'}`} onClick={() => setStep(3)}>③ Agradecimiento</button>
          </div>
          <div className="admin-preview-orientation">
            <button type="button" className={`admin-btn xs ${orientation === 'auto' ? 'primary' : 'ghost'}`} onClick={() => setOrientation('auto')}>Auto</button>
            <button type="button" className={`admin-btn xs ${orientation === 'tcl-landscape' ? 'primary' : 'ghost'}`} onClick={() => setOrientation('tcl-landscape')}>TCL 10L Landscape 1280×800</button>
            <button type="button" className={`admin-btn xs ${orientation === 'movil-portrait' ? 'primary' : 'ghost'}`} onClick={() => setOrientation('movil-portrait')}>📱 Móvil Vertical</button>
          </div>
        </div>
      </div>

      {/* Frame del dispositivo */}
      <div id="preview-device-frame" className="preview-device-frame">
        <div className="screen ganador-screen">
          <div className={claseFondoPreview} />

          {/* COUNTDOWN 8 SEGUNDOS SÓLO PIEZA step1 felSubstep=0 (igual que Ganador real HOY)
              User VERBATIM: "Pieza NO le de click; solo 8 segundos y pase a políticas"
              Si debugShowBtnArea=false → se oculta el overlay de texto para ver la pieza 100% limpia sin números */}
          {step === 1 && felSubstep === 0 && felCountdown !== null && debugShowBtnArea && (
            <div className="ganador-step0-countdown-wrapper">
              <div className="ganador-step0-countdown-titulo">Continuando en</div>
              <div className="ganador-step0-countdown-numero">
                {felCountdown}
                <span className="ganador-step0-countdown-seg">seg</span>
              </div>
              <div className="ganador-step0-countdown-barra-fondo">
                <div
                  className="ganador-step0-countdown-barra-llena"
                  style={{ width: `${((8 - felCountdown + 1) / 8) * 100}%` }}
                />
              </div>
              <div className="ganador-step0-countdown-leyenda">
                Aceptar políticas y completar registro 👇
              </div>
            </div>
          )}

          {/* HEADER: Se oculta SOLO si step=1 y felSubstep=0 (solo imagen pieza limpia sin nada encima) */}
          {(step !== 1 || felSubstep !== 0) && (
            <div className="screen-header instrucciones-header">
              <div className="header-left" />
              <div className="header-middle">
                <h1 className="header-titulo">
                  {step === 1 && felSubstep === -1 ? 'Validando QR...' : tituloHeaderFrame()}
                </h1>
              </div>
              <div className="header-right" />
            </div>
          )}

          {/* CONTENIDO:
              - step 1 felSubstep -1 → PantallaValidando mock (Fondo Vertical.png + icono 🔍 + mensaje)
              - step 1 felSubstep 0  → NADA (solo imagen pieza 100% limpia, sin header sin contenido)
              - step 1 felSubstep 1  → PantallaFelicitaciones (Fondo Vertical.png)
              - step 2 / 3          → PantallaRegistro / PantallaAgradecimiento */}
          {(step !== 1 || felSubstep !== 0) && (
            step === 1 && felSubstep === -1 ? (
              <div className="screen-content ganador-content anim-in">
                <div className="ganador-bloqueo-icono color-blue">🔍</div>
                <h2 className="ganador-titulo ganador-bloqueo-titulo color-blue">Validando código QR...</h2>
                <p className="ganador-subtitulo ganador-bloqueo-mensaje">
                  Estamos confirmando que tu código QR está listo para reclamar el premio. Espera unos segundos.
                </p>
                <div style={{marginTop:18,display:'inline-flex',alignItems:'center',gap:10,color:'#fff',fontSize:'clamp(.85rem,2svw,1rem)',background:'rgba(255,255,255,.12)',backdropFilter:'blur(6px)',borderRadius:999,padding:'8px 20px',border:'1px solid rgba(255,255,255,.22)'}}>
                  <span className="spinner" style={{width:16,height:16,borderWidth:3}} />
                  Mock: duración ~300 ms en producción real
                </div>
                <div className="ganador-qr-wrap" style={{marginTop:14}} title="Mock Preview QR UUID">
                  <QRCodeCanvas value={MOCK_UUID} size={64} level="M" includeMargin={false} />
                </div>
                <div className="ganador-bloqueo-nota">
                  ⓘ Fondo actual (Validando) = Fondo Vertical.png (user pedido).
                </div>
              </div>
            ) : step === 1 ? (
              <PantallaFelicitaciones />
            ) : step === 2 ? (
              <PantallaRegistro />
            ) : (
              <PantallaAgradecimiento />
            )
          )}
        </div>
      </div>

      {/* Pie admin preview: info del fondo usado */}
      <div className="admin-preview-footer">
        <b>Regla de fondos (Ganador.jsx real):</b>&nbsp;
        <b style={{color:'#0ea5e9'}}>Validando QR</b> → <code>Fondo Vertical.png</code> &nbsp;|&nbsp;
        <b style={{color:'#7c3aed'}}>Listo + Click botón AÚN NO DADO</b> → <code>Pieza Ganadores Vertical.jpg</code> (100% limpia) &nbsp;|&nbsp;
        <b style={{color:'#16a34a'}}>Listo + Click botón DADO / Bloqueos</b> → <code>Fondo Vertical.png</code> (checks términos + reg + agradec + pantallas rojas).
        &nbsp; Al terminar registro → <b>QR INHABILITADO AUTOMÁTICO (Capa 3 rowcount atomic)</b>.
      </div>
    </div>
  )
}
