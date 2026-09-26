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
      const resultado = await processFullPipeline(fotoCapturada, seleccionado)

      if (cancelado) return

      setFotoProcesada(resultado.composed)
      setFotoUrlDescarga({
        type: resultado.type,
        url: resultado.url,
        localBlob: resultado.localBlob,
        id: resultado.id,
      })

      limpiarTimeout()
      setTimeout(() => navigate('/resultado'), 380)
    } catch (error) {
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

      <div className="screen-header seleccion-header">
        <div className="header-left">
          <button className="btn-back btn-ghost gh" onClick={() => navigate('/camara')} style={{ padding: '8px 18px', fontSize: 16, minHeight: 44 }}>
            ‹ Atrás
          </button>
        </div>
        <div className="header-middle">
          <div className="seleccion-titulo-wrap">
            <h2 className="seleccion-titulo">Elige tu escenario</h2>
          </div>
        </div>
        <div className="header-right">
          <StepperPaso pasoActual={4} />
        </div>
      </div>

      <div className="screen-content seleccion-content anim-in">
        <div className="esc">
          <div className="pv">
            <div className="fr foto-preview-frame viewport-marco">
              {seleccionado ? (
                <>
                  <img
                    src={seleccionado.backgroundImg || fotoCapturada}
                    alt={seleccionado.nombre}
                    className="fr-bg"
                    onError={(e) => { e.currentTarget.style.display = 'none' }}
                  />
                  <img
                    src={fotoCapturada}
                    alt="Tu foto"
                    className="fr-fg"
                    style={{ opacity: 0.9 }}
                  />
                </>
              ) : (
                <img src={fotoCapturada} alt="Tu foto" className="fr-fg fr-fg-full" />
              )}
              {seleccionado?.botellaImg && (
                <img
                  src={seleccionado.botellaImg}
                  alt={`Botella ${seleccionado.botellaNombre || ''}`}
                  className="fr-botella"
                />
              )}
            </div>
          </div>

          <div className="opts" id="opts">
            {ESCENARIOS.map((esc, i) => {
              const isSel = seleccionado?.id === esc.id
              return (
                <button
                  key={esc.id}
                  className={`op ${isSel ? 'selected' : ''}`}
                  aria-pressed={isSel}
                  onClick={() => handleSeleccionar(esc)}
                  style={{ animationDelay: `${0.1 + i * 0.08}s` }}
                >
                  <div
                    className="sw"
                    style={{
                      background: esc.backgroundImg
                        ? `url(${esc.backgroundImg}) center/cover no-repeat`
                        : (esc.gradiente || 'linear-gradient(135deg,#0047BA,#002a7a)'),
                    }}
                    aria-hidden
                  ></div>
                  <div className="op-info">
                    <b>{esc.nombre}</b>
                    <small>{esc.descripcion}</small>
                  </div>
                </button>
              )
            })}
          </div>
        </div>

        <div className="row seleccion-row" style={{ marginTop: 14 }}>
          <button
            className="btn-primario btn-cta-red cta"
            id="mk-btn"
            onClick={handleContinuar}
            disabled={!seleccionado || procesando}
            autoFocus={!!seleccionado}
          >
            {procesando ? 'Creando tu foto…' : 'CREAR MI FOTO'}
          </button>
        </div>

        <div className={`ov ${procesando && !errorProcesamiento ? 'on' : ''}`}>
          <i aria-hidden></i>
          <span>Creando tu foto…</span>
        </div>
      </div>

      {errorProcesamiento && (
        <div className="ov on pmv2-error-wrap">
          <div className="pmv2-error-card">
            <span className="pmv2-error-icono" aria-hidden>⚠️</span>
            <h3 className="pmv2-titulo-error">No pudimos crear tu foto</h3>
            <p className="pmv2-error-texto">{errorProcesamiento}</p>
            <div className="row error-acciones">
              <button className="btn-primario btn-cta-red cta" onClick={handleContinuar} autoFocus>
                ↻ REINTENTAR
              </button>
              <button className="btn-secundario btn-ghost gh" onClick={() => setErrorProcesamiento(null)}>
                Volver
              </button>
            </div>
          </div>
        </div>
      )}

      <LegalDisclaimer variant="footer-sticky" />
    </div>
  )
}
