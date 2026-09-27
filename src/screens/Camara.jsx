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
  const previewImgRef = useRef(null)

  // 🔧 ✅ 🔴 FIX DEFINITIVO ANTI-FLIP CÁMARA FRONTAL (4TA CAPA: JAVASCRIPT DIRECTO EN DOM).
  // react-webcam a veces mete style="transform:scaleX(-1)" por su cuenta en <video> cuando facingMode=user.
  // Esto ocurre DESPUÉS de que React renderiza (useEffect post render), así que lo forzamos con polling corto 60ms
  // cada 60ms durante 3s después de montar, y después 1s (anti-flip persistente).
  useEffect(() => {
    let frames = 0
    let stop = false
    const MAX_FRAMES = 200   // 200 * 60ms = 12seg polling inicial
    const intervalMs = () => (frames < 60 ? 50 : 700)
    const forceNoFlip = () => {
      try {
        const w = webcamRef?.current
        // 🔧 FORZAR <video> (el real dentro de react-webcam)
        if (w) {
          const vEl = w.video || w
          if (vEl && vEl.style) {
            vEl.style.setProperty('transform', 'scaleX(1)', 'important')
            vEl.style.setProperty('-webkit-transform', 'scaleX(1)', 'important')
            vEl.style.setProperty('-moz-transform', 'scaleX(1)', 'important')
            vEl.style.setProperty('transform-origin', 'center center', 'important')
            vEl.style.setProperty('-webkit-transform-origin', 'center center', 'important')
            vEl.style.setProperty('direction', 'ltr', 'important')
            vEl.style.setProperty('writing-mode', 'horizontal-tb', 'important')
            vEl.style.setProperty('filter', 'none', 'important')
            vEl.style.setProperty('backface-visibility', 'hidden', 'important')
            if (typeof vEl.setAttribute === 'function') {
              vEl.setAttribute('data-no-flip', '1')
              vEl.setAttribute('dir', 'ltr')
            }
          }
        }
        // 🔧 FORZAR <img> preview (ya tomada)
        const imgEl = previewImgRef?.current
        if (imgEl && imgEl.style) {
          imgEl.style.setProperty('transform', 'scaleX(1)', 'important')
          imgEl.style.setProperty('-webkit-transform', 'scaleX(1)', 'important')
          imgEl.style.setProperty('direction', 'ltr', 'important')
          imgEl.style.setProperty('writing-mode', 'horizontal-tb', 'important')
        }
      } catch {}
    }
    const tick = () => {
      if (stop) return
      frames++
      forceNoFlip()
      if (frames < MAX_FRAMES) setTimeout(tick, intervalMs())
      else setTimeout(tick, 1200) // Anti-flip persistente siempre
    }
    tick()
    // Correr inmediatamente 3 veces en 50ms para asegurar 1ra pasada
    setTimeout(forceNoFlip, 50)
    setTimeout(forceNoFlip, 180)
    setTimeout(forceNoFlip, 420)
    return () => { stop = true }
  }, [webcamKey, facingMode, preview])

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
              {/* Usuario: NO pastilla azul ¡Sonríe!. NO texto hint colócate. */}

              <div className="sil" aria-hidden></div>

              {/* BOTÓN CAMBIAR CÁMARA → DENTRO DEL VIEWPORT, arriba izquierda, CORTO + PEQUEÑO */}
              {!preview && !errorCam && (
                <button
                  type="button"
                  className="btn-switch-inside"
                  onClick={handleCambiarCamara}
                  aria-label="Cambiar cámara"
                >
                  <span className="sw-ico" aria-hidden>🔄</span>
                  <span className="sw-txt">Cambiar</span>
                </button>
              )}

              {!preview ? (
                <Webcam
                  key={webcamKey}
                  ref={webcamRef}
                  audio={false}
                  screenshotFormat="image/jpeg"
                  screenshotQuality={0.95}
                  videoConstraints={currentConstraints}
                  mirrored={false}
                  className="webcam-feed"
                  onUserMediaError={onUserMediaError}
                  dir="ltr"
                  style={{
                    transform: 'scaleX(1) !important',
                    WebkitTransform: 'scaleX(1) !important',
                    MozTransform: 'scaleX(1) !important',
                    transformOrigin: 'center center',
                    WebkitTransformOrigin: 'center center',
                    direction: 'ltr',
                    writingMode: 'horizontal-tb',
                    backfaceVisibility: 'hidden',
                    WebkitBackfaceVisibility: 'hidden',
                    filter: 'none',
                    WebkitFilter: 'none',
                  }}
                />
              ) : (
                <img
                  ref={previewImgRef}
                  src={preview}
                  alt="Preview captura"
                  className="preview-img"
                  dir="ltr"
                  style={{
                    transform: 'scaleX(1) !important',
                    WebkitTransform: 'scaleX(1) !important',
                    MozTransform: 'scaleX(1) !important',
                    transformOrigin: 'center center',
                    WebkitTransformOrigin: 'center center',
                    direction: 'ltr',
                    writingMode: 'horizontal-tb',
                    backfaceVisibility: 'hidden',
                    WebkitBackfaceVisibility: 'hidden',
                    filter: 'none',
                    WebkitFilter: 'none',
                    objectFit: 'contain',
                  }}
                />
              )}

              <div className={`cd countdown-overlay ${countdown !== null && countdown > 0 ? 'on' : ''}`}>
                {countdown !== null && countdown > 0 && (
                  <span className="countdown-num" key={countdown}>{countdown}</span>
                )}
              </div>

              <div className={`fl flash-overlay ${flash ? 'on' : ''}`}></div>

              {/* BOTÓN OBTURADOR (TOMAR FOTO) → DENTRO DEL VIEWPORT, ABAJO CENTRO, tamaño mediano */}
              {!preview && !errorCam && (
                <div className="shut-inside-wrap" aria-hidden={false}>
                  <button
                    className={`shut shut-inside ${capturando ? 'capturando' : ''}`}
                    onClick={handleCapturar}
                    disabled={capturando || !!errorCam}
                    aria-label="Sacar foto"
                  ></button>
                </div>
              )}

              {/* BOTONES REPETIR / USAR FOTO → DENTRO DEL VIEWPORT, ABAJO CENTRO (modo preview) */}
              {preview && (
                <div className="preview-actions-inside" role="group" aria-label="Acciones preview">
                  <button type="button" className="btn-preview-inside btn-ghost gh" onClick={handleRepetir}>
                    Repetir
                  </button>
                  <button type="button" className="btn-preview-inside btn-cta-red cta" onClick={handleAceptar} autoFocus>
                    USAR FOTO
                  </button>
                </div>
              )}

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

        {/* ANTIGUA BARRA CONTROLES (ctl) 104px → TOTALMENTE ELIMINADA para maximizar altura cámara en TCL/pc.
            Todos los botones están AHORA DENTRO DEL VIEWPORT. */}
        <div className={`ctl ${preview ? 'ctl-preview' : 'ctl-capture'}`} style={{ display: 'none', height: 0, minHeight: 0, flex: 0 }} aria-hidden="true"></div>
      </div>

      <LegalDisclaimer variant="footer-sticky" />
    </div>
  )
}
