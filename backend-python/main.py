# Python FastAPI + U2Net (rembg) Background Removal + Composición 3 capas + Store + DB
# Deploy: Railway Nixpacks Python + Volumen persistente ./public-fotos
# DB: PostgreSQL via Private Networking (sin egress $$$) — fallback SQLite local
from fastapi import FastAPI, File, UploadFile, HTTPException, Form, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from rembg import remove, new_session
from PIL import Image, ImageDraw, ImageFont, ImageFilter
import io
import base64
import uuid
import os
import time
import math
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

try:
    import psycopg
    from psycopg import sql as pgsql
    HAS_PSYCOPG = True
except Exception:
    HAS_PSYCOPG = False
    pgsql = None

# ====== PATHS / CONSTANTES GLOBALES ======
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BASE_DIR)
# PUBLIC_ASSETS: PRIMERO busca en ./backend-python/assets/ (para Railway Nixpacks: COPY . /app
# → los 3 JPG esc-cristorey/museosalsa/plazavarela están aquí).
# Fallback al antiguo PROJECT_ROOT/public/assets (desarrollo local Windows/Linux).
def _resolve_public_assets() -> str:
    env_dir = os.environ.get("PUBLIC_ASSETS_DIR", "").strip()
    if env_dir and os.path.isdir(env_dir):
        return env_dir
    p1 = os.path.join(BASE_DIR, "assets")
    if os.path.isdir(p1):
        return p1
    p2 = os.path.join(PROJECT_ROOT, "public", "assets")
    if os.path.isdir(p2):
        return p2
    os.makedirs(p1, exist_ok=True)
    return p1
PUBLIC_ASSETS = _resolve_public_assets()
STORAGE_DIR = os.environ.get("STORAGE_DIR", os.path.join(BASE_DIR, "public-fotos"))
os.makedirs(STORAGE_DIR, exist_ok=True)

# ====== DATABASE (PostgreSQL vía Private Network / fallback SQLite) ======
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
# ⚠️ Railway inyecta DATABASE_URL automáticamente AL ATTACHAR LA DB VÍA PRIVATE NETWORKING.
# NO usar el host público crossover.proxy.rlwy.net → cuesta egress.
# Host interno esperado (gratis, 0 egress): *.railway.internal en puerto 5432.
if DATABASE_URL and "proxy.rlwy.net" in DATABASE_URL:
    # Si por accidente se puso el público, advertimos en logs y NO lo usamos para evitar gasto.
    print("[DB] ⚠️ Advertencia: DATABASE_URL apunta a host público proxy.rlwy.net (egress costs). "
          "Se usará SQLite local hasta que configures el endpoint Private Network (*.railway.internal).")
    DATABASE_URL = ""

DB_ENGINE = "POSTGRES" if (HAS_PSYCOPG and DATABASE_URL and DATABASE_URL.startswith("postgres")) else "SQLITE"
SQLITE_PATH = os.path.join(BASE_DIR, "fotos-local.sqlite3")

@contextmanager
def get_db_conn():
    conn = None
    try:
        if DB_ENGINE == "POSTGRES":
            conn = psycopg.connect(DATABASE_URL, autocommit=False, connect_timeout=5)
        else:
            conn = sqlite3.connect(SQLITE_PATH, isolation_level=None, timeout=10)
            conn.row_factory = sqlite3.Row
        yield conn
        if DB_ENGINE != "POSTGRES":
            conn.commit()
    finally:
        if conn is not None:
            try:
                if DB_ENGINE != "POSTGRES":
                    conn.rollback()
            except Exception:
                pass
            try:
                conn.close()
            except Exception:
                pass

CREATE_TABLE_SQL_POSTGRES = """
CREATE TABLE IF NOT EXISTS fotos_procesadas (
    id BIGSERIAL PRIMARY KEY,
    foto_id TEXT UNIQUE NOT NULL,
    filename TEXT NOT NULL,
    url_publica TEXT NOT NULL,
    escenario_id TEXT NOT NULL,
    escenario_nombre TEXT,
    modelo_ia TEXT NOT NULL,
    alpha_matting BOOLEAN NOT NULL DEFAULT TRUE,
    canvas_w INTEGER NOT NULL,
    canvas_h INTEGER NOT NULL,
    formato TEXT NOT NULL,
    bytes_total INTEGER,
    ip_cliente TEXT,
    user_agent TEXT,
    timings JSONB,
    metadata JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_fotos_created_at ON fotos_procesadas (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_fotos_escenario ON fotos_procesadas (escenario_id);
"""

CREATE_TABLE_SQL_SQLITE = """
CREATE TABLE IF NOT EXISTS fotos_procesadas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    foto_id TEXT UNIQUE NOT NULL,
    filename TEXT NOT NULL,
    url_publica TEXT NOT NULL,
    escenario_id TEXT NOT NULL,
    escenario_nombre TEXT,
    modelo_ia TEXT NOT NULL,
    alpha_matting INTEGER NOT NULL DEFAULT 1,
    canvas_w INTEGER NOT NULL,
    canvas_h INTEGER NOT NULL,
    formato TEXT NOT NULL,
    bytes_total INTEGER,
    ip_cliente TEXT,
    user_agent TEXT,
    timings TEXT,
    metadata TEXT,
    created_at TEXT NOT NULL DEFAULT (STRFTIME('%Y-%m-%dT%H:%M:%SZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_fotos_created_at ON fotos_procesadas (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_fotos_escenario ON fotos_procesadas (escenario_id);
"""

