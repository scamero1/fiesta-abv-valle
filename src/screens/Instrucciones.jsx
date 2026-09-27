import { useNavigate } from 'react-router-dom'
import { StepperPaso } from '../components/BrandComponents.jsx'
import '../styles/instrucciones.css'

const PASOS = [
  {
    num: 1,
    titulo: 'Ponte al frente',
    detalle: 'Párate frente a la cámara, con la cara dentro del marco.',
  },
  {
    num: 2,
    titulo: 'Sonríe',
    detalle: 'Cuando pulses el botón rojo hay 3 segundos de cuenta.',
  },
  {
    num: 3,
    titulo: 'Elige tu escenario',
    detalle: 'Calle del Sabor, Plaza Varela o Cristo Rey.',
  },
  {
    num: 4,
    titulo: 'Llévatela',
    detalle: 'Escanea el QR y descarga la foto en tu celular.',
  },
]

export default function Instrucciones() {
  const navigate = useNavigate()

  return (
    <div className="screen instrucciones-screen">
      <div className="screen-bg instrucciones-bg bg-pantone-2728" />

      <div className="screen-header instrucciones-header">
        <div className="header-left">
          <img
            src="/assets/logo-oficial.png"
            alt="Aguardiente Blanco del Valle"
            className="logo-oficial-img"
          />
        </div>
        <div className="header-right">
          <StepperPaso pasoActual={2} />
        </div>
      </div>

      <div className="screen-content instrucciones-content anim-in">
        <div className="instrucciones-titulo-wrap">
          <h2 className="instrucciones-titulo">Así de fácil</h2>
          <p className="instrucciones-sub subtitulo">
            Cuatro pasos y tu foto está lista para llevar.
          </p>
        </div>

        <div className="steps">
          {PASOS.map((paso, i) => (
            <div
              key={paso.num}
              className="card"
              style={{ animationDelay: `${0.1 + i * 0.06}s` }}
            >
              <div className="n">{paso.num}</div>
              <b>{paso.titulo}</b>
              <span>{paso.detalle}</span>
            </div>
          ))}
        </div>

        <div className="row instrucciones-row">
          <button
            className="btn-primario btn-cta-red cta"
            onClick={() => navigate('/camara')}
            autoFocus
          >
            CONTINUAR
          </button>
        </div>
      </div>
    </div>
  )
}
