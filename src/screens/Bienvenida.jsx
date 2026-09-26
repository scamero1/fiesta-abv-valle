import { useNavigate } from 'react-router-dom'
import { useApp } from '../context/AppContext.jsx'
import { LegalDisclaimer, SloganVaConTodo, LogoHeaderStack } from '../components/BrandComponents.jsx'
import '../styles/bienvenida.css'

const BOTELLAS = [
  {
    id: 'sin-azucar',
    nombre: 'Sin Azúcar',
    tag: '29% Vol. • Línea Premium',
    img: '/assets/botella-sin-azucar.png',
    colorAcento: '#E4002B',
    posicion: 'left',
  },
  {
    id: 'fiesta',
    nombre: 'Fiesta',
    tag: '24% Vol. • Edición Campaña',
    img: '/assets/botella-fiesta-azul.png',
    colorAcento: '#0047BA',
    posicion: 'center',
    estrella: true,
  },
  {
    id: 'night',
    nombre: 'Night',
    tag: '27% Vol. • Línea Neon',
    img: '/assets/botella-night.png',
    colorAcento: '#4a148c',
    posicion: 'right',
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

      <div className="particles">
        {Array.from({ length: 18 }).map((_, i) => (
          <span
            key={i}
            className="particle"
            style={{
              left: `${Math.random() * 100}%`,
              top: `${Math.random() * 100}%`,
              animationDelay: `${Math.random() * 8}s`,
              animationDuration: `${6 + Math.random() * 6}s`,
              background: i % 4 === 0 ? '#E4002B' : i % 4 === 1 ? '#d4a017' : i % 4 === 2 ? '#ffffff' : '#6aa6ff',
              boxShadow: i % 4 === 0 ? '0 0 12px #E4002B' : i % 4 === 1 ? '0 0 12px #d4a017' : i % 4 === 2 ? '0 0 10px rgba(255,255,255,0.8)' : '0 0 10px #6aa6ff',
            }}
          />
        ))}
      </div>

      <div className="screen-content bienvenida-content">
        <div className="bienvenida-header fade-in">
          <LogoHeaderStack showFiesta={true} showILV={true} />
          <div className="bienvenida-header-lado">
            <div className="bh-tag bh-tag-simple">
              ✦ FIESTA 2026
            </div>
          </div>
        </div>

        <div className="bienvenida-main">
          <div className="bienvenida-hero slide-up">
            <div className="hero-eyebrow">
              <span className="eyebrow-line" />
              <span className="eyebrow-text">AGUARDIENTE BLANCO DEL VALLE • FIESTA</span>
              <span className="eyebrow-line" />
            </div>

            <h1 className="hero-titulo">
              <span className="hero-titulo-linea1">EL SABOR</span>
              <span className="hero-titulo-linea2">
                que nos <span className="destacado-dorado">une</span>
              </span>
              <span className="hero-titulo-linea3">
                <SloganVaConTodo size="md" />
              </span>
            </h1>

            <div className="hero-subtitulo-wrap">
              <p className="hero-subtitulo">
                VIVE CALI EN UNA <span className="subrayado-dorado">FOTO ÚNICA</span>
              </p>
              <p className="hero-sub-sub">
                Transporta tu imagen a los lugares más emblemáticos con Inteligencia Artificial y llévate tu recuerdo
              </p>
            </div>

            <div className="hero-triptico-tag">
              <div className="htt-tag htt-1" style={{ background: 'rgba(228,0,43,0.18)', borderColor: 'rgba(228,0,43,0.55)', color: '#ffd0d6' }}>Sin Azúcar</div>
              <div className="htt-tag htt-2" style={{ background: 'rgba(255,255,255,0.14)', borderColor: 'rgba(212,160,23,0.55)', color: '#fff7d8' }}>Fiesta</div>
              <div className="htt-tag htt-3" style={{ background: 'rgba(74,20,140,0.22)', borderColor: 'rgba(138, 43, 226, 0.55)', color: '#e9d5ff' }}>Night</div>
              <div className="htt-texto">3 experiencias de sabor</div>
            </div>
          </div>

          <div className="bienvenida-visual fade-in" style={{ animationDelay: '0.3s' }}>
            <div className="triptico-botellas">
              {BOTELLAS.map((b, i) => (
                <div
                  key={b.id}
                  className={`botella-wrap botella-${b.posicion} ${b.estrella ? 'botella-estrella' : ''}`}
                  style={{
                    '--acento': b.colorAcento,
                    animationDelay: `${0.3 + i * 0.12}s`,
                  }}
                >
                  <div className="botella-glow-real" />
                  {b.estrella && (
                    <div className="botella-badge-estrella" style={{ background: 'linear-gradient(135deg, #d4a017, #E4002B)', color: '#fff', borderColor: 'rgba(255,255,255,0.4)' }}>
                      ⭐ EDICIÓN FIESTA
                    </div>
                  )}
                  <img
                    src={b.img}
                    alt={`Aguardiente Blanco del Valle ${b.nombre}`}
                    className="botella-img-real"
                  />
                  <div className="botella-pie-tag">
                    <span className="bpt-nombre">{b.nombre}</span>
                    <span className="bpt-tag">{b.tag}</span>
                  </div>
                </div>
              ))}
            </div>

            <div className="luces-fiesta">
              <div className="luz luz-1" style={{ background: 'radial-gradient(circle, rgba(228,0,43,0.55) 0%, transparent 60%)' }} />
              <div className="luz luz-2" style={{ background: 'radial-gradient(circle, rgba(212,160,23,0.55) 0%, transparent 60%)' }} />
              <div className="luz luz-3" style={{ background: 'radial-gradient(circle, rgba(0,71,186,0.55) 0%, transparent 60%)' }} />
              <div className="luz luz-4" style={{ background: 'radial-gradient(circle, rgba(255,255,255,0.35) 0%, transparent 60%)' }} />
              <div className="luz luz-5" style={{ background: 'radial-gradient(circle, rgba(74,20,140,0.45) 0%, transparent 60%)' }} />
            </div>
          </div>
        </div>

        <div className="bienvenida-footer slide-up" style={{ animationDelay: '0.5s' }}>
          <button className="btn-primario btn-iniciar btn-cta-red" onClick={handleIniciar} autoFocus>
            ¡INICIAR! <span className="btn-flecha">›</span>
          </button>
          <div className="footer-pie">
            <span className="pie-texto">© 2026 Industria de Licores del Valle • ILV</span>
            <span className="pie-hashtag">#ElSaborQueNosUne • ¡VA CON TODO!</span>
          </div>
        </div>
      </div>

      <LegalDisclaimer variant="footer-sticky" />
    </div>
  )
}
