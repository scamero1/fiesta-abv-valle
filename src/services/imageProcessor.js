// 🔐 LIMPIEZA ANTI-BACKTICKS / COMILLAS / ESPACIOS (igual que AdminLogin.jsx)
// Railway NO limpia variables copiadas de bloques de código Markdown.
const _cleanEnvUrl = (raw) => {
  const v = String(raw == null ? '' : raw)
    .replace(/^[\s`"'\u00A0]+/g, '')
    .replace(/[\s`"'\u00A0]+$/g, '')
  return v
}

const _envBackendBase = () =>
  _cleanEnvUrl(
    import.meta.env.VITE_BACKEND_URL ||
    import.meta.env.VITE_PROCESS_URL ||
    import.meta.env.VITE_RAILWAY_URL ||
    ''
  )

const API_CONFIG = {
  // PRIORIDAD 1: VITE_BACKEND_URL  (la que configuras en el Dashboard del Frontend Railway)
  // PRIORIDAD 2: VITE_PROCESS_URL   (legacy Fase2)
  // PRIORIDAD 3: VITE_RAILWAY_URL   (legacy)
  PROCESS_FULL_ENDPOINT: _envBackendBase(),
  // Background removal endpoint: si no hay uno específico, intenta deducirlo desde BACKEND_URL
  // (así solo con configurar VITE_BACKEND_URL ya funciona todo, sin 3 variables distintas)
  BACKGROUND_REMOVAL_ENDPOINT:
    _cleanEnvUrl(import.meta.env.VITE_BG_REMOVAL_URL || '') ||
    (() => {
      const base = _envBackendBase()
      if (!base) return ''
      return base.replace(/\/+$/, '') + '/api/remove-bg-b64'
    })(),
  BACKGROUND_REMOVAL_API_KEY: _cleanEnvUrl(import.meta.env.VITE_BG_REMOVAL_KEY || ''),
  COMPOSITION_ENDPOINT: _cleanEnvUrl(import.meta.env.VITE_COMPOSITION_URL || ''),
  UPLOAD_ENDPOINT: _cleanEnvUrl(import.meta.env.VITE_UPLOAD_URL || ''),
  LOCAL_SERVER_URL: _cleanEnvUrl(import.meta.env.VITE_LOCAL_SERVER_URL || ''),
  USE_MOCK: import.meta.env.VITE_USE_BG_MOCK === 'true',
}

const ERROR_MSG_SIN_ENDPOINTS = () => {
  const ejFase2 = 'https://abv-rembg-production.up.railway.app'
  const ejBgRemoval = `${ejFase2}/api/remove-bg-b64`
  const lines = [
    '⚠️ NO HAY ENDPOINT DE IA CONFIGURADO.',
    '',
    '👉 MÉTODO RECOMENDADO (FASE 2 — Todo en 1):',
    `   Agrega en el .env:  VITE_PROCESS_URL=${ejFase2}`,
    '   (NO es necesario agregar /api/procesar-foto, se concatena automáticamente).',
    '   Este endpoint hace TODO: IA U2Net sin fondo + composición 3 capas + marca/legal + URL pública QR.',
    '',
    '👉 Método alternativo (solo remoción de fondo, sin composición server-side):',
    `   VITE_BG_REMOVAL_URL=${ejBgRemoval}`,
    '',
    'Sin una de las dos variables configuradas NO SE PUEDE eliminar el fondo original',
    'de la foto (sofá, paredes, luces del evento) y el resultado sería incorrecto.',
    '',
    'Verifica que la tableta tenga conexión a la red del evento con internet o reintenta.',
  ]
  return lines.join('\n')
}

export async function removeBackground(imageBase64) {
  if (!API_CONFIG.BACKGROUND_REMOVAL_ENDPOINT && !API_CONFIG.USE_MOCK) {
    throw new Error(ERROR_MSG_SIN_ENDPOINTS())
  }

  try {
    if (API_CONFIG.BACKGROUND_REMOVAL_ENDPOINT) {
      const url = API_CONFIG.BACKGROUND_REMOVAL_ENDPOINT
      const isB64Endpoint = /-b64($|\?)/i.test(url) || /b64/i.test(url)
      let resultB64 = ''

      if (isB64Endpoint) {
        const headers = { 'Content-Type': 'application/json' }
        if (API_CONFIG.BACKGROUND_REMOVAL_API_KEY) {
          headers['Authorization'] = `Bearer ${API_CONFIG.BACKGROUND_REMOVAL_API_KEY}`
          headers['X-Api-Key'] = API_CONFIG.BACKGROUND_REMOVAL_API_KEY
        }
        const payload = JSON.stringify({
          image: imageBase64,
          alpha_matting: true,
          af: 240,
          ab: 10,
          ae: 10,
          az: 1,
        })
        const res = await fetch(url, { method: 'POST', headers, body: payload })
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        const json = await res.json()
        if (!json || !json.ok || !json.image) {
          throw new Error('Backend Python U2Net respondió sin imagen transparente: ' + JSON.stringify(json))
        }
        resultB64 = json.image
      } else {
        const blob = base64ToBlob(imageBase64)
        const fd = new FormData()
        fd.append('file', blob, 'photo.jpg')
        fd.append('alpha_matting', 'true')
        fd.append('af', '240')
        fd.append('ab', '10')
        fd.append('ae', '10')
        fd.append('az', '1')
        const headers = {}
        if (API_CONFIG.BACKGROUND_REMOVAL_API_KEY) {
          headers['Authorization'] = `Bearer ${API_CONFIG.BACKGROUND_REMOVAL_API_KEY}`
          headers['X-Api-Key'] = API_CONFIG.BACKGROUND_REMOVAL_API_KEY
        }
        const res = await fetch(url, { method: 'POST', headers, body: fd })
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        const data = await res.blob()
        resultB64 = await blobToBase64(data)
      }
      return resultB64
    }
  } catch (error) {
    if (API_CONFIG.USE_MOCK) {
      console.warn('Backend removal falló, usando MOCK de desarrollo (NO recomendado para evento):', error.message)
      return await removeBackgroundDevOnly(imageBase64)
    }
    throw new Error(
      '⚠️ NO SE PUDO ELIMINAR EL FONDO.\n\n' +
      'No hay conexión con el servidor de IA (U2Net Railway Python).\n' +
      `Error: ${error.message || String(error)}\n\n` +
      'Contacta al admin del evento para revisar el endpoint VITE_BG_REMOVAL_URL.'
    )
  }

  if (API_CONFIG.USE_MOCK) return await removeBackgroundDevOnly(imageBase64)
  throw new Error('Remove background no tiene endpoint ni mock habilitado.')
}

/**
 * removeBackgroundDevOnly: MOCK DE DESARROLLO, NUNCA EN PRODUCCIÓN / EVENTO.
 *
 * Este mock ES LA ÚLTIMA LÍNEA DE DEFENSA — NUNCA se usa a menos que el admin del evento
 * ponga explícitamente VITE_USE_BG_MOCK=true. A diferencia del mock anterior (que era el
 * bug CRÍTICO porque usaba FADE rectangular 3% que DEJABA el fondo original visible),
 * este mock:
 *   - NO aplica fade, viñeta, óvalo, blur ni formas geométricas.
 *   - RETORNA la foto ORIGINAL TAL CUAL COMO PNG con fondo opaco.
 *   - Así, si se ve mal, el admin sabe INMEDIATAMENTE que el endpoint Railway no funciona.
 *   - NO intenta "arreglar" nada con degradados feos. NUNCA MÁS el efecto marco difuminado.
 */
async function removeBackgroundDevOnly(imageBase64) {
  return new Promise((resolve) => {
    setTimeout(() => resolve(imageBase64), 350)
  })
}

export async function composeImage(userImageBase64, escenario, width = 1080, height = 1350) {
  const canvas = document.createElement('canvas')
  canvas.width = width
  canvas.height = height
  const ctx = canvas.getContext('2d')
  ctx.imageSmoothingEnabled = true
  ctx.imageSmoothingQuality = 'high'

  // -----------------------------------------------------------------------
  // CAPA 0 (FONDO): Escenario elegido (Cristo Rey / Calle del Sabor / Plaza Varela)
  // -----------------------------------------------------------------------
  await drawEscenarioBackground(ctx, width, height, escenario)

  // -----------------------------------------------------------------------
  // CAPA 1 (PERSONA): PNG transparente del usuario devuelto por U2Net.
  //
  // REGLAS ESTRICTAS (no se tocan sin aprobación de marca):
  //   ✗ NO shadowBlur / shadowColor — produce halo difuminado.
  //   ✗ NO filter: blur() / contrast() — borra silueta contorneada.
  //   ✗ NO globalAlpha — la IA ya entrego el canal alfa perfecto.
  //   ✗ NO masks, gradients, clipping paths, óvalos, rectángulos.
  //   ✔ SÓLO: drawImage() centrada, object-fit contain, en el piso del escenario.
  // -----------------------------------------------------------------------
  await new Promise((resolve, reject) => {
    const img = new Image()
    img.onload = () => {
      const userAspect = img.width / img.height
      const maxH = height * 0.78
      const maxW = width * 0.9
      let targetH = maxH
      let targetW = targetH * userAspect
      if (targetW > maxW) {
        targetW = maxW
        targetH = targetW / userAspect
      }
      const x = (width - targetW) * 0.5
      const y = height - targetH - Math.floor(height * 0.14)
      ctx.drawImage(img, x, y, targetW, targetH)
      resolve()
    }
    img.onerror = () => reject(new Error('No se pudo cargar la imagen transparente del usuario.'))
    img.src = userImageBase64
  })

  // -----------------------------------------------------------------------
  // CAPA 2 ELIMINADA (Usuario pide NO pintar nada dentro de foto JPG):
  // NINGÚN marco, NINGÚN logo, NINGÚN botella, NINGUNA barra legal.
  // El aviso legal sigue en la franja negra del footer HTML.
  // -----------------------------------------------------------------------
  return canvas.toDataURL('image/jpeg', 0.97)
}

async function drawEscenarioBackground(ctx, w, h, escenario) {
  ctx.save()
  if (escenario.backgroundImg) {
    const bgImg = await loadAsset(escenario.backgroundImg)
    if (bgImg) {
      const ir = bgImg.naturalWidth / bgImg.naturalHeight
      const cr = w / h
      let dw, dh, dx, dy
      if (ir > cr) {
        dh = h
        dw = h * ir
        dx = (w - dw) / 2
        dy = 0
      } else {
        dw = w
        dh = w / ir
        dx = 0
        dy = (h - dh) / 2
      }
      ctx.drawImage(bgImg, dx, dy, dw, dh)
      ctx.restore()
      return
    }
  }
  const bgGrad = ctx.createLinearGradient(0, 0, w, h)
  const colors = parseGradient(escenario.gradiente)
  bgGrad.addColorStop(0, colors[0])
  bgGrad.addColorStop(1, colors[1])
  ctx.fillStyle = bgGrad
  ctx.fillRect(0, 0, w, h)
  ctx.restore()
}

function parseGradient(str) {
  const match = str.match(/#[0-9a-fA-F]{6}/g)
  return match && match.length >= 2 ? match : ['#002a7a', '#0047BA']
}

const ASSET_CACHE = {}

// BASE_URL safety: Railway Static con subdirectorios != "/" antepone import.meta.env.BASE_URL si la ruta empieza por "/assets/".
// Fix 404 absurdo que pintaba fondo azul gradiente fallback sin los escenario.
const BASE_URL = (import.meta.env.BASE_URL || '/').replace(/\/+$/, '') + '/'
function __resolveAssetSrc(src) {
  if (!src) return src
  if (/^https?:/i.test(src) || /^data:/i.test(src) || src.startsWith('blob:')) return src
  if (src.startsWith(BASE_URL)) return src
  const rel = src.replace(/^\/+/, '')
  return BASE_URL + rel
}

function loadAsset(src) {
  const resolved = __resolveAssetSrc(src)
  if (ASSET_CACHE[resolved] && ASSET_CACHE[resolved].naturalWidth) return Promise.resolve(ASSET_CACHE[resolved])
  return new Promise((resolve, reject) => {
    if (ASSET_CACHE[resolved]) return resolve(ASSET_CACHE[resolved])
    const img = new Image()
    img.crossOrigin = 'anonymous'
    img.onload = () => { ASSET_CACHE[resolved] = img; resolve(img) }
    img.onerror = (e) => {
      console.warn('[loadAsset] 404 ❌ no resuelto=', resolved, 'original=', src)
      resolve(null)
    }
    img.src = resolved
  })
}

const LEGAL_TEXTO_FOTO = 'EL EXCESO DE ALCOHOL ES PERJUDICIAL PARA LA SALUD. PROHÍBASE EL EXPENDIO DE BEBIDAS EMBRIAGANTES A MENORES DE EDAD.'

async function drawBrandFrame(ctx, w, h, escenario) {
  ctx.save()
  ctx.restore()
}

export async function uploadProcessedImage(imageBase64) {
  const localBase = API_CONFIG.LOCAL_SERVER_URL || getLocalServerOrigin()
  try {
    const r = await fetch(localBase + '/api/guardar-foto', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        dataUrl: imageBase64,
        baseUrl: localBase,
      }),
    })
    if (r.ok) {
      const d = await r.json()
      if (d.ok && d.shareUrl) {
        return { type: 'server', url: d.shareUrl, localBlob: generateLocalDownloadUrl(imageBase64), id: d.id }
      }
    }
  } catch (e) {}
  const blobUrl = generateLocalDownloadUrl(imageBase64)
  return { type: 'blob', url: blobUrl, localBlob: blobUrl }
}

