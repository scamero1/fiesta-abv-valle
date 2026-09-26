require('dotenv').config();
const express = require('express');
const cors = require('cors');
const multer = require('multer');
const path = require('path');
const fs = require('fs');
const http = require('http');
const https = require('https');
const { v4: uuidv4 } = require('uuid');
const sharp = require('sharp');

const PYTHON_BG_URL = process.env.PYTHON_BG_URL || 'http://localhost:8000';

const app = express();
const PORT = process.env.PORT || 3001;

const uploadsDir = path.join(__dirname, 'uploads');
if (!fs.existsSync(uploadsDir)) {
  fs.mkdirSync(uploadsDir, { recursive: true });
}

app.use(cors());
app.use(express.json({ limit: '50mb' }));
app.use('/static', express.static(uploadsDir));

const storage = multer.diskStorage({
  destination: (req, file, cb) => {
    cb(null, uploadsDir);
  },
  filename: (req, file, cb) => {
    const ext = path.extname(file.originalname) || '.png';
    cb(null, `${uuidv4()}${ext}`);
  },
});

const upload = multer({
  storage,
  limits: { fileSize: 50 * 1024 * 1024 },
});

app.get('/health', (req, res) => {
  res.status(200).json({ status: 'ok', uptime: process.uptime() });
});

function proxyToPythonBg(targetPath, req, res) {
  try {
    const target = new URL(targetPath, PYTHON_BG_URL);
    const lib = target.protocol === 'https:' ? https : http;

    const options = {
      method: req.method,
      hostname: target.hostname,
      port: target.port,
      path: target.pathname + (target.search || ''),
      headers: {
        ...req.headers,
        host: target.host,
      },
    };
    delete options.headers['content-length'];

    const proxyReq = lib.request(options, (proxyRes) => {
      res.writeHead(proxyRes.statusCode, {
        ...proxyRes.headers,
        'Access-Control-Allow-Origin': '*',
      });
      proxyRes.pipe(res);
    });

    proxyReq.on('error', (e) => {
      console.error('[proxy rembg] Error:', e.message);
      res.status(502).json({
        error: 'No se pudo conectar con el servicio de IA de eliminación de fondo',
        details: e.message,
        pythonUrl: PYTHON_BG_URL,
      });
    });

    req.pipe(proxyReq);
  } catch (e) {
    console.error('[proxy rembg] Excepción:', e);
    res.status(500).json({ error: e.message });
  }
}

app.post('/api/remove-bg', upload.none(), (req, res) => {
  proxyToPythonBg('/api/remove-bg', req, res);
});
app.post('/api/remove-bg-b64', express.json({ limit: '80mb' }), (req, res) => {
  proxyToPythonBg('/api/remove-bg-b64', req, res);
});

app.post('/api/compose', async (req, res) => {
  try {
    const { imgUrl, scenarioId, composicion } = req.body;

    if (!imgUrl || !scenarioId) {
      return res.status(400).json({ error: 'imgUrl y scenarioId son requeridos' });
    }

    const response = await fetch(imgUrl);
    if (!response.ok) {
      return res.status(400).json({ error: 'No se pudo descargar la imagen desde imgUrl' });
    }
    const fgBuffer = Buffer.from(await response.arrayBuffer());

    const scenarioPath = path.join(__dirname, '..', 'public', 'assets', `${scenarioId}.jpg`);
    const scenarioPathPng = path.join(__dirname, '..', 'public', 'assets', `${scenarioId}.png`);

    let bgPath = null;
    if (fs.existsSync(scenarioPath)) bgPath = scenarioPath;
    else if (fs.existsSync(scenarioPathPng)) bgPath = scenarioPathPng;

    if (!bgPath) {
      return res.status(404).json({ error: `Escenario ${scenarioId} no encontrado` });
    }

    const bgMetadata = await sharp(bgPath).metadata();
    const { width: bgWidth, height: bgHeight } = bgMetadata;

    let resize = {};
    let position = 'center';

    if (composicion === 'full') {
      resize = { width: bgWidth, height: bgHeight, fit: 'cover' };
    } else if (composicion === 'bottom') {
      resize = { width: Math.round(bgWidth * 0.9), fit: 'inside' };
      position = 'south';
    } else if (composicion === 'top') {
      resize = { width: Math.round(bgWidth * 0.9), fit: 'inside' };
      position = 'north';
    } else {
      resize = { width: Math.round(bgWidth * 0.85), height: Math.round(bgHeight * 0.85), fit: 'inside' };
    }

    const processedFg = await sharp(fgBuffer).resize(resize).toBuffer();

    const composite = await sharp(bgPath)
      .composite([{ input: processedFg, gravity: position }])
      .png()
      .toBuffer();

    const outputName = `${uuidv4()}.png`;
    const outputPath = path.join(uploadsDir, outputName);
    fs.writeFileSync(outputPath, composite);

    res.status(200).json({
      url: `/static/${outputName}`,
      filename: outputName,
    });
  } catch (error) {
    console.error('Error en compose:', error);
    res.status(500).json({ error: 'Error al componer la imagen', details: error.message });
  }
});

app.listen(PORT, () => {
  console.log(`Servidor corriendo en puerto ${PORT}`);
  console.log(`Health: http://localhost:${PORT}/health`);
  console.log(`Static: http://localhost:${PORT}/static`);
});
