import React, { useMemo } from 'react'

const LETTER_W_MM = 215.9
const LETTER_H_MM = 279.4
const LANDSCAPE_W_MM = LETTER_H_MM
const LANDSCAPE_H_MM = LETTER_W_MM
const PREVIEW_MAX_W_PX = 460
const PREVIEW_MAX_H_PX = 520

const clamp = (v, min, max) => Math.max(min, Math.min(max, v))

export default function PdfConfigModal({
  open,
  onClose,
  onConfirm,
  modo, // 'recien' | 'historial' | 'disponibles'
  qtyInfo, // string: descripción QRs que se exportan
  initialCfg, // objeto defaults
}) {
  const defaults = useMemo(() => Object.assign({
    cols: 3,
    filas_por_pagina: 7,
    pagina_horizontal: false,
    forzar_tamano_cm: null,
    qr_id_on_page: false,            // DEFAULT FALSE por user request: NO mostrar código humano en PDF
    incluir_id_humano: false,        // Alias del mismo flag (front usa este nombre más intuitivo)
    incluir_fecha_titulo: true,
    borde_punteado: true,
    mostrar_info_tecnica: false,     // DEFAULT FALSE por user request: NO mostrar dimensiones en PDF
    id_humano_font_size_pt: 8.5,
    info_font_size_pt: 7.0,
    margen_mm_izq: 15.0,
    margen_mm_der: 15.0,
    margen_mm_sup: 22.0,
    margen_mm_inf: 16.0,
    gap_mm_entre_celdas: 4.0,
    incluir_header_azul: true,
    incluir_footer_legal: true,
    color_header_hex: '#0033A0',
    titulo_pdf: '',
  }, initialCfg || {}), [initialCfg])

  const [cfg, setCfg] = React.useState(defaults)
  React.useEffect(() => {
    if (open) setCfg(defaults)
  }, [open, defaults])

  if (!open) return null

  const setField = (k, v) => setCfg((prev) => {
    const next = { ...prev, [k]: v }
    // Sinonimia entre incluir_id_humano y qr_id_on_page: actualizar ambos siempre
    if (k === 'incluir_id_humano') next.qr_id_on_page = Boolean(v)
    if (k === 'qr_id_on_page') next.incluir_id_humano = Boolean(v)
    return next
  })
  const toggle = (k) => setCfg((prev) => {
    const nextVal = !prev[k]
    const next = { ...prev, [k]: nextVal }
    if (k === 'incluir_id_humano') next.qr_id_on_page = Boolean(nextVal)
    if (k === 'qr_id_on_page') next.incluir_id_humano = Boolean(nextVal)
    return next
  })

  // ===== Cálculos preview miniatura =====
  const pageWmm = cfg.pagina_horizontal ? LANDSCAPE_W_MM : LETTER_W_MM
  const pageHmm = cfg.pagina_horizontal ? LANDSCAPE_H_MM : LETTER_H_MM
  const scale = Math.min(PREVIEW_MAX_W_PX / pageWmm, PREVIEW_MAX_H_PX / pageHmm)
  const pxPerMm = Math.max(0.3, scale)
  const pv = (mm) => mm * pxPerMm

  const mL = clamp(Number(cfg.margen_mm_izq) || 0, 2, 60)
  const mR = clamp(Number(cfg.margen_mm_der) || 0, 2, 60)
  const mT = clamp(Number(cfg.margen_mm_sup) || 0, 2, 80)
  const mB = clamp(Number(cfg.margen_mm_inf) || 0, 2, 60)
  const gap = clamp(Number(cfg.gap_mm_entre_celdas) || 0, 0, 20)
  const cols = clamp(Math.trunc(Number(cfg.cols) || 1), 1, 6)
  const rows = clamp(Math.trunc(Number(cfg.filas_por_pagina) || 1), 1, 12)

  const showHeader = Boolean(cfg.incluir_header_azul)
  const showFooter = Boolean(cfg.incluir_footer_legal)
  // Auto-comprime márgenes si NO header/footer y admin lo dejo default (para preview más fiel):
  const eff_mT = (!showHeader && Number(cfg.margen_mm_sup || 0) === 22) ? 10 : mT
  const eff_mB = (!showFooter && Number(cfg.margen_mm_inf || 0) === 16) ? 8 : mB

  const areaWmm = pageWmm - mL - mR
  const areaHmm = pageHmm - eff_mT - eff_mB
  const cellWmm = Math.max(1, (areaWmm - Math.max(0, cols - 1) * gap) / cols)
  const cellHmm = Math.max(1, (areaHmm - Math.max(0, rows - 1) * gap) / rows)

  // estimar # páginas por cantidad total QRs
  const qtyTotal = Number(qtyInfo && qtyInfo.count) || 0
  const perPage = cols * rows
  const estPages = qtyTotal > 0 ? Math.max(1, Math.ceil(qtyTotal / perPage)) : null

  // Cálculo cm QR estimado (preview visual)
  const id_etiqueta_h_mm = (cfg.qr_id_on_page && cfg.mostrar_info_tecnica) ? 5.0 : (cfg.qr_id_on_page ? 3 : 0)
  const qrAreaHmm = Math.max(1, cellHmm - (id_etiqueta_h_mm + 1))
  const maxSideMm = Math.max(5, Math.min(cellWmm, qrAreaHmm))
  let cmTargetMm = null
  if (cfg.forzar_tamano_cm && Number(cfg.forzar_tamano_cm) > 0) {
    cmTargetMm = Number(cfg.forzar_tamano_cm) * 10
    if (cmTargetMm > maxSideMm) cmTargetMm = maxSideMm
  } else {
    cmTargetMm = maxSideMm
  }
  const qrCmEstimado = round1(cmTargetMm / 10.0)

  function round1(x) {
    return Math.round(Number(x) * 100) / 100
  }

  const modoBadge = (() => {
    switch (modo) {
      case 'recien': return { label: 'QRs RECIÉN GENERADOS', color: '#22c55e', bg: '#dcfce7' }
      case 'disponibles': return { label: 'QRs DISPONIBLES · HABILITADOS / SIN USAR', color: '#ca8a04', bg: '#fef9c3' }
      case 'historial':
      default: return { label: 'HISTORIAL COMPLETO (respeta filtros actuales)', color: '#0ea5e9', bg: '#e0f2fe' }
    }
  })()

  const handleConfirm = () => {
    const body = {}
    // Layout:
    body.cols = cols
    body.filas_por_pagina = rows
    body.pagina_horizontal = Boolean(cfg.pagina_horizontal)
    body.forzar_tamano_cm = (cfg.forzar_tamano_cm != null && String(cfg.forzar_tamano_cm).trim() !== '')
      ? Number(cfg.forzar_tamano_cm)
      : null
    // QR visuales:
    const _incluirId = Boolean(cfg.qr_id_on_page || cfg.incluir_id_humano)
    body.qr_id_on_page = _incluirId
    body.incluir_id_humano = _incluirId
    body.mostrar_info_tecnica = Boolean(cfg.mostrar_info_tecnica)
    body.borde_punteado = Boolean(cfg.borde_punteado)
    body.id_humano_font_size_pt = clamp(Number(cfg.id_humano_font_size_pt) || 8.5, 5, 16)
    body.info_font_size_pt = clamp(Number(cfg.info_font_size_pt) || 7, 4, 14)
    // Márgenes / espaciado:
    body.margen_mm_izq = mL
    body.margen_mm_der = mR
    body.margen_mm_sup = mT
    body.margen_mm_inf = mB
    body.gap_mm_entre_celdas = gap
    // Header/footer:
    body.incluir_header_azul = showHeader
    body.incluir_footer_legal = showFooter
    body.incluir_fecha_titulo = Boolean(cfg.incluir_fecha_titulo)
    body.color_header_hex = (cfg.color_header_hex || '#0033A0').toString().trim().toUpperCase() || '#0033A0'
    if (cfg.titulo_pdf && String(cfg.titulo_pdf).trim()) {
      body.titulo_pdf = String(cfg.titulo_pdf).trim()
    }
    if (onConfirm) onConfirm(body, cols, rows, estPages)
  }

  const borderDashed = cfg.borde_punteado ? '1.2px dashed #94a3b8' : '1px solid #e2e8f0'

  return (
    <div style={{
      position: 'fixed', zIndex: 999999, inset: 0,
      background: 'rgba(2,6,23,0.55)', backdropFilter: 'blur(2px)',
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      padding: 16, overflowY: 'auto',
    }} onClick={(e) => { if (e.target === e.currentTarget) onClose && onClose() }}>
      <div style={{
        width: 'min(1120px, 100%)', background: '#ffffff',
        borderRadius: 14, boxShadow: '0 20px 60px rgba(2,6,23,0.35)',
        border: '1px solid #e2e8f0',
        display: 'flex', flexDirection: 'column',
        maxHeight: 'calc(100vh - 48px)',
      }}>
        {/* Header modal */}
        <div style={{
          padding: '18px 22px', borderBottom: '1px solid #e2e8f0',
          display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12,
        }}>
          <div>
            <div style={{ fontSize: 20, fontWeight: 800, color: '#0f172a', letterSpacing: 0.2 }}>
              🛠 Configurar Diseño PDF · Impresión QRs
            </div>
            <div style={{
              marginTop: 6, padding: '4px 10px', borderRadius: 8,
              background: modoBadge.bg, color: modoBadge.color,
              fontWeight: 700, display: 'inline-block', fontSize: 12.5,
            }}>
              MODO: {modoBadge.label}
            </div>
            <div style={{ marginTop: 4, fontSize: 13, color: '#475569' }}>
              {qtyInfo && qtyInfo.label ? qtyInfo.label : ''}
              {estPages != null ? (
                <span style={{ marginLeft: 8, fontWeight: 700, color: '#0f172a' }}>
                  · ≈ {estPages} hoja{estPages > 1 ? 's' : ''} estimada{estPages > 1 ? 's' : ''}
                </span>
              ) : null}
            </div>
          </div>
          <button
            type="button"
            onClick={() => onClose && onClose()}
            title="Cerrar"
            style={{
              width: 36, height: 36, borderRadius: 10,
              border: '1px solid #e2e8f0', background: '#f8fafc',
              color: '#0f172a', fontSize: 18, cursor: 'pointer', fontWeight: 700,
            }}
          >✕</button>
        </div>

        {/* Body */}
        <div style={{
          display: 'grid', gridTemplateColumns: '1.15fr 1fr',
          gap: 18, padding: '18px 22px',
          minHeight: 0, overflow: 'auto',
        }}>
          {/* IZQUIERDA = CONFIGURACIÓN FORMULARIO */}
          <div style={{
            display: 'flex', flexDirection: 'column', gap: 16,
            minWidth: 0,
          }}>
            {/* Sección 1: LAYOUT */}
            <fieldset style={{
              border: '1px solid #e2e8f0', borderRadius: 12, padding: '14px 16px',
              background: '#fafafa', margin: 0,
            }}>
              <legend style={{ fontWeight: 800, color: '#0f172a', padding: '0 6px', fontSize: 14 }}>
                📐 Layout hoja Carta (216 × 279 mm · Colombia)
              </legend>
              <div style={{
                display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0, 1fr))',
                gap: 12, marginTop: 6,
              }}>
                <div>
                  <label style={{ fontSize: 12.5, fontWeight: 700, color: '#1e293b' }}>Columnas / hoja</label>
                  <select
                    value={cols}
                    onChange={(e) => setField('cols', Number(e.target.value))}
                    style={inputStyle}
                  >
                    {[1,2,3,4,5,6].map((c) => (
                      <option key={c} value={c}>{c} columna{c > 1 ? 's' : ''}</option>
                    ))}
                  </select>
                  <div style={{ fontSize: 11, color: '#64748b', marginTop: 3 }}>
                    Recomendado impresión stickers: 3–4 columnas
                  </div>
                </div>
                <div>
                  <label style={{ fontSize: 12.5, fontWeight: 700, color: '#1e293b' }}>Filas / hoja</label>
                  <select
                    value={rows}
                    onChange={(e) => setField('filas_por_pagina', Number(e.target.value))}
                    style={inputStyle}
                  >
                    {[3,4,5,6,7,8,9,10,11,12].map((r) => (
                      <option key={r} value={r}>{r} filas</option>
                    ))}
                  </select>
                  <div style={{ fontSize: 11, color: '#64748b', marginTop: 3 }}>
                    Default 3 × 7 = 21 QR / hoja Retrato
                  </div>
                </div>
                <div>
                  <label style={{ fontSize: 12.5, fontWeight: 700, color: '#1e293b' }}>Orientación</label>
                  <select
                    value={cfg.pagina_horizontal ? 'L' : 'P'}
                    onChange={(e) => setField('pagina_horizontal', e.target.value === 'L')}
                    style={inputStyle}
                  >
                    <option value="P">Retrato (Vertical · 216×279mm)</option>
                    <option value="L">Paisaje (Horizontal · 279×216mm)</option>
                  </select>
                </div>
                <div>
                  <label style={{ fontSize: 12.5, fontWeight: 700, color: '#1e293b' }}>
                    Forzar tamaño CM <span style={{ color:'#94a3b8', fontWeight: 500 }}>(uniforme todos los QR)</span>
                  </label>
                  <input
                    type="number"
                    step="0.1"
                    min="0"
                    max="15"
                    placeholder="(vacío = usar cm original de cada QR)"
                    value={cfg.forzar_tamano_cm == null ? '' : cfg.forzar_tamano_cm}
                    onChange={(e) => {
                      const v = e.target.value
                      if (v === '' || v == null) setField('forzar_tamano_cm', null)
                      else setField('forzar_tamano_cm', Number(v))
                    }}
                    style={inputStyle}
                  />
                  <div style={{ fontSize: 11, color: '#16a34a', marginTop: 3, fontWeight: 600 }}>
                    ➡ Tamaño QR estimado celda: <b>{qrCmEstimado} cm</b> · {cols}×{rows}
                  </div>
                </div>
              </div>
            </fieldset>

            {/* Sección 2: MÁRGENES y ESPACIADO */}
            <fieldset style={{
              border: '1px solid #e2e8f0', borderRadius: 12, padding: '14px 16px',
              background: '#fafafa', margin: 0,
            }}>
              <legend style={{ fontWeight: 800, color: '#0f172a', padding: '0 6px', fontSize: 14 }}>
                📏 Márgenes &amp; espaciado (milímetros)
              </legend>
              <div style={{
                display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0,1fr))',
                gap: 10, marginTop: 6,
              }}>
                {[
                  { k: 'margen_mm_izq',  label: '← Izquierdo', def: 15 },
                  { k: 'margen_mm_der',  label: '→ Derecho', def: 15 },
                  { k: 'gap_mm_entre_celdas', label: '↔↕ Gap celdas', def: 4 },
                  { k: 'margen_mm_sup',  label: '↑ Superior', def: 22 },
                  { k: 'margen_mm_inf',  label: '↓ Inferior', def: 16 },
                ].map((m) => (
                  <div key={m.k}>
                    <label style={{ fontSize: 12, fontWeight: 700, color: '#1e293b' }}>{m.label}</label>
                    <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                      <input
                        type="number"
                        step="0.5"
                        min="1"
                        max="80"
                        value={cfg[m.k] ?? m.def}
                        onChange={(e) => setField(m.k, Number(e.target.value))}
                        style={{ ...inputStyle, paddingRight: 4 }}
                      />
                      <span style={{ color:'#475569', fontSize: 12 }}>mm</span>
                    </div>
                  </div>
                ))}
              </div>
              <div style={{
                marginTop: 10, display: 'flex', gap: 10, flexWrap: 'wrap',
              }}>
                <button type="button" onClick={() => setCfg({
                  ...cfg,
                  margen_mm_izq: 8, margen_mm_der: 8, margen_mm_sup: 10, margen_mm_inf: 8,
                  gap_mm_entre_celdas: 3, incluir_header_azul: false, incluir_footer_legal: false,
                  qr_id_on_page: false, incluir_id_humano: false, mostrar_info_tecnica: false,
                })} style={chipStylePreset}>
                  ⚡ Preset IMPRENTA (solo QR, sin textos ni marcas)
                </button>
                <button type="button" onClick={() => setCfg({
                  ...cfg,
                  margen_mm_izq: 15, margen_mm_der: 15, margen_mm_sup: 22, margen_mm_inf: 16,
                  gap_mm_entre_celdas: 4, incluir_header_azul: true, incluir_footer_legal: true,
                  color_header_hex: '#0033A0',
                })} style={chipStylePreset}>
                  🏠 Restablecer DEFAULT marca ILV
                </button>
              </div>
            </fieldset>

            {/* Sección 3: VISUAL QR y CONTENIDO */}
            <fieldset style={{
              border: '1px solid #e2e8f0', borderRadius: 12, padding: '14px 16px',
              background: '#fafafa', margin: 0,
            }}>
              <legend style={{ fontWeight: 800, color: '#0f172a', padding: '0 6px', fontSize: 14 }}>
                🎨 Visual QRs &amp; Contenido
              </legend>

              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginTop: 6 }}>
                {/* Toggles */}
                <Toggle label="✅ Mostrar código ID HUMANO debajo del QR" checked={Boolean(cfg.qr_id_on_page || cfg.incluir_id_humano)} onChange={() => toggle('incluir_id_humano')} />
                <Toggle label="ℹ Mostrar info dimensiones (px · cm · dpi · INHAB)" checked={cfg.mostrar_info_tecnica} onChange={() => toggle('mostrar_info_tecnica')} />
                <Toggle label="✂ Borde punteado para cortar stickers" checked={cfg.borde_punteado} onChange={() => toggle('borde_punteado')} />
                <Toggle label="🟦 Header azul ILV 1921 arriba" checked={cfg.incluir_header_azul} onChange={() => toggle('incluir_header_azul')} />
                <Toggle label="📑 Footer legal abajo" checked={cfg.incluir_footer_legal} onChange={() => toggle('incluir_footer_legal')} />
                <Toggle label="🗓 Fecha &amp; admin en subtítulo" checked={cfg.incluir_fecha_titulo} onChange={() => toggle('incluir_fecha_titulo')} disabled={!cfg.incluir_header_azul} />
              </div>

              <div style={{
                display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 12, marginTop: 14,
              }}>
                <div>
                  <label style={{ fontSize: 12, fontWeight: 700, color: '#1e293b' }}>Tamaño fuente ID (pt)</label>
                  <input type="number" step="0.5" min="5" max="16"
                    value={cfg.id_humano_font_size_pt}
                    onChange={(e) => setField('id_humano_font_size_pt', Number(e.target.value))}
                    style={inputStyle} />
                </div>
                <div>
                  <label style={{ fontSize: 12, fontWeight: 700, color: '#1e293b' }}>Tamaño fuente info (pt)</label>
                  <input type="number" step="0.5" min="4" max="14"
                    value={cfg.info_font_size_pt}
                    onChange={(e) => setField('info_font_size_pt', Number(e.target.value))}
                    style={inputStyle} />
                </div>
                <div>
                  <label style={{ fontSize: 12, fontWeight: 700, color: '#1e293b' }}>Color header (hex)</label>
                  <input type="color"
                    value={cfg.color_header_hex || '#0033A0'}
                    onChange={(e) => setField('color_header_hex', String(e.target.value).toUpperCase())}
                    style={{ ...inputStyle, padding: '2px 4px', height: 34, cursor: 'pointer' }} />
                </div>
                <div style={{ gridColumn: 'span 3' }}>
                  <label style={{ fontSize: 12, fontWeight: 700, color: '#1e293b' }}>Título personalizado PDF (opcional)</label>
                  <input
                    type="text"
                    maxLength={120}
                    placeholder="Ej: QRs Fiesta Valle - Evento Centro Comercial Andino - Día 1"
                    value={cfg.titulo_pdf || ''}
                    onChange={(e) => setField('titulo_pdf', e.target.value)}
                    style={inputStyle}
                  />
                </div>
              </div>
            </fieldset>
          </div>

          {/* DERECHA = VISTA PREVIA MINIATURA 1:1 LIVE */}
          <div style={{
            minWidth: 0, display: 'flex', flexDirection: 'column', gap: 10,
          }}>
            <div style={{
              display: 'flex', alignItems: 'baseline', justifyContent: 'space-between',
              padding: '0 4px',
            }}>
              <div style={{ fontSize: 15, fontWeight: 800, color: '#0f172a' }}>
                👁 Vista previa miniatura
              </div>
              <div style={{ fontSize: 11.5, color: '#64748b' }}>
                Escala ≈ 1 : {Math.round(1 / pxPerMm)}
              </div>
            </div>
            <div style={{
              background: '#f1f5f9',
              border: '1.5px solid #cbd5e1',
              borderRadius: 12,
              padding: 14,
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              overflow: 'hidden',
              minHeight: PREVIEW_MAX_H_PX + 28,
            }}>
              {/* HOJA DE PAPEL SIMULADA */}
              <div style={{
                width: pv(pageWmm), height: pv(pageHmm),
                background: '#ffffff',
                border: '1px solid #94a3b8',
                boxShadow: '0 6px 18px rgba(2,6,23,0.12)',
                position: 'relative',
                overflow: 'hidden',
              }}>
                {/* HEADER */}
                {showHeader ? (
                  <div style={{
                    position: 'absolute', left: 0, top: 0, right: 0,
                    height: pv(10),
                    background: cfg.color_header_hex || '#0033A0',
                    color: '#ffffff',
                    display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                    padding: `0 ${pv(2)}px`,
                    fontSize: Math.max(6, Math.round(pv(3.2))),
                    fontWeight: 800,
                  }}>
                    <span>ILV 1921 · ABV</span>
                    <span>Pág 1{estPages ? ` / ${estPages}` : ''}</span>
                  </div>
                ) : null}
                {/* SUBTÍTULO FECHA */}
                {showHeader && cfg.incluir_fecha_titulo ? (
                  <div style={{
                    position: 'absolute', left: pv(2), right: pv(2), top: pv(11),
                    display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                    fontSize: Math.max(5, Math.round(pv(2.8))),
                    color: '#0f172a', fontWeight: 700,
                  }}>
                    <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: '60%' }}>
                      {cfg.titulo_pdf ? cfg.titulo_pdf : 'Códigos QR — Fiesta · ¡Va con todo!'}
                    </span>
                    <span style={{ color: '#475569', fontWeight: 600 }}>
                      01/10/2026 06:00 PM · Admin #1
                    </span>
                  </div>
                ) : null}
                {/* FOOTER */}
                {showFooter ? (
                  <div style={{
                    position: 'absolute', left: 0, right: 0, bottom: 0,
                    height: pv(10),
                    background: '#f1f5f9',
                    borderTop: '1px solid #cbd5e1',
                    padding: `0 ${pv(2)}px`,
                    display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                    fontSize: Math.max(5, Math.round(pv(2.6))),
                    color: '#475569', fontWeight: 600,
                  }}>
                    <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: '70%' }}>
                      Uso exclusivo evento Fiesta ABV · QR 1 solo uso.
                    </span>
                    <span>{qtyTotal || 'N'} QR · {cols}×{rows}</span>
                  </div>
                ) : null}

                {/* GRID CELDAS QR */}
                <div style={{
                  position: 'absolute',
                  left: pv(mL),
                  top: pv(eff_mT),
                  width: pv(areaWmm),
                  height: pv(areaHmm),
                }}>
                  {Array.from({ length: rows }).map((_, fila) => (
                    <div key={fila} style={{
                      display: 'flex',
                      gap: pv(gap),
                      marginBottom: fila < rows - 1 ? pv(gap) : 0,
                      height: pv(cellHmm),
                    }}>
                      {Array.from({ length: cols }).map((__, col) => {
                        const idxCelda = fila * cols + col
                        const isEmpty = qtyTotal > 0 && idxCelda >= qtyTotal
                        return (
                          <div key={col} style={{
                            width: pv(cellWmm),
                            height: pv(cellHmm),
                            flex: `0 0 ${pv(cellWmm)}px`,
                            boxSizing: 'border-box',
                            borderRadius: Math.max(1, pv(0.4)),
                            border: isEmpty ? '1px dashed #f1f5f9' : borderDashed,
                            background: isEmpty ? 'rgba(248,250,252,0.3)' : '#ffffff',
                            padding: pv(0.6),
                            display: 'flex', flexDirection: 'column',
                            alignItems: 'center', justifyContent: 'space-between',
                            overflow: 'hidden',
                          }}>
                            {/* AREA QR MOCK */}
                            {!isEmpty && (
                              <div style={{
                                width: pv(cmTargetMm), height: pv(cmTargetMm),
                                marginTop: 'auto', marginBottom: 0,
                                background:
                                  'repeating-conic-gradient(#0f172a 0% 25%, #ffffff 0% 50%) 50% / 12% 12%',
                                borderRadius: Math.max(1, pv(0.3)),
                                boxShadow: 'inset 0 0 0 1px rgba(2,6,23,0.08)',
                                position: 'relative',
                              }}>
                              {/* Finder corners mock */}
                              {[
                                { l: '8%',  t: '8%'  },
                                { r: '8%',  t: '8%'  },
                                { l: '8%',  b: '8%' },
                              ].map((c, i) => (
                                <div key={i} style={{
                                  position: 'absolute',
                                  width: '20%', height: '20%',
                                  border: `${Math.max(1, Math.round(pv(0.4)))}px solid #0f172a`,
                                  background: '#ffffff',
                                  left: c.l, right: c.r, top: c.t, bottom: c.b,
                                }} />
                              ))}
                              </div>
                            )}
                            {/* ETIQUETA DEBAJO QR (ahora INDEPENDIENTE: ID e info son flags separados) */}
                            {!isEmpty && (cfg.qr_id_on_page || cfg.incluir_id_humano || cfg.mostrar_info_tecnica) ? (
                              <div style={{
                                textAlign: 'center',
                                width: '100%',
                                marginTop: 3,
                                lineHeight: 1.05,
                                padding: '0 1px',
                              }}>
                                {(cfg.qr_id_on_page || cfg.incluir_id_humano) ? (
                                  <div style={{
                                    fontWeight: 800,
                                    color: '#0f172a',
                                    fontSize: Math.max(4, Math.round(cfg.id_humano_font_size_pt * (pxPerMm / 2.8346))),
                                    fontFamily: 'monospace',
                                    whiteSpace: 'nowrap',
                                    overflow: 'hidden',
                                    textOverflow: 'ellipsis',
                                  }}>
                                    FIESTA-{String.fromCharCode(65 + (col % 26))}{String.fromCharCode(65 + (fila % 26))}X{String(fila+1).padStart(2,'0')}{String(col+1).padStart(2,'0')}
                                  </div>
                                ) : null}
                                {cfg.mostrar_info_tecnica ? (
                                  <div style={{
                                    color: '#64748b',
                                    marginTop: (cfg.qr_id_on_page || cfg.incluir_id_humano) ? 1 : 0,
                                    fontSize: Math.max(3.5, Math.round(cfg.info_font_size_pt * (pxPerMm / 2.8346))),
                                    whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
                                  }}>
                                    591px · {qrCmEstimado}cm · 300dpi
                                  </div>
                                ) : null}
                              </div>
                            ) : null}
                          </div>
                        )
                      })}
                    </div>
                  ))}
                </div>

                {/* Líneas guía márgenes (sutil) */}
                <div style={{
                  position: 'absolute',
                  left: pv(mL - 0.4), top: pv(eff_mT - 0.4),
                  right: pv(mR - 0.4), bottom: pv(eff_mB - 0.4),
                  border: `${Math.max(0.6, pv(0.15))}px dotted rgba(14,165,233,0.35)`,
                  pointerEvents: 'none',
                }} />
              </div>
            </div>
            <div style={{
              background: '#eff6ff', border: '1px solid #bfdbfe',
              borderRadius: 10, padding: '8px 12px',
              color: '#1e40af', fontSize: 12.5, fontWeight: 600,
              display: 'flex', justifyContent: 'space-between', gap: 10, flexWrap: 'wrap',
            }}>
              <span>🎯 Tamaño celda aprox: <b>{round1(cellWmm)} × {round1(cellHmm)} mm</b> ({cols}×{rows})</span>
              <span>🚀 QR físico al imprimir 100%: <b>{qrCmEstimado} cm</b></span>
            </div>
          </div>
        </div>

        {/* Footer modal */}
        <div style={{
          borderTop: '1px solid #e2e8f0',
          padding: '14px 22px',
          display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12,
          flexWrap: 'wrap',
          background: '#f8fafc',
          borderBottomLeftRadius: 14,
          borderBottomRightRadius: 14,
        }}>
          <div style={{ fontSize: 12.5, color: '#475569', maxWidth: 620 }}>
            💡 Consejo: imprime con <b>ESCALA 100%</b> (no marcar "Ajustar a página" ni "Fit to printable area") para que el QR mida exactamente {qrCmEstimado} cm.
          </div>
          <div style={{ display: 'flex', gap: 10 }}>
            <button type="button" onClick={() => onClose && onClose()} style={{
              padding: '9px 18px', borderRadius: 8, border: '1px solid #cbd5e1',
              background: '#ffffff', color: '#0f172a', fontWeight: 700, cursor: 'pointer',
              fontSize: 14,
            }}>Cancelar</button>
            <button type="button" onClick={handleConfirm} style={{
              padding: '9px 22px', borderRadius: 8, border: 'none',
              background: 'linear-gradient(180deg, #0033A0 0%, #002277 100%)',
              color: '#ffffff', fontWeight: 800, cursor: 'pointer',
              fontSize: 15, boxShadow: '0 6px 18px rgba(0,51,160,0.3)',
            }}>
              ✅ Generar PDF &amp; Descargar
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

