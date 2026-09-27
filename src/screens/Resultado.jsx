import { useEffect, useState, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { QRCodeCanvas } from 'qrcode.react'
import { useApp } from '../context/AppContext.jsx'
import { shareImageDirect } from '../services/imageProcessor.js'
import { StepperPaso } from '../components/BrandComponents.jsx'
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

  useEffect(() => {
    if (!fotoProcesada || !fotoUrlDescarga) {
      setTimeout(() => navigate('/escenario'), 50)
    }
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

  const qrSizePx = 200

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
    navigate('/camara')
  }

  const handleTerminar = () => {
    navigate('/listo')
  }

  return (
    <div className="screen resultado-screen">
      <div className="screen-bg resultado-bg bg-pantone-2728" />

      <div className="screen-header resultado-header">
        <div className="header-left">
          <button className="btn-back btn-ghost gh" onClick={() => navigate('/escenario')} style={{ padding: '8px 18px', fontSize: 16, minHeight: 44 }}>
            ‹ Atrás
          </button>
        </div>
        <div className="header-middle">
          <div className="resultado-titulo-wrap">
            <h2 className="resultado-titulo">Tu foto está lista</h2>
          </div>
        </div>
        <div className="header-right">
          <StepperPaso pasoActual={5} />
        </div>
      </div>

      <div className="screen-content resultado-content anim-in">
        <div className="res">
          <div className="l">
            <div className="fr foto-final-frame viewport-marco foto-preview-frame">
              <img src={fotoProcesada} alt="Foto final Aguardiente Blanco Fiesta" className="res-img" />
              <div className="lb" aria-hidden></div>
            </div>
          </div>
          <div className="r">
            <b className="qr-leyenda-titulo" style={{ fontSize: '24px', fontWeight: 800, color: '#fff', margin: 0 }}>
              Escanea y descarga
            </b>

            <div className="qr" aria-label="Código QR para descargar la foto">
              <QRCodeCanvas
                value={qrValue}
                size={qrSizePx}
                level="H"
                includeMargin={false}
                bgColor="#FFFFFF"
                fgColor="#002a7a"
                className="qr-code-canvas"
              />
            </div>

            <div className="row res-botones">
              <button className="btn-primario btn-cta-red cta" onClick={handleTerminar} autoFocus={true}>
                TERMINAR
              </button>
              <button className="btn-secundario btn-ghost gh" onClick={handleRepetir}>
                Repetir
              </button>
            </div>

            <div className="row res-botones-2" style={{ gap: 12, marginTop: 4 }}>
              <button className="btn-secundario btn-ghost gh" onClick={handleDescargar} style={{ fontSize: 16, padding: '10px 20px' }}>
                💾 Descargar
              </button>
              <button className="btn-secundario btn-ghost gh" onClick={handleCompartir} style={{ fontSize: 16, padding: '10px 20px' }}>
                🔁 Compartir
              </button>
            </div>

            {mostrarMensaje && (
              <div className="toast-exito" role="status" style={{ marginTop: 6 }}>
                {mostrarMensaje}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
