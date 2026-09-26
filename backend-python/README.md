# Aguardiente Blanco del Valle FIESTA — Python Backend (U2Net Background Removal)

Backend **Python + FastAPI + rembg (U2Net / ISNet)** para la eliminación REAL y estricta del fondo de las fotos.

> Regla cumplida: **NUNCA** retorna el fondo original. Retorna un **PNG canal alfa perfecto** (RGBA) solo con la silueta humana.

---

## 1. ¿Qué hace?

- Recibe una foto (JPG/WebP/PNG con persona + fondo de oficina/evento).
- La procesa con el modelo **U2Net** (default) ó **ISNet General Use** (mejor en cabellos) vía la librería [rembg](https://github.com/danielgatis/rembg).
- Aplica **Alpha Matting** (umbrales 240/10) para contornos de cabello perfectos, sin recortes geométricos (NO óvalos, NO rectángulos, NO fade, NO viñeta, NO blur).
- Retorna un **PNG transparente** (RGBA) con solo a las personas.

---

## 2. Deploy en Railway (1 click)

1. Crea nuevo servicio → selecciona "Empty Service" o arrastra la carpeta `backend-python/`
2. Railway detecta `requirements.txt` + `railway.json`, instala Python 3.11, `rembg` + `onnxruntime CPU`
3. Variables opcionales:
   - `REMBG_MODEL=u2net` (recomendado) o `REMBG_MODEL=isnet-general-use`
4. Cuando deploy esté listo, copia la **URL pública** tipo `https://abv-rembg-production.up.railway.app`.
5. Esa URL la pones en el `.env` del frontend:
   ```
   VITE_BG_REMOVAL_URL=https://TU-URL-RAILWAY-PYTHON.up.railway.app/api/remove-bg
   ```

---

## 3. Endpoints

### 🔴 `POST /api/remove-bg` (multipart/form-data, RECOMENDADO)
```bash
curl -X POST -F "file=@foto.jpg" \
  https://TU-URL/api/remove-bg \
  -F "alpha_matting=true" -F "af=240" -F "ab=10" -F "ae=10" \
  --output persona-transparente.png
```
→ Respuesta: `image/png` 200 OK.

### 🔴 `POST /api/remove-bg-b64` (JSON base64)
Body:
```json
{ "image": "data:image/jpeg;base64,/9j/4AAQSkZJRg...", "alpha_matting": true }
```
→ Respuesta: `{ ok:true, image:"data:image/png;base64,...", bytes: 284719 }`

### ✅ `GET /health`
Deploy Railway lo usa para comprobar que la app viva.

---

## 4. Parámetros Alpha Matting (para contornos de cabello)

| Campo | Default | Qué hace |
|---|---|---|
| `alpha_matting` | `true` | Activa el post-proceso de contornos. **Siempre true.** |
| `af` (foreground) | `240` | Sensibilidad detectar persona. Más alto = más agresivo (210-250). |
| `ab` (background) | `10` | Sensibilidad detectar fondo. Más bajo = menos bordes negros (5-15). |
| `ae` (erode) | `10` | Cuántos px encoge el contorno. Evita halo blanco (8-14). |
| `az` (threshold) | `1` | 0-10, ajuste fino de erode. |

---

## 5. Ejecutar local

```bash
cd backend-python
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # Mac/Linux
pip install -r requirements.txt
uvicorn main:app --reload --host 0.0.0.0 --port 8000
# http://localhost:8000/health
# http://localhost:8000/docs
```
