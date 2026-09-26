import { useNavigate } from 'react-router-dom'
import { LegalDisclaimer, LogoHeaderStack, StepperPaso } from '../components/BrandComponents.jsx'
import '../styles/instrucciones.css'

const PASOS = [
  {
    num: 1,
    icono: '📸',
    titulo: 'Ubícate',
    detalle: 'Colócate frente a la cámara en el área marcada',
    color: '#d4a017',
  },
  {
    num: 2,
    icono: '✨',
    titulo: 'Sonríe',
    detalle: 'Presiona el botón y tómate la foto',
    color: '#d4a017',
  },
  {
    num: 3,
    icono: '🌆',
    titulo: 'Elige tu Cali',
    detalle: 'Selecciona uno de los 3 escenarios emblemáticos',
    color: '#d4a017',
  },
  {
    num: 4,
    icono: '📱',
    titulo: 'Llévatela',
    detalle: 'Escanea el QR y descarga tu foto en segundos',
    color: '#d4a017',
  },
]

export default function Instrucciones() {
  const navigate = useNavigate()

  return (
    <div className="screen instrucciones-screen">
      <div className="screen-bg instrucciones-bg bg-pantone-2728" />

      <div className="particles">
        {Array.from({ length: 14 }).map((_, i) => (
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

      <div className="screen-content instrucciones-content">
        <div className="instrucciones-header fade-in">
          <LogoHeaderStack showFiesta showILV />
          <StepperPaso pasoActual={2} />
        </div>

        <div className="instrucciones-titulo-wrap slide-up">
          <div className="titulo-eyebrow">
            <span className="titulo-icono">🎯</span>
            <span>SIGUE ESTOS PASOS</span>
          </div>
          <h2 className="instrucciones-titulo">
            Sigue estos pasos y <span className="destacado-dorado">vive la experiencia</span>
          </h2>
          <p className="instrucciones-sub">
            En menos de 60 segundos tendrás tu foto lista para compartir
          </p>
        </div>

        <div className="pasos-grid">
          {PASOS.map((paso, i) => (
            <div
              key={paso.num}
              className={`paso-card slide-up ${paso.num === 5 ? 'paso-destacado' : ''}`}
              style={{ animationDelay: `${0.15 + i * 0.08}s` }}
            >
              <div className="paso-numero" style={{ background: paso.color }}>
                {paso.num}
              </div>
              <div className="paso-cuerpo">
                <div className="paso-icono" aria-hidden>{paso.icono}</div>
                <h3 className="paso-titulo">{paso.titulo}</h3>
                <p className="paso-detalle">{paso.detalle}</p>
              </div>
              {i < PASOS.length - 1 && <div className="paso-conector" aria-hidden />}
            </div>
          ))}
        </div>

        <div className="instrucciones-footer">
          <div className="premio-box fade-in" style={{ animationDelay: '0.7s' }}>
            <span className="premio-icono">🎁</span>
            <div className="premio-texto">
              <strong>PREMIO SEMANAL:</strong> 10 botellas de Aguardiente Blanco del Valle para la foto con más likes en Instagram
            </div>
            <span className="premio-tag">@aguardientedelvalle</span>
          </div>
          <button
            className="btn-primario btn-listo btn-cta-red"
            onClick={() => navigate('/camara')}
            autoFocus
          >
            ¡LISTO! <span className="btn-flecha">›</span>
          </button>
        </div>
      </div>
      <LegalDisclaimer variant="footer-sticky" />
    </div>
  )
}
