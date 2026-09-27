import { useEffect, useRef } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import { useApp } from '../context/AppContext.jsx'
import { StepperPaso } from '../components/BrandComponents.jsx'
import '../styles/confirmarVistaPrevia.css'

/**
 * PANTALLA NUEVA: VISTA PREVIA CONFIRMACIÓN (ANTES DE GENERAR QR).
 * Flujo RÁPIDO: no volvemos a reprocesar la foto NUNCA.
 *   - Botón 1: ✅ SÍ, ME GUSTA / GENERAR QR → navega /resultado (mismo fotoId, mismo composed, NO reprocesa)
 *   - Botón 2: ❌ NO, CAMBIAR FONDO → navega /escenario (MISMA fotoCapturada IA cutout, NO volvemos a cámara, no repite /remove-bg)
 */
export default function ConfirmarVistaPrevia() {
  const navigate = useNavigate()
  const location = useLocation()
  const { fotoCapturada, fotoProcesada, fotoUrlDescarga } = useApp()
  const mountedRef = useRef(false)

  // Si llegamos sin fotoProcesada (ruta directa sin pasar por seleccion), volver a /escenario.
  useEffect(() => {
    if (!mountedRef.current) {
      mountedRef.current = true
      if (!fotoProcesada && !fotoUrlDescarga?.url) {
        setTimeout(() => navigate('/escenario', { replace: true }), 150)
      }
    }
  }, [fotoProcesada, fotoUrlDescarga, navigate])

  // Precalentar imagen final en el cache del browser para que Resultado la cargue INSTANTÁNEA
  useEffect(() => {
    if (fotoProcesada) {
      const img = new Image()
      img.decoding = 'async'
      img.src = fotoProcesada
    }
    if (fotoUrlDescarga?.url) {
      const img2 = new Image()
      img2.decoding = 'async'
      img2.src = fotoUrlDescarga.url
    }
  }, [fotoProcesada, fotoUrlDescarga])

  if (!fotoCapturada) {
    setTimeout(() => navigate('/camara'), 60)
    return null
  }

  const handleConfirmar = () => {
    navigate('/resultado')
  }

  const handleCambiarFondo = () => {
    // VOLVEMOS AL MENÚ DE SELECCIÓN — MANTENEMOS fotoCapturada (IA cutout YA HECHO, no repetimos /remove-bg)
    navigate('/escenario', { replace: true })
  }

  return (
    <div className="screen preview-screen">
      <div className="screen-bg preview-bg bg-pantone-2728" />

      <div className="screen-header preview-header">
        <div className="header-left">
          <button className="btn-back btn-ghost gh" onClick={handleCambiarFondo} style={{ padding: '8px 18px', fontSize: 16, minHeight: 44 }}>
            ‹ Atrás
          </button>
        </div>
        <div className="header-middle">
          <div className="preview-titulo-wrap">
            <h2 className="preview-titulo">¿Te gusta cómo quedó?</h2>
          </div>
        </div>
        <div className="header-right">
          <StepperPaso pasoActual={5} />
        </div>
      </div>

      <div className="screen-content preview-content anim-in">
        <div className="preview-main">
          {/* FOTO FINAL 16:9 GRANDE, igual que Resultado */}
          <div className="preview-foto-wrap">
            <div className="preview-foto foto-final-frame">
              {fotoProcesada && (
                <img
                  src={fotoProcesada}
                  alt="Vista previa de tu foto final"
                  className="preview-foto-img"
                  loading="eager"
                  decoding="async"
                />
              )}
            </div>
          </div>

          {/* COLUMNA DERECHA: PREGUNTA + 2 BOTONES GRANDES */}
          <div className="preview-acciones">
            <div className="preview-pregunta">
              <p className="preview-pregunta-titulo">Así se verá tu foto final</p>
              <p className="preview-pregunta-sub">Si todo está bien, generamos tu código QR para que la descargues.</p>
            </div>

            <div className="preview-botones">
              <button
                className="btn-primario btn-cta-red cta btn-preview-confirmar"
                onClick={handleConfirmar}
                autoFocus
              >
                ✅ SÍ, GENERAR QR
              </button>
              <button
                className="btn-secundario btn-ghost gh btn-preview-cambiar"
                onClick={handleCambiarFondo}
              >
                🔁 NO, CAMBIAR FONDO
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
