import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { QRCodeCanvas } from 'qrcode.react'
import { leerJWTValido, borrarJWT, BACKEND_URL, apiUrl } from './AdminLogin.jsx'
import PdfConfigModal from './PdfConfigModal.jsx'
import '../styles/adminDashboard.css'

const TABS = ['Configuración', 'Registros', 'Códigos QR']

export default function AdminDashboard() {
  const navigate = useNavigate()
  const [activeTab, setActiveTab] = useState(0)
  const [toast, setToast] = useState(null)
  const [toastTimer, setToastTimer] = useState(null)

  const limpiarTimerToast = () => {
    if (toastTimer) {
      clearTimeout(toastTimer)
      setToastTimer(null)
    }
  }

  const mostrarToast = (mensaje, tipo = 'ok', persistente = null) => {
    limpiarTimerToast()
    const persistir = (persistente != null) ? Boolean(persistente) : (tipo === 'err')
    setToast({ msg: mensaje, tipo, persistir, id: Date.now() })
    if (!persistir) {
      const t = setTimeout(() => setToast(null), 4200)
      setToastTimer(t)
    }
  }

  const cerrarToastManual = () => {
    limpiarTimerToast()
    setToast(null)
  }

  useEffect(() => {
    if (!leerJWTValido()) {
      navigate('/admin', { replace: true })
    }
    return () => limpiarTimerToast()
  }, [navigate])

  const getAuthHeaders = () => {
    const token = leerJWTValido()
    return {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    }
  }

  const handleLogout = () => {
    borrarJWT()
    navigate('/admin', { replace: true })
  }

  return (
    <div className="screen admin-dashboard-screen">
      <div className="screen-bg admin-dashboard-bg" />

      <div className="admin-dashboard-header">
        <div className="admin-dashboard-header-top">
          <h1 className="admin-dashboard-titulo">🎛 Panel de Administración — ILV 1921</h1>
          <button type="button" className="admin-logout-btn" onClick={handleLogout}>
            Cerrar sesión
          </button>
        </div>
        <div className="admin-tabs" role="tablist">
          {TABS.map((t, i) => (
            <button
              key={t}
              role="tab"
              aria-selected={activeTab === i}
              className={`admin-tab-btn ${activeTab === i ? 'active' : ''}`}
              onClick={() => setActiveTab(i)}
              type="button"
            >
              {t}
            </button>
          ))}
        </div>
      </div>

      <div className="admin-dashboard-content">
        {activeTab === 0 && <TabConfiguracion authHeaders={getAuthHeaders} toast={mostrarToast} />}
        {activeTab === 1 && <TabRegistros authHeaders={getAuthHeaders} toast={mostrarToast} />}
        {activeTab === 2 && <TabQRCodigos authHeaders={getAuthHeaders} toast={mostrarToast} />}
      </div>

      {toast && (
        <div className={`admin-toast ${toast.tipo}${toast.persistir ? ' persistente' : ''}`} role="status">
          <div className="admin-toast-msg">{toast.msg}</div>
          {toast.persistir && (
            <button
              type="button"
              className="admin-toast-close"
              aria-label="Cerrar notificación de error"
              onClick={cerrarToastManual}
            >
              ✕ Cerrar
            </button>
          )}
        </div>
      )}
    </div>
  )
}

