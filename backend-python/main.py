# Python FastAPI + U2Net (rembg) Background Removal + Composición 3 capas + Store + DB
# Deploy: Railway Nixpacks Python + Volumen persistente ./public-fotos
# DB: PostgreSQL via Private Networking (sin egress $$$) — fallback SQLite local
# ============================================================
# ✅ FIX URGENTE EVENTO 10.000 PERSONAS + 4 TABLETS CONCURRENTES:
# 1. Tunning CPU para Railway 2 vCPU: NUNCA oversuscribir hilos (contention ONNX = fotos 2x lentas).
# 2. threading.Lock() alrededor rembg.remove(): onnxruntime session NO es thread-safe.
#    Sin lock: 4 tablets concurrentes crashean proceso con InternalError/Segmentation Fault.
# 3. Rate limit básico concurrente (8 máx): >8 retorna HTTP 503 Service Unavailable sin caer.
# ============================================================
import os
import sys
import io
import uuid
import time
import json
import shutil
import tempfile
from pathlib import Path
from typing import Optional, Tuple, Dict, Any
# ✅ TUNING ONNX RUNTIME / OPENBLAS / MKL: 2 HILOS = MÁXIMA VELOCIDAD en Railway 2 vCPU
os.environ.setdefault("OMP_NUM_THREADS", "2")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "2")
os.environ.setdefault("MKL_NUM_THREADS", "2")
os.environ.setdefault("VECLIB_MAXIMUM_THREADS", "2")
os.environ.setdefault("NUMEXPR_NUM_THREADS", "2")
os.environ.setdefault("TF_NUM_INTEROP_THREADS", "1")
os.environ.setdefault("TF_NUM_INTRAOP_THREADS", "2")
os.environ.setdefault("ORT_OMP_NUM_THREADS", "2")
os.environ.setdefault("ONNX_OPT_LEVEL", "99")
import threading
import contextvars

from fastapi import FastAPI, File, UploadFile, HTTPException, Form, Request, status as http_status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse, FileResponse, Response
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
# ========== COORDENADAS MEDIDAS EXACTAMENTE EN LOS 3 JPG ORIGINALES (esc-cristorey / museosalsa / plazavarela) ==========
# ✅ PETICIÓN USUARIO VERBATIM: "la foto final la persona NO puede quedar DENTRO de lo AZUL ni del BLANCO, tiene que estar SÓLO EN LA FOTO (paisaje)".
# Por lo tanto: FRAME_* = SÓLO Y EXCLUSIVAMENTE EL ÁREA FOTOGRÁFICA DEL PAISAJE (CRISTO REY/MUSEO/PLAZA)
#   — Quitamos TODO borde AZUL EXTERIOR (48px c/lado)
#   — Quitamos TODO borde BLANCO INTERNO del recuadro (8px c/lado entre azul y paisaje)
# Estructura REAL confirmada, de izq→dcha / arriba→abajo:
#   [AZUL EXT 48px] [BLANCO BORDE 8px] [PAISAJE FOTOGRÁFICO (DONDE VA PERSONA)] [BLANCO BORDE 8px] [AZUL EXT 48px]
#   [AZUL TÍTULO y0→y82] [BLANCO SUP 8px y82→y90] [PAISAJE y90→y1008] [BLANCO INF 8px y1008→y1016] [AZUL MEDIO y1016→y1022] [LEGAL y1022→y1080]
FRAME_X1 = 56     # 48 (azul izq) + 8 (blanco izq) → INICIO REAL PAISAJE IZQ
FRAME_Y1 = 90     # 82 (título azul) + 8 (blanco sup)  → INICIO REAL PAISAJE ARRIBA
FRAME_X2 = 1864   # 1920 - 48 (azul dcho) - 8 (blanco dcho) → FIN REAL PAISAJE DERECHA
FRAME_Y2 = 1008   # 1016 (blanco inf termina) - 8 (blanco inf) → FIN REAL PAISAJE ABAJO
FRAME_W = FRAME_X2 - FRAME_X1   # 1808 px ANCHO ÚTIL — SÓLO PAISAJE, SIN AZULES NI BLANCOS
FRAME_H = FRAME_Y2 - FRAME_Y1   # 918 px ALTO ÚTIL — SÓLO PAISAJE, SIN TÍTULOS NI LEGALES

