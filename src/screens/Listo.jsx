import { useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { useApp } from '../context/AppContext.jsx'
import { LegalDisclaimer, LogoHeaderStack } from '../components/BrandComponents.jsx'
import '../styles/listo.css'

export default function Listo() {
  const navigate = useNavigate()
  const { reiniciarFlujo } = useApp()

  useEffect(() => {
    const t = setTimeout(() => {
      reiniciarFlujo()
      navigate('/')
    }, 60000)
    return () => clearTimeout(t)
  }, [navigate, reiniciarFlujo])

  return (
    <div className="screen listo-screen">
      <div className="screen-bg listo-bg bg-pantone-2728" />

      <div className="particles">
        {Array.from({ length: 12 }).map((_, i) => (
          <span
            key={i}
            className="particle"
            style={{
              left: `${Math.random() * 100}%`,
              top: `${Math.random() * 100}%`,
              animationDelay: `${Math.random() * 6}s`,
              background: ['#d4a017', '#E4002B', '#0047BA', '#FFFFFF'][i % 4],
            }}
          />
        ))}
      </div>

      <div className="screen-content listo-content">
        <div className="listo-header fade-in">
          <LogoHeaderStack showFiesta showILV />
        </div>

        <div className="listo-main">
          <div className="listo-mensaje-col slide-up">
            <div className="check-grande" aria-hidden="true">
              <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                <path d="M4 12.5L9.5 18L20 7" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round"/>
              </svg>
              <div className="check-ondas">
                <span />
                <span />
              </div>
            </div>

            <h1 className="listo-titulo">
              ¡Gracias por participar!
            </h1>
            <p className="listo-sub">
              ¡Comparte tu foto y etiquétanos para ganar <strong className="destacado-dorado">10 botellas semanales</strong>!
            </p>

            <div className="premio-box">
              <span className="pb-icon">🥂</span>
              <div className="pb-textos">
                <div className="pb-tit">Premio semanal</div>
                <div className="pb-desc">Sube tu foto a Instagram con <b className="hash-main">#ElSaborQueNosUne</b> y menciona <b>@aguardientedelvalle</b></div>
              </div>
            </div>
          </div>
        </div>

        <div className="listo-footer slide-up" style={{ animationDelay: '0.4s' }}>
          <button
            className="btn-primario btn-nueva-foto btn-cta-red"
            onClick={() => { reiniciarFlujo(); navigate('/') }}
            autoFocus
          >
            VOLVER A EMPEZAR <span className="btn-flecha">›</span>
          </button>
        </div>
      </div>
      <LegalDisclaimer variant="footer-sticky" />
    </div>
  )
}
