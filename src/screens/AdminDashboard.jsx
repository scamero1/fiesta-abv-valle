import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { QRCodeCanvas } from 'qrcode.react'
import { leerJWTValido, borrarJWT } from './AdminLogin.jsx'
import '../styles/adminDashboard.css'

const TABS = ['Configuración', 'Registros', 'Códigos QR']

export default function AdminDashboard() {
  const navigate = useNavigate()
  const [activeTab, setActiveTab] = useState(0)
  const [toast, setToast] = useState(null)

  useEffect(() => {
    if (!leerJWTValido()) {
      navigate('/admin', { replace: true })
    }
  }, [navigate])

  const mostrarToast = (mensaje, tipo = 'ok') => {
    setToast({ msg: mensaje, tipo })
    setTimeout(() => setToast(null), 3000)
  }

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
        <div className={`admin-toast ${toast.tipo}`} role="status">
          {toast.msg}
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
        const res = await fetch('/api/admin/config', {
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
      const res = await fetch('/api/admin/config', {
        method: 'PUT',
        headers: authHeaders(),
        body: JSON.stringify(config),
      })
      if (res.ok) {
        toast('✅ Configuración guardada correctamente', 'ok')
      } else {
        const d = await res.json().catch(() => ({}))
        toast(`❌ ${d.message || 'No se pudo guardar'}`, 'err')
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
      const res = await fetch('/api/admin/registros?page=1&per_page=100', {
        headers: authHeaders(),
      })
      if (res.ok) {
        const d = await res.json().catch(() => ({}))
        setRegistros(Array.isArray(d) ? d : (d.registros || d.data || []))
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
      const res = await fetch('/api/admin/registros/xlsx', {
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
      const res = await fetch(`/api/admin/registros/${encodeURIComponent(id)}`, {
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
        toast(`❌ ${d.message || 'Error'}`, 'err')
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
      const res = await fetch(`/api/admin/registros/${encodeURIComponent(id)}`, {
        method: 'DELETE',
        headers: authHeaders(),
      })
      if (res.ok) {
        toast(`🗑 Registro #${deleteConfirm.posicion} eliminado`, 'ok')
        setDeleteConfirm(null)
        cargar()
      } else {
        const d = await res.json().catch(() => ({}))
        toast(`❌ ${d.message || 'Error'}`, 'err')
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
  const [tamano, setTamano] = useState(512)
  const [formato, setFormato] = useState('PNG')
  const [generando, setGenerando] = useState(false)
  const [resultados, setResultados] = useState([])

  const handleGenerar = async () => {
    if (!cantidad || cantidad < 1 || cantidad > 5000) {
      toast('❌ Cantidad debe ser 1-5000', 'err')
      return
    }
    if (tamano < 256 || tamano > 2048) {
      toast('❌ Tamaño debe ser 256-2048', 'err')
      return
    }
    setGenerando(true)
    try {
      const res = await fetch('/api/admin/qr/generar', {
        method: 'POST',
        headers: authHeaders(),
        body: JSON.stringify({ cantidad, tamano_pixeles: tamano, formato }),
      })
      if (res.ok) {
        const d = await res.json().catch(() => ({}))
        const lista = Array.isArray(d) ? d : (d.codigos || d.qrs || d.data || [])
        setResultados(lista)
        toast(`✅ ${lista.length} código(s) QR generados`, 'ok')
      } else {
        const fallback = Array.from({ length: cantidad }).map((_, i) => ({
          id: `QR-${Date.now()}-${i + 1}`,
          id_humano: `FIESTA-${String(i + 1).padStart(6, '0')}`,
          status: 'SIN USAR',
          uuid: `${Date.now()}-${i}`,
        }))
        setResultados(fallback)
        toast(`⚠ API no disponible, ${fallback.length} QR locales`, 'err')
      }
    } catch {
      const fallback = Array.from({ length: cantidad }).map((_, i) => ({
        id: `QR-${Date.now()}-${i + 1}`,
        id_humano: `FIESTA-${String(i + 1).padStart(6, '0')}`,
        status: 'SIN USAR',
        uuid: `${Date.now()}-${i}`,
      }))
      setResultados(fallback)
      toast(`⚠ Modo offline: ${fallback.length} QR locales`, 'err')
    } finally {
      setGenerando(false)
    }
  }

  const descargarIndividual = (qr, idx) => {
    try {
      const canvas = document.querySelector(`#qr-canvas-${idx} canvas`)
      if (!canvas) {
        toast('❌ Canvas no disponible', 'err')
        return
      }
      const url = canvas.toDataURL('image/png')
      const a = document.createElement('a')
      a.href = url
      a.download = `QR_${qr.id_humano || qr.id || idx + 1}.png`
      document.body.appendChild(a)
      a.click()
      a.remove()
    } catch {
      toast('❌ Error descargando QR', 'err')
    }
  }

  const descargarTodosZipFront = () => {
    toast('ℹ Descarga ZIP requiere backend o librería JSZip', 'err')
  }

  return (
    <div className="admin-panel">
      <div className="admin-panel-header">
        <h2 className="admin-panel-title">🔲 Códigos QR Promoción</h2>
        {resultados.length > 0 && (
          <button type="button" className="admin-btn primary" onClick={descargarTodosZipFront}>
            ⬇ Descargar TODOS ZIP (front)
          </button>
        )}
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
          <label>Tamaño en píxeles (256-2048)</label>
          <input
            type="number"
            min={256}
            max={2048}
            step={256}
            value={tamano}
            onChange={(e) => setTamano(Math.max(256, Math.min(2048, Number(e.target.value) || 256)))}
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
            {generando ? '⏳ Generando...' : '✨ GENERAR'}
          </button>
        </div>
      </div>

      {resultados.length === 0 ? (
        <p style={{ color: '#64748b', textAlign: 'center', padding: '20px 0' }}>
          Configura los parámetros y pulsa GENERAR para crear códigos QR.
        </p>
      ) : (
        <div className="admin-qr-grid">
          {resultados.slice(0, 100).map((qr, i) => {
            const val = qr.qr_value || qr.uuid || qr.id_humano || qr.id || `QR-${i}`
            return (
              <div key={qr.id || qr.uuid || i} className="admin-qr-item">
                <div className="admin-qr-canvas-wrap" id={`qr-canvas-${i}`}>
                  <QRCodeCanvas
                    value={val}
                    size={128}
                    level="H"
                    includeMargin={true}
                  />
                </div>
                <div className="admin-qr-id">{qr.id_humano || qr.id_humano || qr.id || `QR-${i + 1}`}</div>
                <span className="admin-qr-status sin-usar">
                  {qr.status || qr.estado || 'SIN USAR'}
                </span>
                <button type="button" className="admin-btn sm primary" onClick={() => descargarIndividual(qr, i)}>
                  ⬇ Descargar
                </button>
              </div>
            )
          })}
          {resultados.length > 100 && (
            <div style={{ gridColumn: '1 / -1', textAlign: 'center', padding: 16, color: '#64748b' }}>
              Mostrando 100 de {resultados.length} códigos generados.
            </div>
          )}
        </div>
      )}
    </div>
  )
}

