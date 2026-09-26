# Valle del Blanco - Backend

Backend para eliminación de fondo y composición de imágenes.

## Instalación local

```bash
cd backend
npm install
cp .env.example .env
npm run start
```

Servidor: http://localhost:3001

## Endpoints

- `GET /health` - Estado del servidor
- `POST /api/remove-bg` - Form-data campo `image` → retorna PNG transparente
- `POST /api/compose` - Body `{ imgUrl, scenarioId, composicion? }` → retorna `{ url }`
- `GET /static/*` - Archivos subidos

## Deploy en Railway

1. Subir la carpeta `backend/` a un repositorio Git
2. En Railway → **New Project** → **Deploy from GitHub repo**
3. Seleccionar el repo. Railway detecta automáticamente `railway.json`
4. Variables de entorno (opcional): agregar `PORT` en Railway → Variables
5. Click **Deploy** → listo. El startCommand es `node server.js`

## Scripts

```bash
npm run start   # Producción
npm run dev     # Desarrollo con nodemon
```
