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
    const nombreLimpio = nombres && nombres !== 'participante' ? ` ${nombres}` : ''
    if (esRecogerCra74) {
      return (
        <>
          <p className="agradecimiento-mensaje">
            ✅ <b>¡Gracias por registrarte{nombreLimpio}!</b> Tu premio está listo.
          </p>
          <p className="agradecimiento-mensaje">
            🏬 Tu botella <b>Fiesta Aguardiente Blanco del Valle</b> la RECOGES PRESENCIALMENTE en:
          </p>
          <p className="agradecimiento-mensaje" style={{ fontWeight: 800, color: '#0f172a', fontSize: '1.08em' }}>
            📍 Cra. 74a #51a-87, Bogotá D.C.
          </p>
          <p className="agradecimiento-mensaje">
            📅 Presenta tu <b>cédula de ciudadanía original</b> de lunes a viernes en horario <b>9:00am – 5:00pm</b>.
          </p>
        </>
      )
    }
    // Domicilio (incluye todos los casos no-Recoger: BOGOTA_DOMICILIO / DOMICILIO u otro)
    const ciudadPais = (data?.ciudad || data?.municipio) ? ` para ${data?.ciudad || data?.municipio}` : ''
    return (
      <>
        <p className="agradecimiento-mensaje">
          ✅ <b>¡Gracias por registrarte{nombreLimpio}!</b> Tu premio está confirmado.
        </p>
        <p className="agradecimiento-mensaje">
          🚚 Tu botella <b>Fiesta Aguardiente Blanco del Valle</b> será ENTREGADA EN LA DIRECCIÓN que registraste{ciudadPais}:
        </p>
        <p className="agradecimiento-mensaje" style={{ fontWeight: 800, color: '#0f172a', fontSize: '1.08em' }}>
          📍 {data?.direccion || 'Tu dirección registrada'}
          {(data?.barrio) ? ` · ${data.barrio}` : ''}
        </p>
        <p className="agradecimiento-mensaje">
          📅 Tiempo estimado de entrega: <b>10 días hábiles</b> después de hoy.
        </p>
        <p className="agradecimiento-mensaje" style={{ marginTop: 14, color: '#475569' }}>
          🥃 ¡Disfruta con responsabilidad! #VaConTodo
        </p>
      </>
    )
  }

  return (
    <div className="screen ganador-screen">
      <div className="screen-bg ganador-bg-fondo-vertical" />

      <div className="screen-header instrucciones-header">
        <div className="header-left" />
        <div className="header-middle">
          <h1 className="header-titulo">¡Gracias por registrarte!</h1>
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
            <div className="agradecimiento-icon ok">✓</div>
            <h1>¡Gracias por registrarte!</h1>
            <p className="agradecimiento-mensaje">
              Tu información fue recibida correctamente. En breve un asesor validará el registro y contactará contigo
              para coordinar la entrega de tu premio. ✨
            </p>
          </div>
        ) : (
          <div className="agradecimiento-card">
            <div className={`agradecimiento-icon ${esGanador ? 'ok' : 'ok'}`}>
              ✓
            </div>
            <h1>¡Gracias por registrarte{esGanador ? ' ¡Ganaste!' : ''}</h1>
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
