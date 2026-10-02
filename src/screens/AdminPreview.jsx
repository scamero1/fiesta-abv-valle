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
        CONTINUAR AL FORMULARIO →
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
  const [step, setStep] = useState(1)
  const [orientation, setOrientation] = useState('auto')

  // Forzamos landscape TCL 1280x800 o Portrait móvil 412x915 con un Wrapper CSS
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

  return (
    <div className="admin-preview-pagina">
      {/* Barra de control preview */}
      <div className="admin-preview-controls">
        <div className="admin-preview-controls-left">
          <button type="button" className="admin-btn sm ghost" onClick={() => navigate('/admin/dashboard')}>← Volver al Panel</button>
          <span className="admin-preview-titulo">👀 Vista previa — Promoción "FIESTA"</span>
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
          <div className="screen-bg ganador-bg" />
          <div className="screen-header instrucciones-header">
            <div className="header-left" />
            <div className="header-middle">
              <h1 className="header-titulo">
                {step === 1 ? '¡FELICIDADES GANASTE!' : step === 2 ? 'Completa tus datos' : '✅ Registro Exitoso'}
              </h1>
            </div>
            <div className="header-right" />
          </div>
          {step === 1 ? <PantallaFelicitaciones /> : step === 2 ? <PantallaRegistro /> : <PantallaAgradecimiento />}
        </div>
      </div>

      {/* Pie admin preview: info del fondo usado */}
      <div className="admin-preview-footer">
        Fondo actual: <b>Pieza Ganadores Vertical.jpg</b> (oficial del evento — archivo <code>src/assets/pieza-ganadores-vertical.jpg</code>).
        Responsive portrait móvil: TODO CENTRADO.
      </div>
    </div>
  )
}
