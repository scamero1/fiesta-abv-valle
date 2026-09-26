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
    const t = setTimeout(() => setCountdown(countdown - 1), 900)
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
      setTimeout(() => setFlash(false), 250)
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

      <div className="screen-header camara-header">
        <div className="header-left">
          <button className="btn-back btn-ghost gh" onClick={() => navigate('/instrucciones')} style={{ padding: '8px 18px', fontSize: 16, minHeight: 44 }}>
            ‹ Atrás
          </button>
        </div>
        <div className="header-middle">
          <div className="camara-titulo">
            <h2>¡Sonríe!</h2>
          </div>
        </div>
        <div className="header-right">
          <StepperPaso pasoActual={3} />
        </div>
      </div>

      <div className="screen-content camara-content anim-in">
        <div className="camara-body">
          <div className="camwrap">
            <div className="vp viewport-marco foto-preview-frame">
              <div className="hint camara-hint" id="camara-hint">
                {preview ? '¿Te gusta cómo quedó?' : 'Ubícate en el centro de la cruz'}
              </div>

              <div className="sil" aria-hidden></div>

              {!preview ? (
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
              ) : (
                <img src={preview} alt="Preview captura" className="preview-img" />
              )}

              <div className={`cd countdown-overlay ${countdown !== null && countdown > 0 ? 'on' : ''}`}>
                {countdown !== null && countdown > 0 && (
                  <span className="countdown-num" key={countdown}>{countdown}</span>
                )}
              </div>

              <div className={`fl flash-overlay ${flash ? 'on' : ''}`}></div>

              {errorCam && !preview && (
                <div className="camara-error error-box">
                  <span className="error-icono">⚠️</span>
                  <p className="error-tit">No pudimos acceder a la cámara</p>
                  <p className="error-detalle">Activa los permisos en Ajustes → Aplicaciones → Chrome → Cámara</p>
                  <button className="btn-secundario btn-ghost gh" onClick={handleReintentarPermisos} style={{ marginTop: 12 }}>
                    Reintentar
                  </button>
                </div>
              )}
            </div>
          </div>
        </div>

        <div className={`ctl ${preview ? 'ctl-preview' : 'ctl-capture'}`}>
          {!preview ? (
            <>
              <button className="btn-lateral btn-ghost gh" onClick={handleCambiarCamara} style={{ fontSize: 16, padding: '10px 20px' }}>
                🔄 Cambiar
              </button>

              <button
                className={`shut ${capturando ? 'capturando' : ''}`}
                onClick={handleCapturar}
                disabled={capturando || !!errorCam}
                aria-label="Sacar foto"
              ></button>

              <div className="camara-status" aria-hidden>
                <span className="status-dot" />
                Colócate en el centro
              </div>
            </>
          ) : (
            <>
              <button className="btn-secundario btn-ghost gh" onClick={handleRepetir}>
                Repetir
              </button>
              <button className="btn-primario btn-cta-red cta" onClick={handleAceptar} autoFocus>
                USAR FOTO
              </button>
            </>
          )}
        </div>
      </div>

      <LegalDisclaimer variant="footer-sticky" />
    </div>
  )
}
