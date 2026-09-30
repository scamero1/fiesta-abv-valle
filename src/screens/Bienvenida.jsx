import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useApp } from '../context/AppContext.jsx'
import '../styles/bienvenida.css'

import logo100 from '../assets/Logo 100 años.png'
import logoBlanco from '../assets/Logo aguardiente blanco.png'
import esloganImg from '../assets/El sabor que nos une.png'
import botellaImg from '../assets/Botella.png'

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
        <div className="nuevo-login-wrap">

          <div className="logos-top-row">
            <img src={logo100} alt="100 años" className="logo-top logo-100" />
            <img src={logoBlanco} alt="Aguardiente Blanco" className="logo-top logo-abv" />
          </div>

          <div className="eslogan-zone">
            <img src={esloganImg} alt="El sabor que nos une" className="eslogan-img" />
          </div>

          <div className="botella-zone">
            <img src={botellaImg} alt="Botella Aguardiente Blanco" className="botella-login" />
          </div>

          <div className="zona-inferior-login">
            <label className="check-tyc-wrap" htmlFor="chk-tyc">
              <input
                type="checkbox"
                id="chk-tyc"
                className="check-tyc-input"
                checked={aceptoTyC}
                onChange={(e) => setAceptoTyC(e.target.checked)}
              />
              <span className="check-tyc-label">
                Acepto los términos y condiciones y la política de tratamiento de datos
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
    </div>
  )
}