function getLocalServerOrigin() {
  if (typeof location === 'undefined') return 'http://localhost:3000'
  const { protocol, hostname } = location
  return `${protocol}//${hostname}:3000`
}

export async function shareImageDirect(imageBase64, fileName = 'Aguardiente-Fiesta.jpg') {
  const blob = base64ToBlob(imageBase64)
  const file = new File([blob], fileName, { type: blob.type })

  if (navigator.canShare && navigator.canShare({ files: [file] })) {
    try {
      await navigator.share({
        title: 'Aguardiente Blanco del Valle - FIESTA',
        text: '#ElSaborQueNosUne • Cali Siempre Inspira',
        files: [file],
      })
      return { ok: true, method: 'web-share' }
    } catch (e) {
      if (e.name !== 'AbortError') return fallbackDownload(blob, fileName)
      return { ok: false, aborted: true }
    }
  }
  return fallbackDownload(blob, fileName)
}

function fallbackDownload(blob, fileName) {
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = fileName
  document.body.appendChild(a)
  a.click()
  setTimeout(() => { URL.revokeObjectURL(a.href); a.remove() }, 1000)
  return { ok: true, method: 'download' }
}

function generateLocalDownloadUrl(base64) {
  const blob = base64ToBlob(base64)
  return URL.createObjectURL(blob)
}