function TabConfiguracion({ authHeaders, toast }) {
  const [config, setConfig] = useState({
    max_ganadores: 100,
    estado: 'ABIERTO',
    titulo_premio: 'Botella Aguardiente Blanco del Valle Fiesta 750ml',
    descripcion: 'Premio por orden de llegada. Presenta cédula original.',
    dir_recogida_fuera_bogota: 'Cra. 74a #51a-87, Bogotá D.C.',
  })
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    let cancelado = false
    const cargar = async () => {
      try {
        const res = await fetch(apiUrl('/api/admin/config'), {
          method: 'GET',
          headers: authHeaders(),
        })
        if (res.ok) {
          const d = await res.json().catch(() => ({}))
          if (!cancelado && d) {
            setConfig((prev) => ({ ...prev, ...d }))
          }
        }
      } catch {
      } finally {
        if (!cancelado) setLoading(false)
      }
    }
    cargar()
    return () => { cancelado = true }
  }, [authHeaders])

  const handleGuardar = async () => {
    setSaving(true)
    try {
      const res = await fetch(apiUrl('/api/admin/config'), {
        method: 'PUT',
        headers: authHeaders(),
        body: JSON.stringify(config),
      })
      if (res.ok) {
        toast('✅ Configuración guardada correctamente', 'ok')
      } else {
        const d = await res.json().catch(() => ({}))
        toast(`❌ ${d.detail || d.message || 'No se pudo guardar'}`, 'err')
      }
    } catch {
      toast('❌ Error de conexión', 'err')
    } finally {
      setSaving(false)
    }
  }

  const abierto = config.estado === 'ABIERTO'

  return (
    <div className="admin-panel">
      <div className="admin-panel-header">
        <h2 className="admin-panel-title">⚙ Configuración General de la Promoción</h2>
      </div>
      {loading ? (
        <p style={{ color: '#64748b' }}>Cargando configuración...</p>
      ) : (
        <div className="admin-form-grid">
          <div className="admin-campo">
            <label>Máximo Ganadores (promoción)</label>
            <input
              type="number"
              min={1}
              max={99999}
              value={config.max_ganadores}
              onChange={(e) => setConfig({ ...config, max_ganadores: Number(e.target.value) || 0 })}
            />
          </div>

          <div className="admin-campo">
            <label>Estado Promoción</label>
            <div className="admin-toggle-wrap">
              <label className="admin-toggle">
                <input
                  type="checkbox"
                  checked={abierto}
                  onChange={(e) => setConfig({ ...config, estado: e.target.checked ? 'ABIERTO' : 'CERRADO' })}
                />
                <span className="admin-toggle-slider" />
              </label>
              <span className={`admin-toggle-label ${abierto ? 'on' : 'off'}`}>
                {abierto ? '🟢 ABIERTO' : '🔴 CERRADO'}
              </span>
            </div>
          </div>

          <div className="admin-campo full">
            <label>Título Premio</label>
            <textarea
              rows={2}
              value={config.titulo_premio}
              onChange={(e) => setConfig({ ...config, titulo_premio: e.target.value })}
            />
          </div>

          <div className="admin-campo full">
            <label>Descripción Premio</label>
            <textarea
              rows={3}
              value={config.descripcion}
              onChange={(e) => setConfig({ ...config, descripcion: e.target.value })}
            />
          </div>

          <div className="admin-campo full">
            <label>Dir. Recogida Fuera Bogotá</label>
            <input
              type="text"
              value={config.dir_recogida_fuera_bogota}
              onChange={(e) => setConfig({ ...config, dir_recogida_fuera_bogota: e.target.value })}
            />
          </div>

          <div className="full" style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 6 }}>
            <button
              type="button"
              className="admin-btn primary"
              onClick={handleGuardar}
              disabled={saving}
            >
              {saving ? '💾 Guardando...' : '💾 GUARDAR CAMBIOS'}
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

function TabRegistros({ authHeaders, toast }) {
  const [registros, setRegistros] = useState([])
  const [loading, setLoading] = useState(true)
  const [editRegistro, setEditRegistro] = useState(null)
  const [editForm, setEditForm] = useState({})
  const [deleteConfirm, setDeleteConfirm] = useState(null)

  const cargar = async () => {
    setLoading(true)
    try {
      const res = await fetch(apiUrl('/api/admin/registros?page=1&per_page=100'), {
        headers: authHeaders(),
      })
      if (res.ok) {
        const d = await res.json().catch(() => ({}))
        // ✅ FIX alineado: backend retorna {"items":[...], "total":N, ...} por defecto.
        // Retrocompatibilidad si alguna versión usa otras keys (registros, data).
        // Fallback orden de prioridad: items (oficial) > registros > data > array raw
        let arr = []
        if (Array.isArray(d)) {
          arr = d
        } else if (d && typeof d === 'object') {
          arr = (
            (Array.isArray(d.items) ? d.items : null) ||
            (Array.isArray(d.registros) ? d.registros : null) ||
            (Array.isArray(d.data) ? d.data : null) ||
            []
          )
        }
        setRegistros(arr)
      }
    } catch {
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { cargar() }, [authHeaders])

  const handleDescargarExcel = async () => {
    try {
      const token = leerJWTValido()
      const res = await fetch(apiUrl('/api/admin/registros/xlsx'), {
        headers: {
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
      })
      if (!res.ok) throw new Error('No se pudo descargar')
      const blob = await res.blob()
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      const d = new Date()
      const pad = n => String(n).padStart(2, '0')
      const stamp = `${d.getFullYear()}${pad(d.getMonth() + 1)}${pad(d.getDate())}-${pad(d.getHours())}${pad(d.getMinutes())}${pad(d.getSeconds())}`
      a.download = `abv-promo-registros-${stamp}.xlsx`
      document.body.appendChild(a)
      a.click()
      a.remove()
      URL.revokeObjectURL(url)
      toast('📥 Excel descargado correctamente', 'ok')
    } catch {
      toast('❌ Error descargando Excel. Revisa que el backend Python esté encendido y autenticado.', 'err')
    }
  }

  const abrirEditar = (r) => {
    setEditRegistro(r)
    setEditForm({ ...r })
  }

  const guardarEditar = async () => {
    if (!editRegistro) return
    try {
      const id = editForm.id || editForm.registro_id || editRegistro.id || editRegistro.registro_id
      const res = await fetch(apiUrl(`/api/admin/registros/${encodeURIComponent(id)}`), {
        method: 'PUT',
        headers: authHeaders(),
        body: JSON.stringify(editForm),
      })
      if (res.ok) {
        toast('✅ Registro actualizado', 'ok')
        setEditRegistro(null)
        cargar()
      } else {
        const d = await res.json().catch(() => ({}))
        toast(`❌ ${d.detail || d.message || 'Error'}`, 'err')
      }
    } catch {
      toast('❌ Error de conexión', 'err')
    }
  }

  const confirmarEliminar = (r) => {
    const posicion = r.posicion || r.pos || r.numero || 'N'
    setDeleteConfirm({ registro: r, posicion })
  }

  const ejecutarEliminar = async () => {
    if (!deleteConfirm) return
    const r = deleteConfirm.registro
    try {
      const id = r.id || r.registro_id
      const res = await fetch(apiUrl(`/api/admin/registros/${encodeURIComponent(id)}`), {
        method: 'DELETE',
        headers: authHeaders(),
      })
      if (res.ok) {
        toast(`🗑 Registro #${deleteConfirm.posicion} eliminado`, 'ok')
        setDeleteConfirm(null)
        cargar()
      } else {
        const d = await res.json().catch(() => ({}))
        toast(`❌ ${d.detail || d.message || 'Error'}`, 'err')
      }
    } catch {
      toast('❌ Error de conexión', 'err')
    }
  }

  return (
    <div className="admin-panel">
      <div className="admin-panel-header">
        <h2 className="admin-panel-title">📋 Registros de Participantes</h2>
        <button type="button" className="admin-btn success" onClick={handleDescargarExcel}>
          📥 DESCARGAR EXCEL COMPLETO (.xlsx)
        </button>
      </div>

      {loading ? (
        <p style={{ color: '#64748b' }}>Cargando registros...</p>
      ) : registros.length === 0 ? (
        <p style={{ color: '#64748b', textAlign: 'center', padding: '30px 0' }}>
          No hay registros aún.
        </p>
      ) : (
        <div className="admin-table-wrap">
          <table className="admin-table">
            <thead>
              <tr>
                <th>Pos</th>
                <th>Fecha Registro</th>
                <th>Nombres</th>
                <th>Celular</th>
                <th>Correo</th>
                <th>Ciudad</th>
                <th>Bogotá?</th>
                <th>Modalidad</th>
                <th>Ganó?</th>
                <th>Acciones</th>
              </tr>
            </thead>
            <tbody>
              {registros.map((r, idx) => {
                const pos = r.posicion || r.pos || idx + 1
                const esBta = /bogotá|bogota|santafé|santafe/i.test(r.ciudad || '')
                const gano = !!r.ganador
                return (
                  <tr key={r.id || r.registro_id || idx}>
                    <td style={{ fontWeight: 700, color: 'var(--color-azul-primario)' }}>#{pos}</td>
                    <td>{(r.fecha_registro || r.created_at || r.fecha || '').toString().slice(0, 19).replace('T', ' ')}</td>
                    <td style={{ fontWeight: 600 }}>{r.nombres_apellidos || r.nombres || '-'}</td>
                    <td>{r.celular || '-'}</td>
                    <td style={{ maxWidth: 220, overflow: 'hidden', textOverflow: 'ellipsis' }}>{r.correo_electronico || r.correo || '-'}</td>
                    <td>{r.ciudad || '-'}</td>
                    <td>{esBta ? <span className="admin-badge info">Sí</span> : <span className="admin-badge warn">No</span>}</td>
                    <td>
                      <span className={`admin-badge ${r.modalidad_entrega === 'BOGOTA_DOMICILIO' || r.modalidad === 'DOMICILIO' ? 'info' : r.modalidad_entrega === 'RECOGER_CRA74' ? 'warn' : 'ok'}`}>
                        {r.modalidad_entrega || r.modalidad || '—'}
                      </span>
                    </td>
                    <td>{gano ? <span className="admin-badge ok">SÍ</span> : <span className="admin-badge no">No</span>}</td>
                    <td>
                      <div className="admin-acciones">
                        <button type="button" className="admin-btn sm ghost" onClick={() => abrirEditar(r)}>✏ EDITAR</button>
                        <button type="button" className="admin-btn sm danger" onClick={() => confirmarEliminar(r)}>🗑 ELIMINAR</button>
                      </div>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      {editRegistro && (
        <div className="admin-modal-backdrop" onClick={() => setEditRegistro(null)}>
          <div className="admin-modal" onClick={(e) => e.stopPropagation()}>
            <h3>✏ Editar Registro #{editForm.posicion || editForm.pos || '?'}</h3>
            <div className="admin-form-grid">
              {[
                ['nombres_apellidos', 'Nombres y Apellidos', 'text'],
                ['celular', 'Celular', 'tel'],
                ['correo_electronico', 'Correo', 'email'],
                ['direccion', 'Dirección', 'text'],
                ['barrio', 'Barrio', 'text'],
                ['ciudad', 'Ciudad', 'text'],
                ['municipio', 'Municipio', 'text'],
                ['modalidad_entrega', 'Modalidad Entrega', 'text'],
              ].map(([k, lbl, type]) => (
                <div key={k} className="admin-campo">
                  <label>{lbl}</label>
                  <input
                    type={type}
                    value={editForm[k] || ''}
                    onChange={(e) => setEditForm({ ...editForm, [k]: e.target.value })}
                  />
                </div>
              ))}
              <div className="admin-campo">
                <label>¿Ganó?</label>
                <div className="admin-toggle-wrap">
                  <label className="admin-toggle">
                    <input
                      type="checkbox"
                      checked={!!editForm.ganador}
                      onChange={(e) => setEditForm({ ...editForm, ganador: e.target.checked })}
                    />
                    <span className="admin-toggle-slider" />
                  </label>
                </div>
              </div>
            </div>
            <div className="admin-modal-actions">
              <button type="button" className="admin-btn ghost" onClick={() => setEditRegistro(null)}>Cancelar</button>
              <button type="button" className="admin-btn primary" onClick={guardarEditar}>💾 Guardar</button>
            </div>
          </div>
        </div>
      )}

      {deleteConfirm && (
        <div className="admin-modal-backdrop" onClick={() => setDeleteConfirm(null)}>
          <div className="admin-modal" onClick={(e) => e.stopPropagation()}>
            <h3 style={{ color: 'var(--color-rojo-acento)' }}>⚠️ Confirmar Eliminación</h3>
            <p style={{ margin: 0, color: '#475569', lineHeight: 1.5, fontWeight: 500 }}>
              Al eliminar la persona con posición <b style={{ color: 'var(--color-rojo-acento)' }}>#{deleteConfirm.posicion}</b>,
              todas las posiciones &gt; X se <b>RESTAN 1</b> (la #31 pasa a #30, etc). <br />¿Continuar?
            </p>
            <div className="admin-modal-actions">
              <button type="button" className="admin-btn ghost" onClick={() => setDeleteConfirm(null)}>Cancelar</button>
              <button type="button" className="admin-btn danger" onClick={ejecutarEliminar}>🗑 Sí, eliminar</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

function TabQRCodigos({ authHeaders, toast }) {
  const [cantidad, setCantidad] = useState(1)
  const [tamano, setTamano] = useState(5)
  const [unidadTamaño, setUnidadTamaño] = useState('centimetros')
  const [dpi, setDpi] = useState(300)
  const [formato, setFormato] = useState('PNG')
  const [generando, setGenerando] = useState(false)
  const [resultados, setResultados] = useState([])
  const [ultimoErrorQR, setUltimoErrorQR] = useState(null) // { titulo, httpStatus, detail, body, url, stack, fechaIso }

  const [listadoTodos, setListadoTodos] = useState([])
  const [cargandoListado, setCargandoListado] = useState(false)
  const [pagListado, setPagListado] = useState(1)
  const [totalListado, setTotalListado] = useState(0)
  const [perPageListado] = useState(50)
  const [busquedaQR, setBusquedaQR] = useState('')
  const [filtroHab, setFiltroHab] = useState(null)
  const [filtroUsado, setFiltroUsado] = useState(null)
  const [confirmQR, setConfirmQR] = useState(null)

  // === MODAL CONFIGURACIÓN PDF + VISTA PREVIA ======
  const [pdfModalOpen, setPdfModalOpen] = useState(false)
  const [pdfModalModo, setPdfModalModo] = useState('recien') // 'recien' | 'historial' | 'disponibles'
  const [pdfModalExtraInfo, setPdfModalExtraInfo] = useState({ label: '', count: 0 })

  const abrirPdfModal = (modo, extra = {}) => {
    setPdfModalModo(modo)
    setPdfModalExtraInfo({ count: Number(extra && extra.count) || 0, label: extra && extra.label ? String(extra.label) : '' })
    setPdfModalOpen(true)
  }

  // Contar QRs disponibles (habilitados + no usados) en el historial actual
  const cantDisponiblesLive = () => {
    if (Array.isArray(listadoTodos) && listadoTodos.length > 0) {
      let c = 0
      for (const qr of listadoTodos) {
        const hab = qr.habilitado === true || qr.habilitado === 1 || qr.habilitado === '1' || qr.habilitado === 'true'
        const usado = !!(qr.usado_registro_id != null)
        if (hab && !usado) c++
      }
      return c
    }
    return Number(totalListado) || 0
  }

  const recalcularPx = (valor, unidad, d, returnString = false) => {
    if (unidad === 'centimetros') {
      const cm = parseFloat(valor) || 0
      const px = Math.max(256, Math.min(2048, Math.round((cm * (parseInt(d) || 300)) / 2.54)))
      return returnString ? `${px} px` : px
    } else {
      const px = Math.max(256, Math.min(2048, Math.round(parseFloat(valor) || 0)))
      return returnString ? `${px} px` : px
    }
  }

  const cargarListadoBD = async (pageOverride = pagListado) => {
    setCargandoListado(true)
    try {
      const params = new URLSearchParams()
      params.set('page', pageOverride)
      params.set('per_page', perPageListado)
      if (busquedaQR && busquedaQR.trim()) params.set('q', busquedaQR.trim())
      if (filtroHab !== null) params.set('habilitado', filtroHab ? 'true' : 'false')
      if (filtroUsado !== null) params.set('usado', filtroUsado ? 'true' : 'false')
      const urlFull = apiUrl(`/api/admin/qr/list?${params.toString()}`)
      const res = await fetch(urlFull, {
        method: 'GET',
        headers: authHeaders(),
      })
      if (res.ok) {
        const d = await res.json().catch(() => ({}))
        setListadoTodos(d.items || [])
        setTotalListado(d.total || 0)
        setPagListado(pageOverride)
      } else {
        const textoCrudo = await res.text().catch(() => '')
        let d = {}
        try { d = JSON.parse(textoCrudo) } catch {}
        const msj = d.detail || d.message || textoCrudo || `HTTP ${res.status}`
        console.error('[Admin] Cargar listado QR falló:', { status: res.status, url: urlFull, msj })
      }
    } catch (e) {
      console.error('[Admin] Cargar listado QR exception:', e && e.message)
    } finally {
      setCargandoListado(false)
    }
  }

  // Cargar listado cuando cambian los filtros (con debounce simple)
  useEffect(() => {
    const t = setTimeout(() => cargarListadoBD(1), 300)
    return () => clearTimeout(t)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [busquedaQR, filtroHab, filtroUsado])

  const handleGenerar = async () => {
    if (!cantidad || cantidad < 1 || cantidad > 5000) {
      toast('❌ Cantidad debe ser 1-5000', 'err')
      setUltimoErrorQR({
        titulo: 'Validación frontend',
        httpStatus: 400,
        detail: `Cantidad inválida = ${cantidad}. Debe estar entre 1 y 5000.`,
        fechaIso: new Date().toISOString(),
      })
      return
    }
    const sizePxFinal = recalcularPx(tamano, unidadTamaño, dpi)
    setGenerando(true)
    setUltimoErrorQR(null)
    const body = {
      cantidad,
      unidad: unidadTamaño,
      tamano_valor: parseFloat(tamano) || 0,
      dpi: parseInt(dpi) || 300,
      size_px: sizePxFinal,
      formato: formato.toLowerCase(),
    }
    const urlFull = apiUrl('/api/admin/qr/generar')
    console.groupCollapsed('%c🔧 [Admin] DEBUG Generar QR request', 'color:#0ea5e9;font-weight:bold')
    console.log('URL:', urlFull)
    console.log('METHOD: POST')
    console.log('HEADERS auth:', Object.keys(authHeaders()).join(','))
    console.log('BODY:', JSON.stringify(body, null, 2))
    console.log('Backend URL config actual (AdminLogin BACKEND_URL):', BACKEND_URL)
    console.groupEnd()

    try {
      const res = await fetch(urlFull, {
        method: 'POST',
        headers: authHeaders(),
        body: JSON.stringify(body),
      })
      console.log('%c[Admin] POST /generar QR HTTP Status =', 'color:#f59e0b;font-weight:900', res.status, res.statusText, '| ok?', res.ok)
      const textoCrudo = await res.text()
      let d = {}
      try { d = JSON.parse(textoCrudo) } catch (e) { d = { _raw_texto_html: textoCrudo.slice(0, 1200) } }
      console.log('%c[Admin] POST /generar RESPUESTA (texto/json parseado):', 'color:#94a3b8', d)

      if (res.ok) {
        const itemsGenerados = d.items || []
        setResultados(itemsGenerados)
        toast(
          `✅ ${d.created_count || itemsGenerados.length} QR(s) generados correctamente. Tamaño final: ${d.size_px_final || sizePxFinal} px` +
          (d.tamano_cm_final ? ` (${d.tamano_cm_final} cm @ ${d.dpi_final || 300} dpi)` : ''),
          'ok'
        )
        cargarListadoBD(1)
      } else {
        const msj = d.detail || d.message || d.error || d._raw_texto_html || 'No se pudieron generar los QR'
        console.error('%c🚨 ERROR RESPUESTA BACKEND /generar QR:', 'background:#b91c1c;color:white;font-weight:bold;padding:2px 6px;border-radius:4px', {
          status: res.status, statusText: res.statusText, url: urlFull, parsed: d, rawLength: textoCrudo.length,
        })
        setUltimoErrorQR({
          titulo: 'BACKEND rechazó la solicitud (HTTP ≠ 2xx)',
          httpStatus: res.status,
          detail: msj,
          url: urlFull,
          bodyEnviado: body,
          respuestaRaw: textoCrudo.slice(0, 2000),
          respuestaJson: d,
          fechaIso: new Date().toISOString(),
        })
        toast(`❌ HTTP ${res.status} · ${String(msj).slice(0, 160)}`, 'err')
      }
    } catch (e) {
      console.groupCollapsed('%c🚨 [Admin] ERROR FETCH NETWORK /generar QR (CORS/Backend caído/Timeout)', 'background:#991b1b;color:white;font-weight:bold;padding:2px 6px;border-radius:4px')
      console.error('Exception message:', e && e.message)
      console.error('Exception stack:', e && e.stack)
      console.error('URL intentada:', urlFull)
      console.error('BACKEND_URL configurado:', BACKEND_URL || '(VACIO = mismo dominio)')
      console.groupEnd()
      const msj = (e && e.message) ? `Error de conexión: ${e.message}` : 'Error de conexión con el servidor (CORS o backend caído)'
      setUltimoErrorQR({
        titulo: 'ERROR FETCH / RED / CORS / BACKEND CAÍDO',
        httpStatus: 0,
        detail: msj,
        url: urlFull,
        stack: (e && e.stack) ? String(e.stack).slice(0, 1500) : null,
        bodyEnviado: body,
        fechaIso: new Date().toISOString(),
      })
      toast(`❌ ${msj}`, 'err')
    } finally {
      setGenerando(false)
    }
  }

  const ejecutarPatchQR = async (qr, nuevoHabilitado) => {
    const id = qr.id || qr.qr_uuid || qr.uuid_qr
    try {
      const res = await fetch(apiUrl(`/api/admin/qr/${encodeURIComponent(id)}`), {
        method: 'PATCH',
        headers: authHeaders(),
        body: JSON.stringify({ habilitado: nuevoHabilitado }),
      })
      if (res.ok) {
        toast(nuevoHabilitado ? '✅ QR HABILITADO' : '🚫 QR INHABILITADO', 'ok')
        cargarListadoBD(pagListado)
        setResultados(prev => prev.map(r => {
          const match = (r.id === qr.id) || (r.qr_uuid && (r.qr_uuid === (qr.qr_uuid || qr.uuid_qr)))
          if (!match) return r
          return {
            ...r,
            habilitado: nuevoHabilitado,
            usado: (r.usado_registro_id != null) || (r.usado === true),
          }
        }))
      } else {
        const d = await res.json().catch(() => ({}))
        toast(`❌ ${d.detail || d.message || 'Error'}`, 'err')
      }
    } catch {
      toast('❌ Error de conexión', 'err')
    } finally {
      setConfirmQR(null)
    }
  }

  const ejecutarDeleteQR = async (qr) => {
    const id = qr.id || qr.qr_uuid || qr.uuid_qr
    try {
      const res = await fetch(apiUrl(`/api/admin/qr/${encodeURIComponent(id)}`), {
        method: 'DELETE',
        headers: authHeaders(),
      })
      if (res.ok) {
        toast('🗑 QR eliminado de la base de datos', 'ok')
        cargarListadoBD(pagListado)
        setResultados(prev => prev.filter(r => !(r.id === qr.id || (r.qr_uuid && r.qr_uuid === qr.uuid_qr))))
      } else {
        const d = await res.json().catch(() => ({}))
        toast(`❌ ${d.detail || d.message || 'Error eliminando'}`, 'err')
      }
    } catch {
      toast('❌ Error de conexión', 'err')
    } finally {
      setConfirmQR(null)
    }
  }

  const descargarIndividual = (qr, idx, valOverride) => {
    try {
      if (qr.data_url_png_b64 && typeof qr.data_url_png_b64 === 'string' && qr.data_url_png_b64.startsWith('data:image')) {
        const a = document.createElement('a')
        a.href = qr.data_url_png_b64
        a.download = `QR_${qr.id_humano || qr.id || 'qr'}.png`
        document.body.appendChild(a)
        a.click()
        a.remove()
        return
      }
      void valOverride
      let canvas = null
      if (typeof idx === 'number' && !Number.isNaN(idx)) {
        canvas = document.querySelector(`#qr-canvas-${idx} canvas`)
      }
      if (!canvas && qr && qr._rowCanvasSel) {
        canvas = document.querySelector(qr._rowCanvasSel)
      }
      if (!canvas) {
        toast('ℹ Descarga: QR re-genera nuevo bloque o usa 🔗 Probar → print como imagen', 'info')
        return
      }
      const url = canvas.toDataURL('image/png')
      const a = document.createElement('a')
      a.href = url
      const sufijo = (typeof idx === 'number' && !Number.isNaN(idx)) ? (idx + 1) : (qr.id_humano || qr.id || 'qr')
      a.download = `QR_${sufijo}.png`
      document.body.appendChild(a)
      a.click()
      a.remove()
    } catch (e) {
      console.error('[Admin] descargarIndividual error:', e)
      toast('❌ Error descargando QR', 'err')
    }
  }

  const descargarTodosZipFront = () => {
    toast('ℹ Descarga ZIP requiere backend; usa descarga individual', 'err')
  }

  const descargarPDF = async (body, nombreSufijo = '') => {
    const genName = () => {
      const d = new Date()
      const pad = (n) => String(n).padStart(2, '0')
      return `QRs_Fiesta_ABV_${d.getFullYear()}${pad(d.getMonth()+1)}${pad(d.getDate())}_${pad(d.getHours())}${pad(d.getMinutes())}${pad(d.getSeconds())}${nombreSufijo ? '_'+nombreSufijo : ''}.pdf`
    }
    try {
      const res = await fetch(apiUrl('/api/admin/qr/pdf'), {
        method: 'POST',
        headers: authHeaders(),
        body: JSON.stringify(body || {}),
      })
      if (res.ok) {
        const blob = await res.blob()
        const url = URL.createObjectURL(blob)
        const a = document.createElement('a')
        a.href = url
        const cdHeader = (res.headers && res.headers.get) ? res.headers.get('Content-Disposition') : ''
        let nombre = ''
        if (cdHeader && /filename="?([^"]+)"?/i.test(cdHeader)) {
          const mm = cdHeader.match(/filename="?([^"]+)"?/i)
          if (mm && mm[1]) nombre = mm[1]
        }
        a.download = nombre || genName()
        document.body.appendChild(a)
        a.click()
        a.remove()
        setTimeout(() => { try { URL.revokeObjectURL(url) } catch {} }, 1500)
        // ====== WARNING TAMAÑO QR REDUCIDO (nuevo headers backend dcdfad3 ======
        // El admin pidió cm y el layout del PDF tenía celda demasiado chica,
        // los QRs se encogieron sin avisar. Ahora backend devuelve headers X-QR-*
        // entonces si X-QRs-Reducidos-Count > 0 mostramos toast AMARILLO hint.
        let warningMsg = null
        try {
          const reducidosHdr = (res.headers && res.headers.get) ? Number(res.headers.get('X-QRs-Reducidos-Count') || '0') : 0
          if (Number.isFinite(reducidosHdr) && reducidosHdr > 0) {
            const cellW = (res.headers.get('X-QR-Cell-W-cm') || '').toString()
            const cellH = (res.headers.get('X-QR-Cell-H-cm') || '').toString()
            const cmTarget = (res.headers.get('X-QR-Cm-Target-Max') || '').toString()
            const cmEff = (res.headers.get('X-QR-Cm-Efectivo-Max') || '').toString()
            const cols = (res.headers.get('X-QR-Layout-Cols') || '').toString()
            const rows = (res.headers.get('X-QR-Layout-Rows') || '').toString()
            const partes = []
            if (cmTarget && cmEff) partes.push(`Tú pediste ~${cmTarget}cm y ${reducidosHdr} QR${reducidosHdr === 1 ? '' : 's'} sali${reducidosHdr === 1 ? '' : 'e'} en ~${cmEff}cm`)
            if (cols && rows) partes.push(`Layout actual: ${cols}×${rows} cols×filas`)
            if (cellW && cellH) partes.push(`Tamaño util celda: ${cellW}×${cellH} cm`)
            partes.push('👉 Prueba REDUCIR columnas/filas o aumentar forzar_tamano_cm.')
            warningMsg = `⚠️ ${reducidosHdr} QR${reducidosHdr === 1 ? '' : 's'} reducido${reducidosHdr === 1 ? '' : 's'} de tamaño en PDF. ${partes.join(' · ')}`
          }
        } catch {}
        if (warningMsg) {
          console.warn('%c[Admin] PDF QRs REDUCIDOS:', 'background:#713f12;color:#fde68a;padding:4px 8px;', warningMsg)
          setTimeout(() => toast(warningMsg, 'warn'), 600)
        } else {
          toast(`✅ PDF generado correctamente (${Math.round(blob.size/1024)} kB). Descarga iniciada.`, 'ok')
        }
      } else {
        const texto = await res.text().catch(() => '')
        let d = {}
        try { d = JSON.parse(texto) } catch { d = { _raw: texto.slice(0, 1200) } }
        const msj = d.detail || d.message || d.error || d._raw || `Error HTTP ${res.status}`
        toast(`❌ PDF falló: HTTP ${res.status} · ${String(msj).slice(0, 240)}`, 'err')
        setUltimoErrorQR({
          titulo: `BACKEND rechazó solicitud PDF (HTTP ${res.status})`,
          httpStatus: res.status,
          detail: msj,
          url: apiUrl('/api/admin/qr/pdf'),
          bodyEnviado: body,
          respuestaRaw: texto.slice(0, 2500),
          respuestaJson: d,
          fechaIso: new Date().toISOString(),
        })
      }
    } catch (e) {
      console.error('[Admin] descargarPDF exception:', e)
      const msj = (e && e.message) ? `Error de conexión PDF: ${e.message}` : 'Error de conexión al generar PDF'
      toast(`❌ ${msj}`, 'err')
      setUltimoErrorQR({
        titulo: 'ERROR NETWORK PDF (CORS / Backend caído / Timeout)',
        httpStatus: 0,
        detail: msj,
        url: apiUrl('/api/admin/qr/pdf'),
        stack: (e && e.stack) ? String(e.stack).slice(0, 1500) : null,
        bodyEnviado: body,
        fechaIso: new Date().toISOString(),
      })
    }
  }

  // ===== HANDLER ON-CONFIRM MODAL CONFIG PDF (junta modo + cfg del modal) =====
  const handlePdfModalConfirm = (cfgFinalDelModal) => {
    const cfg = cfgFinalDelModal && typeof cfgFinalDelModal === 'object' ? cfgFinalDelModal : {}
    let body = { ...cfg } // layout / visibilidad / margenes ya vienen del modal
    let sufijo = 'pdf'
    let qty = 0
    switch (pdfModalModo) {
      case 'recien': {
        const idsOk = (resultados || [])
          .map((r) => (r && r.id != null) ? Number(r.id) : null)
          .filter((x) => Number.isFinite(x) && x > 0)
        body.ids = idsOk
        body.max_qrs = Math.max(500, (idsOk.length + 500))
        sufijo = 'recien-generados'
        qty = idsOk.length
        break
      }
      case 'disponibles': {
        // QRs SOLAMENTE HABILITADOS + NO USADOS (exactamente lo que pediste: los que están disponibles para usar)
        body.habilitado = true
        body.usado = false
        body.q = busquedaQR && busquedaQR.trim() ? busquedaQR.trim() : null
        body.max_qrs = 5000
        sufijo = 'disponibles-sin-usar'
        qty = cantDisponiblesLive()
        break
      }
      case 'historial':
      default: {
        body.habilitado = filtroHab
        body.usado = filtroUsado
        body.q = busquedaQR && busquedaQR.trim() ? busquedaQR.trim() : null
        body.max_qrs = 1000
        sufijo = 'historial-completo'
        qty = Number(totalListado) || 0
        break
      }
    }
    setPdfModalOpen(false)
    // Ejecutar la descarga real:
    setTimeout(() => descargarPDF(body, sufijo), 30)
    // Feedback leve
    if (qty > 0) {
      toast(`⏳ Generando PDF con ~${qty} QR(s)... (${String(sufijo).toUpperCase()})`, 'ok')
    }
  }

  return (
    <div className="admin-panel">
      <div className="admin-panel-header">
        <h2 className="admin-panel-title">🔲 Códigos QR Promoción</h2>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          <button
            type="button"
            className="admin-btn ghost"
            onClick={() => cargarListadoBD(pagListado)}
            disabled={cargandoListado}
          >
            {cargandoListado ? '⏳ Cargando...' : '🔄 Recargar listado BD'}
          </button>
          {resultados.length > 0 && (
            <button
              type="button"
              className="admin-btn primary"
              onClick={() => descargarTodosZipFront()}
            >
              ⬇ Descargar TODOS ZIP (front)
            </button>
          )}
          {/* ============ 3 BOTONES PDF CON MODAL CONFIG + VISTA PREVIA ============ */}
          <button
            type="button"
            className="admin-btn success"
            onClick={() => abrirPdfModal('recien', {
              count: (resultados || []).length || 0,
              label: (resultados || []).length
                ? `✅ Exportar los ${(resultados || []).length} QR recién generados (IDs exactos arriba, mismo orden)`
                : '⚠ Primero genera códigos QR con el botón azul para exportar los recién creados.',
            })}
            disabled={(resultados || []).length === 0}
            title={(resultados || []).length
              ? `Abrir configuración PDF con vista previa · ${(resultados || []).length} QR recién generados (IDs exactos)`
              : '⚠ Primero genera códigos QR con el botón azul'}
          >
            📄 PDF Recién Generados
          </button>
          <button
            type="button"
            className="admin-btn ghost"
            style={{
              background: 'linear-gradient(180deg, #fef9c3 0%, #fde047 100%)',
              border: '1.5px solid #ca8a04',
              color: '#713f12',
              fontWeight: 800,
            }}
            onClick={() => {
              const c = cantDisponiblesLive()
              abrirPdfModal('disponibles', {
                count: c,
                label: c
                  ? `✅ Exportar los ${c} QR HABILITADOS Y SIN USAR (solo los que ESTÁN DISPONIBLES para repartir)`
                  : '⚠ No hay QRs disponibles en este momento. Genera códigos primero.',
              })
            }}
            title="Abrir configuración PDF + vista previa · Exporta SOLO los QR HABILITADOS + NO USADOS (los que aún puedes entregar)"
          >
            🟨 PDF DISPONIBLES (Solo no usados)
          </button>
          <button
            type="button"
            className="admin-btn ghost"
            style={{
              background: 'linear-gradient(180deg, #fff7ed 0%, #ffedd5 100%)',
              border: '1.5px solid #fb923c',
              color: '#9a3412',
            }}
            onClick={() => abrirPdfModal('historial', {
              count: Number(totalListado) || 0,
              label: `📚 Exportar TODO el historial de QRs. RESPETA filtros actuales (habilitado: ${
                filtroHab === null ? 'TODOS' : (filtroHab ? 'SÓLO HABILITADOS' : 'SÓLO INHABILITADOS')
              } · usado: ${
                filtroUsado === null ? 'TODOS' : (filtroUsado ? 'SÓLO USADOS' : 'SÓLO SIN USAR')
              }${busquedaQR && busquedaQR.trim() ? ` · búsqueda "${busquedaQR.trim()}"` : ''})`,
            })}
            title="Abrir configuración PDF + vista previa · Historial completo, respeta filtros (busqueda / hab / uso). Límite 1000 QRs."
          >
            📑 PDF Historial (filtros)
          </button>
        </div>
      </div>

      <div className="admin-form-grid" style={{ marginBottom: 20 }}>
        <div className="admin-campo">
          <label>Cantidad a generar (1-5000)</label>
          <input
            type="number"
            min={1}
            max={5000}
            value={cantidad}
            onChange={(e) => setCantidad(Math.max(1, Math.min(5000, Number(e.target.value) || 1)))}
          />
        </div>
        <div className="admin-campo">
          <label>Unidad de tamaño</label>
          <select value={unidadTamaño} onChange={(e) => setUnidadTamaño(e.target.value)}>
            <option value="centimetros">Centímetros (cm)</option>
            <option value="pixeles">Píxeles (px)</option>
          </select>
        </div>
        <div className="admin-campo">
          <label>
            Tamaño ({unidadTamaño === 'centimetros' ? 'cm' : 'píxeles'})
          </label>
          <input
            type="number"
            step={unidadTamaño === 'centimetros' ? 0.5 : 256}
            min={unidadTamaño === 'centimetros' ? 2 : 256}
            max={unidadTamaño === 'centimetros' ? 18 : 2048}
            value={tamano}
            onChange={(e) => setTamano(Number(e.target.value) || 0)}
          />
          <div style={{ marginTop: 4, fontSize: 11.5, color: '#64748b', lineHeight: 1.4 }}>
            Equivale ≈ <b style={{ color: '#1e293b' }}>{recalcularPx(tamano, unidadTamaño, dpi, true)}</b>
            {unidadTamaño === 'centimetros' && <span> (DPI {dpi})</span>}
          </div>
        </div>
        <div className="admin-campo" style={{ opacity: unidadTamaño === 'centimetros' ? 1 : 0.45 }}>
          <label>DPI (solo para cm — 300 estándar impresión)</label>
          <input
            type="number"
            min={72}
            max={1200}
            step={12}
            value={dpi}
            disabled={unidadTamaño !== 'centimetros'}
            onChange={(e) => setDpi(Math.max(72, Math.min(1200, Number(e.target.value) || 300)))}
          />
        </div>
        <div className="admin-campo">
          <label>Formato</label>
          <select value={formato} onChange={(e) => setFormato(e.target.value)}>
            <option value="PNG">PNG</option>
            <option value="SVG">SVG</option>
          </select>
        </div>
        <div style={{ display: 'flex', alignItems: 'flex-end' }}>
          <button
            type="button"
            className="admin-btn primary"
            style={{ width: '100%' }}
            onClick={handleGenerar}
            disabled={generando}
          >
            {generando ? '⏳ Generando...' : '✨ GENERAR QR(S)'}
          </button>
        </div>
      </div>

      {/* ================ PANEL ERROR VISIBLE PERMANENTE (si hubo error último intento) ================ */}
      {ultimoErrorQR && (
        <div
          className="admin-panel-error-qr"
          role="alert"
          style={{
            border: '2px solid #dc2626',
            borderRadius: 10,
            padding: '12px 14px 14px',
            marginTop: 14,
            marginBottom: 6,
            background:
              'linear-gradient(180deg,  #fff1f2 0%, #fee2e2 100%)',
            boxShadow: '0 2px 0 #fecaca inset, 0 10px 20px -12px rgba(220,38,38,0.55)',
            color: '#1f2937',
            overflow: 'hidden',
            position: 'relative',
            zIndex: 3,
          }}
        >
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 10, marginBottom: 8 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <div style={{
                background: '#b91c1c', color: 'white', width: 28, height: 28, borderRadius: '50%',
                display: 'grid', placeItems: 'center', fontSize: 16, fontWeight: 900, lineHeight: 1,
                boxShadow: '0 1px 2px rgba(0,0,0,0.2)',
              }}>!</div>
              <div>
                <div style={{ fontSize: 13.5, fontWeight: 800, color: '#991b1b' }}>
                  ⚠️ Error detectado al generar QR
                </div>
                <div style={{ fontSize: 11.5, color: '#7f1d1d', marginTop: 2 }}>
                  <b>Título</b>: {ultimoErrorQR.titulo} &nbsp;·&nbsp;
                  <b>HTTP</b>: {ultimoErrorQR.httpStatus || 'N/A'} &nbsp;·&nbsp;
                  <b>Hora</b>: {new Date(ultimoErrorQR.fechaIso || Date.now()).toLocaleString('es-CO')}
                </div>
              </div>
            </div>
            <div style={{ display: 'flex', gap: 6, flexShrink: 0 }}>
              <button
                type="button"
                className="admin-btn sm primary"
                style={{ padding: '4px 10px', fontSize: 12, borderRadius: 6 }}
                onClick={async () => {
                  try {
                    const txt = JSON.stringify(ultimoErrorQR, null, 2)
                    if (navigator.clipboard && navigator.clipboard.writeText) {
                      await navigator.clipboard.writeText(txt)
                      toast('📋 Error copiado al portapapeles. Pégamelo por WhatsApp!', 'ok')
                    } else {
                      prompt('Copia esto manualmente:', txt)
                    }
                  } catch {
                    prompt('Copia esto manualmente:', JSON.stringify(ultimoErrorQR, null, 2))
                  }
                }}
              >📋 COPIAR ERROR</button>
              <button
                type="button"
                className="admin-btn sm ghost"
                style={{ padding: '4px 10px', fontSize: 12, borderRadius: 6 }}
                onClick={() => setUltimoErrorQR(null)}
              >✕ Ocultar</button>
            </div>
          </div>

          <div style={{
            background: 'white',
            border: '1px solid #fecaca',
            borderRadius: 8,
            padding: '10px 12px',
            marginTop: 4,
            fontSize: 13.5,
            lineHeight: 1.55,
            color: '#7f1d1d',
            fontWeight: 700,
            wordBreak: 'break-word',
          }}>
            💬 {ultimoErrorQR.detail || '(sin mensaje)'}
          </div>

          <textarea
            readOnly
            style={{
              width: '100%',
              minHeight: 170,
              maxHeight: 360,
              marginTop: 10,
              padding: '10px 12px',
              fontSize: 11.5,
              fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Consolas, monospace',
              lineHeight: 1.5,
              color: '#1e293b',
              background: '#f8fafc',
              border: '1px solid #cbd5e1',
              borderRadius: 8,
              resize: 'vertical',
            }}
            value={JSON.stringify({
              BACKEND_URL_config: BACKEND_URL || '(VACIO = mismo dominio que frontend)',
              error: ultimoErrorQR,
            }, null, 2)}
          />
        </div>
      )}


      {resultados.length === 0 ? (
        <p style={{ color: '#64748b', textAlign: 'center', padding: '20px 0' }}>
          Configura los parámetros y pulsa GENERAR para crear códigos QR.
        </p>
      ) : (
        <>
          <h3 style={{ margin: '8px 0 14px', color: '#0f172a' }}>
            🆕 Últimos {resultados.length} QR(s) recién generados
          </h3>
          <div className="admin-qr-grid">
            {resultados.slice(0, 100).map((qr, i) => {
              const val =
                (qr.url && qr.url.startsWith('http')) ? qr.url :
                (qr.qr_value && (String(qr.qr_value).startsWith('http'))) ? qr.qr_value :
                (() => {
                  try {
                    const origen = (typeof window !== 'undefined' && window.location && window.location.origin) ? window.location.origin : ''
                    const qrUuid = qr.qr_uuid || qr.uuid_qr || qr.uuid || ''
                    return qrUuid ? `${origen}/ganador?qr=${qrUuid}` : ''
                  } catch { return '' }
                })()
              const hab = typeof qr.habilitado === 'boolean' ? qr.habilitado : (qr.habilitado === 1 || qr.habilitado === '1')
              return (
                <div key={qr.id || qr.uuid || qr.qr_uuid || i} className="admin-qr-item" style={{ opacity: hab ? 1 : 0.5 }}>
                  {val && (
                    <a
                      href={val}
                      target="_blank"
                      rel="noopener noreferrer nofollow"
                      title="Abrir link QR en pestaña nueva para probar"
                      style={{ display: 'block' }}
                    >
                      <div className="admin-qr-canvas-wrap" id={`qr-canvas-${i}`}>
                        <QRCodeCanvas
                          value={val}
                          size={128}
                          level="H"
                          includeMargin={true}
                        />
                      </div>
                    </a>
                  )}
                  {!val && (
                    <div className="admin-qr-canvas-wrap" id={`qr-canvas-${i}`}>
                      <QRCodeCanvas
                        value={String(qr.qr_uuid || qr.id_humano || 'QR')}
                        size={128}
                        level="H"
                        includeMargin={true}
                      />
                    </div>
                  )}
                  <div className="admin-qr-id">{qr.id_humano || qr.id || `QR-${i + 1}`}</div>
                  <div style={{ fontSize: 11, color: '#475569', margin: '4px 0' }}>
                    {qr.size_px ? `${qr.size_px} px` : ''}
                    {qr.tamano_cm ? ` · ${Number(qr.tamano_cm).toFixed(1)} cm` : ''}
                    {qr.dpi ? ` · ${qr.dpi} dpi` : ''}
                    {qr.unidad && qr.unidad !== 'pixeles' ? ` · ${qr.unidad}` : ''}
                  </div>
                  {val && (
                    <a
                      href={val}
                      target="_blank"
                      rel="noopener noreferrer nofollow"
                      className="admin-qr-url-link"
                      style={{
                        fontSize: 10.5,
                        color: '#1d4ed8',
                        textDecoration: 'underline',
                        textAlign: 'center',
                        wordBreak: 'break-all',
                        lineHeight: 1.35,
                        padding: '0 4px',
                        minHeight: 18,
                      }}
                      title="Probar link del QR"
                    >🔗 {String(val).length > 68 ? (String(val).slice(0, 65) + '…') : val}</a>
                  )}
                  <span className={`admin-qr-status ${qr.usado ? 'usado' : (hab ? 'sin-usar' : 'invalido')}`}>
                    {qr.usado ? 'USADO' : (hab ? 'SIN USAR' : 'INHABILITADO')}
                  </span>
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 6, width: '100%', marginTop: 6 }}>
                    {val && (
                      <button
                        type="button"
                        className="admin-btn sm success"
                        onClick={() => window.open(val, '_blank', 'noopener,noreferrer')}
                        title="Abrir el link del QR en pestaña nueva"
                      >
                        🔗 Probar link
                      </button>
                    )}
                    {!val && <div style={{ visibility: 'hidden' }} />}
                    <button type="button" className="admin-btn sm primary" onClick={() => descargarIndividual(qr, i, val)}>
                      ⬇ Descargar
                    </button>
                    {hab ? (
                      <button type="button" className="admin-btn sm ghost" onClick={() => setConfirmQR({ tipo: 'INHAB', qr })}>
                        🚫 Inhab
                      </button>
                    ) : (
                      <button type="button" className="admin-btn sm ghost" onClick={() => setConfirmQR({ tipo: 'HAB', qr })}>
                        ✅ Hab
                      </button>
                    )}
                    <button type="button" className="admin-btn sm danger" style={{ gridColumn: '1 / -1' }} onClick={() => setConfirmQR({ tipo: 'DEL', qr })}>
                      🗑 Eliminar
                    </button>
                  </div>
                </div>
              )
            })}
            {resultados.length > 100 && (
              <div style={{ gridColumn: '1 / -1', textAlign: 'center', padding: 16, color: '#64748b' }}>
                Mostrando 100 de {resultados.length} códigos generados.
              </div>
            )}
          </div>
        </>
      )}

      {/* ============================ LISTADO HISTORIAL BD ============================ */}
      <div style={{ borderTop: '1px solid #e2e8f0', marginTop: 24, paddingTop: 16 }}>
        <h3 style={{ margin: '0 0 12px', color: '#0f172a' }}>
          📚 Historial completo ({totalListado} QRs en base de datos)
        </h3>

        <div className="admin-form-grid" style={{ marginBottom: 14 }}>
          <div className="admin-campo" style={{ gridColumn: 'span 2' }}>
            <label>🔎 Buscar QR (ID, UUID, código humano)</label>
            <input
              type="text"
              value={busquedaQR}
              placeholder="Ej: ID 123, FIESTA-ABC, 550e8400-e29b..."
              onChange={(e) => setBusquedaQR(e.target.value)}
            />
          </div>
          <div className="admin-campo">
            <label>Estado habilitación</label>
            <select value={filtroHab === null ? '' : filtroHab ? '1' : '0'} onChange={(e) => {
              const v = e.target.value
              setFiltroHab(v === '' ? null : v === '1')
            }}>
              <option value="">Todos</option>
              <option value="1">✅ Sólo Habilitados</option>
              <option value="0">🚫 Sólo Inhabilitados</option>
            </select>
          </div>
          <div className="admin-campo">
            <label>Estado de uso</label>
            <select value={filtroUsado === null ? '' : filtroUsado ? '1' : '0'} onChange={(e) => {
              const v = e.target.value
              setFiltroUsado(v === '' ? null : v === '1')
            }}>
              <option value="">Todos</option>
              <option value="1">✔ Sólo Usados</option>
              <option value="0">🕒 Sólo Sin Usar</option>
            </select>
          </div>
        </div>

        {cargandoListado ? (
          <p style={{ textAlign: 'center', color: '#94a3b8' }}>⏳ Cargando listado QR desde base de datos...</p>
        ) : listadoTodos.length === 0 ? (
          <p style={{ textAlign: 'center', color: '#94a3b8' }}>
            No hay códigos QR generados todavía en la base de datos. Usa el botón GENERAR arriba.
          </p>
        ) : (
          <div style={{ overflowX: 'auto', borderRadius: 10, border: '1px solid #e2e8f0' }}>
            <table className="admin-table" style={{ width: '100%', minWidth: 900 }}>
              <thead>
                <tr>
                  <th style={{ textAlign: 'left' }}>ID</th>
                  <th style={{ textAlign: 'left' }}>Código Humano</th>
                  <th style={{ textAlign: 'left' }}>Vista Previa</th>
                  <th style={{ textAlign: 'left' }}>Tamaño</th>
                  <th style={{ textAlign: 'left' }}>Formato</th>
                  <th style={{ textAlign: 'left' }}>Estado</th>
                  <th style={{ textAlign: 'left' }}>Creado</th>
                  <th style={{ textAlign: 'center' }}>Acciones</th>
                </tr>
              </thead>
              <tbody>
                {listadoTodos.map((qr, rowIdx) => {
                  const hab = !!qr.habilitado
                  const usado = !!qr.usado
                  const linkReal =
                    (qr.url && String(qr.url).startsWith('http')) ? qr.url :
                    (qr.qr_value && String(qr.qr_value).startsWith('http')) ? qr.qr_value :
                    (() => {
                      try {
                        const origen = (typeof window !== 'undefined' && window.location && window.location.origin) ? window.location.origin : (BACKEND_URL ? BACKEND_URL.replace(/\/+$/, '') : '')
                        const qrUuid = qr.qr_uuid || qr.uuid_qr || qr.uuid || ''
                        return qrUuid ? `${origen}/ganador?qr=${qrUuid}` : ''
                      } catch { return '' }
                    })()
                  const canvasSel = `#qr-row-canvas-${qr.id} canvas`
                  return (
                    <tr key={qr.id} style={{ opacity: hab ? 1 : 0.52 }}>
                      <td style={{ color: '#475569', fontFamily: 'monospace', fontSize: 12 }}>{qr.id}</td>
                      <td style={{ fontWeight: 700, color: '#0f172a' }}>{qr.id_humano}</td>
                      <td>
                        {linkReal ? (
                          <a href={linkReal} target="_blank" rel="noopener noreferrer nofollow" title="Probar link QR en pestaña nueva">
                            <div id={`qr-row-canvas-${qr.id}`} style={{ width: 72, height: 72, background: 'white', padding: 6, border: '1px solid #cbd5e1', borderRadius: 8 }}>
                              <QRCodeCanvas value={linkReal} size={60} level="H" includeMargin={false} />
                            </div>
                          </a>
                        ) : (
                          <div id={`qr-row-canvas-${qr.id}`} style={{ width: 72, height: 72, background: 'white', padding: 6, border: '1px solid #cbd5e1', borderRadius: 8 }}>
                            <QRCodeCanvas value={qr.uuid_qr || String(qr.id)} size={60} level="H" includeMargin={false} />
                          </div>
                        )}
                      </td>
                      <td style={{ fontSize: 12.5, lineHeight: 1.4 }}>
                        <div>{qr.size_px} <span style={{ color: '#64748b' }}>px</span></div>
                        {qr.tamano_cm && (
                          <div style={{ color: '#475569' }}>
                            {Number(qr.tamano_cm).toFixed(1)} <span style={{ color: '#64748b' }}>cm</span>
                            {qr.dpi && <span style={{ color: '#64748b' }}> · {qr.dpi} dpi</span>}
                          </div>
                        )}
                        {qr.unidad && qr.unidad !== 'pixeles' && <div style={{ color: '#0284c7' }}>{qr.unidad}</div>}
                      </td>
                      <td style={{ textTransform: 'uppercase', fontWeight: 600, color: '#475569' }}>{qr.formato}</td>
                      <td>
                        <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                          <span className={`admin-qr-status ${hab ? 'sin-usar' : 'invalido'}`}>
                            {hab ? 'HABILITADO' : 'INHABILITADO'}
                          </span>
                          <span className={`admin-qr-status ${usado ? 'usado' : 'sin-usar'}`}>
                            {usado ? 'USADO' : 'SIN USAR'}
                          </span>
                        </div>
                        {linkReal && (
                          <a
                            href={linkReal}
                            target="_blank"
                            rel="noopener noreferrer nofollow"
                            title={linkReal}
                            style={{
                              marginTop: 6,
                              display: 'block',
                              fontSize: 10.5,
                              color: '#1d4ed8',
                              textDecoration: 'underline',
                              wordBreak: 'break-all',
                              lineHeight: 1.3,
                            }}
                          >🔗 Link</a>
                        )}
                      </td>
                      <td style={{ fontSize: 12, color: '#64748b', fontFamily: 'monospace' }}>
                        <div>{(qr.created_at || '').slice(0, 10)}</div>
                        <div>{(qr.created_at || '').slice(11, 19)}</div>
                      </td>
                      <td style={{ textAlign: 'center' }}>
                        <div style={{ display: 'inline-flex', flexWrap: 'wrap', gap: 6, justifyContent: 'center' }}>
                          {linkReal && (
                            <button
                              type="button"
                              className="admin-btn sm success"
                              title="Probar: abrir en pestaña nueva el link del QR"
                              onClick={() => window.open(linkReal, '_blank', 'noopener,noreferrer')}
                            >
                              🔗
                            </button>
                          )}
                          <button type="button" className="admin-btn sm primary" onClick={() => descargarIndividual({
                            ...qr,
                            url: linkReal,
                            qr_uuid: qr.qr_uuid || qr.uuid_qr,
                            _rowCanvasSel: canvasSel,
                          }, rowIdx + 10000)}>
                            ⬇
                          </button>
                          {hab ? (
                            <button type="button" className="admin-btn sm ghost" title="Inhabilitar QR" onClick={() => setConfirmQR({ tipo: 'INHAB', qr })}>
                              🚫
                            </button>
                          ) : (
                            <button type="button" className="admin-btn sm ghost" title="Rehabilitar QR" onClick={() => setConfirmQR({ tipo: 'HAB', qr })}>
                              ✅
                            </button>
                          )}
                          <button type="button" className="admin-btn sm danger" title="Eliminar QR de la base de datos" onClick={() => setConfirmQR({ tipo: 'DEL', qr })}>
                            🗑
                          </button>
                        </div>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}

        {totalListado > perPageListado && !cargandoListado && (
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: 14, color: '#475569', fontSize: 13 }}>
            <div>
              Página {pagListado} de {Math.ceil(totalListado / perPageListado)}
            </div>
            <div style={{ display: 'flex', gap: 6 }}>
              <button
                type="button"
                className="admin-btn sm ghost"
                disabled={pagListado <= 1}
                onClick={() => cargarListadoBD(pagListado - 1)}
              >
                ← Anterior
              </button>
              <button
                type="button"
                className="admin-btn sm ghost"
                disabled={pagListado >= Math.ceil(totalListado / perPageListado)}
                onClick={() => cargarListadoBD(pagListado + 1)}
              >
                Siguiente →
              </button>
            </div>
          </div>
        )}
      </div>

      {/* Modal confirmación acciones QR (INHABILITAR / HABILITAR / ELIMINAR) */}
      {confirmQR && (
        <div className="admin-modal-backdrop" onClick={() => setConfirmQR(null)}>
          <div className="admin-modal" onClick={(e) => e.stopPropagation()}>
            {confirmQR.tipo === 'INHAB' && (
              <>
                <h3 style={{ color: '#ca8a04' }}>🚫 Confirmar Inhabilitar QR</h3>
                <p style={{ color: '#475569', lineHeight: 1.5 }}>
                  Al inhabilitar el QR <b>{confirmQR.qr.id_humano || confirmQR.qr.id}</b>, cualquier persona que lo escanee recibirá "QR inhabilitado por el administrador" y NO podrá registrarse con él.
                </p>
                <p style={{ color: '#64748b', fontSize: 12.5 }}>⚠ Se puede rehabilitar más tarde (no es permanente).</p>
                <div className="admin-modal-actions">
                  <button type="button" className="admin-btn ghost" onClick={() => setConfirmQR(null)}>Cancelar</button>
                  <button type="button" className="admin-btn ghost" style={{ background: '#854d0e', color: 'white' }} onClick={() => ejecutarPatchQR(confirmQR.qr, false)}>🚫 Sí, INHABILITAR</button>
                </div>
              </>
            )}
            {confirmQR.tipo === 'HAB' && (
              <>
                <h3 style={{ color: '#047857' }}>✅ Confirmar Rehabilitar QR</h3>
                <p style={{ color: '#475569', lineHeight: 1.5 }}>
                  El QR <b>{confirmQR.qr.id_humano || confirmQR.qr.id}</b> volverá a estar habilitado para escanear y registrar personas.
                </p>
                <div className="admin-modal-actions">
                  <button type="button" className="admin-btn ghost" onClick={() => setConfirmQR(null)}>Cancelar</button>
                  <button type="button" className="admin-btn primary" onClick={() => ejecutarPatchQR(confirmQR.qr, true)}>✅ Sí, HABILITAR</button>
                </div>
              </>
            )}
            {confirmQR.tipo === 'DEL' && (
              <>
                <h3 style={{ color: 'var(--color-rojo-acento)' }}>🗑 Confirmar Eliminación QR</h3>
                <p style={{ color: '#475569', lineHeight: 1.5 }}>
                  Se eliminará el QR <b>{confirmQR.qr.id_humano || confirmQR.qr.id}</b> de la tabla <code>promo_qr_codes</code> PERMANENTEMENTE. Esta operación NO se puede deshacer.
                </p>
                <p style={{ color: '#64748b', fontSize: 12.5 }}>
                  Si el QR ya fue usado, se desasocia de los registros existentes para no romperlos.
                </p>
                <div className="admin-modal-actions">
                  <button type="button" className="admin-btn ghost" onClick={() => setConfirmQR(null)}>Cancelar</button>
                  <button type="button" className="admin-btn danger" onClick={() => ejecutarDeleteQR(confirmQR.qr)}>🗑 Sí, ELIMINAR PERMANENTEMENTE</button>
                </div>
              </>
            )}
          </div>
        </div>
      )}

      {/* ====== MODAL CONFIGURACIÓN PDF + VISTA PREVIA MINIATURA LIVE ====== */}
      <PdfConfigModal
        open={pdfModalOpen}
        onClose={() => setPdfModalOpen(false)}
        onConfirm={(cfgFinalDelModal) => handlePdfModalConfirm(cfgFinalDelModal)}
        modo={pdfModalModo}
        qtyInfo={pdfModalExtraInfo}
      />
    </div>
  )
}


