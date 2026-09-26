const http = require('http');
const https = require('https');
const fs = require('fs');
const path = require('path');
const os = require('os');
const crypto = require('crypto');

const PORT = process.env.PORT || 3000;
const STORAGE_DIR = path.join(__dirname, '.offline-fotos');
const DIST_DIR = path.join(__dirname, 'dist');
const PYTHON_BG_URL = process.env.PYTHON_BG_URL || process.env.RAILWAY_PYTHON_URL || 'http://localhost:8000';

if (!fs.existsSync(STORAGE_DIR)) {
  fs.mkdirSync(STORAGE_DIR, { recursive: true });
}

const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'application/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.svg': 'image/svg+xml',
  '.ico': 'image/x-icon',
  '.webp': 'image/webp',
  '.woff': 'font/woff',
  '.woff2': 'font/woff2',
};

function sendJSON(res, status, data) {
  res.writeHead(status, {
    'Content-Type': 'application/json; charset=utf-8',
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Methods': 'GET,POST,OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type',
  });
  res.end(JSON.stringify(data));
}

function streamFile(res, filePath, mime, asAttachment = false) {
  const headers = {
    'Content-Type': mime,
    'Cache-Control': 'public, max-age=3600',
    'Access-Control-Allow-Origin': '*',
  };
  if (asAttachment) {
    const name = path.basename(filePath);
    headers['Content-Disposition'] = `attachment; filename="${encodeURIComponent(name)}"`;
  }
  res.writeHead(200, headers);
  fs.createReadStream(filePath).pipe(res);
}

function safeJoin(base, p) {
  const resolved = path.resolve(base, '.' + p.split('?')[0]);
  if (!resolved.startsWith(base)) return null;
  return resolved;
}

function proxyToPythonBg(targetPath, req, res) {
  try {
    const target = new URL(targetPath, PYTHON_BG_URL);
    const lib = target.protocol === 'https:' ? https : http;
    const options = {
      method: req.method,
      hostname: target.hostname,
      port: target.port,
      path: target.pathname + (target.search || ''),
      headers: { ...req.headers, host: target.host },
      timeout: 90000,
    };
    delete options.headers['content-length'];

    const proxyReq = lib.request(options, (proxyRes) => {
      const outHeaders = { ...proxyRes.headers, 'Access-Control-Allow-Origin': '*' };
      res.writeHead(proxyRes.statusCode, outHeaders);
      proxyRes.pipe(res);
    });

    proxyReq.on('timeout', () => {
      proxyReq.destroy(new Error('Timeout esperando servicio de IA (90s)'));
    });
    proxyReq.on('error', (e) => {
      console.error('[proxy rembg offline] Error:', e.message);
      sendJSON(res, 503, {
        ok: false,
        error: 'Servicio IA no disponible en esta tableta',
        detalle: e.message,
        sugerencia: 'Conecta la tableta a Wi-Fi con internet para usar el servicio en la nube, o instala rembg localmente.',
        pythonUrl: PYTHON_BG_URL,
      });
    });
    req.pipe(proxyReq);
  } catch (e) {
    console.error('[proxy rembg offline] Excepción:', e);
    sendJSON(res, 500, { ok: false, error: e.message });
  }
}