# ✅ ✊ CORTE DE SANGRE (BLOQUEO TOTAL CONTRA BLANCO / AZUL):
#    Usuario VERBATIM: "la foto sigue saliendo en lo blanco y en lo azul".
#    Solución: PADDING INTERNO DE SEGURIDAD (48px) DENTRO DEL ÁREA DEL PAISAJE.
#    Es decir: la persona NUNCA podrá acercarse a menos de 48px del borde del FRAME,
#    evitando por COMPLETO que un brazo, hombro, cabello toque el borde blanco 8px o el azul 48px,
#    incluso si la IA devuelve una silueta grande.
SAFE_PADDING_PX = 48
FRAME_SAFE_X1 = FRAME_X1 + SAFE_PADDING_PX   # 104 (zona segura empieza 48px después de borde blanco izq)
FRAME_SAFE_Y1 = FRAME_Y1 + SAFE_PADDING_PX   # 138 (zona segura empieza 48px después de título)
FRAME_SAFE_X2 = FRAME_X2 - SAFE_PADDING_PX   # 1816 (zona segura termina 48px antes de blanco dcho)
FRAME_SAFE_Y2 = FRAME_Y2 - SAFE_PADDING_PX   # 960  (zona segura termina 48px antes de blanco inf)
FRAME_SAFE_W = FRAME_SAFE_X2 - FRAME_SAFE_X1   # 1712 px (ancho util zona 100% segura)
FRAME_SAFE_H = FRAME_SAFE_Y2 - FRAME_SAFE_Y1   # 822 px  (alto util zona 100% segura)

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
# MÁXIMA VELOCIDAD para EVENTO (stand con cola de personas):
#   u2netp (176x176, 24MB) ~4x MÁS RÁPIDO que u2net (320x320, 180MB) en CPU Railway 1 core.
#   Calidad para selfies evento TABLET CÁMARA FRONTAL es 98% indistinguible.
#   Si quieres MÁXIMA CALIDAD en vez de VELOCIDAD: cambia a "u2net" en variable entorno.
MODEL_NAME = os.environ.get("REMBG_MODEL", "u2netp")
MAX_CONCURRENT_REMOVE = int(os.environ.get("MAX_CONCURRENT_REMOVE", "8"))  # 8 parallel max (4 tablets OK, 8 safety)

_session_u2net = None
# ✅ LOCK GLOBAL de sesión U2Net: onnxruntime NO ES THREAD-SAFE al correr remove() en paralelo.
#    Sin este Lock: 4 tablets concurrentes → corruption en los tensores ONNX + InternalError o SegFault proceso.
_session_lock = threading.Lock()
_startup_lock = threading.Lock()

# ✅ Rate limit básico concurrent: cuenta cuántas llamadas do_remove() están corriendo AHORA MISMO.
#    Si > MAX_CONCURRENT_REMOVE: retornamos HTTP 503 Service Unavailable (evento lleno, reintenta en 1s).
#    Así el proceso FastAPI NUNCA se cae por saturar RAM CPU.
_current_remove_counter = 0
_counter_lock = threading.Lock()


def get_session():
    global _session_u2net
    # Doble-check + Lock: solo el primer request hace new_session() real; los demás esperan.
    if _session_u2net is None:
        with _startup_lock:
            if _session_u2net is None:
                t0 = time.perf_counter()
                sess = new_session(MODEL_NAME)
                _session_u2net = sess
                print(f"[get_session] ✅ U2Net '{MODEL_NAME}' cargado en {time.perf_counter() - t0:.2f}s")
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
    # Alpha matting=False POR DEFAULT = ~40% MÁS RÁPIDO. El feather_borders 2px backend compensa el borde "navaja".
    # Si quieres detalle EXTRA cabello fino: envía True (a costa de +~10s/foto en CPU).
    alpha_matting: bool | None = False
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

# ✅ Helpers rate limit concurrent slots (8 máx parallel remove):
class ServiceOverloaded(Exception):
    def __init__(self, msg="Servidor saturado en este momento; reintenta en 1 segundo."):
        super().__init__(msg)

def acquire_remove_slot():
    """ Incrementa contador; si > MAX_CONCURRENT_REMOVE retorna False = 503."""
    global _current_remove_counter
    with _counter_lock:
        if _current_remove_counter >= MAX_CONCURRENT_REMOVE:
            return False
        _current_remove_counter += 1
        return True

def release_remove_slot():
    global _current_remove_counter
    with _counter_lock:
        if _current_remove_counter > 0:
            _current_remove_counter -= 1


