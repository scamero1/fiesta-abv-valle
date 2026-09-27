import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { SloganVaConTodo } from '../components/BrandComponents.jsx'
import '../styles/landing.css'

export default function LandingDescarga() {
  const { id } = useParams()
  const [fotoUrl, setFotoUrl] = useState('')
  const [cargando, setCargando] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    let alive = true
    async function load() {
      try {
        setCargando(true)
        const s = sessionStorage.getItem('agv-fiesta-flujo-state-v1')
        let imgLocal = ''
        if (s) {
          try {
            const parsed = JSON.parse(s)
            if (parsed && parsed.fotoProcesada) imgLocal = parsed.fotoProcesada
            else if (parsed && parsed.fotoUrlDescarga) {
              const fud = parsed.fotoUrlDescarga
              if (typeof fud === 'string') imgLocal = fud
              else if (fud && fud.url) imgLocal = fud.url
            }
          } catch {}
        }
        if (!imgLocal) {
          const baseBackend = (() => {
            try {
              const envUrl = import.meta.env.VITE_BACKEND_URL || import.meta.env.VITE_RAILWAY_BACKEND_URL || ''
              if (envUrl && /^https?:\/\//i.test(envUrl)) return envUrl.replace(/\/+$/, '')
            } catch {}
            return `${location.protocol}//${location.hostname}:8000`
          })()
          const url = `${baseBackend}/fotos/foto-${id}.jpg`
          imgLocal = url
        }
        if (alive) {
          setFotoUrl(imgLocal)
          setCargando(false)
        }
      } catch (e) {
        if (alive) {
          setError('No pudimos encontrar tu foto. Pide que la vuelvan a generar.')
          setCargando(false)
        }
      }
    }
    load()
    return () => { alive = false }
  }, [id])

  const handleDescargar = async () => {
    if (!fotoUrl) return
    try {
      const a = document.createElement('a')
      a.href = fotoUrl
      a.download = `Aguardiente-Fiesta-${id || 'foto'}.jpg`
      a.target = '_blank'
      a.rel = 'noopener'
      document.body.appendChild(a)
      a.click()
      setTimeout(() => a.remove(), 1000)
    } catch {
      window.open(fotoUrl, '_blank')
    }
  }

  const handleCompartir = async () => {
    if (!fotoUrl) return
    try {
      if (navigator.share) {
        await navigator.share({
          title: 'Mi foto en Aguardiente Blanco del Valle Fiesta',
          text: '#ElSaborQueNosUne • ¡VA CON TODO!',
          url: location.href,
        })
      } else if (navigator.clipboard) {
        await navigator.clipboard.writeText(location.href)
        alert('Enlace copiado al portapapeles')
      }
    } catch {}
  }

  return (
    <div className="screen landing-screen">
      <div className="screen-bg landing-bg bg-pantone-2728" />

      <div className="particles">
        {Array.from({ length: 14 }).map((_, i) => (
          <span
            key={i}
            className="particle pt"
            style={{
              left: `${(i * 7.3) % 100}%`,
              top: `${(i * 13.7) % 100}%`,
              animationDelay: `${(i % 5) * 0.7}s`,
            }}
          />
        ))}
      </div>

      <div className="landing-contenido">
        <div className="landing-header anim-in">
          <img
            src="/assets/logo-oficial.png"
            alt="Aguardiente Blanco del Valle"
            className="logo-oficial-img"
          />
        </div>

        <div className="landing-hero anim-in" style={{ animationDelay: '0.1s' }}>
          <h1 className="landing-title">
            <span className="lt-1">¡Tu foto está lista, </span>
            <SloganVaConTodo size="sm" />
            <span className="lt-1">!</span>
          </h1>
          <p className="landing-sub">
            Descárgala, compártela y usa <span className="hashtag">#ElSaborQueNosUne</span>
          </p>
        </div>

        <div className="landing-main-wrap anim-in" style={{ animationDelay: '0.2s' }}>
          <div className="landing-foto-card">
            {cargando && (
              <div className="landing-cargando">
                <div className="landing-spinner" />
                <p>Cargando tu foto...</p>
              </div>
            )}
            {error && !cargando && (
              <div className="landing-error">
                <div className="le-icon">⚠</div>
                <p>{error}</p>
                <button className="btn-primario btn-cta-red btn-error-reintentar" onClick={() => window.location.reload()}>
                  REINTENTAR
                </button>
              </div>
            )}
            {fotoUrl && !cargando && !error && (
              <img
                src={fotoUrl}
                alt="Mi foto Aguardiente Blanco del Valle Fiesta"
                className="landing-foto-img"
                onError={() => setError('La foto no se pudo cargar. Por favor vuelve a escanear el QR desde la tableta.')}
              />
            )}
          </div>

          <div className="landing-acciones-col">
            <button className="btn-primario btn-cta-red btn-landing btn-descargar" onClick={handleDescargar} autoFocus>
              DESCARGAR FOTO
            </button>
            <button className="btn-secundario btn-ghost btn-landing btn-compartir" onClick={handleCompartir}>
              COMPARTIR
            </button>
            <div className="landing-info" aria-label="Pasos para guardar y compartir">
              <div className="li-item">
                <span className="li-chip li-chip-1">1</span>
                <span className="li-texto">Toca DESCARGAR para guardar la foto en tu galería</span>
              </div>
              <div className="li-item">
                <span className="li-chip li-chip-2">2</span>
                <span className="li-texto">Sube la foto a tus redes con <b>#ElSaborQueNosUne</b></span>
              </div>
              <div className="li-item">
                <span className="li-chip li-chip-3">3</span>
                <span className="li-texto">¡Etiqueta a <b>@aguardientedelvalle</b> y participa!</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
