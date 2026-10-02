import { useState, useEffect } from 'react'
import { useParams } from 'react-router-dom'
import '../styles/ganador.css'

export default function AgradecimientoGanador() {
  const { id } = useParams()

  const [loading, setLoading] = useState(true)
  const [data, setData] = useState(null)
  const [error, setError] = useState('')

  useEffect(() => {
    let cancelado = false
    const cargar = async () => {
      if (!id) {
        setError('No se encontró el registro')
        setLoading(false)
        return
      }
      try {
        const res = await fetch(`/api/promo/agradecimiento/${encodeURIComponent(id)}`)
        if (res.ok) {
          const d = await res.json().catch(() => ({}))
          if (!cancelado) {
            setData(d || {})
          }
        } else {
          if (!cancelado) {
            setError('No se pudo cargar la información del registro')
          }
        }
      } catch {
        if (!cancelado) {
          setError('Error de conexión')
        }
      } finally {
        if (!cancelado) setLoading(false)
      }
    }
    cargar()
    return () => { cancelado = true }
  }, [id])

  const nombres = data?.nombres_apellidos || data?.nombres || 'participante'
  const esGanador = !!data?.ganador
  const modalidad = (data?.modalidad_entrega || data?.modalidad || '').toString().toUpperCase()
  const esBogotaDomicilio = modalidad === 'BOGOTA_DOMICILIO' || modalidad === 'DOMICILIO'
  const esRecogerCra74 = modalidad === 'RECOGER_CRA74' || modalidad === 'RECOGIDA'

  const renderMensaje = () => {
    if (!esGanador) {
      return (
        <p className="agradecimiento-mensaje">
          Lo sentimos, los premios de esta promoción ya fueron entregados por estricto orden de llegada.
          ¡Gracias por participar! Te esperamos en la próxima fiesta ILV 1921.
        </p>
      )
    }
    if (esRecogerCra74) {
      return (
        <p className="agradecimiento-mensaje">
          Tu botella ganadora la RECOGES en{' '}
          <b>Cra. 74a #51a-87, Bogotá D.C.</b>.
          Presenta tu cédula de ciudadanía original de lunes a viernes 9am-5pm.
        </p>
      )
    }
    return (
      <p className="agradecimiento-mensaje">
        Tu botella Fiesta será entregada a la dirección registrada en 10 días hábiles.
        ¡Bebe con responsabilidad!
      </p>
    )
  }

  return (
    <div className="screen ganador-screen">
      <div className="screen-bg ganador-bg-fondo-vertical" />

      <div className="screen-header instrucciones-header">
        <div className="header-left" />
        <div className="header-middle">
          <h1 className="header-titulo">{esGanador ? '¡Premio Confirmado!' : 'Información'}</h1>
        </div>
        <div className="header-right" />
      </div>

      <div className="screen-content ganador-content anim-in">
        {loading ? (
          <div className="agradecimiento-card">
            <div className="spinner" style={{ width: 28, height: 28, border: '4px solid #cbd5e1', borderTopColor: 'var(--color-azul-secundario)', borderRadius: '50%', animation: 'spin .8s linear infinite' }} />
            <p style={{ margin: 0, color: '#475569', fontWeight: 600 }}>Cargando información...</p>
          </div>
        ) : error ? (
          <div className="agradecimiento-card">
            <div className="agradecimiento-icon info">ℹ</div>
            <h1>Información</h1>
            <p className="agradecimiento-mensaje" style={{ color: '#991b1b' }}>{error}</p>
          </div>
        ) : (
          <div className="agradecimiento-card">
            <div className={`agradecimiento-icon ${esGanador ? 'ok' : 'info'}`}>
              {esGanador ? '✓' : 'ℹ'}
            </div>
            <h1>¡Gracias {nombres}!</h1>
            {renderMensaje()}
          </div>
        )}
      </div>

      <style>{`
        @keyframes spin { to { transform: rotate(360deg); } }
      `}</style>
    </div>
  )
}