def init_db_tables():
    with get_db_conn() as conn:
        cur = conn.cursor()
        if DB_ENGINE == "POSTGRES":
            cur.execute(CREATE_TABLE_SQL_POSTGRES)
        else:
            cur.executescript(CREATE_TABLE_SQL_SQLITE)
        if DB_ENGINE == "POSTGRES":
            conn.commit()

def insert_foto_procesada(row: dict):
    with get_db_conn() as conn:
        cur = conn.cursor()
        payload = (
            row["foto_id"],
            row["filename"],
            row["url_publica"],
            row["escenario_id"],
            row.get("escenario_nombre"),
            row["modelo_ia"],
            bool(row.get("alpha_matting", True)),
            int(row["canvas_w"]),
            int(row["canvas_h"]),
            row["formato"],
            row.get("bytes_total"),
            row.get("ip_cliente"),
            row.get("user_agent"),
            json.dumps(row.get("timings_ms"), ensure_ascii=False) if row.get("timings_ms") else None,
            json.dumps(row.get("metadata"), ensure_ascii=False) if row.get("metadata") else None,
        )
        if DB_ENGINE == "POSTGRES":
            cur.execute(
                """
                INSERT INTO fotos_procesadas
                (foto_id, filename, url_publica, escenario_id, escenario_nombre, modelo_ia,
                 alpha_matting, canvas_w, canvas_h, formato, bytes_total,
                 ip_cliente, user_agent, timings, metadata)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                payload,
            )
            rowid = cur.fetchone()
            conn.commit()
            return int(rowid[0]) if rowid else None
        else:
            cur.execute(
                """
                INSERT INTO fotos_procesadas
                (foto_id, filename, url_publica, escenario_id, escenario_nombre, modelo_ia,
                 alpha_matting, canvas_w, canvas_h, formato, bytes_total,
                 ip_cliente, user_agent, timings, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                payload,
            )
            return cur.lastrowid

def stats_fotos_db():
    with get_db_conn() as conn:
        cur = conn.cursor()
        if DB_ENGINE == "POSTGRES":
            cur.execute("SELECT COUNT(*) FROM fotos_procesadas")
            count = cur.fetchone()[0]
            cur.execute(
                """
                SELECT escenario_id, escenario_nombre, COUNT(*) AS c
                FROM fotos_procesadas GROUP BY 1,2 ORDER BY c DESC
                """
            )
            por_escenario = [{"id": r[0], "nombre": r[1], "count": int(r[2])} for r in cur.fetchall()]
            cur.execute(
                """
                SELECT foto_id, filename, url_publica, escenario_id, escenario_nombre, created_at
                FROM fotos_procesadas ORDER BY created_at DESC LIMIT 10
                """
            )
            latest = [
                {
                    "foto_id": r[0], "filename": r[1], "url": r[2],
                    "escenario_id": r[3], "escenario_nombre": r[4], "created_at": str(r[5])
                }
                for r in cur.fetchall()
            ]
        else:
            cur.execute("SELECT COUNT(*) FROM fotos_procesadas")
            count = cur.fetchone()[0]
            cur.execute(
                """
                SELECT escenario_id, escenario_nombre, COUNT(*) AS c
                FROM fotos_procesadas GROUP BY 1,2 ORDER BY c DESC
                """
            )
            por_escenario = [{"id": r[0], "nombre": r[1], "count": int(r[2])} for r in cur.fetchall()]
            cur.execute(
                """
                SELECT foto_id, filename, url_publica, escenario_id, escenario_nombre, created_at
                FROM fotos_procesadas ORDER BY created_at DESC LIMIT 10
                """
            )
            latest = [
                {
                    "foto_id": r[0], "filename": r[1], "url": r[2],
                    "escenario_id": r[3], "escenario_nombre": r[4], "created_at": str(r[5])
                }
                for r in cur.fetchall()
            ]
    return {
        "engine": DB_ENGINE,
        "count": int(count),
        "por_escenario": por_escenario,
        "latest": latest,
    }


CANVAS_W = 1920
CANVAS_H = 1080  # Relación 16:9 HORIZONTAL (Full HD) — para fotos anchas de evento
JPEG_QUALITY = 95

# ============ RECTÁNGULO BLANCO INTERNO (MARCO) COMÚN A LOS 3 JPG DE FONDO ========
# Medido exactamente desde los JPG originales Cristo Rey / Museo Salsa / Plaza Varela:
#   - Borde azul exterior: 0..CANVAS_W / 0..CANVAS_H
#   - Marco BLANCO INTERNO donde va la persona:
FRAME_X1 = 54     # px desde el borde izquierdo (azul) hasta el blanco empieza
FRAME_Y1 = 86     # px desde el borde superior (azul, CRISTO REY/MUSEO/PLAZA title) hasta blanco empieza
FRAME_X2 = 1866   # px desde el izquierdo hasta el fin blanco (empieza azul dcha)
FRAME_Y2 = 970    # px desde arriba hasta fin blanco (empieza franja legal al pie blanca)
FRAME_W = FRAME_X2 - FRAME_X1   # 1812 px ancho útil interno
FRAME_H = FRAME_Y2 - FRAME_Y1   # 884 px alto útil interno (NO se usa, pero útil)

# Colores Manual ILV MARCA FIESTA (Pantone)
AZUL_2728 = (0, 42, 122, 255)
AZUL_2728_SEC = (0, 71, 186, 255)
ROJO_185 = (228, 0, 43, 255)
DORADO_ILV = (212, 160, 23, 255)
CREMA_ORO = (244, 207, 91, 255)
NEGRO_BLACK6 = (0, 0, 0, 255)
BLANCO = (255, 255, 255, 255)
BLANCO_98 = (255, 255, 255, 250)

LEGAL_TEXTO_FOTO = (
    "EL EXCESO DE ALCOHOL ES PERJUDICIAL PARA LA SALUD. "
    "PROHÍBASE EL EXPENDIO DE BEBIDAS EMBRIAGANTES A MENORES DE EDAD."
)
HASHTAG = "#ElSaborQueNosUne"
SLOGAN_PREFIX = "¡VA CON"
SLOGAN_SUFIX = "TODO!"

# ====== MODELOS DISPONIBLES ======
MODEL_NAME = os.environ.get("REMBG_MODEL", "u2net")
_session_u2net = None

def get_session():
    global _session_u2net
    if _session_u2net is None:
        _session_u2net = new_session(MODEL_NAME)
    return _session_u2net

# ====== FASTAPI APP ======
app = FastAPI(
    title="Aguardiente ABV Fiesta — Background Removal + Composition API",
    version="2.0.0",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
def startup_init_db_and_model():
    print(f"[startup] engine={DB_ENGINE} (DATABASE_URL_set={bool(DATABASE_URL)}) | IA model={MODEL_NAME} | CPU only")
    try:
        init_db_tables()
        print(f"[startup] ✅ Tabla fotos_procesadas lista en {DB_ENGINE}. Storage={STORAGE_DIR}")
    except Exception as e:
        print(f"[startup] ⚠️ Falló init DB: {str(e)}")
    try:
        get_session()  # precarga el modelo U2Net en memoria antes del primer request
        print("[startup] ✅ Modelo IA U2Net precargado OK.")
    except Exception as e:
        print(f"[startup] ⚠️ Falló precarga modelo IA (se cargará al primer request): {str(e)}")

class BodyB64(BaseModel):
    image: str
    model: str | None = None
    return_mask: bool | None = False
    alpha_matting: bool | None = True
    af: int | None = 240
    ab: int | None = 10
    ae: int | None = 10
    az: int | None = 1

# ====== UTILIDADES ======
def pil_to_png_bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=False)
    buf.seek(0)
    return buf.read()

def bytes_to_pil(b: bytes) -> Image.Image:
    return Image.open(io.BytesIO(b)).convert("RGBA")

def do_remove(input_bytes: bytes, alpha_matting: bool = True, af=240, ab=10, ae=10, az=1, model_override=None):
    """
    Elimina 100% del fondo usando U2Net / ISNet.
    Retorna PIL.Image (RGBA) — solo silueta, transparencia perfecta.
    """
    sess = get_session() if not model_override else new_session(model_override)
    result_bytes = remove(
        input_bytes,
        session=sess,
        alpha_matting=alpha_matting,
        alpha_matting_foreground_threshold=af,
        alpha_matting_background_threshold=ab,
        alpha_matting_erode_size=ae,
        alpha_matting_erode_threshold=az/10 if az > 0 else 10,
        post_process_mask=True,
    )
    return bytes_to_pil(result_bytes)

def filename_png():
    return f"person-{uuid.uuid4().hex[:10]}.png"

# ====== ENDPOINTS ======
@app.get("/health")
def health():
    return {
        "ok": True,
        "service": "abv-fiesta-rembg",
        "model": MODEL_NAME,
        "session_loaded": _session_u2net is not None,
        "ts": int(time.time()),
    }

@app.get("/")
def root():
    return health()

# 1) MULTIPART/FORM (recomendado, más rápido, mejor memoria)
@app.post("/api/remove-bg")
async def remove_bg_multipart(
    file: UploadFile = File(...),
    alpha_matting: bool = Form(True),
    af: int = Form(240),
    ab: int = Form(10),
    ae: int = Form(10),
    az: int = Form(1),
):
    if not file.content_type or not file.content_type.lower().startswith("image"):
        raise HTTPException(status_code=400, detail="El archivo debe ser una imagen")
    try:
        raw = await file.read()
        result_img = do_remove(raw, alpha_matting=alpha_matting, af=af, ab=ab, ae=ae, az=az)
        png_bytes = pil_to_png_bytes(result_img)
        return StreamingResponse(
            io.BytesIO(png_bytes),
            media_type="image/png",
            headers={
                "Content-Length": str(len(png_bytes)),
                "Content-Disposition": f'inline; filename="{filename_png()}"',
                "X-ABV-Model": MODEL_NAME,
            },
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Procesamiento fallido: {str(e)}")

# 2) JSON BASE64 (cuando multipart no es práctico, ej: navegador antiguo)
@app.post("/api/remove-bg-b64")
def remove_bg_b64(body: BodyB64):
    try:
        if body.image.startswith("data:image"):
            b64_clean = body.image.split(",", 1)[1]
        else:
            b64_clean = body.image
        raw = base64.b64decode(b64_clean)
        result_img = do_remove(
            raw,
            alpha_matting=bool(body.alpha_matting),
            af=body.af,
            ab=body.ab,
            ae=body.ae,
            az=body.az,
            model_override=body.model if body.model and body.model != MODEL_NAME else None,
        )
        png_bytes = pil_to_png_bytes(result_img)
        b64 = base64.b64encode(png_bytes).decode("ascii")
        return {
            "ok": True,
            "image": f"data:image/png;base64,{b64}",
            "content_type": "image/png",
            "bytes": len(png_bytes),
            "model": MODEL_NAME,
        }
    except Exception as e:
        return JSONResponse(status_code=500, content={"ok": False, "error": str(e)})


# ==========================================================================
# FASE 2 — ENDPOINT UNIFICADO /api/procesar-foto (IA + Composición + Almacén)
# ==========================================================================

ESCENARIO_CONFIG = {
    # IDs NUEVOS prompt: Atardecer Vallecaucano = Cristo Rey, Feria de Cali = Plaza Varela, Salsa Neón = Museo Salsa
    #   x_offset_pct: + = MOVER A LA DERECHA, - = MOVER A LA IZQUIERDA (para no tapar objetos principales del fondo).
    #   scale_in_frame: cuánto del ancho FRAME_W (1812px) ocupa la persona (0.72 = 72% ancho del marco blanco).
    #   bottom_from_frame_pct: 0.45 = 45% DESDE LA PARTE INFERIOR del marco blanco FRAME_Y2 (ideal selfies torso/cabeza).
    "sunset": {
        "nombre": "Atardecer Vallecaucano",
        "botellaImg": "botella-fiesta-azul.png",
        "backgroundImg": "esc-cristorey.jpg",
        "fallback_gradient": ((14, 165, 233), (7, 89, 133)),
        "persona_scale": 0.86,
        "persona_bottom_pct": 0.36,
        "x_offset_pct": -0.18,   # Cristo Rey estatua en el MEDIO → persona IZQUIERDA 18% para no taparla
        "scale_in_frame": 0.72,
        "bottom_from_frame_pct": 0.42,
    },
    "feria": {
        "nombre": "Feria de Cali",
        "botellaImg": "botella-night.png",
        "backgroundImg": "esc-plazavarela.jpg",
        "fallback_gradient": ((124, 58, 237), (76, 29, 149)),
        "persona_scale": 0.86,
        "persona_bottom_pct": 0.36,
        "x_offset_pct": -0.10,   # Trompeta Plaza Varela ocupa centro-dcha → persona +10% IZQ
        "scale_in_frame": 0.74,
        "bottom_from_frame_pct": 0.42,
    },
    "neon": {
        "nombre": "Salsa Neón",
        "botellaImg": "botella-sin-azucar.png",
        "backgroundImg": "esc-museosalsa.jpg",
        "fallback_gradient": ((249, 115, 22), (180, 83, 9)),
        "persona_scale": 0.86,
        "persona_bottom_pct": 0.36,
        "x_offset_pct": -0.20,   # Museo graffiti MUSEO DE LA SALSA en DERECHA → persona 20% IZQ no taparlo
        "scale_in_frame": 0.70,
        "bottom_from_frame_pct": 0.42,
    },
    # IDs EXISTENTES (compatibilidad con frontend actual)
    "calle-del-sabor": {
        "nombre": "Museo de la Salsa",
        "botellaImg": "botella-fiesta-azul.png",
        "backgroundImg": "esc-museosalsa.jpg",
        "fallback_gradient": ((249, 115, 22), (180, 83, 9)),
        "persona_scale": 0.86,
        "persona_bottom_pct": 0.36,
        "x_offset_pct": -0.20,
        "scale_in_frame": 0.70,
        "bottom_from_frame_pct": 0.42,
    },
    "plaza-varela": {
        "nombre": "Plaza Varela",
        "botellaImg": "botella-night.png",
        "backgroundImg": "esc-plazavarela.jpg",
        "fallback_gradient": ((124, 58, 237), (76, 29, 149)),
        "persona_scale": 0.86,
        "persona_bottom_pct": 0.36,
        "x_offset_pct": -0.10,
        "scale_in_frame": 0.74,
        "bottom_from_frame_pct": 0.42,
    },
    "cristo-rey": {
        "nombre": "Cristo Rey",
        "botellaImg": "botella-sin-azucar.png",
        "backgroundImg": "esc-cristorey.jpg",
        "fallback_gradient": ((14, 165, 233), (7, 89, 133)),
        "persona_scale": 0.86,
        "persona_bottom_pct": 0.36,
        "x_offset_pct": -0.18,
        "scale_in_frame": 0.72,
        "bottom_from_frame_pct": 0.42,
    },
}


def load_asset(filename: str) -> Image.Image | None:
    p = os.path.join(PUBLIC_ASSETS, filename)
    if os.path.exists(p):
        try:
            return Image.open(p).convert("RGBA")
        except Exception:
            return None
    return None


def gradient_cover(w: int, h: int, color_top: tuple, color_bot: tuple) -> Image.Image:
    base = Image.new("RGBA", (w, h), (0, 0, 0, 255))
    px = base.load()
    for y in range(h):
        t = y / max(1, h - 1)
        r = int(color_top[0] * (1 - t) + color_bot[0] * t)
        g = int(color_top[1] * (1 - t) + color_bot[1] * t)
        b = int(color_top[2] * (1 - t) + color_bot[2] * t)
        for x in range(w):
            px[x, y] = (r, g, b, 255)
    return base


def cover_resize(img: Image.Image, w: int, h: int) -> Image.Image:
    iw, ih = img.size
    scale = max(w / iw, h / ih)
    nw, nh = max(1, int(iw * scale)), max(1, int(ih * scale))
    resized = img.resize((nw, nh), Image.LANCZOS)
    left = (nw - w) // 2
    top = (nh - h) // 2
    return resized.crop((left, top, left + w, top + h))


def fit_contain(img: Image.Image, max_w: int, max_h: int) -> Image.Image:
    iw, ih = img.size
    scale = min(max_w / max(1, iw), max_h / max(1, ih), 1.0)
    nw, nh = max(1, int(iw * scale)), max(1, int(ih * scale))
    return img.resize((nw, nh), Image.LANCZOS)


def load_font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    # Intentar fuentes del sistema; fallback default
    candidates = []
    if os.name == "nt":
        candidates += [
            "C:/Windows/Fonts/Inter-Bold.ttf" if bold else "C:/Windows/Fonts/Inter-Regular.ttf",
            "C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf",
            "C:/Windows/Fonts/segoeuib.ttf" if bold else "C:/Windows/Fonts/segoeui.ttf",
        ]
    else:
        candidates += [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        ]
    for c in candidates:
        if os.path.exists(c):
            try:
                return ImageFont.truetype(c, size=size)
            except Exception:
                pass
    return ImageFont.load_default()


def draw_text_centered(draw, xy, text, font, fill, anchor="mm"):
    draw.text(xy, text, font=font, fill=fill, anchor=anchor)


def feather_borders_alpha(person: Image.Image, feather_px: int = 2) -> Image.Image:
    """Suavizado mínimo 2px en el borde del canal alfa para no ver 'navaja'."""
    if feather_px <= 0:
        return person
    alpha = person.split()[-1]
    alpha_blur = alpha.filter(ImageFilter.GaussianBlur(radius=feather_px))
    out = person.copy()
    out.putalpha(alpha_blur)
    return out


def close_alpha_holes(person: Image.Image, radius_px: int = 3) -> Image.Image:
    """Cierra agujeros/transparencias DENTRO de la persona (camisa, cuello, botones).
       Morphology: MaxFilter(expandir alfa) -> MinFilter(encoger alfa) = cerrar huecos <= radius_px.
       NO TOCA los bordes EXTERIORES de la silueta, solo los interiores transparentes."""
    if radius_px <= 0:
        return person
    r, g, b, a = person.split()
    # Paso 1: Dilatación (max filter) → rellenar agujeritos
    a_dilate = a.filter(ImageFilter.MaxFilter(radius_px * 2 + 1))
    # Paso 2: Erosión (min filter) → mantener tamaño original silueta exterior
    a_close = a_dilate.filter(ImageFilter.MinFilter(radius_px * 2 + 1))
    # Paso 3: Fusionar con el original para no engordar bordes → elija MAX alpha final (si original tenía borde, lo mantiene)
    from PIL import ImageChops
    a_final = ImageChops.lighter(a_close, a)
    out = Image.merge("RGBA", (r, g, b, a_final))
    return out


def draw_legal_bar_minimal(composed: Image.Image) -> Image.Image:
    """
    CAPA 2 MINIMA (LO UNICO QUE SE AGREGA A LA FOTO JPG, NADA MAS):
    Barra blanca 4.5% altura con texto LEGAL OBLIGATORIO (ley colombiana de licores).
    SIN marcos, SIN footer negro 12%, SIN logos, SIN botellas, SIN hashtags, SIN slogans.
    SOLO barra blanca + texto negro.
    """
    w, h = composed.size
    draw = ImageDraw.Draw(composed, "RGBA")
    legal_h = max(30, int(h * 0.045))
    legal_y = h - legal_h
    # Barra blanca ANCHO COMPLETO (no 0.018 padding — más limpio editorial)
    draw.rectangle([0, legal_y, w, h], fill=BLANCO)
    # Borde superior 1px gris muy sutil para separar del escenario
    draw.rectangle([0, legal_y, w, legal_y + 1], fill=(210, 210, 210, 255))
    # Texto legal en mayúsculas, negrita, centrado vertical/horizontal
    legal_font = load_font(max(14, int(h * 0.017)), bold=True)
    draw_text_centered(draw, (w // 2, legal_y + legal_h // 2 + 1), LEGAL_TEXTO_FOTO, legal_font, NEGRO_BLACK6)
    return composed


def compose_full(
    persona_rgba: Image.Image,
    escenario_id: str,
    alpha_matting: bool = True,
) -> Image.Image:
    """
    Composicion 2 CAPAS PRINCIPALES + LEGAL MINIMO (NADA DE MARCAS) — FORMATO HORIZONTAL 16:9:
      0 (Fondo): escenario JPG cover resize 1920x1080 (Full HD 16:9 horizontal)
      1 (Persona): PNG transparente IA, escala 82%, TOCA EL SUELO (pies pegados a barra legal)
      2 (Legal OBLIGATORIO): UNICAMENTE barra blanca 4.5% con texto.
    NADA DE MARCOS, NADA DE FOOTER NEGRO, NADA DE LOGOS, NADA DE BOTELLAS, NADA DE SLOGANS, NADA DE HASHTAGS.
    """
    cfg = ESCENARIO_CONFIG.get(escenario_id)
    if cfg is None:
        raise HTTPException(status_code=400, detail=f"Escenario '{escenario_id}' no existe. Opciones: sunset, feria, neon, calle-del-sabor, plaza-varela, cristo-rey")

    # ====== CAPA 0: FONDO ESCENARIO ======
    fondo_pil = load_asset(cfg["backgroundImg"]) if cfg.get("backgroundImg") else None
    if fondo_pil is not None:
        fondo = cover_resize(fondo_pil, CANVAS_W, CANVAS_H)
    else:
        fondo = gradient_cover(CANVAS_W, CANVAS_H, cfg["fallback_gradient"][0], cfg["fallback_gradient"][1])

    canvas = Image.new("RGBA", (CANVAS_W, CANVAS_H), (0, 0, 0, 0))
    canvas.alpha_composite(fondo.convert("RGBA"), (0, 0))

    # ====== CAPA 1: PERSONA — (1) CLOSE HOLES morphology interior (camisa agujeritos), (2) FEATHER mínima.
    #          Calculamos posición DENTRO DEL MARCO BLANCO INTERNO (FRAME_X1/X2/Y1/Y2) medido exacto en cada JPG.
    #          No se sale del marco, no se corta con los bordes azules exteriores.
    persona_rgba = persona_rgba.convert("RGBA")
    persona_no_holes = close_alpha_holes(persona_rgba, radius_px=3)
    persona_clean = feather_borders_alpha(persona_no_holes, feather_px=2)

    # Paso 1: Tamaño persona. Priorizamos scale_in_frame (% del ancho útil del marco blanco)
    #           si está definido, fallback al antiguo persona_scale (% del canvas).
    scale_in_frame = cfg.get("scale_in_frame", None)
    if scale_in_frame and 0.2 < float(scale_in_frame) < 1.0:
        sif = float(scale_in_frame)
        target_max_w_frame = int(FRAME_W * sif)
        target_max_h_frame = int(FRAME_H * (sif * 1.12))
        fitted = fit_contain(persona_clean, target_max_w_frame, target_max_h_frame)
    else:
        scale_legacy = cfg.get("persona_scale", 0.82)
        t_w = int(CANVAS_W * scale_legacy)
        t_h = int(CANVAS_H * (scale_legacy * 1.12))
        fitted = fit_contain(persona_clean, t_w, t_h)
    fw, fh = fitted.size

    # Paso 2: Posición X dentro del marco blanco
    #   x_offset_pct: + = mover a la DERECHA sobre el centro; - = mover a la IZQUIERDA.
    #   Siempre dentro del rango [FRAME_X1, FRAME_X2 - fw] (no se sale del marco).
    frame_center_x = FRAME_X1 + (FRAME_W // 2)
    x_offset_pct = float(cfg.get("x_offset_pct", 0.0))
    x = int(frame_center_x - (fw // 2) + (FRAME_W * x_offset_pct))
    x_min = FRAME_X1 + 6
    x_max = FRAME_X2 - fw - 6
    x = max(x_min, min(x_max, x))

    # Paso 3: Posición Y dentro del marco blanco
    #   bottom_from_frame_pct: 0.42 = 42% DESDE ABAJO del marco blanco (FRAME_Y2)
    #   → ideal selfies torso/cabeza sin pies. Nunca se sale por arriba ni por abajo del marco.
    bottom_pct_frame = float(cfg.get("bottom_from_frame_pct", cfg.get("persona_bottom_pct", 0.38)))
    # Baseline (pies de la persona, o parte inferior del recorte selfies):
    # FRAME_Y2 - 4 es el "suelo" interior (justo antes de que empiece la franja legal blanca inferior del JPG)
    y_baseline_inside_frame = int(FRAME_Y2 - 6 - (FRAME_H * bottom_pct_frame))
    y = int(y_baseline_inside_frame - fh)
    y_min = FRAME_Y1 + 6
    y_max = FRAME_Y2 - fh - 6
    y = max(y_min, min(y_max, y))
    canvas.alpha_composite(fitted, (x, y))

    # ====== CAPA 2: BARRA LEGAL BLANCA AL PIE DEL JPG FINAL (SIEMPRE PINTADA) ======
    # Usuario lo confirma VERBATIM en 2 mensajes:
    #   "EL EXCESO DE ALCOHOL ES PERJUDICIAL PARA LA SALUD. PROHÍBASE EL EXPENDIO DE BEBIDAS
    #    EMBRIAGANTES A MENORES DE EDAD. en la foto"
    # Se pinta a pesar de que los JPG ya la incluyan, para asegurar la ley colombiana 100%
    # (incluso si alguien usa un fondo custom sin ella). El overlay no daña, se ve igual.
    canvas = draw_legal_bar_minimal(canvas)

    return canvas


def save_public_image(img_rgba: Image.Image, as_jpg: bool = True) -> tuple[str, str, str, int]:
    """Guarda la imagen final en STORAGE_DIR, retorna (id, filename, path_abs, bytes_total)."""
    id_ = uuid.uuid4().hex[:12]
    ext = "jpg" if as_jpg else "png"
    filename = f"foto-{id_}.{ext}"
    out_path = os.path.join(STORAGE_DIR, filename)
    if as_jpg:
        flat = Image.new("RGB", img_rgba.size, (255, 255, 255))
        flat.paste(img_rgba, mask=img_rgba.split()[-1])
        flat.save(out_path, format="JPEG", quality=JPEG_QUALITY, optimize=True, progressive=True)
    else:
        img_rgba.save(out_path, format="PNG", optimize=False)
    bytes_total = os.path.getsize(out_path) if os.path.exists(out_path) else 0
    return id_, filename, out_path, bytes_total


def build_public_url(request_host: str, filename: str) -> str:
    raw_base = (
        os.environ.get("PUBLIC_URL")
        or os.environ.get("RAILWAY_STATIC_URL")
        or os.environ.get("BASE_URL")
        or ""
    )
    if not raw_base:
        if request_host and isinstance(request_host, str):
            rh = request_host.strip()
            if rh.startswith("http://") or rh.startswith("https://"):
                raw_base = rh
            elif "localhost" in rh or "127.0.0.1" in rh or rh.startswith("192.168.") or rh.startswith("10."):
                raw_base = f"http://{rh}"
            else:
                raw_base = f"https://{rh}"
        else:
            raw_base = "http://localhost:8000"
    elif not (raw_base.startswith("http://") or raw_base.startswith("https://")):
        if "localhost" in raw_base or "127.0.0.1" in raw_base:
            raw_base = f"http://{raw_base}"
        else:
            raw_base = f"https://{raw_base}"
    base = raw_base.rstrip("/")
    return f"{base}/fotos/{filename}"


@app.post("/api/procesar-foto")
async def procesar_foto_unificado(
    request: Request,
    foto: UploadFile = File(...),
    escenario: str = Form(...),
    alpha_matting: bool = Form(True),
    af: int = Form(240),
    ab: int = Form(10),
    ae: int = Form(10),
    az: int = Form(1),
    formato: str = Form("jpg"),
):
    """
    Endpoint TODO-EN-1: recibe foto + escenario →
      (1) rembg IA U2Net (sin fondo real),
      (2) composición 3 capas Pillow,
      (3) guarda en almacén público Railway,
      (4) registra en DB (Postgres vía Private Network / fallback SQLite)
      (5) retorna { id, url, filename, preview_b64, db_id, timings }
    """
    t0 = time.time()
    if not foto.content_type or not foto.content_type.lower().startswith("image"):
        raise HTTPException(status_code=400, detail="El archivo 'foto' debe ser una imagen (JPG/PNG).")
    esc_id = (escenario or "").strip().lower()
    if esc_id not in ESCENARIO_CONFIG:
        raise HTTPException(
            status_code=400,
            detail=f"Escenario inválido: '{escenario}'. Usa uno de: sunset, feria, neon, calle-del-sabor, plaza-varela, cristo-rey"
        )

    # Extraer IP cliente (X-Forwarded-For / X-Real-IP cuando hay proxy Railway)
    try:
        ip_cliente = request.headers.get("x-forwarded-for") or request.headers.get("x-real-ip") or getattr(request.client, "host", None)
        if isinstance(ip_cliente, str) and "," in ip_cliente:
            ip_cliente = ip_cliente.split(",")[0].strip()
    except Exception:
        ip_cliente = None
    user_agent = request.headers.get("user-agent")

    raw_bytes = await foto.read()
    t_read = time.time()

    # Paso 1: IA rembg
    try:
        persona_rgba = do_remove(raw_bytes, alpha_matting=alpha_matting, af=af, ab=ab, ae=ae, az=az)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Fallo eliminación de fondo (IA): {str(e)}")
    t_ia = time.time()

    # Paso 2: Composición 3 capas
    try:
        final_rgba = compose_full(persona_rgba, esc_id, alpha_matting=alpha_matting)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Fallo composición Pillow: {str(e)}")
    t_comp = time.time()

    # Paso 3: Almacenar imagen
    as_jpg = (formato or "jpg").lower() in ("jpg", "jpeg")
    bytes_total = 0
    try:
        id_, filename, _out_path, bytes_total = save_public_image(final_rgba, as_jpg=as_jpg)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Fallo al guardar imagen: {str(e)}")
    t_save = time.time()

    # Paso 4: URL pública
    try:
        request_host = request.headers.get("x-forwarded-host") or request.headers.get("host") or getattr(request.client, "host", None) or ""
    except Exception:
        request_host = ""
    rail_domain = os.environ.get("RAILWAY_PUBLIC_DOMAIN") or os.environ.get("RAILWAY_STATIC_URL") or ""
    if rail_domain:
        request_host = rail_domain.strip()
    elif not request_host:
        request_host = "localhost:8000"
    url_publica = build_public_url(request_host, filename)

    # Paso 5: Persistir en DB (Postgres internal / SQLite fallback) — NO bloquea si falla
    timings_obj = {
        "total": round((time.time() - t0) * 1000),
        "lectura": round((t_read - t0) * 1000),
        "ia_rembg": round((t_ia - t_read) * 1000),
        "composicion": round((t_comp - t_ia) * 1000),
        "almacenamiento": round((t_save - t_comp) * 1000),
    }
    db_id = None
    db_error = None
    try:
        db_id = insert_foto_procesada({
            "foto_id": id_,
            "filename": filename,
            "url_publica": url_publica,
            "escenario_id": esc_id,
            "escenario_nombre": ESCENARIO_CONFIG[esc_id]["nombre"],
            "modelo_ia": MODEL_NAME,
            "alpha_matting": bool(alpha_matting),
            "canvas_w": CANVAS_W,
            "canvas_h": CANVAS_H,
            "formato": ("jpeg" if as_jpg else "png"),
            "bytes_total": int(bytes_total or 0),
            "ip_cliente": ip_cliente,
            "user_agent": (user_agent or "")[:512],
            "timings_ms": timings_obj,
            "metadata": {
                "db_engine": DB_ENGINE,
                "foto_content_type": foto.content_type,
                "foto_bytes_original": len(raw_bytes),
                "alpha_params": {"af": af, "ab": ab, "ae": ae, "az": az},
            },
        })
    except Exception as e:
        db_error = str(e)
        print(f"[db] ⚠️ Falló insert fotos_procesadas: {db_error}")

    # Preview base64 (opcional, para mostrar instantáneo en tablet antes de QR)
    preview_b64 = None
    try:
        buf = io.BytesIO()
        flat = Image.new("RGB", final_rgba.size, (255, 255, 255))
        flat.paste(final_rgba, mask=final_rgba.split()[-1])
        flat.save(buf, format="JPEG", quality=85, optimize=True)
        preview_b64 = "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii")
    except Exception:
        preview_b64 = None

    respuesta = {
        "ok": True,
        "id": id_,
        "db_id": db_id,
        "db_engine": DB_ENGINE,
        "filename": filename,
        "url": url_publica,
        "escenario": esc_id,
        "escenario_nombre": ESCENARIO_CONFIG[esc_id]["nombre"],
        "modelo_ia": MODEL_NAME,
        "alpha_matting": alpha_matting,
        "tamano_lienzo": {"w": CANVAS_W, "h": CANVAS_H},
        "formato": ("jpeg" if as_jpg else "png"),
        "bytes_total": int(bytes_total or 0),
        "ip": ip_cliente,
        "preview": preview_b64,
        "timings_ms": timings_obj,
    }
    if db_error:
        respuesta["db_warning"] = db_error
    return respuesta


# ============================================================
# Archivos finales servidos públicamente (para QR)
# ============================================================
app.mount("/fotos", StaticFiles(directory=STORAGE_DIR), name="fotos-publicas")


@app.get("/fotos/{filename}")
async def get_foto_publica(filename: str):
    p = os.path.join(STORAGE_DIR, os.path.basename(filename))
    if not os.path.exists(p):
        raise HTTPException(status_code=404, detail="Foto no encontrada")
    ext = os.path.splitext(p)[1].lower()
    media = "image/jpeg" if ext in (".jpg", ".jpeg") else ("image/png" if ext == ".png" else "application/octet-stream")
    return FileResponse(
        p,
        media_type=media,
        filename=filename,
        headers={
            "Content-Disposition": f'inline; filename="{filename}"',
            "Cache-Control": "public, max-age=31536000, immutable",
        }
    )


@app.get("/api/fotos-stats")
def stats():
    db_stats = {"engine": DB_ENGINE, "count": 0, "por_escenario": [], "latest": []}
    db_err = None
    try:
        db_stats = stats_fotos_db()
    except Exception as e:
        db_err = str(e)

    try:
        files = [f for f in os.listdir(STORAGE_DIR) if f.startswith("foto-")]
    except Exception:
        files = []

    payload = {
        "ok": True,
        "db_engine": DB_ENGINE,
        "storage_dir": STORAGE_DIR,
        "files_count": len(files),
        "latest_files": list(sorted(files, reverse=True))[:10],
        "fotos_count": db_stats.get("count", 0),
        "por_escenario": db_stats.get("por_escenario", []),
        "latest_fotos": db_stats.get("latest", []),
    }
    if db_err:
        payload["db_error"] = db_err
    return payload