/**
 * FASE 2: PIPELINE UNIFICADO EN BACKEND PYTHON RAILWAY.
 *
 * Si está configurado VITE_PROCESS_URL (o VITE_RAILWAY_URL), llama al endpoint
 *   POST /api/procesar-foto (multipart/form-data)
 * que hace TODO: (1) rembg IA U2Net sin fondo real, (2) composición 3 capas
 * (fondo, persona, marca + legal), (3) guarda en almacén y retorna
 * URL pública para el QR + preview base64 instantáneo.
 *
 * Si NO hay PROCESS_FULL_ENDPOINT configurado → fallback al pipeline local
 * (removeBackground endpoint + composeImage canvas local + guardar foto en
 * servidor offline tableta).
 */
export async function processFullPipelineServerSide(fotoBase64, escenario) {
  const base = (API_CONFIG.PROCESS_FULL_ENDPOINT || '').replace(/\/+$/, '')
  const url = base + '/api/procesar-foto'

  // ✅ MAX_RETRIES 6 (antes 4) + timeout 120s (antes 75s) para WiFi/4G inestable de EVENTOS MASIVOS.
  //    Si backend retorna HTTP 503 Service Unavailable (overloaded): reintenta automáticamente.
  //    Si hay errores de red (conexión WiFi evento se cayó, 4G intermitente): reintento 6 veces con wait creciente.
  const MAX_RETRIES = 6
  const FETCH_TIMEOUT_MS = 120000 // 2 min — Railway workers=2 en modo IA, foto grande 4G lento.

  // Diagnóstico Network Information API (si existe, Chrome Android)
  let netDiag = ''
  try {
    const conn = (typeof navigator !== 'undefined' && (navigator.connection || navigator.mozConnection || navigator.webkitConnection))
    if (conn) {
      netDiag = ` | Net: ${conn.effectiveType || ''} down~${conn.downlink || '?'}Mbps RTT~${conn.rtt || '?'}ms online=${navigator.onLine}`
    } else {
      netDiag = ` | online=${typeof navigator !== 'undefined' ? navigator.onLine : 'n/a'}`
    }
  } catch { netDiag = '' }

  console.info('[processFullPipeline] → Endpoint calculado:', {
    base_raw: API_CONFIG.PROCESS_FULL_ENDPOINT,
    base_limpio: base,
    url_final: url,
    escenario_id: escenario?.id,
    escenario_nombre: escenario?.nombre,
    net_diag: netDiag,
  })

  const fdBase = new FormData()
  fdBase.append('foto', dataUrlToBlob(fotoBase64), `foto-${Date.now()}.jpg`)
  fdBase.append('escenario', String(escenario?.id || '').toLowerCase())
  fdBase.append('alpha_matting', 'false')   // alpha_matting=False GLOBAL (2x más rápido) 🔥 Velocidad evento
  fdBase.append('af', '240')
  fdBase.append('ab', '10')
  fdBase.append('ae', '10')
  fdBase.append('az', '1')
  fdBase.append('formato', 'jpg')

  const headers = {}
  if (API_CONFIG.BACKGROUND_REMOVAL_API_KEY) {
    headers['Authorization'] = `Bearer ${API_CONFIG.BACKGROUND_REMOVAL_API_KEY}`
    headers['X-Api-Key'] = API_CONFIG.BACKGROUND_REMOVAL_API_KEY
  }

  let lastError = null
  for (let intento = 1; intento <= MAX_RETRIES; intento++) {
    let res
    let timeoutId = null
    try {
      // Timeout fetch con AbortController (evita que request se quede colgado 5min en red mala)
      const ctrl = new AbortController()
      timeoutId = setTimeout(() => ctrl.abort(new Error(`Timeout ${FETCH_TIMEOUT_MS / 1000}s — red del evento muy lenta.`)), FETCH_TIMEOUT_MS)
      res = await fetch(url, { method: 'POST', headers, body: fdBase, signal: ctrl.signal })
      clearTimeout(timeoutId)
    } catch (networkError) {
      clearTimeout(timeoutId)
      lastError = networkError
      if (intento < MAX_RETRIES) {
        // Wait creciente: intento 1=800ms, 2=1600, 3=2400, 4=3200, 5=4200, 6=5500.
        // Suficiente para que el WiFi/4G del evento se recupere en picos.
        const wait = 700 * intento + Math.floor(Math.random() * 400)
        console.warn(`[processFullPipeline] retry=${intento}/${MAX_RETRIES} network → wait=${wait}ms | err=${networkError?.message || networkError}${netDiag}`)
        await new Promise(r => setTimeout(r, wait))
        continue
      }
      const esTimeout = /timeout|abort/i.test(String(networkError?.message || ''))
      console.error('[processFullPipeline] X NETWORK ERROR fetch (agotados ' + MAX_RETRIES + ' reintentos):', networkError?.message || networkError)
      throw new Error(
        '🌐 FALLO LA CONEXIÓN CON EL SERVIDOR (RED DEL EVENTO).\n\n' +
        `Intento ${intento} de ${MAX_RETRIES}.\n\n` +
        (esTimeout ? `Tiempo máximo agotado (${FETCH_TIMEOUT_MS / 1000}s) — WiFi/4G está lento.\n\n` : '') +
        `Dominio: ${base || '(FALTA VITE_BACKEND_URL — revisa variables Railway Servicio 2 Frontend)'}\n\n` +
        `Detalle: ${networkError?.message || String(networkError)}${netDiag}\n\n` +
        'QUÉ HACER AHORA:\n' +
        '  1. Apaga y enciende el WiFi de la tableta.\n' +
        '  2. Si sigue fallando, usa Hotspot de datos móviles 4G.\n' +
        '  3. Presiona ✅ REINTENTAR cuando la red vuelva.\n' +
        '  4. Verifica Railway Proyecto: Servicio 1 Backend = VERDE (no está redeployando).'
      )
    }

    console.info('[processFullPipeline] ← HTTP Status del backend (intento ' + intento + '/' + MAX_RETRIES + '):', res.status, res.statusText)

    // ✅ HTTP 503 overloaded: reintento según Retry-After header (1s por defecto)
    if (res.status === 503) {
      let waitMs = 1000
      try {
        const json = await res.json().catch(() => null)
        waitMs = Math.min(4000, Math.max(500, ((json || {}).retry_after_ms) || ((res.headers.get('Retry-After') || '1') | 0) * 1000))
      } catch {}
      if (intento < MAX_RETRIES) {
        waitMs += Math.floor(Math.random() * 500)
        console.warn(`[processFullPipeline] retry=${intento}/${MAX_RETRIES} 503 overloaded → wait=${waitMs}ms${netDiag}`)
        await new Promise(r => setTimeout(r, waitMs))
        continue
      }
    }

    let payload = null
    try {
      payload = await res.json()
    } catch (e) {
      const txt = await res.text()
      console.error('[processFullPipeline] ← Respuesta NO JSON del backend:', txt.substring(0, 300))
      throw new Error(
        `⚠️ Backend respondió con error.\n\n` +
        `Código HTTP: ${res.status} ${res.statusText}\n\n` +
        `Respuesta corta: ${txt.substring(0, 220)}`
      )
    }
    if (!res.ok) {
      if (res.status === 503 && intento < MAX_RETRIES) continue
      console.error('[processFullPipeline] ← Backend HTTP NOT OK, payload:', payload)
      throw new Error(
        `⚠️ NO SE PUDO PROCESAR LA FOTO EN EL SERVIDOR.\n\n` +
        `Código HTTP: ${res.status}\n` +
        `Detalle: ${payload?.detail || payload?.error || JSON.stringify(payload).substring(0, 200)}\n\n` +
        `Endpoint usado: ${url}\n\n` +
        'Reintenta pulsando REINTENTAR (la foto no se pierde, se vuelve a enviar).'
      )
    }
    if (!payload?.ok || !payload?.url) {
      console.error('[processFullPipeline] ← Backend respondió OK pero faltaba .ok o .url en payload:', payload)
      throw new Error('El servidor respondió OK pero no devolvió la URL de la foto. Vuelve a intentarlo.')
    }
    const composed = payload.preview && typeof payload.preview === 'string'
      ? payload.preview
      : payload.url
    console.info('[processFullPipeline] ✅ Éxito en intento ' + intento + '/' + MAX_RETRIES + '. fotoId=' + (payload.id || 'sin-id') + ' | URL pública=' + payload.url)
    return {
      noBg: null,
      composed,
      composedServerUrl: payload.url,
      serverPreview: payload.preview || null,
      id: payload.id,
      filename: payload.filename,
      escenario_nombre: payload.escenario_nombre,
      modelo_ia: payload.modelo_ia,
      timings_ms: payload.timings_ms || null,
      type: 'server-public',
      url: payload.url,
      localBlob: generateLocalDownloadUrl(composed),
    }
  }
  // Llegar aquí significa que agotamos retries y falló en todos (503 persistentemente o error).
  throw new Error(
    `⚠️ Servidor saturado o red del evento inestable tras ${MAX_RETRIES} intentos.\n\n` +
    `Espera 2 segundos y pulsa ✅ REINTENTAR.\n\n` +
    `Endpoint: ${url}${netDiag}`
  )
}

