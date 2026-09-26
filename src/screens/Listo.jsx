import { useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { useApp } from '../context/AppContext.jsx'
import { LegalDisclaimer } from '../components/BrandComponents.jsx'
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
        {Array.from({ length: 18 }).map((_, i) => (
          <span
            key={i}
            className="particle pt"
            style={{
              left: `${(i * 5.5) % 100}%`,
              top: `${(i * 11.3) % 100}%`,
              animationDelay: `${(i % 6) * 0.6}s`,
            }}
          />
        ))}
      </div>

      <div className="screen-content listo-content">
        <div className="listo-header anim-in">
          <img
            src="/assets/logo-oficial.png"
            alt="Aguardiente Blanco del Valle"
            className="logo-oficial-img"
          />
        </div>

        <div className="listo-main">
          <div className="listo-hero anim-in" style={{ animationDelay: '0.1s' }}>
            <div className="ok-circle" aria-hidden="true">
              <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                <path d="M4 12.5L9.5 18L20 7" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round"/>
              </svg>
            </div>

            <h1 className="listo-titulo">
              ¡Gracias por participar!
            </h1>
            <p className="listo-sub">
              Tu foto ya está en tu celular.
            </p>
          </div>
        </div>

        <div className="listo-footer anim-in" style={{ animationDelay: '0.3s' }}>
          <button
            className="btn-primario btn-cta-red btn-nueva-foto"
            onClick={() => { reiniciarFlujo(); navigate('/') }}
            autoFocus
          >
            VOLVER A EMPEZAR
          </button>
        </div>
      </div>
      <LegalDisclaimer variant="footer-sticky" />
    </div>
  )
}
