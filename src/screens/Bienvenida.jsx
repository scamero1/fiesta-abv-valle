import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useApp } from '../context/AppContext.jsx'
import '../styles/bienvenida.css'

const URL_TERMINOS_Y_CONDICIONES_PDF = `/Terminos_y_Condiciones_ILV_Extrem_Marketing_VERSION_FINAL.pdf`
const URL_POLITICA_TRATAMIENTO_DATOS_PDF = `/POLITICA-DE-PROTECCION-DE-DATOS-PERSONALES-2025.pdf`

export default function Bienvenida() {
  const navigate = useNavigate()
  const { reiniciarFlujo } = useApp()
  const [aceptoTyC, setAceptoTyC] = useState(false)

  const handleIniciar = () => {
    if (!aceptoTyC) return
    reiniciarFlujo()
    navigate('/instrucciones')
  }

  return (
    <div className="screen bienvenida-screen">
      <div className="screen-bg bienvenida-bg fondo-pieza-ganadores" />

      <div className="screen-content bienvenida-content anim-in">
        <div className="login-zone-med-centro">

          <label className="check-tyc-wrap" htmlFor="chk-tyc">
            <input
              type="checkbox"
              id="chk-tyc"
              className="check-tyc-input"
              checked={aceptoTyC}
              onChange={(e) => setAceptoTyC(e.target.checked)}
            />
            <span className="check-tyc-label">
              Acepto los&nbsp;
              <a
                href={URL_TERMINOS_Y_CONDICIONES_PDF}
                target="_blank"
                rel="noreferrer noopener"
                title="Abrir Términos y Condiciones (PDF en nueva pestaña)"
                style={{
                  color: '#002A7A',
                  textDecoration: 'underline 1.5px',
                  textUnderlineOffset: '2px',
                  fontWeight: 800,
                  borderRadius: '4px',
                  paddingInline: '2px',
                  transition: 'background .1s ease-out',
                }}
                onClick={(e) => e.stopPropagation()}
                onFocus={(e) => (e.currentTarget.style.background = 'rgba(0,71,186,.1)')}
                onBlur={(e) => (e.currentTarget.style.background = 'transparent')}
              >
                términos y condiciones
              </a>
              &nbsp;y autorizo el&nbsp;
              <a
                href={URL_POLITICA_TRATAMIENTO_DATOS_PDF}
                target="_blank"
                rel="noreferrer noopener"
                title="Abrir Política de Protección de Datos Personales (PDF en nueva pestaña)"
                style={{
                  color: '#002A7A',
                  textDecoration: 'underline 1.5px',
                  textUnderlineOffset: '2px',
                  fontWeight: 800,
                  borderRadius: '4px',
                  paddingInline: '2px',
                  transition: 'background .1s ease-out',
                }}
                onClick={(e) => e.stopPropagation()}
                onFocus={(e) => (e.currentTarget.style.background = 'rgba(0,71,186,.1)')}
                onBlur={(e) => (e.currentTarget.style.background = 'transparent')}
              >
                tratamiento de mis datos personales
              </a>
            </span>
          </label>

          <button
            className={`btn-primario btn-iniciar btn-cta-red cta ${!aceptoTyC ? 'is-disabled' : ''}`}
            onClick={handleIniciar}
            disabled={!aceptoTyC}
            autoFocus
          >
            ¡INICIAR!
          </button>

        </div>
      </div>
    </div>
  )
}