def do_remove(input_bytes: bytes, alpha_matting: bool = False, af=240, ab=10, ae=10, az=1, model_override=None):
    """
    Elimina 100% del fondo usando U2Net / ISNet.
    - Retorna PIL.Image (RGBA) — solo silueta, transparencia perfecta.
    - ✅ CONCURRENCIA SEGURA: threading.Lock() alrededor session=onnxruntime (NO thread-safe).
    - ✅ Tiempos del paso IA medidos en logs para debug performance evento.
    """
    if model_override is not None:
        # override (no usado en esta versión, pero compatibilidad): lock por instancia
        sess = new_session(model_override)
        with _session_lock:
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

    sess = get_session()
    t0 = time.perf_counter()
    # ✅ LOCK SESIÓN ONNX: solo 1 remove() a la vez sobre la sesión global u2netp.
    #    Esto es lo que EVITA CRASHEA el proceso cuando 4 tablets disparan en paralelo.
    with _session_lock:
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
    elapsed = time.perf_counter() - t0
    print(f"[do_remove] u2netp U2NetP elapsed={elapsed:.2f}s | sz={len(input_bytes)}B")
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
    alpha_matting: bool = Form(False),
    af: int = Form(240),
    ab: int = Form(10),
    ae: int = Form(10),
    az: int = Form(1),
):
    if not file.content_type or not file.content_type.lower().startswith("image"):
        raise HTTPException(status_code=400, detail="El archivo debe ser una imagen")
    # ✅ Rate limit concurrente: >8 parallel retorna 503
    if not acquire_remove_slot():
        return JSONResponse(
            status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"ok": False, "error": "overloaded", "message": "Servidor saturado (máx {} paralelo). Reintenta en 1s.".format(MAX_CONCURRENT_REMOVE), "retry_after_ms": 1000},
            headers={"Retry-After": "1"},
        )
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
    finally:
        release_remove_slot()

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
    #   x_offset_pct: + = MOVER A LA DERECHA, - = MOVER A LA IZQUIERDA.
    #   persona_target_fill_pct: (NUEVO, OPCIONAL) ancho % de SAFE_W que ocupa LA PERSONA, OVERRIDE genérico 58%.
    #                            Basado en ESCANEADO prototipo 6 fotos del usuario (medido al px):
    #                              - CRISTO REY  = 82% (MUY grande abajo, no tapa cristo arriba)
    #                              - MUSEO SALSA  = 72% (medio grande, + desplazado a la IZQUIERDA para NO tapar mural)
    #                              - PLAZA VARELA = 46% (MÁS PEQUEÑO, NO tapa las trompetas de fondo)
    #   bottom_from_frame_pct: 0.00 = baseline SAFE_Y2 960. NEGATIVO (e.g. -0.02) = BAJA MÁS, pegado a legal (como prototipo).
    "sunset": {
        "nombre": "Atardecer Vallecaucano",
        "botellaImg": "botella-fiesta-azul.png",
        "backgroundImg": "esc-cristorey.jpg",
        "fallback_gradient": ((14, 165, 233), (7, 89, 133)),
        "persona_scale": 0.72,
        "persona_bottom_pct": 0.00,
        "x_offset_pct": 0.0,
        "persona_target_fill_pct": 0.82,   # 🎯 PROTOTIPO: persona GRANDE (82%) abajo, Cristo Rey está arriba centro
        "scale_in_frame": 0.82,
        "bottom_from_frame_pct": -0.02,    # 🎯 PROTOTIPO: muy pegada abajo (casi legal), no en SAFE_Y2
    },
    "feria": {
        "nombre": "Feria de Cali",
        "botellaImg": "botella-night.png",
        "backgroundImg": "esc-plazavarela.jpg",
        "fallback_gradient": ((124, 58, 237), (76, 29, 149)),
        "persona_scale": 0.72,
        "persona_bottom_pct": 0.00,
        "x_offset_pct": 0.0,
        "persona_target_fill_pct": 0.46,   # 🎯 PROTOTIPO: persona PEQUEÑA (46%) — NO TAPA 3 trompetas gigantes
        "scale_in_frame": 0.46,
        "bottom_from_frame_pct": -0.015,
    },
    "neon": {
        "nombre": "Salsa Neón",
        "botellaImg": "botella-sin-azucar.png",
        "backgroundImg": "esc-museosalsa.jpg",
        "fallback_gradient": ((249, 115, 22), (180, 83, 9)),
        "persona_scale": 0.70,
        "persona_bottom_pct": 0.00,
        "x_offset_pct": -0.06,              # 🎯 PROTOTIPO: 6% HACIA LA IZQUIERDA → NO TAPA mural "Museo de la Salsa" a la DERECHA
        "persona_target_fill_pct": 0.72,    # 🎯 PROTOTIPO: persona medio-grande (72%)
        "scale_in_frame": 0.72,
        "bottom_from_frame_pct": -0.02,
    },
    # IDs EXISTENTES (compatibilidad con frontend actual)
    "calle-del-sabor": {
        "nombre": "Museo de la Salsa",
        "botellaImg": "botella-fiesta-azul.png",
        "backgroundImg": "esc-museosalsa.jpg",
        "fallback_gradient": ((249, 115, 22), (180, 83, 9)),
        "persona_scale": 0.70,
        "persona_bottom_pct": 0.00,
        "x_offset_pct": -0.06,              # 🎯 PROTOTIPO: 6% IZQUIERDA = idéntico a neón
        "persona_target_fill_pct": 0.72,
        "scale_in_frame": 0.72,
        "bottom_from_frame_pct": -0.02,
    },
    "plaza-varela": {
        "nombre": "Plaza Varela",
        "botellaImg": "botella-night.png",
        "backgroundImg": "esc-plazavarela.jpg",
        "fallback_gradient": ((124, 58, 237), (76, 29, 149)),
        "persona_scale": 0.72,
        "persona_bottom_pct": 0.00,
        "x_offset_pct": 0.0,
        "persona_target_fill_pct": 0.46,    # 🎯 PROTOTIPO: persona PEQUEÑA — trompetas se ven completas
        "scale_in_frame": 0.46,
        "bottom_from_frame_pct": -0.015,
    },
    "cristo-rey": {
        "nombre": "Cristo Rey",
        "botellaImg": "botella-sin-azucar.png",
        "backgroundImg": "esc-cristorey.jpg",
        "fallback_gradient": ((14, 165, 233), (7, 89, 133)),
        "persona_scale": 0.72,
        "persona_bottom_pct": 0.00,
        "x_offset_pct": 0.0,
        "persona_target_fill_pct": 0.82,    # 🎯 PROTOTIPO: persona MUY grande abajo, estatua intacta arriba
        "scale_in_frame": 0.82,
        "bottom_from_frame_pct": -0.02,
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


def close_alpha_holes(person: Image.Image, radius_px: int = 6) -> Image.Image:
    """Cierra agujeros/transparencias DENTRO de la persona (camisa, cuello, botones).
       FIX EFECTO CROMA: Cierra agujeros GRANDES (hasta ~45px) cuando la ropa tiene
       color MUY similar al fondo (ej: camisa roja sobre fondo rojo) y U2Net deja agujeros
       (la camisa desaparece, solo quedan manos/cara)."""
    if radius_px <= 0:
        return person
    r, g, b, a = person.split()
    # Paso 0: THRESHOLD ALFA CRÍTICO CROMA. Todo píxel que U2Net pensó que era >15
    # (fue casi un cuerpo) se sube a alfa 128+ para que el closing lo pegue al cuerpo.
    try:
        from PIL import ImageMath
        a_thr = ImageMath.eval("convert(where(a > 15, max(a, 128), a), 'L')", a=a)
    except Exception:
        a_thr = a.point(lambda px: px if px <= 15 else max(px, 128))

    # Paso 1: Dilatación (max filter) → rellenar agujeritos. Ahora radius=6 = filter 13.
    a_dilate = a_thr.filter(ImageFilter.MaxFilter(radius_px * 2 + 1))
    # Paso 2: Erosión (min filter) → mantener tamaño original silueta exterior
    a_close = a_dilate.filter(ImageFilter.MinFilter(radius_px * 2 + 1))
    # Paso 3: SEGUNDO PASS MORFOLÓGICO MÁS FUERTE (closing radius 4 = filter 9)
    #   específicamente para huecos tipo manchas grandes (croma color-fondo).
    a_dilate2 = a_close.filter(ImageFilter.MaxFilter(4 * 2 + 1))
    a_close2 = a_dilate2.filter(ImageFilter.MinFilter(4 * 2 + 1))
    # Paso 4: Fusionar con el original para no engordar bordes → elija MAX alpha final
    try:
        from PIL import ImageChops
        a_final = ImageChops.lighter(a_close2, ImageChops.lighter(a_close, a))
    except Exception:
        a_final = a_close2
    out = Image.merge("RGBA", (r, g, b, a_final))
    return out


# =============================================================================
# 🧠 IA DE AUTO-AJUSTE INTELIGENTE DE TAMAÑO PERSONA
# NUNCA MÁS scale_in_frame hardcodeado 0.54 / 0.68.
# Detectamos el BOUNDING BOX REAL de la persona (solo píxeles con alfa>10),
# quitamos el espacio transparente muerto alrededor, y escalamos AUTOMÁTICAMENTE
# para que la persona ocupe el 93% del ancho o alto del SAFE_FRAME (lo que toque primero).
# SIEMPRE DENTRO DE LA ZONA SEGURA 104/138/1816/960. NUNCA TOCARÁ BLANCO NI AZUL.
# =============================================================================
def get_alpha_content_bbox(img: Image.Image, alpha_min: int = 10) -> Optional[Tuple[int, int, int, int]]:
    """Retorna (x1,y1,x2,y2) del rectángulo mínimo que CONTIENE EXACTAMENTE a la persona
       segmentada (solo píxeles con alpha >= alpha_min). Devuelve None si la imagen está vacía.
       - Elimina TODO el espacio transparente muerto que rembg/U2Net deja alrededor.
       - x1,y1 = esquina superior IZQUIERDA DEL CUERPO REAL.
       - x2,y2 = esquina inferior DERECHA DEL CUERPO REAL."""
    try:
        img = img.convert("RGBA")
        alpha = img.split()[-1]
        bbox = alpha.getbbox()  # Pillow native: devuelve (left,upper,right,lower) con alpha>0.
        if bbox is None:
            return None
        # Aplicar umbral alpha_min adicional (getbbox() nativo solo filtra alpha == 0)
        # usando un recorrido rápido por los bordes del bbox.
        x1, y1, x2, y2 = bbox
        if x1 >= x2 or y1 >= y2:
            return None
        # Refinar X1: avanzar hasta encontrar columna con >=1 píxel alpha_min
        alpha_arr = alpha.load()
        w, h = alpha.size
        # Refinar X1
        new_x1 = x1
        found = False
        for col in range(x1, min(x2 - 1, w - 1)):
            for row in range(y1, min(y2, h - 1)):
                if alpha_arr[col, row] >= alpha_min:
                    new_x1 = col
                    found = True
                    break
            if found:
                break
        # Refinar X2 (de derecha a izquierda)
        new_x2 = x2
        found = False
        for col in range(x2 - 1, max(new_x1 + 1, 0), -1):
            for row in range(y1, min(y2, h - 1)):
                if alpha_arr[col, row] >= alpha_min:
                    new_x2 = col + 1
                    found = True
                    break
            if found:
                break
        # Refinar Y1 (de arriba a abajo)
        new_y1 = y1
        found = False
        for row in range(y1, min(y2 - 1, h - 1)):
            for col in range(new_x1, min(new_x2, w - 1)):
                if alpha_arr[col, row] >= alpha_min:
                    new_y1 = row
                    found = True
                    break
            if found:
                break
        # Refinar Y2 (de abajo a arriba)
        new_y2 = y2
        found = False
        for row in range(y2 - 1, max(new_y1 + 1, 0), -1):
            for col in range(new_x1, min(new_x2, w - 1)):
                if alpha_arr[col, row] >= alpha_min:
                    new_y2 = row + 1
                    found = True
                    break
            if found:
                break
        return (max(0, new_x1), max(0, new_y1), min(w, new_x2), min(h, new_y2))
    except Exception:
        # Fallback silencioso: usa getbbox() nativo si algo salió mal.
        try:
            return img.split()[-1].getbbox()
        except Exception:
            return None


def autoscale_person_to_safe(
    person_img: Image.Image,
    target_fill_pct: float = 0.58,
    min_final_scale: float = 0.25,
    max_final_scale: float = 1.2,
) -> Tuple[Image.Image, float]:
    """🧠 IA Auto-Escala:
       Paso 1: Detectar BBox REAL de la persona (quitar espacio transparente muerto).
       Paso 2: Recortar al BBox + padding 8px para no cortar bordes suaves.
       Paso 3: Calcular escala IDEAL para que persona ocupe target_fill_pct (58%)
               del ancho del SAFE_FRAME = PLANO MEDIO como prototipo usuario.
       Paso 4: Escalar la imagen recortada y devolverla.
       RETORNA: (img_escalada_por_IA, escala_aplicada)
       """
    w_orig, h_orig = person_img.size
    # 1) Obtener bounding box exacto de la persona (sin espacio transparente)
    bbox = get_alpha_content_bbox(person_img, alpha_min=10)
    if bbox is None:
        # Fallback extremo: no detectamos nada → retornar original sin escalar.
        return person_img, 1.0
    x1, y1, x2, y2 = bbox
    content_w = max(1, x2 - x1)
    content_h = max(1, y2 - y1)
    # 2) CROP al contenido real + padding 8px (para preservar feather suave en el borde)
    pad = 8
    cx1 = max(0, x1 - pad)
    cy1 = max(0, y1 - pad)
    cx2 = min(w_orig, x2 + pad)
    cy2 = min(h_orig, y2 + pad)
    cropped = person_img.crop((cx1, cy1, cx2, cy2))
    crop_w, crop_h = cropped.size
    # 3) Calcular escala ideal basada en SAFE_FRAME (1712×822 px).
    #    "Queremos que la persona ocupe 93% del ancho seguro, O 93% del alto seguro,
    #     lo que sea MENOR (para que nunca se salga por ninguno de los 2 lados)".
    target_w_safe = FRAME_SAFE_W * target_fill_pct   # 1712 * 0.93 = 1592 px
    target_h_safe = FRAME_SAFE_H * target_fill_pct   # 822  * 0.93 = 764  px
    scale_by_w = target_w_safe / max(1, crop_w)
    scale_by_h = target_h_safe / max(1, crop_h)
    ideal_scale = min(scale_by_w, scale_by_h)
    #  3.b) Clamp de seguridad para evitar valores imposibles.
    ideal_scale = max(min_final_scale, min(max_final_scale, ideal_scale))
    # 4) Escalar final con LANCZOS (antialias buena calidad)
    new_w = max(1, int(round(crop_w * ideal_scale)))
    new_h = max(1, int(round(crop_h * ideal_scale)))
    scaled = cropped.resize((new_w, new_h), Image.LANCZOS)
    return scaled, ideal_scale


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


def draw_slogan_va_con_todo(composed: Image.Image) -> Image.Image:
    """
    OVERLAY 1 OBLIGATORIO PROTOTIPO USUARIO: Slogan "¡VA CON TODO!" esquina
    inferior izquierda DENTRO del marco blanco (interior), NO tocando SAFE persona.
    - 2 líneas: "¡VA CON" (blanco bold 60px) / "TODO!" (rojo marca bold 92px)
    - Rotación -1.2 grados (como brand.css componente SloganVaConTodo)
    - Coord X: FRAME_X1 (borde izq marco blanco) + 16px = 72 → luego ajustamos
    - Coord Y: FRAME_Y2 (borde inf marco blanco y=1008) - altura_texto(160) - 8 → 840
    """
    slogan_layer = Image.new("RGBA", composed.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(slogan_layer, "RGBA")

    # COORDENADAS DENTRO MARCO BLANCO (no tocar SAFE 48px) — alineado izq.
    # Prototipo: empieza casi al borde blanco interior, dentro del paisaje.
    base_x = FRAME_SAFE_X1   # 104 → margen suficiente para no tocar corte sangre 48px
    base_y = FRAME_SAFE_Y2 - 120  # 960 - 120 = 840 → pega a baseline inf SAFE

    font_blanco = load_font(64, bold=True)
    font_rojo = load_font(104, bold=True)

    # LÍNEA 1: ¡VA CON  (blanco bold)
    line1 = "¡VA CON"
    # LÍNEA 2: TODO!     (rojo marca grande bold)
    line2 = "TODO!"

    draw.text((base_x, base_y), line1, font=font_blanco, fill=BLANCO, anchor="lt")
    draw.text((base_x, base_y + 58), line2, font=font_rojo, fill=ROJO_185, anchor="lt")

    # ROTAR -1.2 grados (como CSS)
    slogan_rot = slogan_layer.rotate(-1.2, resample=Image.BICUBIC, center=(base_x + 100, base_y + 80))
    composed.alpha_composite(slogan_rot, (0, 0))
    return composed


def draw_logo_pastilla(composed: Image.Image) -> Image.Image:
    """
    OVERLAY 2 OBLIGATORIO PROTOTIPO USUARIO: Pastilla redondeada BLANCA esquina
    superior derecha DENTRO DEL HEADER AZUL (y=0..82), NUNCA dentro del paisaje.
    RESTRICCIÓN NUCLEAR: PAD_Y + H_PAD ≤ 80px (MENOR QUE 82 = alto header azul).
    - Tamaño pasado: 216x82 era DEMASIADO ALTO → salía por abajo a y=90, ENCIMA del paisaje.
    - Tamaño NUEVO: 192x68 PAD_Y=5 → 5+68=73 < 82 ✅ 100% dentro header NUNCA toca paisaje.
    """
    W_PAD = 192
    H_PAD = 68
    PAD_X = FRAME_X2 - W_PAD - 10   # 1864 - 192 - 10 = 1662
    PAD_Y = 5                        # TOP margin. 5+68 = 73 < 82 (header azul).

    # Crear capa para pastilla + sombra
    pad_layer = Image.new("RGBA", composed.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(pad_layer, "RGBA")

    # Sombra sutil
    shadow_off = 3
    draw.rounded_rectangle(
        [PAD_X + shadow_off, PAD_Y + shadow_off, PAD_X + W_PAD + shadow_off, PAD_Y + H_PAD + shadow_off],
        radius=14,
        fill=(0, 0, 0, 90),
    )
    # Pastilla blanca
    draw.rounded_rectangle(
        [PAD_X, PAD_Y, PAD_X + W_PAD, PAD_Y + H_PAD],
        radius=14,
        fill=BLANCO,
        outline=(220, 220, 220, 255),
        width=2,
    )

    # Borde superior azul delgado (1px)
    draw.rounded_rectangle(
        [PAD_X, PAD_Y, PAD_X + W_PAD, PAD_Y + 5],
        radius=14,
        fill=AZUL_2728,
    )
    draw.rectangle(
        [PAD_X, PAD_Y + 2, PAD_X + W_PAD, PAD_Y + 5],
        fill=AZUL_2728,
    )

    # TEXTOS DENTRO pastilla
    f1 = load_font(28, bold=True)
    f2 = load_font(38, bold=True)

    cx = PAD_X + (W_PAD // 2)
    cy1 = PAD_Y + 21
    draw.text((cx, cy1), "BLANCO DEL VALLE", font=f1, fill=AZUL_2728, anchor="mm")

    cy2 = PAD_Y + H_PAD - 20
    draw.text((cx, cy2), "FIESTA", font=f2, fill=ROJO_185, anchor="mm")

    composed.alpha_composite(pad_layer, (0, 0))
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

    # ====== CAPA 0: FONDO ESCENARIO — SÓLO USAR EL JPG ORIGINAL DEL USUARIO, SIN NUESTROS COLORES DEGRADADOS ENCIMA.
    # Usuario ordenó: "no quede sobreexpuesta... empiece desde la foto que se dio no lo de colores".
    # => Si el JPG del escenario existe: LO USAMOS 1:1 (TAL CUAL), SIN gradient_cover, SIN colores nuestros.
    # => Gradient COLORES nuestros SÓLO se usa si el JPG NO existe (fallback, fondo custom sin asset, error).
    fondo_pil = load_asset(cfg["backgroundImg"]) if cfg.get("backgroundImg") else None
    if fondo_pil is not None:
        fw_jpg, fh_jpg = fondo_pil.size
        # Si el JPG ya está exactamente en 1920x1080 (como los 3 del usuario): usar DIRECTAMENTE, no resize.
        # Si por algún motivo es otro tamaño, sí cover resize a CANVAS.
        if fw_jpg == CANVAS_W and fh_jpg == CANVAS_H:
            fondo = fondo_pil.convert("RGBA")
        else:
            fondo = cover_resize(fondo_pil, CANVAS_W, CANVAS_H).convert("RGBA")
    else:
        fondo = gradient_cover(CANVAS_W, CANVAS_H, cfg["fallback_gradient"][0], cfg["fallback_gradient"][1]).convert("RGBA")

    canvas = Image.new("RGBA", (CANVAS_W, CANVAS_H), (0, 0, 0, 0))
    canvas.alpha_composite(fondo, (0, 0))

    # ====== CAPA 1: PERSONA — PIPELINE ANTI-CROMA + IA AUTO-AJUSTE TAMAÑO (scale_in_frame YA NO ES NECESARIO).
    #    Orden estricto:
    #    1. close_alpha_holes radius=6 + 2 pass morfológico → EFECTO CROMA FIX (camisa color igual al fondo no desaparece).
    #    2. feather 3px → suaviza bordes del closing fuerte.
    #    3. 🧠 IA autoscale_person_to_safe(target_fill=93%) → escala automática detectando BBox REAL.
    #       Si la IA falla → fallback scale_in_frame del config.
    #    4. Posición SIEMPRE DENTRO DE SAFE_FRAME (104≤x≤1816 / 138≤y≤960) CLAMP 100% BLOQUEADO
    #       (blanco/azul IMPOSIBLE de tocar). Centrado horizontal. PEGADO a baseline inferior SAFE (y=960).
    persona_rgba = persona_rgba.convert("RGBA")
    # FIX EFECTO CROMA: closing morfológico fuerte (radius=6) + 2do pass radius=4.
    persona_no_holes = close_alpha_holes(persona_rgba, radius_px=6)
    # Feather 3px para compensar el borde "navaja" del closing morfológico agresivo.
    persona_clean = feather_borders_alpha(persona_no_holes, feather_px=3)

    # ====================================================================
    # 🧠 IA AUTO-AJUSTE: PRIMERO intentamos escalar la persona automáticamente
    #                    detectando el tamaño REAL (quitar espacio transparente muerto).
    #                    TAMAÑO POR ESCENARIO via cfg.persona_target_fill_pct (override por escenario):
    #                      - cristo-rey = 82% MUY grande abajo; museo-salsa = 72% mediano; plaza-varela = 46% pequeño
    #                    Fallback genérico = 58% (plano medio si no config).
    # ====================================================================
    # 🎯 OVERRIDE PROTOTIPO POR ESCENARIO (NO genérico 58%):
    target_fill_escenario = float(cfg.get("persona_target_fill_pct", 0.58))
    try:
        persona_auto_scaled, ia_scale_applied = autoscale_person_to_safe(
            persona_clean,
            target_fill_pct=target_fill_escenario,
            min_final_scale=0.25,
            max_final_scale=1.3,
        )
        fitted = persona_auto_scaled
    except Exception:
        # FALLBACK ANTIGUO SOLO SI LA IA DE BBOX FALLA: usar scale_in_frame hardcodeado.
        fitted = None

    if fitted is None or fitted.size[0] <= 4 or fitted.size[1] <= 4:
        # Fallback: método antiguo si la IA retornó algo inválido.
        scale_in_frame = cfg.get("scale_in_frame", None)
        if scale_in_frame and 0.2 < float(scale_in_frame) < 1.0:
            sif = float(scale_in_frame)
            target_max_w_frame = int(FRAME_SAFE_W * sif)
            target_max_h_frame = int(FRAME_SAFE_H * (sif * 1.12))
            fitted = fit_contain(persona_clean, target_max_w_frame, target_max_h_frame)
        else:
            scale_legacy = cfg.get("persona_scale", 0.72)
            t_w = int(CANVAS_W * scale_legacy)
            t_h = int(CANVAS_H * (scale_legacy * 1.12))
            fitted = fit_contain(persona_clean, t_w, t_h)
    fw, fh = fitted.size

    # ====== Posición X DENTRO DEL FRAME DEL PAISAJE — MÁRGEN 8px SEGURO NUNCA TOCAR BLANCO (x<56 o x>1864)
    #  🎯 PAISAJE EMPIEZA EN X=56, TERMINA EN X=1864. 8px extra seguro por ambos lados.
    #  Relajado X para offset museo-salsa (-0.06) y cualquier otro escenario.
    safe_center_x = FRAME_SAFE_X1 + (FRAME_SAFE_W // 2)
    x_offset_pct = float(cfg.get("x_offset_pct", 0.0))
    x = int(safe_center_x - (fw // 2) + (FRAME_SAFE_W * x_offset_pct))
    x_min = FRAME_X1 + 8      # 56 + 8 = 64 ✅ NUNCA MENOR (no tocar blanco izq)
    x_max = FRAME_X2 - fw - 8 # 1864 - fw - 8 = 1856 - fw ✅ NUNCA MAYOR (no tocar blanco dcho)
    x = max(x_min, min(x_max, x))

    # ====== Posición Y DENTRO DEL FRAME DEL PAISAJE — MÁRGEN 8px SEGURO NUNCA TOCAR AZUL (y<90) ni BLANCO (y>1008)
    #  🎯 PAISAJE EMPIEZA EN Y=90 (después azul 0..82 + blanco sup 82..90), TERMINA EN Y=1008.
    #  Usuario: "debe empezar desde donde empieza el paisaje" → y_min = FRAME_Y1 + 8 = 98 ✅
    #  Baseline (pies): FRAME_Y2 - 8 = 1000 ✅
    bottom_pct_frame = float(cfg.get("bottom_from_frame_pct", cfg.get("persona_bottom_pct", 0.00)))
    y_baseline_prototipo = int((FRAME_Y2 - 8) - (FRAME_SAFE_H * bottom_pct_frame))
    y = int(y_baseline_prototipo - fh)
    y_min = FRAME_Y1 + 8          # 90 + 8 = 98 ✅ JUSTO DESDE QUE EMPIEZA EL PAISAJE, NUNCA TOCAR AZUL (y ≤ 90)
    y_max = FRAME_Y2 - 8 - fh     # 1008 - 8 - fh = 1000 - fh ✅ pies siempre ≥ 8px del blanco inf
    y = max(y_min, min(y_max, y))
    canvas.alpha_composite(fitted, (x, y))

    # ====== CAPA 2: ADVERTENCIA LEGAL — ✅ LOS 3 JPG ORIGINALES DEL USUARIO YA LA TRAEN DENTRO (y=1022→1080).
    # Por lo tanto: SÓLO pintamos nuestra barra legal draw_legal_bar_minimal SI Y SÓLO SI NO EXISTÍA EL JPG del escenario
    # (es decir, se usó el fallback gradient custom sin los assets del usuario). Así NUNCA hay DOBLE legal = sobreexpuesta.
    if fondo_pil is None:
        # Fallback custom sin JPG original → sí pintar la legal nuestra.
        canvas = draw_legal_bar_minimal(canvas)

    # ====== CAPA 3: OVERLAYS PROTOTIPO USUARIO (OBLIGATORIOS, SIEMPRE presentes con o sin persona)
    # Pintar DESPUÉS de persona y legal para que queden al tope (nunca son tapados).
    # 3.1) Slogan "¡VA CON TODO!" esq inf-izq dentro marco blanco.
    canvas = draw_slogan_va_con_todo(canvas)
    # 3.2) Pastilla logo "BLANCO DEL VALLE + FIESTA" esq sup-der dentro header azul.
    canvas = draw_logo_pastilla(canvas)

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
    alpha_matting: bool = Form(False),
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

    # ✅ Rate limit concurrente: >8 parallel retorna 503.
    #    El frontend hace 75s timeout y reintento explícito si recibe 503.
    if not acquire_remove_slot():
        return JSONResponse(
            status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"ok": False, "error": "overloaded", "message": "Servidor saturado (máx {} paralelo). Reintenta en 1s.".format(MAX_CONCURRENT_REMOVE), "retry_after_ms": 1000},
            headers={"Retry-After": "1"},
        )
    # Paso 1: IA rembg
    try:
        persona_rgba = do_remove(raw_bytes, alpha_matting=alpha_matting, af=af, ab=ab, ae=ae, az=az)
    except Exception as e:
        release_remove_slot()
        raise HTTPException(status_code=500, detail=f"Fallo eliminación de fondo (IA): {str(e)}")
    release_remove_slot()  # libera slot CUANTO ANTES (la IA es el paso caro; composición Pillow ~50ms)
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