const inputStyle = {
  width: '100%',
  height: 34,
  padding: '0 10px',
  border: '1.2px solid #cbd5e1',
  borderRadius: 8,
  background: '#ffffff',
  fontSize: 13.5,
  color: '#0f172a',
  fontWeight: 500,
  outline: 'none',
  boxSizing: 'border-box',
}

const chipStylePreset = {
  padding: '6px 12px',
  borderRadius: 999,
  border: '1.2px solid #cbd5e1',
  background: '#ffffff',
  color: '#0f172a',
  fontWeight: 700,
  cursor: 'pointer',
  fontSize: 12,
}

function Toggle({ label, checked, onChange, disabled }) {
  return (
    <label style={{
      display: 'flex', alignItems: 'center', gap: 9,
      padding: '8px 10px',
      background: disabled ? '#f1f5f9' : '#ffffff',
      border: `1.2px solid ${disabled ? '#e2e8f0' : '#cbd5e1'}`,
      borderRadius: 8,
      cursor: disabled ? 'not-allowed' : 'pointer',
      opacity: disabled ? 0.55 : 1,
      userSelect: 'none',
      color: '#0f172a',
      fontSize: 12.5,
      fontWeight: 600,
    }}>
      <div
        onClick={(e) => {
          e.preventDefault()
          if (!disabled && onChange) onChange()
        }}
        style={{
          width: 34, height: 20, borderRadius: 999,
          background: checked ? '#2563eb' : '#cbd5e1',
          position: 'relative',
          transition: 'background .15s ease',
          flexShrink: 0,
        }}
      >
        <div style={{
          position: 'absolute',
          top: 2, left: checked ? 16 : 2,
          width: 16, height: 16, borderRadius: '50%',
          background: '#ffffff',
          boxShadow: '0 1px 3px rgba(2,6,23,0.2)',
          transition: 'left .15s ease',
        }} />
      </div>
      <span>{label}</span>
    </label>
  )
}