const server = http.createServer((req, res) => {
  if (req.method === 'OPTIONS') {
    res.writeHead(204, {
      'Access-Control-Allow-Origin': '*',
      'Access-Control-Allow-Methods': 'GET,POST,OPTIONS',
      'Access-Control-Allow-Headers': 'Content-Type, Authorization',
    });
    return res.end();
  }

  const url = decodeURIComponent(req.url || '/').split('?')[0];

  if (req.method === 'POST' && url === '/api/remove-bg') {
    return proxyToPythonBg('/api/remove-bg', req, res);
  }
  if (req.method === 'POST' && url === '/api/remove-bg-b64') {
    return proxyToPythonBg('/api/remove-bg-b64', req, res);
  }

  if (req.method === 'POST' && url === '/api/guardar-foto') {
    let body = '';
    req.on('data', (chunk) => { body += chunk.toString(); });
    req.on('end', () => {
      try {
        const payload = JSON.parse(body);
        if (!payload.dataUrl || !payload.dataUrl.startsWith('data:image/')) {
          return sendJSON(res, 400, { ok: false, error: 'dataUrl inválido' });
        }
        const match = payload.dataUrl.match(/^data:image\/(png|jpe?g);base64,(.+)$/);
        if (!match) return sendJSON(res, 400, { ok: false, error: 'formato no soportado' });
        const ext = match[1] === 'jpg' ? 'jpg' : match[1];
        const id = crypto.randomBytes(8).toString('hex') + '-' + Date.now();
        const fileName = `foto-${id}.${ext}`;
        const filePath = path.join(STORAGE_DIR, fileName);
        fs.writeFileSync(filePath, Buffer.from(match[2], 'base64'));
        sendJSON(res, 200, {
          ok: true,
          id,
          fileName,
          url: `/fotos/${fileName}`,
          // listo para QR
          shareUrl: payload.baseUrl ? `${payload.baseUrl}/fotos/${fileName}` : `/fotos/${fileName}`,
        });
      } catch (e) {
        sendJSON(res, 500, { ok: false, error: e.message });
      }
    });
    return;
  }

  if (req.method === 'GET' && url.startsWith('/fotos/')) {
    const rel = url.replace('/fotos/', '');
    if (rel.includes('..') || rel.includes('/') || rel.includes('\\')) {
      return sendJSON(res, 403, { ok: false });
    }
    const filePath = path.join(STORAGE_DIR, rel);
    if (!fs.existsSync(filePath)) {
      res.writeHead(404); return res.end('Not found');
    }
    const ext = path.extname(filePath).toLowerCase();
    return streamFile(res, filePath, MIME[ext] || 'application/octet-stream', true);
  }

  if (req.method === 'GET' && url === '/api/fotos-list') {
    const files = fs.readdirSync(STORAGE_DIR)
      .filter((f) => f.startsWith('foto-'))
      .sort((a, b) => fs.statSync(path.join(STORAGE_DIR, b)).mtimeMs - fs.statSync(path.join(STORAGE_DIR, a)).mtimeMs)
      .slice(0, 200)
      .map((f) => ({ name: f, url: `/fotos/${f}` }));
    return sendJSON(res, 200, { ok: true, fotos: files });
  }

  if (req.method === 'GET' && url === '/api/status') {
    return sendJSON(res, 200, {
      ok: true,
      mode: 'offline-local',
      port: PORT,
      storageDir: STORAGE_DIR,
      count: fs.readdirSync(STORAGE_DIR).filter((f) => f.startsWith('foto-')).length,
      ips: getIPs(),
    });
  }

  // SPA fallback: cualquier GET sirve el dist
  if (req.method === 'GET') {
    let filePath;
    if (url === '/' || url === '') {
      filePath = path.join(DIST_DIR, 'index.html');
    } else {
      filePath = safeJoin(DIST_DIR, url);
      if (!filePath || !fs.existsSync(filePath) || fs.statSync(filePath).isDirectory()) {
        filePath = path.join(DIST_DIR, 'index.html');
      }
    }
    if (!fs.existsSync(filePath)) {
      res.writeHead(404); return res.end('Not found');
    }
    const ext = path.extname(filePath).toLowerCase();
    return streamFile(res, filePath, MIME[ext] || 'application/octet-stream');
  }

  res.writeHead(405); res.end('Method Not Allowed');
});

function getIPs() {
  const nets = os.networkInterfaces();
  const ips = [];
  for (const name of Object.keys(nets)) {
    for (const net of nets[name]) {
      if (net.family === 'IPv4' && !net.internal) {
        ips.push({ name, address: net.address });
      }
    }
  }
  return ips;
}

server.listen(PORT, '0.0.0.0', () => {
  const ips = getIPs();
  console.log('\n🎉 SERVIDOR OFFLINE ACTIVO — Aguardiente Blanco Fiesta\n');
  console.log(`📁 App SPA servida desde:   ${DIST_DIR}`);
  console.log(`💾 Carpeta de fotos:         ${STORAGE_DIR}`);
  console.log(`📡 Puerto:                   ${PORT}\n`);
  console.log('🌐 URLs de acceso (tablet y celulares conectados a la misma red):');
  if (ips.length === 0) {
    console.log(`   • localhost:    http://localhost:${PORT}`);
    console.log('\n   ⚠️  Sin interfaces de red — Activa el Hotspot/Móvil con Wi-Fi.');
  }
  for (const ip of ips) {
    console.log(`   • [${ip.name}]  http://${ip.address}:${PORT}`);
  }
  console.log('\n📸 Las fotos generadas se guardan en carpeta .offline-fotos/');
  console.log('📲 QR de cada foto apunta a:  http://<IP_TABLET>:' + PORT + '/fotos/<archivo>.jpg');
  console.log('\n💡 Tip: activa Hotspot móvil en la tablet para que los celulares se conecten sin internet.');
});

process.on('uncaughtException', (e) => console.error('[!]', e.message));
