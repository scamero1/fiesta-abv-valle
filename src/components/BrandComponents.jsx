import React from 'react'
import '../styles/brand.css'

export const LEGAL_TEXT = 'EL EXCESO DE ALCOHOL ES PERJUDICIAL PARA LA SALUD. PROHÍBASE EL EXPENDIO DE BEBIDAS EMBRIAGANTES A MENORES DE EDAD.'

export function LegalDisclaimer({ variant = 'footer-sticky' }) {
  if (variant === 'footer-sticky') {
    return (
      <div className="legal-disclaimer legal-footer legal-stripe-black">
        <div className="legal-inner legal-inner-black" role="note" aria-label="Aviso legal obligatorio">
          <span className="legal-icon" aria-hidden>⚠</span>
          <span className="legal-text">{LEGAL_TEXT}</span>
        </div>
      </div>
    )
  }
  if (variant === 'inline-light') {
    return (
      <div className="legal-disclaimer legal-inline legal-light-bg">
        <span className="legal-icon legal-icon-dark" aria-hidden>⚠</span>
        <span className="legal-text legal-text-dark">{LEGAL_TEXT}</span>
      </div>
    )
  }
  return (
    <div className="legal-disclaimer legal-inline legal-stripe-black legal-inner-black-inline">
      <span className="legal-icon" aria-hidden>⚠</span>
      <span className="legal-text">{LEGAL_TEXT}</span>
    </div>
  )
}

export function SloganVaConTodo({ size = 'md' }) {
  return (
    <div className={`slogan-vacontodo slogan-${size}`} aria-label="¡VA CON TODO!">
      <span className="svt-prefix">¡VA CON&nbsp;</span>
      <span className="svt-sufix-wrap" aria-hidden="false">
        <span className="svt-sufix-pastilla">
          <span className="svt-sufix">TODO!</span>
        </span>
      </span>
    </div>
  )
}

export function LogoHeaderStack({ showILV = true, showFiesta = true }) {
  return (
    <div className="logo-header-stack">
      {showFiesta && (
        <img
          src="/assets/logo-oficial.png"
          alt="Aguardiente Blanco del Valle Fiesta"
          className="logo-fiesta-main logo-oficial-img"
          draggable={false}
          onError={(e) => { e.currentTarget.style.display = 'none' }}
        />
      )}
      {showILV && (
        <div className="logo-ilv-pill" title="Industria de Licores del Valle">
          <span className="ilv-letters">ILV</span>
          <span className="ilv-text">Industria de Licores del Valle</span>
        </div>
      )}
    </div>
  )
}

const STEP_LABELS = ['Bienvenida', 'Instrucciones', 'Cámara', 'Escenario', 'Resultado']

export function StepperPaso({ pasoActual = 1, mostrarNumeros = false, mostrarLeyenda = false }) {
  const total = 5
  const p = Math.max(1, Math.min(total, Number(pasoActual) || 1))

  return (
    <div className="stepper-wrapper" aria-label={`Paso ${p} de ${total}`}>
      <div className="stepper-bar" role="progressbar" aria-valuemin={1} aria-valuemax={total} aria-valuenow={p}>
        {Array.from({ length: total }).map((_, i) => {
          const stepNum = i + 1
          const state = stepNum < p ? 'done' : stepNum === p ? 'current' : 'pending'
          return (
            <div
              key={stepNum}
              className={`stepper-seg ${state}`}
              title={`${STEP_LABELS[i]} — ${state === 'done' ? 'Completo' : state === 'current' ? 'Actual' : 'Pendiente'}`}
            >
              {mostrarNumeros && (
                <span className="stepper-num">
                  {stepNum}
                </span>
              )}
            </div>
          )
        })}
      </div>
      {mostrarLeyenda && (
        <div className="stepper-leyenda" aria-hidden="true">
          {STEP_LABELS.map((lbl, i) => {
            const stepNum = i + 1
            const cls = stepNum < p ? 'sl-done' : stepNum === p ? 'sl-current' : ''
            return (
              <span key={lbl} className={cls}>{lbl}</span>
            )
          })}
        </div>
      )}
    </div>
  )
}

