import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useApp } from '../context/AppContext.jsx'
import '../styles/bienvenida.css'

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
              Acepto los términos y condiciones y autorizo el tratamiento de mis datos personales
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
