import { useState, useRef, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { useApp } from '../context/AppContext.jsx'
import { ESCENARIOS } from '../data/escenarios.js'
import { processFullPipeline } from '../services/imageProcessor.js'
import { LegalDisclaimer, StepperPaso } from '../components/BrandComponents.jsx'
import '../styles/seleccionEscenario.css'

const ERROR_MSG_SIMPLE = 'No pudimos crear tu foto: Revisa que la tableta tenga conexión a la red del evento.'

export default function SeleccionEscenario() {
  const navigate = useNavigate()
  const {
    fotoCapturada,
    setEscenarioSeleccionado,
    setFotoProcesada,
    setFotoUrlDescarga,
    setLoadingProcesamiento,
  } = useApp()
  const [seleccionado, setSeleccionado] = useState(null)
  const [procesando, setProcesando] = useState(false)
  const [progreso, setProgreso] = useState(0)
  const [etapa, setEtapa] = useState('')
  const [errorProcesamiento, setErrorProcesamiento] = useState(null)
  const timeoutRef = useRef(null)

  if (!fotoCapturada) {
    setTimeout(() => navigate('/camara'), 100)
    return null
  }

  const handleSeleccionar = (escenario) => {
    if (procesando) return
    setSeleccionado(escenario)
  }

  const limpiarTimeout = () => {
    if (timeoutRef.current) {
      clearTimeout(timeoutRef.current)
      timeoutRef.current = null
    }
  }

  useEffect(() => {
    return () => limpiarTimeout()
  }, [])

  const handleContinuar = async () => {
    if (!seleccionado) return
    setErrorProcesamiento(null)
    setProcesando(true)
    setLoadingProcesamiento(true)
    setEscenarioSeleccionado(seleccionado)
    limpiarTimeout()

    let cancelado = false

    timeoutRef.current = setTimeout(() => {
      if (cancelado) return
      setErrorProcesamiento(ERROR_MSG_SIMPLE)
      setProcesando(false)
      setLoadingProcesamiento(false)
    }, 30000)

    try {
      const processUrl = (import.meta.env.VITE_PROCESS_URL || import.meta.env.VITE_RAILWAY_URL || '').trim()
      const usaPipelineServidor = !!processUrl
      if (usaPipelineServidor) {
        setEtapa('Creando tu foto en IA...')
        setProgreso(12)
        await new Promise((r) => setTimeout(r, 300))
      } else {
        setEtapa('Componiendo tu escena de Cali...')
        setProgreso(20)
        await new Promise((r) => setTimeout(r, 400))
      }

      const resultado = await processFullPipeline(fotoCapturada, seleccionado)

      if (cancelado) return
      setProgreso(85)
      await new Promise((r) => setTimeout(r, 280))

      setFotoProcesada(resultado.composed)
      setFotoUrlDescarga({
        type: resultado.type,
        url: resultado.url,
        localBlob: resultado.localBlob,
        id: resultado.id,
      })
      setProgreso(100)

      limpiarTimeout()
      setTimeout(() => navigate('/resultado'), 380)
    } catch (error) {
      console.error('Error procesamiento:', error)
      if (cancelado) return
      limpiarTimeout()
      setErrorProcesamiento(ERROR_MSG_SIMPLE)
      setProcesando(false)
      setLoadingProcesamiento(false)
    } finally {
      cancelado = true
    }
  }

  return (
    <div className="screen seleccion-screen">
      <div className="screen-bg seleccion-bg bg-pantone-2728" />

      <div className="particles">
        {Array.from({ length: 12 }).map((_, i) => (
          <span
            key={i}
            className="particle"
            style={{
              left: `${Math.random() * 100}%`,
              top: `${Math.random() * 100}%`,
              animationDelay: `${Math.random() * 8}s`,
            }}
          />
        ))}
      </div>

      <div className="screen-content seleccion-content">
        <div className="seleccion-header fade-in">
          <button className="btn-back" onClick={() => navigate('/camara')}>
            ‹ Atrás
          </button>
          <div className="seleccion-titulo-wrap">
            <span className="seleccion-eyebrow">PASO 4 · ELIGE TU CALI</span>
            <h2 className="seleccion-titulo">
              ¿En qué <span className="destacado-dorado">Cali</span> quieres estar?
            </h2>
            <p className="seleccion-sub">
              Elige tu escenario y deja que la IA te lleve allí ✨
            </p>
          </div>
          <StepperPaso pasoActual={4} />
        </div>

        <div className="seleccion-body panel-layout">
          <div className="foto-preview-col work-area">
            <div className="foto-preview-card fade-in">
              <div className="foto-preview-head">
                <span className="fp-tag">Tu foto</span>
              </div>
              <div className="foto-preview-frame">
                <img src={fotoCapturada} alt="Tu foto capturada" className="fp-img" />
              </div>
            </div>
          </div>

          <div className="escenarios-col side-area">
            <div className="escenarios-stack">
              {ESCENARIOS.map((esc, i) => {
                const isSelected = seleccionado?.id === esc.id
                const hasBg = !!esc.backgroundImg
                return (
                  <div
                    key={esc.id}
                    className={`escenario-card ${isSelected ? 'seleccionado' : ''}`}
                    role="button"
                    tabIndex={0}
                    aria-pressed={isSelected}
                    style={{
                      animationDelay: `${0.15 + i * 0.12}s`,
                    }}
                    onClick={() => handleSeleccionar(esc)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' || e.key === ' ') {
                        e.preventDefault()
                        handleSeleccionar(esc)
                      }
                    }}
                  >
                    <div
                      className="esc-visual"
                      style={{
                        background: hasBg ? `url(${esc.backgroundImg}) center/cover no-repeat` : esc.gradiente,
                      }}
                    >
                      <div className="esc-icono-grande" aria-hidden>{esc.icono}</div>
                      <div className="esc-id-box">
                        <span className="esc-num">{String(i + 1).padStart(2, '0')}</span>
                      </div>
                      {esc.botellaImg && (
                        <img
                          src={esc.botellaImg}
                          alt={`Aguardiente ${esc.botellaNombre}`}
                          className="esc-mini-botella"
                        />
                      )}
                      {isSelected && (
                        <div className="esc-check">
                          <span>✓</span>
                        </div>
                      )}
                    </div>
                    <div className="esc-info">
                      <h3 className="esc-nombre">{esc.nombre}</h3>
                      <p className="esc-descripcion">{esc.descripcion}</p>
                      <div className="esc-tags">
                        {esc.tags.map((t) => (
                          <span key={t} className="esc-tag">{t}</span>
                        ))}
                      </div>
                    </div>
                  </div>
                )
              })}
            </div>
          </div>
        </div>

        <div className="seleccion-footer">
          <div className="seleccion-leyenda">
            <span className="leyenda-icono">⚡</span>
            IA en tiempo real · Resultado en menos de 10 segundos
          </div>
          <button
            className="btn-primario btn-cta-red"
            onClick={handleContinuar}
            disabled={!seleccionado || procesando}
            autoFocus={!!seleccionado}
          >
            {procesando ? (
              <>Creando tu foto... <span className="spinner-mini" /></>
            ) : (
              <>CREAR MI FOTO <span className="btn-flecha">›</span></>
            )}
          </button>
        </div>
      </div>

      {(procesando || errorProcesamiento) && (
        <div className="procesamiento-overlay">
          {errorProcesamiento ? (
            <div className="procesamiento-modal pm-v2 pm-v2-error">
              <div className="pmv2-error-icono" aria-hidden>⚠️</div>
              <h3 className="pmv2-titulo pmv2-titulo-error">
                No pudimos crear tu foto
              </h3>
              <p className="pmv2-error-texto-simple">{errorProcesamiento}</p>
              <div className="pmv2-error-acciones">
                <button
                  className="btn-primario btn-cta-red"
                  onClick={handleContinuar}
                  autoFocus
                >
                  ↻ REINTENTAR
                </button>
                <button
                  className="btn-secundario"
                  onClick={() => setErrorProcesamiento(null)}
                >
                  Volver a escenarios
                </button>
              </div>
            </div>
          ) : (
            <div className="procesamiento-modal pm-v2 pm-v2-loading">
              <div className="pmv2-spinner-wrap">
                <div className="pmv2-ring" />
                <div className="pmv2-ring pmv2-ring-2" />
                <div className="pmv2-centro">
                  <span className="pmv2-centro-porc">{progreso}</span>
                </div>
              </div>
              <h3 className="pmv2-titulo pmv2-titulo-loading">
                Creando tu foto en <span className="destacado-dorado">{seleccionado?.nombre}</span>…
              </h3>
              <div className="pmv2-barra-wrap">
                <div className="pmv2-barra" style={{ width: `${Math.min(100, progreso)}%` }} />
              </div>
            </div>
          )}
        </div>
      )}
      <LegalDisclaimer variant="footer-sticky" />
    </div>
  )
}
