import { useState, useRef, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import Webcam from 'react-webcam'
import { useApp } from '../context/AppContext.jsx'
import { LegalDisclaimer, StepperPaso } from '../components/BrandComponents.jsx'
import '../styles/camara.css'

const TARGET_RATIO = 16 / 9

const CONSTRAINT_SEQUENCE = [
  { width: { ideal: 1920 }, height: { ideal: 1080 }, aspectRatio: { ideal: 16 / 9 } },
  { width: { ideal: 1920 }, height: { ideal: 1080 }, aspectRatio: { ideal: 4 / 3 } },
  { width: { ideal: 1920 }, height: { ideal: 1080 } },
]

export default function Camara() {
  const navigate = useNavigate()
  const { setFotoCapturada } = useApp()
  const webcamRef = useRef(null)
  const [facingMode, setFacingMode] = useState('user')
  const [capturando, setCapturando] = useState(false)
  const [flash, setFlash] = useState(false)
  const [preview, setPreview] = useState(null)
  const [errorCam, setErrorCam] = useState(null)
  const [countdown, setCountdown] = useState(null)
  const [constraintIdx, setConstraintIdx] = useState(0)
  const [webcamKey, setWebcamKey] = useState(0)
  const intentosRef = useRef(0)

  const currentConstraints = {
    ...CONSTRAINT_SEQUENCE[Math.min(constraintIdx, CONSTRAINT_SEQUENCE.length - 1)],
    facingMode,
  }

  const handleCambiarCamara = () => {
    setFacingMode((prev) => (prev === 'user' ? 'environment' : 'user'))
    setWebcamKey((k) => k + 1)
  }

  const handleCapturar = () => {
    if (capturando) return
    setCapturando(true)
    setCountdown(3)
  }

  useEffect(() => {
    if (countdown === null) return
    if (countdown === 0) {
      ejecutarCaptura()
      setCountdown(null)
      return
    }
    const t = setTimeout(() => setCountdown(countdown - 1), 800)
    return () => clearTimeout(t)
  }, [countdown])

  const recortarCover16x9 = useCallback((sourceVideo) => {
    const canvas = document.createElement('canvas')
    const ctx = canvas.getContext('2d')
    if (!ctx || !sourceVideo) return null

    const vW = sourceVideo.videoWidth || 1920
    const vH = sourceVideo.videoHeight || 1080
    const videoRatio = vW / vH

    let targetW
    let targetH
    let offsetX = 0
    let offsetY = 0

    if (videoRatio > TARGET_RATIO) {
      targetH = vH
      targetW = Math.floor(vH * TARGET_RATIO)
      offsetX = Math.floor((vW - targetW) / 2)
      offsetY = 0
    } else {
      targetW = vW
      targetH = Math.floor(vW / TARGET_RATIO)
      offsetY = Math.floor((vH - targetH) / 2)
      offsetX = 0
    }

    const OUT_W = 1920
    const OUT_H = 1080
    canvas.width = OUT_W
    canvas.height = OUT_H
    ctx.drawImage(sourceVideo, offsetX, offsetY, targetW, targetH, 0, 0, OUT_W, OUT_H)

    return canvas.toDataURL('image/jpeg', 0.95)
  }, [])

  const ejecutarCaptura = useCallback(() => {
    if (!webcamRef.current) {
      setCapturando(false)
      return
    }
    try {
      const videoEl = webcamRef.current.video
      if (!videoEl || !videoEl.videoWidth) {
        setCapturando(false)
        return
      }
      setFlash(true)
      setTimeout(() => setFlash(false), 220)
      const recortada = recortarCover16x9(videoEl)
      if (recortada) {
        setPreview(recortada)
      } else {
        const fallback = webcamRef.current.getScreenshot()
        if (fallback) setPreview(fallback)
        else setCapturando(false)
      }
    } catch (e) {
      setCapturando(false)
    }
  }, [recortarCover16x9])

  const handleAceptar = () => {
    if (!preview) return
    setFotoCapturada(preview)
    navigate('/escenario')
  }

  const handleRepetir = () => {
    setPreview(null)
    setCapturando(false)
  }

  const handleReintentarPermisos = () => {
    intentosRef.current += 1
    const nextIdx = Math.min(constraintIdx + 1, CONSTRAINT_SEQUENCE.length - 1)
    if (nextIdx !== constraintIdx) {
      setConstraintIdx(nextIdx)
    }
    setErrorCam(null)
    setWebcamKey((k) => k + 1)
  }

  const onUserMediaError = (err) => {
    const nextIdx = Math.min(constraintIdx + 1, CONSTRAINT_SEQUENCE.length - 1)
    if (nextIdx !== constraintIdx && intentosRef.current < CONSTRAINT_SEQUENCE.length) {
      intentosRef.current += 1
      setConstraintIdx(nextIdx)
      setWebcamKey((k) => k + 1)
      return
    }
    setErrorCam(err)
  }

  return (
    <div className="screen camara-screen">
      <div className="camara-bg-dark bg-pantone-2728" />

      <div className="screen-content camara-content">
        <div className="camara-header fade-in">
          <button className="btn-back" onClick={() => navigate('/instrucciones')}>
            ‹ Atrás
          </button>
          <div className="camara-titulo">
            <span className="camara-eyebrow">PASO 3</span>
            <h2>¡Sonríe! Estamos tomando tu foto</h2>
          </div>
          <StepperPaso pasoActual={3} />
        </div>

        <div className="camara-body">
          <div className="camara-viewport">
            <div className="viewport-marco">
              <div className="marco-esquina marco-tl" />
              <div className="marco-esquina marco-tr" />
              <div className="marco-esquina marco-bl" />
              <div className="marco-esquina marco-br" />

              {!preview ? (
                <>
                  <Webcam
                    key={webcamKey}
                    ref={webcamRef}
                    audio={false}
                    screenshotFormat="image/jpeg"
                    screenshotQuality={0.95}
                    videoConstraints={currentConstraints}
                    mirrored={facingMode === 'user'}
                    className="webcam-feed"
                    onUserMediaError={onUserMediaError}
                  />
                  <div className="silueta-guia" aria-hidden>
                    <svg viewBox="0 0 200 300" fill="none" xmlns="http://www.w3.org/2000/svg">
                      <circle cx="100" cy="62" r="44" stroke="rgba(255,255,255,0.28)" strokeWidth="2" />
                      <path d="M38 298 C 42 202 70 152 100 152 C 130 152 158 202 162 298 Z" stroke="rgba(255,255,255,0.28)" strokeWidth="2" strokeLinecap="round" />
                    </svg>
                  </div>
                </>
              ) : (
                <img src={preview} alt="Preview captura" className="preview-img" />
              )}

              {countdown !== null && countdown > 0 && (
                <div className="countdown-overlay">
                  <span className="countdown-num">{countdown}</span>
                </div>
              )}

              {flash && <div className="flash-overlay" />}

              {errorCam && !preview && (
                <div className="camara-error">
                  <span className="error-icono">⚠️</span>
                  <div className="error-texto-wrap">
                    <p className="error-tit">No pudimos acceder a la cámara</p>
                    <p className="error-detalle">Activa los permisos en Ajustes → Aplicaciones → Chrome → Cámara</p>
                  </div>
                  <button className="btn-secundario btn-reintentar-cam" onClick={handleReintentarPermisos}>
                    Reintentar
                  </button>
                </div>
              )}
            </div>
          </div>

          {preview && (
            <div className="camara-confirmacion">
              <p className="confirmacion-preg">¿Te gusta cómo quedó?</p>
            </div>
          )}
        </div>

        <div className="camara-footer">
          {!preview ? (
            <>
              <button className="btn-lateral" onClick={handleCambiarCamara}>
                <span className="btn-lat-ico">🔄</span>
                <span className="btn-lat-texto">Cambiar cámara</span>
              </button>

              <button
                className={`obturador ${capturando ? 'capturando' : ''}`}
                onClick={handleCapturar}
                disabled={capturando || !!errorCam}
                aria-label="Sacar foto"
              >
                <span className="obturador-inner" />
                <span className="obturador-ring" />
              </button>

              <div className="camara-status">
                <span className="status-dot" />
                Colócate en el centro y sonríe
              </div>
            </>
          ) : (
            <>
              <button className="btn-secundario btn-preview-repetir" onClick={handleRepetir}>
                ↻ Repetir foto
              </button>
              <button className="btn-primario btn-preview-aceptar btn-cta-red" onClick={handleAceptar} autoFocus>
                USAR FOTO <span className="btn-flecha">›</span>
              </button>
            </>
          )}
        </div>
      </div>
      <LegalDisclaimer variant="footer-sticky" />
    </div>
  )
}
