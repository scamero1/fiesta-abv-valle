import { useNavigate } from 'react-router-dom'
import { useApp } from '../context/AppContext.jsx'
import { SloganVaConTodo } from '../components/BrandComponents.jsx'
import '../styles/bienvenida.css'

const BOTELLAS = [
  {
    id: 'sin-azucar',
    img: '/assets/botella-sin-azucar.png',
    posicion: 'side',
  },
  {
    id: 'fiesta',
    img: '/assets/botella-fiesta-azul.png',
    posicion: 'mid',
  },
  {
    id: 'night',
    img: '/assets/botella-night.png',
    posicion: 'side',
  },
]

export default function Bienvenida() {
  const navigate = useNavigate()
  const { reiniciarFlujo } = useApp()

  const handleIniciar = () => {
    reiniciarFlujo()
    navigate('/instrucciones')
  }

  return (
    <div className="screen bienvenida-screen">
      <div className="screen-bg bienvenida-bg bg-pantone-2728" />

      <div className="particles bienvenida-particles">
        {Array.from({ length: 18 }).map((_, i) => (
          <span
            key={i}
            className="particle pt"
            style={{
              left: `${Math.random() * 100}%`,
              top: `${Math.random() * 100}%`,
              animationDelay: `${Math.random() * 4}s`,
            }}
          />
        ))}
      </div>

      <div className="screen-content bienvenida-content anim-in">
        <div className="hero">
          <div className="mark hero-mark">
            <img
              src="/assets/logo-oficial.png"
              alt="Aguardiente Blanco del Valle"
              className="logo-oficial-img hero-logo"
              onError={(e) => { e.currentTarget.style.display = 'none'; const sib = e.currentTarget.nextElementSibling; if (sib) sib.style.display = '' }}
            />
            <span className="hero-mark-text" style={{ display: 'none' }}>Aguardiente Blanco del Valle <b>FIESTA</b></span>
          </div>

          <div className="slogan-wrap">
            <SloganVaConTodo size="lg" />
          </div>

          <div className="trip">
            {BOTELLAS.map((b, i) => (
              <img
                key={b.id}
                src={b.img}
                alt="Aguardiente Blanco del Valle"
                className={`bt-img-pura ${b.posicion === 'mid' ? 'mid' : 'side'}`}
                style={{
                  animationDelay: `${i * 0.9}s`,
                }}
              />
            ))}
          </div>

          <div className="hero-cta-wrap">
            <button className="btn-primario btn-iniciar btn-cta-red cta" onClick={handleIniciar} autoFocus>
              ¡INICIAR!
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