export async function processFullPipeline(fotoBase64, escenario) {
  const tienePipelineServer = !!API_CONFIG.PROCESS_FULL_ENDPOINT
  const tieneBgRemoval = !!API_CONFIG.BACKGROUND_REMOVAL_ENDPOINT
  const tieneMock = !!API_CONFIG.USE_MOCK

  // ====== VALIDACIÓN INICIAL (único mensaje claro, NO errores encadenados) ======
  if (!tienePipelineServer && !tieneBgRemoval && !tieneMock) {
    throw new Error(ERROR_MSG_SIN_ENDPOINTS())
  }

  // ====== INTENTO 1: Pipeline server-side FASE 2 (recomendado, todo en 1) ======
  if (tienePipelineServer) {
    try {
      return await processFullPipelineServerSide(fotoBase64, escenario)
    } catch (serverError) {
      // Si hay fallback válido local (bg-removal+canvas o mock), caemos ahí.
      // Si NO lo hay, lanzamos el server error directo, no hacemos doble error.
      const puedeFallbackLocal = tieneBgRemoval || tieneMock
      console.warn('[processFullPipeline] Server-side falló; ' +
        (puedeFallbackLocal ? 'usando fallback local compose canvas.' : 'sin fallback local disponible.'))
      if (!puedeFallbackLocal) {
        throw serverError
      }
    }
  }

  // ====== INTENTO 2: Fallback local (tableta offline + bg-removal standalone) ======
  // removeBackground ya valida internamente si hay endpoint/mock.
  const noBg = await removeBackground(fotoBase64)
  const composed = await composeImage(noBg, escenario)
  const upload = await uploadProcessedImage(composed)
  return { noBg, composed, ...upload }
}

function dataUrlToBlob(dataUrl) {
  const [headerPart, dataPart] = dataUrl.split(',')
  const mimeMatch = headerPart.match(/:(.*?);/)
  const mime = mimeMatch ? mimeMatch[1] : 'image/jpeg'
  const binary = atob(dataPart)
  const len = binary.length
  const bytes = new Uint8Array(len)
  for (let i = 0; i < len; i++) bytes[i] = binary.charCodeAt(i)
  return new Blob([bytes], { type: mime })
}

function base64ToBlob(base64) {
  const parts = base64.split(',')
  const mimeMatch = parts[0].match(/:(.*?);/)
  const mime = mimeMatch ? mimeMatch[1] : 'image/jpeg'
  const binary = atob(parts[1])
  const len = binary.length
  const bytes = new Uint8Array(len)
  for (let i = 0; i < len; i++) bytes[i] = binary.charCodeAt(i)
  return new Blob([bytes], { type: mime })
}

function blobToBase64(blob) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(reader.result)
    reader.onerror = reject
    reader.readAsDataURL(blob)
  })
}
