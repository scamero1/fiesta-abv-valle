import { useEffect, useState, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { QRCodeCanvas } from 'qrcode.react'
import { useApp } from '../context/AppContext.jsx'
import { shareImageDirect } from '../services/imageProcessor.js'
import { LegalDisclaimer, StepperPaso } from '../components/BrandComponents.jsx'
import '../styles/resultado.css'

export default function Resultado() {
  const navigate = useNavigate()
  const {
    fotoProcesada,
    fotoUrlDescarga,
    escenarioSeleccionado,
    reiniciarFlujo,
  } = useApp()
  const [mostrarMensaje, setMostrarMensaje] = useState('')
  const autoTimerRef = useRef(null)

  useEffect(() => {
    if (!fotoProcesada || !fotoUrlDescarga) {
      setTimeout(() => navigate('/escenario'), 50)
      return
    }
    autoTimerRef.current = setTimeout(() => {
      navigate('/listo')
    }, 90000)
    return () => clearTimeout(autoTimerRef.current)
  }, [fotoProcesada, fotoUrlDescarga, navigate])

  const downloadObj = fotoUrlDescarga && typeof fotoUrlDescarga === 'object'
    ? fotoUrlDescarga
    : { type: fotoUrlDescarga?.startsWith?.('blob:') ? 'blob' : 'server', url: fotoUrlDescarga, localBlob: fotoUrlDescarga }

  if (!fotoProcesada || !fotoUrlDescarga) return null

  const fotoId = downloadObj.id || `local-${Date.now().toString(36)}`
  const qrBase = (() => {
    try {
      const urlRailway = import.meta.env.VITE_PUBLIC_URL || import.meta.env.VITE_RAILWAY_URL || ''
      if (urlRailway && /^https?:\/\//i.test(urlRailway)) return urlRailway.replace(/\/+$/, '')
    } catch {}
    return location.origin
  })()
  const qrValue = `${qrBase}/foto/${fotoId}`

  const qrSizePx = Math.max(340, Math.floor((typeof window !== 'undefined' ? window.innerWidth : 1200) * 0.3))

  const handleDescargar = () => {
    const a = document.createElement('a')
    a.href = fotoProcesada
    a.download = `aguardiente-blanco-fiesta-${Date.now()}.jpg`
    document.body.appendChild(a)
    a.click()
    setTimeout(() => a.remove(), 200)
    setMostrarMensaje('✓ Foto descargada')
    setTimeout(() => setMostrarMensaje(''), 2200)
  }

  const handleCompartir = async () => {
    try {
      const r = await shareImageDirect(fotoProcesada, `Cali-${escenarioSeleccionado?.id || 'fiesta'}-${Date.now()}.jpg`)
      if (r.ok && r.method === 'web-share') {
        setMostrarMensaje('✓ Compartiendo…')
      } else if (r.ok && r.method === 'download') {
        setMostrarMensaje('✓ Lista para compartir')
      }
    } catch {
      handleDescargar()
    }
    setTimeout(() => setMostrarMensaje(''), 2800)
  }

  const handleRepetir = () => {
    clearTimeout(autoTimerRef.current)
    navigate('/camara')
  }

  const handleTerminar = () => {
    clearTimeout(autoTimerRef.current)
    navigate('/listo')
  }

  return (
    <div className="screen resultado-screen">
      <div className="screen-bg resultado-bg bg-pantone-2728" />

      <div className="particles">
        {Array.from({ length: 18 }).map((_, i) => (
          <span
            key={i}
            className="particle"
            style={{
              left: `${Math.random() * 100}%`,
              top: `${Math.random() * 100}%`,
              animationDelay: `${Math.random() * 8}s`,
              background: i % 2 === 0 ? '#d4a017' : '#E4002B',
              boxShadow: i % 2 === 0 ? '0 0 10px #d4a017' : '0 0 10px #E4002B',
            }}
          />
        ))}
      </div>

      <div className="screen-content resultado-content">
        <div className="resultado-header fade-in">
          <button className="btn-back" onClick={() => navigate('/escenario')}>
            ‹ Atrás
          </button>
          <div className="resultado-titulo-wrap">
            <h2 className="resultado-titulo">
              ¡Tu foto está <span className="destacado-dorado">lista!</span>
            </h2>
            <p className="resultado-sub">
              Escanea el QR o descárgala directo
            </p>
          </div>
          <StepperPaso pasoActual={5} />
        </div>

        <div className="resultado-body panel-layout">
          <div className="foto-final-col work-area slide-up">
            <div className="foto-final-card">
              <div className="foto-final-frame">
                <img src={fotoProcesada} alt="Foto final Aguardiente Blanco Fiesta" className="foto-final-img" />
              </div>
              <div className="foto-final-etiquetas">
                <span className="ef-escenario">📍 {escenarioSeleccionado?.nombre}</span>
                <span className="ef-fecha">{new Date().toLocaleDateString('es-CO', { day: 'numeric', month: 'short' })}</span>
              </div>
            </div>
            {mostrarMensaje && (
              <div className="toast-exito">{mostrarMensaje}</div>
            )}
          </div>

          <div className="qr-col side-area fade-in" style={{ animationDelay: '0.2s' }}>
            <div className="qr-card">
              <div className="qr-wrap">
                <QRCodeCanvas
                  value={qrValue}
                  size={qrSizePx}
                  level="H"
                  includeMargin={true}
                  bgColor="#FFFFFF"
                  fgColor="#002a7a"
                  imageSettings={{
                    src: '/assets/logo-oficial.png',
                    height: 48,
                    width: 48,
                    excavate: true,
                  }}
                  className="qr-code"
                />
              </div>
              <p className="qr-leyenda">Apunta la cámara de tu celular al código</p>
            </div>

            <div className="resultado-botones">
              <button className="btn-primario btn-cta-red btn-descargar-primario" onClick={handleDescargar} autoFocus>
                💾 DESCARGAR
              </button>
              <button className="btn-secundario btn-compartir-sec" onClick={handleCompartir}>
                🔁 Compartir
              </button>
              <div className="btn-fila-secundaria">
                <button className="btn-secundario btn-chico" onClick={handleRepetir}>
                  ↻ Repetir foto
                </button>
                <button className="btn-secundario btn-chico" onClick={handleTerminar}>
                  Terminar
                </button>
              </div>
            </div>

            <div className="premio-recordar">
              <span className="pr-icono">🏆</span>
              <div>
                <strong>¡Gana 10 botellas semanales!</strong>
                <p>Comparte tu foto y etiqueta @aguardientedelvalle.</p>
              </div>
            </div>
          </div>
        </div>
      </div>

      <LegalDisclaimer variant="footer-sticky" />
    </div>
  )
}
