import { useState, useEffect } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { QRCodeCanvas } from 'qrcode.react'
import '../styles/ganador.css'

export default function Ganador() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const qr_uuid = searchParams.get('qr') || ''

  const [aceptaTerminos, setAceptaTerminos] = useState(false)
  const [aceptaHabeas, setAceptaHabeas] = useState(false)
  const [terminosTs, setTerminosTs] = useState('')
  const [habeasTs, setHabeasTs] = useState('')

  const puedeContinuar = !!(qr_uuid && aceptaTerminos && aceptaHabeas)

  const formatearTimestamp = (iso) => {
    if (!iso) return ''
    try {
      const d = new Date(iso)
      const hh = String(d.getHours()).padStart(2, '0')
      const mm = String(d.getMinutes()).padStart(2, '0')
      const ss = String(d.getSeconds()).padStart(2, '0')
      return `ⓘ Aceptado ${hh}:${mm}:${ss} servidor`
    } catch {
      return ''
    }
  }

  const enviarAceptacion = async (tipo) => {
    if (!qr_uuid) return null
    try {
      const res = await fetch('/api/promo/aceptacion', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          qr_uuid,
          tipo,
        }),
      })
      if (res.ok) {
        const data = await res.json().catch(() => ({}))
        return data.server_timestamp_iso || new Date().toISOString()
      }
    } catch {
    }
    return new Date().toISOString()
  }

  const handleToggleTerminos = async (e) => {
    const checked = e.target.checked
    setAceptaTerminos(checked)
    if (checked) {
      const ts = await enviarAceptacion('terminos')
      setTerminosTs(formatearTimestamp(ts))
    } else {
      setTerminosTs('')
    }
  }

  const handleToggleHabeas = async (e) => {
    const checked = e.target.checked
    setAceptaHabeas(checked)
    if (checked) {
      const ts = await enviarAceptacion('habeas')
      setHabeasTs(formatearTimestamp(ts))
    } else {
      setHabeasTs('')
    }
  }

  const handleContinuar = () => {
    if (!puedeContinuar) return
    navigate('/ganador/registro', {
      state: {
        qr_uuid,
        acepta_terminos_at: terminosTs ? new Date().toISOString() : null,
        acepta_habeas_at: habeasTs ? new Date().toISOString() : null,
      },
    })
  }

  return (
    <div className="screen ganador-screen">
      <div className="screen-bg ganador-bg" />

      <div className="screen-header instrucciones-header">
        <div className="header-left">
          <button
            type="button"
            className="header-btn-atras"
            onClick={() => navigate('/')}
          >
            ‹ Atrás
          </button>
        </div>
        <div className="header-middle">
          <h1 className="header-titulo">¡FELICIDADES GANASTE!</h1>
        </div>
        <div className="header-right" />
      </div>

      <div className="screen-content ganador-content anim-in">
        <h2 className="ganador-titulo">¡Felicidades!</h2>
        <p className="ganador-subtitulo">
          Ganaste una botella de Aguardiente Blanco del Valle Fiesta 🎉
        </p>

        {qr_uuid && (
          <div className="ganador-qr-wrap" title={`QR: ${qr_uuid}`}>
            <QRCodeCanvas
              value={qr_uuid}
              size={64}
              level="M"
              includeMargin={false}
            />
          </div>
        )}

        <div className="ganador-checks">
          <label className="ganador-check-wrap" htmlFor="chk-terminos">
            <input
              type="checkbox"
              id="chk-terminos"
              checked={aceptaTerminos}
              onChange={handleToggleTerminos}
            />
            <span className="ganador-check-label">
              <b>He leído y acepto los TÉRMINOS Y CONDICIONES de la promoción</b>
              <div className="ganador-check-detalle">
                Premio 1 botella Fiesta, ganador por orden de llegada, entrega en Bogotá D.C.,
                ILV 1921 se reserva derecho de admisión, mayor de edad 18+, licor no se devuelve.
              </div>
              {terminosTs && (
                <span className="ganador-aceptado-timestamp">{terminosTs}</span>
              )}
            </span>
          </label>

          <label className="ganador-check-wrap" htmlFor="chk-habeas">
            <input
              type="checkbox"
              id="chk-habeas"
              checked={aceptaHabeas}
              onChange={handleToggleHabeas}
            />
            <span className="ganador-check-label">
              <b>Autorizo el TRATAMIENTO DE DATOS PERSONALES de acuerdo a la Ley 1581/2012 y política Habeas Data ILV 1921</b>
              <div className="ganador-check-detalle">
                Uso de datos solo para entrega del premio, no se comparten terceros.
              </div>
              {habeasTs && (
                <span className="ganador-aceptado-timestamp">{habeasTs}</span>
              )}
            </span>
          </label>
        </div>

        <button
          type="button"
          className={`btn-primario btn-cta-red ganador-btn-continuar ${!puedeContinuar ? 'is-disabled' : ''}`}
          onClick={handleContinuar}
          disabled={!puedeContinuar}
        >
          CONTINUAR AL FORMULARIO →
        </button>
      </div>
    </div>
  )
}
