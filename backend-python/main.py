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
import numpy as np

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
JPEG_QUALITY = 98

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
#    Solución: PADDING INTERNO DE SEGURIDAD (16px) DENTRO DEL ÁREA DEL PAISAJE.
#    ✅ ACTUALIZADO de 48px a 16px para hacer MATCH con SAFE_PAD_X/Y 16 usados en
#    clamps X/Y (consistencia total). 16px = suficiente para NO tocar blanco/azul 8px + 48px.
#    48px era DEMASIADO GRANDE, hacía que x_offset negativo NO se cumpliera (persona terminaba a la derecha).
SAFE_PADDING_PX = 16
FRAME_SAFE_X1 = FRAME_X1 + SAFE_PADDING_PX   # 72 (zona segura empieza 16px después de borde blanco izq)
FRAME_SAFE_Y1 = FRAME_Y1 + SAFE_PADDING_PX   # 106 (zona segura empieza 16px después de título)
FRAME_SAFE_X2 = FRAME_X2 - SAFE_PADDING_PX   # 1848 (zona segura termina 16px antes de blanco dcho)
FRAME_SAFE_Y2 = FRAME_Y2 - SAFE_PADDING_PX   # 992  (zona segura termina 16px antes de blanco inf)
FRAME_SAFE_W = FRAME_SAFE_X2 - FRAME_SAFE_X1   # 1776 px (ancho util zona 100% segura, antes 1712 → +64px MÁS espacio)
FRAME_SAFE_H = FRAME_SAFE_Y2 - FRAME_SAFE_Y1   # 886 px  (alto util zona 100% segura, antes 822 → +64px MÁS)

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
    # ====== INICIALIZACIÓN TABLAS PROMO / ADMIN (idempotente) ======
    try:
        init_promo_db_tables_and_seeds()
        print(f"[startup] ✅ 6 Tablas promo/admin + seeds OK en {DB_ENGINE}.")
    except Exception as e:
        print(f"[startup] ⚠️ Falló init promo/admin DB: {str(e)}")

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
    #   persona_target_fill_pct: ancho % de SAFE_W que ocupa LA PERSONA.
    #                            NUEVOS valores basados en FOTOS REALES user (personas grandes, centro del paisaje, NO PEGADAS ABAJO).
    #                            - Cristo Rey = 0.62, Plaza Varela = 0.70, Museo Salsa = 0.60.
    #   bottom_from_frame_pct: NEGATIVO SUBE persona (persona queda CENTRADA vertical, NO pegada abajo blanco inf).
    #                            -0.10 ≈ 90px arriba blanco inf (perfecto centro).
    "sunset": {
        "nombre": "Atardecer Vallecaucano",
        "botellaImg": "botella-fiesta-azul.png",
        "backgroundImg": "esc-cristorey.jpg",
        "fallback_gradient": ((14, 165, 233), (7, 89, 133)),
        "persona_scale": 0.72,
        "persona_bottom_pct": 0.00,
        "x_offset_pct": 0.0,
        "persona_target_fill_pct": 0.62,
        "scale_in_frame": 0.62,
        "bottom_from_frame_pct": -0.10,
    },
    "feria": {
        "nombre": "Feria de Cali",
        "botellaImg": "botella-night.png",
        "backgroundImg": "esc-plazavarela.jpg",
        "fallback_gradient": ((124, 58, 237), (76, 29, 149)),
        "persona_scale": 0.72,
        "persona_bottom_pct": 0.00,
        "x_offset_pct": 0.0,
        "persona_target_fill_pct": 0.70,
        "scale_in_frame": 0.70,
        "bottom_from_frame_pct": -0.10,
    },
    "neon": {
        "nombre": "Salsa Neón",
        "botellaImg": "botella-sin-azucar.png",
        "backgroundImg": "esc-museosalsa.jpg",
        "fallback_gradient": ((249, 115, 22), (180, 83, 9)),
        "persona_scale": 0.70,
        "persona_bottom_pct": 0.00,
        # ✅ Ajuste correcto tras comparar JPG ORIGINAL vs GENERADO pixel a pixel:
        # -0.17 = 17% izq. ANTES -0.20 se acercaba mucho al blanco izq (gafas casi lo tocaban).
        # Resultado: 301.9px izq del centro → persona separada suficiente de blanco izq,
        #            mural de "Museo de la Salsa" (x=700-1500) 100% visible NO TAPADO.
        "x_offset_pct": -0.17,
        "persona_target_fill_pct": 0.60,
        "scale_in_frame": 0.60,
        "bottom_from_frame_pct": -0.10,
    },
    # IDs EXISTENTES (compatibilidad con frontend actual)
    "calle-del-sabor": {
        "nombre": "Museo de la Salsa",
        "botellaImg": "botella-fiesta-azul.png",
        "backgroundImg": "esc-museosalsa.jpg",
        "fallback_gradient": ((249, 115, 22), (180, 83, 9)),
        "persona_scale": 0.70,
        "persona_bottom_pct": 0.00,
        "x_offset_pct": -0.17,
        "persona_target_fill_pct": 0.60,
        "scale_in_frame": 0.60,
        "bottom_from_frame_pct": -0.10,
    },
    "plaza-varela": {
        "nombre": "Plaza Varela",
        "botellaImg": "botella-night.png",
        "backgroundImg": "esc-plazavarela.jpg",
        "fallback_gradient": ((124, 58, 237), (76, 29, 149)),
        "persona_scale": 0.72,
        "persona_bottom_pct": 0.00,
        "x_offset_pct": 0.0,
        "persona_target_fill_pct": 0.70,
        "scale_in_frame": 0.70,
        "bottom_from_frame_pct": -0.10,
    },
    "cristo-rey": {
        "nombre": "Cristo Rey",
        "botellaImg": "botella-sin-azucar.png",
        "backgroundImg": "esc-cristorey.jpg",
        "fallback_gradient": ((14, 165, 233), (7, 89, 133)),
        "persona_scale": 0.72,
        "persona_bottom_pct": 0.00,
        "x_offset_pct": 0.0,
        "persona_target_fill_pct": 0.62,
        "scale_in_frame": 0.62,
        "bottom_from_frame_pct": -0.10,
    },
}


# ==============================================================================
# PASO 0 y PASO 1 - CACHE DE ASSETS MEDIDOS y CARGA INICIAL (al arrancar FastAPI)
#   - escenarios.json (coordenadas px/pct + valores recomendados
#   - 3 fondos JPG resize LANCZOS a 1920x1080 (UN resize posterior)
#   - 3 máscaras PNG L (ventana paisaje - keepout pastilla)
#   - mapa 6 IDs frontend -> 3 keys del JSON
# ==============================================================================
def _load_escenarios_json():
    p = os.path.join(PUBLIC_ASSETS, "escenarios.json")
    if not os.path.exists(p):
        print("[BOOT] ⚠️ No se encontró escenarios.json en assets. Usar defaults.")
        return {}
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"[BOOT] ⚠️ Falló carga escenarios.json: {e}")
        return {}

ESCENARIOS_JSON: Dict[str, Any] = _load_escenarios_json()

# Mapa 6 IDs frontend -> key del JSON (cristorey/museosalsa/plazavarela)
MAPA_IDS_ESCENARIO_KEY: Dict[str, str] = {}
for _key, _val in ESCENARIOS_JSON.items():
    if not isinstance(_val, dict) or str(_key).startswith("__"):
        continue
    for _id in _val.get("ids_frontend", []):
        MAPA_IDS_ESCENARIO_KEY[_id] = _key

# Cache fondos 1920x1080 RGBA (inicializado None, se carga lazy al primer uso)
FONDOS_CACHE: Dict[str, "Image.Image"] = {}
# Cache máscaras de ventana (L (1920x1080, 255=paisaje, 0=marco)
MASCARAS_VENTANA: Dict[str, "Image.Image"] = {}


def _cargar_assets_escenario(key: str):
    """Carga lazy fondo (1920x1080 RGBA) y máscara PNG L para un escenario."""
    if key in FONDOS_CACHE and key in MASCARAS_VENTANA:
        return
    esc = ESCENARIOS_JSON.get(key)
    if not esc:
        return
    fname = esc.get("archivo_fondo", "")
    if fname:
        p = os.path.join(PUBLIC_ASSETS, fname)
        if os.path.exists(p):
            try:
                with Image.open(p) as im:
                    im.load()
                    if im.size == (CANVAS_W, CANVAS_H):
                        fondo = im.convert("RGBA")
                    else:
                        fondo = im.convert("RGBA").resize((CANVAS_W, CANVAS_H), Image.LANCZOS)
                FONDOS_CACHE[key] = fondo
            except Exception as e:
                print(f"[BOOT] ⚠️ Falló cargar fondo {fname}: {e}")
    mask_name = f"mask_{key}.png"
    pm = os.path.join(PUBLIC_ASSETS, mask_name)
    if os.path.exists(pm):
        try:
            with Image.open(pm) as mk:
                MASCARAS_VENTANA[key] = mk.convert("L")
        except Exception as e:
            print(f"[BOOT] ⚠️ Falló cargar mascara {mask_name}: {e}")
    print(f"[BOOT] ✅ Assets cargados: {key}")


# Cargar todos los assets INMEDIATAMENTE al importar main.py (cache caliente)
for _k in list(ESCENARIOS_JSON.keys()):
    if not _k.startswith("__"):
        _cargar_assets_escenario(_k)


# ==============================================================================
# FUNCIONES AUXILIARES NUEVAS (PROMPT MAESTRO PASO 2)
#   - connected_components (labelizado binario simple, 8-vecindad, NumPy)
#   - filtrar componentes conexas (área >= 25% de la mayor, o que toquen su bbox)
#   - obtener key escenario desde ID frontend
# ==============================================================================
def connected_components(binario: np.ndarray) -> tuple[np.ndarray, int]:
    """Labelizado de componentes conexas 8-vecindad. Retorna (labels, n_labels).
       Implementacion Union-Find sin errores de sintaxis.
       binario: ndarray bool shape (H,W), True = foreground.
    """
    H, W = binario.shape
    labels = np.zeros((H, W), dtype=np.int32)
    parent: list[int] = [0]
    lbl_counter = 0

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for y in range(H):
        for x in range(W):
            if not binario[y, x]:
                continue
            neighbors: list[int] = []
            yp = y - 1
            if yp >= 0:
                for dx in (-1, 0, 1):
                    xp = x + dx
                    if 0 <= xp < W and labels[yp, xp] > 0:
                        neighbors.append(int(labels[yp, xp]))
            xp = x - 1
            if xp >= 0 and labels[y, xp] > 0:
                neighbors.append(int(labels[y, xp]))
            if not neighbors:
                lbl_counter += 1
                parent.append(lbl_counter)
                labels[y, x] = lbl_counter
            else:
                min_l = min(neighbors)
                labels[y, x] = min_l
                for nl in neighbors:
                    if nl != min_l:
                        union(min_l, nl)
    mapping: dict[int, int] = {0: 0}
    new_id = 0
    final_labels = np.zeros_like(labels)
    for y in range(H):
        for x in range(W):
            lab = int(labels[y, x])
            if lab == 0:
                continue
            root = find(lab)
            if root not in mapping:
                new_id += 1
                mapping[root] = new_id
            final_labels[y, x] = mapping[root]
    return final_labels, new_id


def _bbox_from_mask(mask_bool: np.ndarray) -> tuple[int, int, int, int] | None:
    ys, xs = np.nonzero(mask_bool)
    if len(xs) == 0:
        return None
    return int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())


def filter_person_components(alpha_uma: np.ndarray, min_area_ratio: float = 0.25) -> np.ndarray:
    """PROMPT MAESTRO PASO 2.2: Mantener componente mayor + toda componente con
       area >= 25% del area mayor, O QUE TOQUE el bbox expandido de la mayor.
       alpha_uma: uint8 (H,W) con valores 0..255.
    """
    bin = alpha_uma >= 15
    if not bin.any():
        return alpha_uma
    labels, n = connected_components(bin)
    if n <= 1:
        return alpha_uma
    areas: list[int] = [0] * (n + 1)
    bboxes: dict[int, tuple[int, int, int, int]] = {}
    H, W = alpha_uma.shape
    # Histograma por label y extremos por label
    minx: list[int] = [W] * (n + 1)
    miny: list[int] = [H] * (n + 1)
    maxx: list[int] = [-1] * (n + 1)
    maxy: list[int] = [-1] * (n + 1)
    for y in range(H):
        row = labels[y]
        for x in range(W):
            lb = int(row[x])
            if lb == 0:
                continue
            areas[lb] += 1
            if x < minx[lb]:
                minx[lb] = x
            if x > maxx[lb]:
                maxx[lb] = x
            if y < miny[lb]:
                miny[lb] = y
            if y > maxy[lb]:
                maxy[lb] = y
    for lb in range(1, n + 1):
        if areas[lb] > 0:
            bboxes[lb] = (minx[lb], miny[lb], maxx[lb], maxy[lb])
    id_mayor = 1
    area_mayor = areas[1]
    for lb in range(2, n + 1):
        if areas[lb] > area_mayor:
            area_mayor = areas[lb]
            id_mayor = lb
    bbox_mayor = bboxes.get(id_mayor)
    keep = labels == id_mayor
    area_min = int(area_mayor * min_area_ratio)
    if bbox_mayor is not None:
        x1m, y1m, x2m, y2m = bbox_mayor
        pad = 10
        for lb in range(1, n + 1):
            if lb == id_mayor:
                continue
            if lb not in bboxes:
                continue
            x1, y1, x2, y2 = bboxes[lb]
            area_ok = areas[lb] >= area_min
            toca_bbox_mayor = (x1 <= x2m + pad) and (x2 >= x1m - pad) and (y1 <= y2m + pad) and (y2 >= y1m - pad)
            if area_ok or toca_bbox_mayor:
                keep = keep | (labels == lb)
    out = alpha_uma.copy()
    out[~keep] = 0
    return out


def escenario_key_from_id(escenario_id: str) -> str | None:
    return MAPA_IDS_ESCENARIO_KEY.get(escenario_id)


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
    slogan_rot = slogan_layer.rotate(-1.2, resample=Image.LANCZOS, center=(base_x + 100, base_y + 80))
    composed.alpha_composite(slogan_rot, (0, 0))
    return composed


def draw_logo_pastilla(composed: Image.Image) -> Image.Image:
    """
    OVERLAY 2 PROTOTIPO USUARIO: Pastilla BLANCA esquina superior DERECHA,
    DENTRO DEL HEADER AZUL PARCEHADO (x1648..1908 y=4..148). NUNCA DENTRO DEL PAISAJE.
    Tamaño compacto 180x66 (antes 192x68), ubicado y=12 → 12+66=78 < 148 (100% header azul).
    """
    W_PAD = 180
    H_PAD = 66
    # Right aligned: 1864 (FRAME_X2) - 180 - 20 = 1664 → perfecto centro del parche.
    PAD_X = 1864 - W_PAD - 20
    PAD_Y = 12  # TOP. 12 + 66 = 78 < 148 → 100% dentro del header azul parcheado.

    pad_layer = Image.new("RGBA", composed.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(pad_layer, "RGBA")

    shadow_off = 3
    draw.rounded_rectangle(
        [PAD_X + shadow_off, PAD_Y + shadow_off, PAD_X + W_PAD + shadow_off, PAD_Y + H_PAD + shadow_off],
        radius=14,
        fill=(0, 0, 0, 80),
    )
    draw.rounded_rectangle(
        [PAD_X, PAD_Y, PAD_X + W_PAD, PAD_Y + H_PAD],
        radius=14,
        fill=BLANCO,
        outline=(220, 220, 220, 255),
        width=2,
    )
    draw.rounded_rectangle(
        [PAD_X, PAD_Y, PAD_X + W_PAD, PAD_Y + 5],
        radius=14,
        fill=AZUL_2728,
    )
    draw.rectangle(
        [PAD_X, PAD_Y + 2, PAD_X + W_PAD, PAD_Y + 5],
        fill=AZUL_2728,
    )

    f1 = load_font(26, bold=True)
    f2 = load_font(34, bold=True)

    cx = PAD_X + (W_PAD // 2)
    cy1 = PAD_Y + 21
    draw.text((cx, cy1), "BLANCO DEL VALLE", font=f1, fill=AZUL_2728, anchor="mm")
    cy2 = PAD_Y + H_PAD - 18
    draw.text((cx, cy2), "FIESTA", font=f2, fill=ROJO_185, anchor="mm")

    composed.alpha_composite(pad_layer, (0, 0))
    return composed


# ==============================================================================
# HELPERS NUEVOS CALIDAD DE RECORTE y COMPOSICION (L6 nueva especificacion)
# SIN dependencia scipy (solo Pillow + NumPy). Union-Find connected_components propio.
# ==============================================================================
def _alpha_erode(alpha_pil: Image.Image, radius_px: int = 2) -> Image.Image:
    """Erosiona el alfa 1-2 px (quitar halo / borde claro residual)."""
    if radius_px <= 0:
        return alpha_pil.copy()
    from PIL import ImageFilter
    return alpha_pil.filter(ImageFilter.MinFilter(size=2 * radius_px + 1))


def _alpha_dilate(alpha_pil: Image.Image, radius_px: int = 1) -> Image.Image:
    if radius_px <= 0:
        return alpha_pil.copy()
    from PIL import ImageFilter
    return alpha_pil.filter(ImageFilter.MaxFilter(size=2 * radius_px + 1))


def _binary_dilate_np(mask_bool: np.ndarray, iterations: int = 2) -> np.ndarray:
    """Dilatación binaria SIN scipy: usa Pillow MaxFilter sobre imagen L binaria."""
    if iterations <= 0 or not mask_bool.any():
        return mask_bool.copy()
    arr = (mask_bool.astype(np.uint8) * 255)
    img = Image.fromarray(arr, mode="L")
    from PIL import ImageFilter
    k = 2 * iterations + 1
    img = img.filter(ImageFilter.MaxFilter(size=k))
    return np.asarray(img, dtype=np.uint8) > 127


def _decontaminate_border(rgba_pil: Image.Image, erosion_r: int = 2) -> Image.Image:
    """Descontamina el color del borde: en alfa parcial, reemplaza RGB por el
    color interior cercano (evita halo claro/blanco/gris de fondo residual).
    SIN scipy."""
    arr = np.asarray(rgba_pil, dtype=np.uint8)
    h, w = arr.shape[:2]
    rgb = arr[..., :3].astype(np.int16)
    a = arr[..., 3].astype(np.float32) / 255.0

    # Interior: píxeles con alfa ~1 (core puro de la persona, sin borde).
    a_core_bool = (a >= 0.92)
    # Dilatamos el core: binary_dilate con erosion_r+2 iteraciones (sin scipy)
    core_dil = _binary_dilate_np(a_core_bool, iterations=erosion_r + 2)
    # Borde: píxeles con alfa parcial (0.06 < alfa < 0.92) dentro de core_dil.
    border_mask = ((a > 0.06) & (a < 0.92)) & core_dil
    if not border_mask.any():
        return rgba_pil.copy()

    # Color promedio interior core
    if not a_core_bool.any():
        return rgba_pil.copy()
    avg_r = float(np.mean(rgb[a_core_bool, 0]))
    avg_g = float(np.mean(rgb[a_core_bool, 1]))
    avg_b = float(np.mean(rgb[a_core_bool, 2]))

    rgb_new = rgb.copy()
    bm = border_mask
    weight = (1.0 - a[bm])[:, None]
    weight = np.clip(weight, 0.0, 0.95)
    interior = np.array([avg_r, avg_g, avg_b], dtype=np.float32)
    rgb_new[bm] = (
        rgb[bm].astype(np.float32) * (1.0 - weight)
        + interior * weight
    ).astype(np.int16)

    out = np.zeros_like(arr)
    out[..., :3] = np.clip(rgb_new, 0, 255).astype(np.uint8)
    out[..., 3] = arr[..., 3]
    return Image.fromarray(out, mode="RGBA")


def _feather_on_landscape_only(
    persona_rgba_local: Image.Image,
    mascara_ventana_local: Image.Image,
    feather_px: float = 1.8,
) -> Image.Image:
    """Aplica feather suave SOLO en el contorno sobre el paisaje.
    ENTRADAS MISMO TAMAÑO (coords LOCALES del bbox persona, NO canvas global):
      - persona_rgba_local: RGBA de la persona resize + crop bbox (fw x fh).
      - mascara_ventana_local: canal L de la MÁSCARA VENTANA recortada en la misma
        región (fw x fh). 255 = interior paisaje, 0 = marco azul/blanco.
    Donde mascara_ventana_local=0 (marco) el recorte sigue DURO.
    SIN scipy.
    """
    if feather_px <= 0:
        return persona_rgba_local.copy()
    fw_local, fh_local = persona_rgba_local.size
    mw, mh = mascara_ventana_local.size
    if (fw_local, fh_local) != (mw, mh):
        return persona_rgba_local.copy()
    from PIL import ImageFilter
    radius = max(1, int(round(feather_px)))
    alpha_orig = persona_rgba_local.split()[-1]
    alpha_soft = alpha_orig.filter(ImageFilter.GaussianBlur(radius=radius))
    # Frontera suave persona (alfa parcial, contorno real del cutout)
    arr_a_orig = np.asarray(alpha_orig)
    contour = (arr_a_orig > 5) & (arr_a_orig < 250)
    # Solo aplicar feather DENTRO del paisaje (mascara ventana > 0)
    arr_masc_local = np.asarray(mascara_ventana_local)
    contour_landscape = contour & (arr_masc_local > 0)
    if not contour_landscape.any():
        return persona_rgba_local.copy()
    # Dilatacion (sin scipy): 2 iteraciones -> 5x5 MaxFilter
    contour_landscape = _binary_dilate_np(contour_landscape, iterations=2)
    arr_a_soft = np.asarray(alpha_soft).astype(np.uint8)
    arr_a_new = arr_a_orig.copy()
    arr_a_new[contour_landscape] = arr_a_soft[contour_landscape]
    out = persona_rgba_local.copy()
    out.putalpha(Image.fromarray(arr_a_new, mode="L"))
    return out


def _detect_n_personas_from_components(
    alpha_crop: np.ndarray,
    min_area_ratio: float = 0.05,
) -> str:
    """Cuenta componentes conexas 8-vecindad con área >= min_area_ratio * max_area.
    Usa UNION-FIND connected_components propio (no scipy).
    Retorna '1' / '2' / '3+'."""
    a = (alpha_crop >= 15).astype(np.uint8)
    if a.sum() < 64:
        return "2"
    try:
        labels, n_labels = connected_components(a)
    except Exception:
        return "2"
    # labels es np.ndarray shape=alpha_crop.shape, background = 0 probable
    if n_labels <= 1:
        return "1"
    flat_labels = labels.ravel().astype(np.int64)
    counts = np.bincount(flat_labels)
    # Ignorar label 0 si es fondo
    if len(counts) > 0 and counts[0] == flat_labels.size and n_labels == 1:
        return "1"
    # Obtener areas (solo labels 1..n_labels)
    start_i = 1 if counts.size > 1 else 0
    areas = counts[start_i:start_i + n_labels] if start_i + n_labels <= counts.size else counts
    areas = areas[areas > 0]
    if areas.size == 0:
        return "2"
    max_area = float(areas.max())
    threshold = max_area * min_area_ratio
    count_main = int(np.sum(areas >= threshold))
    if count_main <= 0:
        return "2"
    if count_main == 1:
        return "1"
    if count_main == 2:
        return "2"
    return "3+"


def _get_cfg_for_n(v2_block: dict, key_cfg: str, n: str) -> tuple[list, float]:
    """Obtiene rango y default del sub-bloque cfg por nro personas."""
    sub = v2_block.get(key_cfg, {})
    cfg = sub.get(n) or sub.get("2") or sub.get("1") or {}
    rango = list(cfg.get("rango", [0.30, 0.50]))
    default = float(cfg.get("default", (rango[0] + rango[1]) / 2.0))
    if cfg.get("modelo_medido_override") is not None:
        default = float(cfg["modelo_medido_override"])
    return rango, default


def compose_full(
    persona_rgba: Image.Image,
    escenario_id: str,
    alpha_matting: bool = True,
) -> Image.Image:
    """
    NUEVA ESPECIFICACION L1-L7 (2026-09-28):
      0) FONDO SAGRADO: solo se copia 1:1 del cache 1920x1080 (1 resize LANCZOS).
      1) ESCALA POR ANCHO del bbox alfa: 1pers 0.27-0.31, 2pers 0.38-0.46, 3+ 0.50-0.55 del canvas_w. Max 0.55.
      2) POS VERTICAL POR TOPE CABEZA (rango pct canvas_h por escenario + n_personas). y_top = tope_cabeza_target.
      3) COBERTURA INF OBLIGATORIA: bottom = y_top + alto_escalado >= y_base + 4px.
           Si no: baja persona hasta bottom = y_base+4; si cabeza < rango_inf - 0.10, sube escala minimo hasta 0.55 ancho.
      4) MARGEN SUPERIOR: tope alfa >= ventana_top + 12px y fuera keep-outs (slogan/logo). Si no -> reduce escala.
      5) POS HORIZONTAL: centro bbox en rango pct canvas_w por escenario. Restricciones estatua CR / mural MS.
      6) CALIDAD RECORTE: erosion 1-2px alfa, descontaminar borde, feather 1.5-2px SOLO sobre paisaje (DURO contra marco). Eliminar islas pequeñas >= 8% area.
      7) SIN offsets fijos. Sin clonar/repintar fondo. Marco/título/logo/slogan/legal 100% intactos.
    VALIDACION: Regla4 diff=0 fuera de alfa persona.
    """
    CANVAS_W, CANVAS_H = 1920, 1080
    # ------------------------------------------------------------------
    # PASO 1: RESOLVER escenario_id -> key JSON + fondo cacheado
    # ------------------------------------------------------------------
    key = escenario_key_from_id(escenario_id)
    cfg_old = ESCENARIO_CONFIG.get(escenario_id)
    if cfg_old is None:
        raise HTTPException(
            status_code=400,
            detail=f"Escenario '{escenario_id}' no existe. Opciones: sunset, feria, neon, calle-del-sabor, plaza-varela, cristo-rey",
        )

    if key is not None and key in FONDOS_CACHE and key in MASCARAS_VENTANA:
        esc = ESCENARIOS_JSON[key]
        fondo = FONDOS_CACHE[key].copy()
        mascara_ventana_full = MASCARAS_VENTANA[key]
        y_base_px = int(esc["y_base_px"])                     # 987
        y_top_px_ventana = int(esc["ventana_paisaje_px"]["y_top_paisaje"])  # 89
        alto_ventana_paisaje = y_base_px - y_top_px_ventana   # ~898
        ancho_inf_ventana = int(esc["ventana_paisaje_px"].get("ancho_ventana_inf_px", 1816))
        kslog = esc.get("keep_out_slogan_px", {}).get("bbox", [134, 140, 499, 432])
        klogo = esc.get("keep_out_logo_px", {}).get("bbox", [1536, 21, 1891, 237])
        v2 = esc.get("valores_recomendados_v2", {})
        ANCHO_MAX_GLOBAL_PCT = float(v2.get("ancho_max_global_pct_canvas", 0.55))
        MARGEN_SUP_MIN_PX = int(v2.get("margen_superior_min_px", 12))
        MARGEN_LAT_MIN_PX = int(v2.get("margen_lateral_min_px", 12))
        RESTR_ESP = v2.get("restricciones_especiales", {}) or {}
        KEEP_ESTATUA_PCT = RESTR_ESP.get("keep_out_estatua_cabeza_brazos_pct")
        BORDE_DER_MAX_PCT = RESTR_ESP.get("borde_der_grupo_max_pct")
        using_cache = True
        _which_source = f"[OK v2 JSON key={key}] y_base={y_base_px} vent_top={y_top_px_ventana}"
    else:
        # Fallback minimalista (no debería suceder nunca con JSON actual)
        fondo_pil = load_asset(cfg_old["backgroundImg"]) if cfg_old.get("backgroundImg") else None
        using_cache = False
        if fondo_pil is not None:
            fw_jpg, fh_jpg = fondo_pil.size
            if (fw_jpg, fh_jpg) == (CANVAS_W, CANVAS_H):
                fondo = fondo_pil.convert("RGBA")
            else:
                fondo = cover_resize(fondo_pil, CANVAS_W, CANVAS_H).convert("RGBA")
        else:
            fondo = gradient_cover(CANVAS_W, CANVAS_H, cfg_old["fallback_gradient"][0], cfg_old["fallback_gradient"][1]).convert("RGBA")
        mascara_ventana_full = Image.new("L", (CANVAS_W, CANVAS_H), 255)
        y_base_px = 987
        y_top_px_ventana = 89
        alto_ventana_paisaje = y_base_px - y_top_px_ventana
        ancho_inf_ventana = 1816
        kslog = [134, 140, 499, 432]
        klogo = [1536, 21, 1891, 237]
        ANCHO_MAX_GLOBAL_PCT = 0.55
        MARGEN_SUP_MIN_PX = 12
        MARGEN_LAT_MIN_PX = 12
        KEEP_ESTATUA_PCT = None
        BORDE_DER_MAX_PCT = None
        # fallback cfg v2 por key
        FALLBACK_V2 = {
            "cristorey":   {"a_1":[0.27,0.31,0.29],"a_2":[0.38,0.46,0.41],"a_3+":[0.50,0.55,0.525],"t_1":[0.40,0.45,0.425],"t_2":[0.40,0.45,0.425],"t_3+":[0.40,0.45,0.425],"cx_1":[0.50,0.55,0.525],"cx_2":[0.50,0.55,0.525],"cx_3+":[0.50,0.55,0.525]},
            "museosalsa":  {"a_1":[0.27,0.31,0.29],"a_2":[0.38,0.48,0.47],"a_3+":[0.50,0.55,0.525],"t_1":[0.38,0.44,0.410],"t_2":[0.38,0.44,0.410],"t_3+":[0.38,0.44,0.410],"cx_1":[0.30,0.38,0.340],"cx_2":[0.30,0.38,0.340],"cx_3+":[0.30,0.38,0.340]},
            "plazavarela": {"a_1":[0.27,0.31,0.29],"a_2":[0.38,0.46,0.42],"a_3+":[0.50,0.55,0.525],"t_1":[0.20,0.28,0.240],"t_2":[0.34,0.42,0.380],"t_3+":[0.34,0.42,0.380],"cx_1":[0.42,0.47,0.445],"cx_2":[0.42,0.47,0.445],"cx_3+":[0.42,0.47,0.445]},
        }
        fbk = key if key in FALLBACK_V2 else "museosalsa"
        _fb = FALLBACK_V2[fbk]
        v2 = {"ancho_objetivo_pct_canvas_por_personas": {},
              "tope_cabeza_pct_canvas_por_personas": {},
              "centro_x_pct_canvas_por_personas": {}}
        for n, suf in (("1","1"),("2","2"),("3+","3+")):
            lo,hi,med = _fb[f"a_{suf}"]
            v2["ancho_objetivo_pct_canvas_por_personas"][n] = {"rango":[lo,hi],"default":med,"modelo_medido_override":None}
            lo,hi,med = _fb[f"t_{suf}"]
            v2["tope_cabeza_pct_canvas_por_personas"][n] = {"rango":[lo,hi],"default":med}
            lo,hi,med = _fb[f"cx_{suf}"]
            v2["centro_x_pct_canvas_por_personas"][n] = {"rango":[lo,hi],"default":med}
        _which_source = f"[FALLBACK v2 key={fbk}]"

    print(f"[compose_full] esc_id={escenario_id!r} -> {_which_source}")

    # ------------------------------------------------------------------
    # PASO 2: Pipeline persona (anti-croma, componentes, crop)
    # ------------------------------------------------------------------
    persona_rgba = persona_rgba.convert("RGBA")
    persona_no_holes = close_alpha_holes(persona_rgba, radius_px=6)

    # ==================================================================
    # NUEVO PASO 6 INICIO (pre-calidad): erosión 1-2px + eliminar islas
    # ==================================================================
    alpha_pil = persona_no_holes.split()[-1]
    # erosion 1.5px aproximado (MinFilter 3x3 = 1px, luego un extra en componente suave)
    alpha_eroded_1 = _alpha_erode(alpha_pil, radius_px=2)
    persona_eroded = persona_no_holes.copy()
    persona_eroded.putalpha(alpha_eroded_1)

    # Umbral alfa > 15 + eliminar islas pequeñas (componentes conexas < 25% area mayor)
    try:
        alpha_clean_arr = np.asarray(persona_eroded.split()[-1], dtype=np.uint8)
        alpha_filt_arr = filter_person_components(alpha_clean_arr, min_area_ratio=0.25)
        persona_filt = persona_eroded.copy()
        persona_filt.putalpha(Image.fromarray(alpha_filt_arr, mode="L"))
    except Exception:
        persona_filt = persona_eroded

    # Crop al BBOX REAL del alfa >= 15
    bbox = get_alpha_content_bbox(persona_filt, alpha_min=15)
    if bbox is None:
        bbox = (0, 0, persona_filt.size[0], persona_filt.size[1])
    pad = 6
    iw, ih = persona_filt.size
    cr = persona_filt.crop((
        max(0, bbox[0] - pad), max(0, bbox[1] - pad),
        min(iw, bbox[2] + pad), min(ih, bbox[3] + pad),
    ))
    crop_w, crop_h = cr.size
    alpha_crop_arr = np.asarray(cr.split()[-1], dtype=np.uint8)

    # Detectar N personas para elegir rangos
    n_pers = _detect_n_personas_from_components(alpha_crop_arr, min_area_ratio=0.05)
    print(f"[compose_full] n_personas detectado={n_pers!r} crop_w={crop_w} crop_h={crop_h}")

    # Rangos por N personas (L1, L2, L5):
    ancho_rng, ancho_default = _get_cfg_for_n(v2, "ancho_objetivo_pct_canvas_por_personas", n_pers)
    tope_rng, tope_default   = _get_cfg_for_n(v2, "tope_cabeza_pct_canvas_por_personas", n_pers)
    cx_rng, cx_default       = _get_cfg_for_n(v2, "centro_x_pct_canvas_por_personas", n_pers)

    # ================================================================
    # NUEVA LÓGICA 1-5 DE POSICIONAMIENTO Y ESCALA
    # ================================================================
    # L1 ESCALA INICIAL POR ANCHO del bbox (no por altura).
    ancho_target_px = int(round(CANVAS_W * ancho_default))
    ancho_target_px = min(ancho_target_px, int(round(CANVAS_W * ANCHO_MAX_GLOBAL_PCT)))
    scale = ancho_target_px / max(1, crop_w)
    target_w = max(1, int(round(crop_w * scale)))
    target_h = max(1, int(round(crop_h * scale)))

    # Resize inicial por ancho (L1)
    fitted = cr.resize((target_w, target_h), Image.LANCZOS)
    fw, fh = fitted.size

    # Helper: calcular tope (min Y del alfa >= 15) y bottom dentro del fitted.
    def _calc_tope_bottom(fit_img):
        a = np.asarray(fit_img.split()[-1])
        ys = np.where(a >= 15)[0]
        if len(ys) == 0:
            return 0, fit_img.size[1] - 1
        return int(ys.min()), int(ys.max())

    tope_in_fitted, bottom_in_fitted = _calc_tope_bottom(fitted)
    # L2 POSICION VERTICAL INICIAL: y = tope_default * CANVAS_H - tope_in_fitted
    y = int(round(tope_default * CANVAS_H)) - tope_in_fitted
    # L5 POSICION H INICIAL: centro_x = cx_default * CANVAS_W
    x = int(round(cx_default * CANVAS_W)) - (fw // 2)

    # Keep-out estatua CR (zona x 0.47-0.53, y 0.14-0.30 NO debe cubrir persona)
    keep_estatua_bbox_px = None
    if KEEP_ESTATUA_PCT and len(KEEP_ESTATUA_PCT) == 4:
        keep_estatua_bbox_px = [
            int(KEEP_ESTATUA_PCT[0] * CANVAS_W), int(KEEP_ESTATUA_PCT[1] * CANVAS_H),
            int(KEEP_ESTATUA_PCT[2] * CANVAS_W), int(KEEP_ESTATUA_PCT[3] * CANVAS_H),
        ]

    # Helper: bbox de persona en canvas coords
    def _pers_bbox(xx, yy, ww, hh):
        return [xx, yy, xx + ww, yy + hh]

    def _intersect(a, b):
        return not (a[2] <= b[0] or a[0] >= b[2] or a[3] <= b[1] or a[1] >= b[3])

    max_iter = 10
    for _ in range(max_iter):
        changed = False
        tope_in_fitted, bottom_in_fitted = _calc_tope_bottom(fitted)
        fw, fh = fitted.size
        bbox_canvas = _pers_bbox(x, y, fw, fh)
        bottom_canvas = y + bottom_in_fitted
        tope_canvas_real = y + tope_in_fitted

        # L3 COBERTURA INF OBLIGATORIA: bottom_canvas >= y_base_px + 4
        if bottom_canvas < y_base_px + 4:
            # Bajar la persona para que bottom_canvas = y_base + 4
            dy = (y_base_px + 4) - bottom_canvas
            # Pero la cabeza (tope_canvas_real) no debe bajar de tope_rng[0] - 0.10 * CANVAS_H
            tope_max_allowed = int(round((tope_rng[0] - 0.10) * CANVAS_H))
            # La cabeza nueva después de mover: tope_canvas_real + dy
            if tope_canvas_real + dy <= tope_max_allowed:
                # OK mover
                y += dy
                changed = True
            else:
                # Mover hasta el tope_max_allowed y luego SUBIR escala hasta 0.55 ancho.
                dy_move = tope_max_allowed - tope_canvas_real
                y += max(0, dy_move)
                # Calcular cuánta escala hace falta para que bottom_canvas llegue a y_base+4.
                # nuevo_bottom_target = y_base_px + 4 - y (inferior del fitted en canvas)
                target_bottom_local = (y_base_px + 4) - y
                if target_bottom_local > bottom_in_fitted:
                    need_scale = target_bottom_local / max(1, bottom_in_fitted)
                    new_scale = scale * need_scale
                    # Verificar que ancho no supere ANCHO_MAX_GLOBAL_PCT.
                    new_cw = int(round(crop_w * new_scale))
                    max_cw = int(round(CANVAS_W * ANCHO_MAX_GLOBAL_PCT))
                    if new_cw <= max_cw:
                        scale = new_scale
                    else:
                        scale = max_cw / max(1, crop_w)
                    target_w = max(1, int(round(crop_w * scale)))
                    target_h = max(1, int(round(crop_h * scale)))
                    fitted = cr.resize((target_w, target_h), Image.LANCZOS)
                    fw, fh = fitted.size
                    # re-posicionar X por el centro por default
                    x = int(round(cx_default * CANVAS_W)) - (fw // 2)
                    changed = True

        # Actualizar valores post cambio
        tope_in_fitted, bottom_in_fitted = _calc_tope_bottom(fitted)
        tope_canvas_real = y + tope_in_fitted

        # L4 MARGEN SUPERIOR: tope_canvas_real >= ventana_top + MARGEN_SUP_MIN_PX
        #                    Y tope_canvas_real >= 12px debajo de kslog[1] (slogan top) y no invadir kslog/klogo
        min_y_tope = max(y_top_px_ventana + MARGEN_SUP_MIN_PX, kslog[1] + MARGEN_SUP_MIN_PX)
        if tope_canvas_real < min_y_tope:
            # Opcion 1: bajar la persona (aumentar y), siempre que L3 siga OK
            dy_min = min_y_tope - tope_canvas_real
            # Verificar que después de bajar, bottom_canvas siga >= y_base+4 (o si no, re-aplicar L3 luego)
            # Pero si baja mucho, puede romper L3: preferimos REDUCE escala.
            target_bottom_local = (y_base_px + 4) - y
            if bottom_in_fitted + dy_min <= target_bottom_local:
                y += dy_min
            else:
                # reducir escala para que tope quede en min_y_tope y bottom siga >= y_base+4.
                # La cabeza (tope_in_fitted) tiene que quedar en min_y_tope - y => local min_tope_local.
                # => new_scale tal que new_tope_in_fitted ≈ (min_y_tope - y). Y además new_bottom_in_fitted >= target_bottom_local.
                # Escala por el factor que reduce altura:
                espacio_disponible_hasta_base = (y_base_px + 4) - min_y_tope  # altura total disponible
                # Necesitamos fh * (bottom_in_fitted - tope_in_fitted)/old_fh <= espacio_disponible... más fácil: factor = espacio / (old_bottom - old_tope)
                alt_util_orig = bottom_in_fitted - tope_in_fitted
                if alt_util_orig > 4:
                    factor = espacio_disponible_hasta_base / max(1, alt_util_orig)
                    factor = min(1.0, factor)  # solo reducir
                    new_scale = scale * factor
                    new_cw = max(1, int(round(crop_w * new_scale)))
                    new_ch = max(1, int(round(crop_h * new_scale)))
                    # verificar ancho mínimo rango
                    min_cw_rango = int(round(CANVAS_W * ancho_rng[0]))
                    if new_cw < min_cw_rango:
                        # mantener mínimo (aceptar margen superior invadido mejor que achicar demasiado)
                        pass
                    else:
                        scale = new_scale
                        fitted = cr.resize((new_cw, new_ch), Image.LANCZOS)
                        fw, fh = fitted.size
            changed = True

        # Releer después de L4
        tope_in_fitted, bottom_in_fitted = _calc_tope_bottom(fitted)
        fw, fh = fitted.size
        tope_canvas_real = y + tope_in_fitted
        bottom_canvas = y + bottom_in_fitted

        # Bucle keep-outs slogan / pastilla (si invade, achicar escala ligeramente)
        for __ in range(4):
            bbox_canvas = _pers_bbox(x, y, fw, fh)
            hit = False
            for kb in (kslog, klogo):
                if kb and _intersect(bbox_canvas, kb):
                    hit = True
                    break
            if keep_estatua_bbox_px and _intersect(bbox_canvas, keep_estatua_bbox_px):
                hit = True
            if not hit:
                break
            factor = 0.93
            scale *= factor
            target_w = max(1, int(round(crop_w * scale)))
            target_h = max(1, int(round(crop_h * scale)))
            fitted = cr.resize((target_w, target_h), Image.LANCZOS)
            fw, fh = fitted.size
            tope_in_fitted, bottom_in_fitted = _calc_tope_bottom(fitted)
            # recentrar X y recalcular Y para mantener tope_default
            y = int(round(tope_default * CANVAS_H)) - tope_in_fitted
            x = int(round(cx_default * CANVAS_W)) - (fw // 2)
            changed = True

        # L5 POS HORIZONTAL: clamp a cx_rango y restricciones especiales
        cx_actual = (x + fw / 2.0) / CANVAS_W
        cx_min_px = int(round(cx_rng[0] * CANVAS_W)) - fw // 2
        cx_max_px = int(round(cx_rng[1] * CANVAS_W)) - fw // 2
        vent_izq_min = 52
        vent_der_max = 1868
        x_min_abs = max(cx_min_px, vent_izq_min + MARGEN_LAT_MIN_PX)
        x_max_abs = min(cx_max_px, vent_der_max - MARGEN_LAT_MIN_PX - fw)
        if BORDE_DER_MAX_PCT is not None:
            # Borde derecho del grupo <= BORDE_DER_MAX_PCT para MS mural
            borde_der_max_px = int(round(BORDE_DER_MAX_PCT * CANVAS_W)) - fw
            x_max_abs = min(x_max_abs, borde_der_max_px)
        if x < x_min_abs:
            x = x_min_abs
            changed = True
        if x > x_max_abs:
            x = x_max_abs
            changed = True

        # Verificar nuevamente L3 después de achicar escala
        tope_in_fitted, bottom_in_fitted = _calc_tope_bottom(fitted)
        bottom_canvas = y + bottom_in_fitted
        if bottom_canvas < y_base_px + 4:
            # Subir un poco la escala para cumplir L3
            target_bottom_local = (y_base_px + 4) - y
            if target_bottom_local > bottom_in_fitted and target_bottom_local > 20:
                need = target_bottom_local / max(1, bottom_in_fitted)
                new_scale = scale * need
                new_cw = int(round(crop_w * new_scale))
                max_cw = int(round(CANVAS_W * ANCHO_MAX_GLOBAL_PCT))
                min_cw_rango = int(round(CANVAS_W * ancho_rng[0]))
                if new_cw <= max_cw and new_cw >= int(0.9 * min_cw_rango):
                    scale = new_scale
                    target_w = max(1, new_cw)
                    target_h = max(1, int(round(crop_h * scale)))
                    fitted = cr.resize((target_w, target_h), Image.LANCZOS)
                    fw, fh = fitted.size
                    changed = True

        if not changed:
            break

    # Último ajuste L3: si aún bottom_canvas < y_base+4 (por mínimos), bajar persona aunque supere un poco el tope.
    tope_in_fitted, bottom_in_fitted = _calc_tope_bottom(fitted)
    bottom_canvas = y + bottom_in_fitted
    if bottom_canvas < y_base_px + 4:
        dy = (y_base_px + 4) - bottom_canvas
        y += dy
        tope_in_fitted, bottom_in_fitted = _calc_tope_bottom(fitted)

    fw, fh = fitted.size
    print(f"[compose_full] result escala={scale:.3f} target_ancho={fw/CANVAS_W:.3f}(rng {ancho_rng[0]:.2f}-{ancho_rng[1]:.2f}) "
          f"tope_real={(y+tope_in_fitted)/CANVAS_H:.3f}(rng {tope_rng[0]:.2f}-{tope_rng[1]:.2f}) "
          f"cx={(x+fw/2)/CANVAS_W:.3f}(rng {cx_rng[0]:.2f}-{cx_rng[1]:.2f}) "
          f"bottom={(y+bottom_in_fitted)} y_base+4={y_base_px+4}")

    # ==================================================================
    # PASO 2.8 FINAL: RECORTE DURO (alfa persona * mascara_ventana)
    #   + PASO 6 CALIDAD: descontaminar borde + feather SOLO paisaje
    # ==================================================================
    # 6a) Descontaminar color del borde (sacar halo claro)
    fitted_clean = _decontaminate_border(fitted, erosion_r=2)

    # 6b) Recorte DURO contra mascara_ventana (sin feather contra marco)
    x1_c = max(0, x)
    y1_c = max(0, y)
    x2_c = min(CANVAS_W, x + fw)
    y2_c = min(CANVAS_H, y + fh)
    sub_w = x2_c - x1_c
    sub_h = y2_c - y1_c
    alfa_recorte = Image.new("L", (fw, fh), 0)
    if sub_w > 0 and sub_h > 0:
        crop_mask_area = mascara_ventana_full.crop((x1_c, y1_c, x2_c, y2_c))
        lx = x1_c - x
        ly = y1_c - y
        alfa_recorte.paste(crop_mask_area, (lx, ly))
    alfa_pers = fitted_clean.split()[-1]
    import PIL.ImageChops as _IC
    alfa_final_hard = _IC.multiply(alfa_pers, alfa_recorte)
    persona_hard_cut = fitted_clean.copy()
    persona_hard_cut.putalpha(alfa_final_hard)

    # 6c) Feather SOLO en contorno sobre PAISAJE (NO contra el marco).
    # Pasamos alfa_recorte (mismo tamaño fw x fh) = máscara de ventana LOCAL.
    persona_final = _feather_on_landscape_only(persona_hard_cut, alfa_recorte, feather_px=1.8)
    # Volver a asegurar recorte duro: multiply alfa_recorte nuevamente por si feather expandió alfa al marco.
    alfa_recheck = persona_final.split()[-1]
    alfa_recheck = _IC.multiply(alfa_recheck, alfa_recorte)
    persona_final.putalpha(alfa_recheck)

    # ------------------------------------------------------------------
    # PASO 3: COMPOSICION SIMPLE (canvas = fondo.copy(), paste con alfa)
    # ------------------------------------------------------------------
    canvas = fondo.copy()
    canvas.paste(persona_final, (x, y), persona_final)

    if not using_cache:
        fondo_pil_exist = (key is None and load_asset(cfg_old.get("backgroundImg", "")) is None)
        if fondo_pil_exist or (not using_cache and cfg_old.get("backgroundImg") and load_asset(cfg_old["backgroundImg"]) is None):
            canvas = draw_legal_bar_minimal(canvas)

    # ------------------------------------------------------------------
    # REGLA 4: Validación numérica diferencia = 0 fuera de persona
    # ------------------------------------------------------------------
    try:
        import warnings
        _arr_canvas = np.asarray(canvas.convert("RGB"), dtype=np.int16)
        _arr_fondo = np.asarray(fondo.convert("RGB"), dtype=np.int16)
        _mask_persona = np.zeros((CANVAS_H, CANVAS_W), dtype=bool)
        if 0 <= x < CANVAS_W and 0 <= y < CANVAS_H and fw > 0 and fh > 0:
            _xa = max(0, x); _ya = max(0, y)
            _xb = min(CANVAS_W, x + fw); _yb = min(CANVAS_H, y + fh)
            _a = np.asarray(
                persona_final.split()[-1].crop((_xa - x, _ya - y, _xb - x, _yb - y)),
                dtype=np.uint8,
            )
            _mask_persona[_ya:_yb, _xa:_xb] = _a > 0
        _fuera = ~_mask_persona
        _diff = int(np.sum(np.abs(
            _arr_canvas[_fuera].reshape(-1) - _arr_fondo[_fuera].reshape(-1)
        )))
        if _diff != 0:
            warnings.warn(
                f"[REGLA4 FAIL] Diferencia total FUERA de persona = {_diff} (≠0). "
                f"VIOLA Regla1 (fondo sagrado NO intacto).",
                RuntimeWarning,
                stacklevel=2,
            )
        del _arr_canvas, _arr_fondo, _mask_persona, _fuera
    except Exception as _errR4:
        import warnings
        warnings.warn(
            f"[REGLA4 SKIP] No se pudo ejecutar validacion: {str(_errR4)}",
            RuntimeWarning,
            stacklevel=2,
        )

    # Exportar info de este compose para tests numéricos
    _last_compose_info = {
        "escala": round(float(scale), 4),
        "ancho_pct": round(float(fw) / CANVAS_W, 4),
        "ancho_rng_min": round(float(ancho_rng[0]), 4),
        "ancho_rng_max": round(float(ancho_rng[1]), 4),
        "tope_pct": round(float(y + tope_in_fitted) / CANVAS_H, 4),
        "tope_rng_min": round(float(tope_rng[0]), 4),
        "tope_rng_max": round(float(tope_rng[1]), 4),
        "cx_pct": round(float(x + fw / 2.0) / CANVAS_W, 4),
        "cx_rng_min": round(float(cx_rng[0]), 4),
        "cx_rng_max": round(float(cx_rng[1]), 4),
        "bottom_px": int(y + bottom_in_fitted),
        "y_base_mas_4": int(y_base_px + 4),
        "vent_top_px": int(y_top_px_ventana),
        "tope_abs_px": int(y + tope_in_fitted),
    }
    import sys as _sys
    _sys.modules[__name__]._last_compose_info = _last_compose_info

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
        # MÁXIMA CALIDAD JPG (usuario: las fotos deben salir a buena calidad)
        # - subsampling=0 → 4:4:4 SIN chroma subsampling (colores rojos/azules más vivos, no borrosos)
        # - optimize=False → Pillow no re-cuantiza/rebaja calidad para comprimir
        # - progressive=True → carga gradual
        # - dpi=300 → metadata buena
        flat.save(
            out_path,
            format="JPEG",
            quality=JPEG_QUALITY,
            subsampling=0,
            optimize=False,
            progressive=True,
            dpi=(300, 300),
        )
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
        flat.save(buf, format="JPEG", quality=JPEG_QUALITY, subsampling=0, optimize=False, progressive=True, dpi=(300, 300))
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


# ============================================================
# SISTEMA DE PROMOCIÓN / ADMINISTRACIÓN ABV FIESTA
# ============================================================
# (Todo el código nuevo se agrega aquí. Nada de L1-L2119 se tocó.)
# ============================================================

import re as _promo_re
import string as _promo_string
import random as _promo_random
from datetime import timedelta as _promo_timedelta
from fastapi import Depends as _promo_Depends

# Hash bcrypt 12 rounds de "Fiesta2026!Valle" (hardcodeado, idempotente)
_PROMO_ILV1921_BCRYPT_HASH = "$2b$12$kNO8n8JLtvG6RULPSAy1nuNraPoWU3E2bTeA6btS7IbqKfyZK6nlW"

_PROMO_SQL_CREATE_POSTGRES = """
CREATE TABLE IF NOT EXISTS promo_admin_users (
    id SERIAL PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS promo_config (
    id INTEGER PRIMARY KEY,
    max_ganadores INTEGER NOT NULL DEFAULT 1,
    estado_abierto BOOLEAN NOT NULL DEFAULT TRUE,
    titulo_premio TEXT DEFAULT 'Botella Aguardiente Blanco del Valle Fiesta',
    desc_premio TEXT,
    dir_fuera_bogota TEXT NOT NULL DEFAULT 'Cra. 74a #51a-87, Bogotá',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS promo_qr_codes (
    id BIGSERIAL PRIMARY KEY,
    uuid_qr TEXT UNIQUE NOT NULL,
    id_humano VARCHAR(16) UNIQUE NOT NULL,
    size_px INTEGER NOT NULL DEFAULT 512,
    formato TEXT NOT NULL DEFAULT 'png',
    usado_registro_id BIGINT,
    usado_at TIMESTAMPTZ,
    creado_admin_id INTEGER,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_promo_qr_uuid ON promo_qr_codes (uuid_qr);
CREATE INDEX IF NOT EXISTS idx_promo_qr_usado ON promo_qr_codes (usado_registro_id);

CREATE TABLE IF NOT EXISTS promo_registros (
    id BIGSERIAL PRIMARY KEY,
    posicion_orden_ganador BIGINT UNIQUE,
    qr_id BIGINT NOT NULL REFERENCES promo_qr_codes(id),
    qr_uuid TEXT NOT NULL,
    acepta_terminos BOOLEAN NOT NULL,
    acepta_habeas BOOLEAN NOT NULL,
    acepta_terminos_at TIMESTAMPTZ NOT NULL,
    acepta_habeas_at TIMESTAMPTZ NOT NULL,
    nombres_apellidos TEXT NOT NULL,
    celular TEXT,
    telefono_fijo TEXT,
    celular_confirmacion TEXT,
    correo_electronico TEXT NOT NULL,
    direccion TEXT NOT NULL,
    barrio TEXT,
    municipio TEXT,
    ciudad TEXT NOT NULL,
    es_bogota_direccion BOOLEAN NOT NULL,
    modalidad_entrega VARCHAR(16) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ip_cliente TEXT,
    user_agent TEXT
);
CREATE INDEX IF NOT EXISTS idx_promo_reg_created ON promo_registros (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_promo_reg_posicion ON promo_registros (posicion_orden_ganador);
CREATE INDEX IF NOT EXISTS idx_promo_reg_bogota ON promo_registros (es_bogota_direccion);
CREATE INDEX IF NOT EXISTS idx_promo_reg_qr ON promo_registros (qr_uuid);

CREATE TABLE IF NOT EXISTS promo_auditoria_admin (
    id BIGSERIAL PRIMARY KEY,
    admin_id INTEGER NOT NULL,
    accion VARCHAR(32) NOT NULL,
    detalles JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_promo_aud_created ON promo_auditoria_admin (created_at DESC);

CREATE TABLE IF NOT EXISTS promo_sorteo_lock (
    id INTEGER PRIMARY KEY,
    dummy INTEGER NOT NULL DEFAULT 0
);
"""

_PROMO_SQL_CREATE_SQLITE = """
CREATE TABLE IF NOT EXISTS promo_admin_users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (STRFTIME('%Y-%m-%dT%H:%M:%SZ','now'))
);

CREATE TABLE IF NOT EXISTS promo_config (
    id INTEGER PRIMARY KEY,
    max_ganadores INTEGER NOT NULL DEFAULT 1,
    estado_abierto INTEGER NOT NULL DEFAULT 1,
    titulo_premio TEXT DEFAULT 'Botella Aguardiente Blanco del Valle Fiesta',
    desc_premio TEXT,
    dir_fuera_bogota TEXT NOT NULL DEFAULT 'Cra. 74a #51a-87, Bogotá',
    updated_at TEXT NOT NULL DEFAULT (STRFTIME('%Y-%m-%dT%H:%M:%SZ','now'))
);

CREATE TABLE IF NOT EXISTS promo_qr_codes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid_qr TEXT UNIQUE NOT NULL,
    id_humano TEXT UNIQUE NOT NULL,
    size_px INTEGER NOT NULL DEFAULT 512,
    formato TEXT NOT NULL DEFAULT 'png',
    usado_registro_id INTEGER,
    usado_at TEXT,
    creado_admin_id INTEGER,
    created_at TEXT NOT NULL DEFAULT (STRFTIME('%Y-%m-%dT%H:%M:%SZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_promo_qr_uuid ON promo_qr_codes (uuid_qr);
CREATE INDEX IF NOT EXISTS idx_promo_qr_usado ON promo_qr_codes (usado_registro_id);

CREATE TABLE IF NOT EXISTS promo_registros (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    posicion_orden_ganador INTEGER UNIQUE,
    qr_id INTEGER NOT NULL REFERENCES promo_qr_codes(id),
    qr_uuid TEXT NOT NULL,
    acepta_terminos INTEGER NOT NULL,
    acepta_habeas INTEGER NOT NULL,
    acepta_terminos_at TEXT NOT NULL,
    acepta_habeas_at TEXT NOT NULL,
    nombres_apellidos TEXT NOT NULL,
    celular TEXT,
    telefono_fijo TEXT,
    celular_confirmacion TEXT,
    correo_electronico TEXT NOT NULL,
    direccion TEXT NOT NULL,
    barrio TEXT,
    municipio TEXT,
    ciudad TEXT NOT NULL,
    es_bogota_direccion INTEGER NOT NULL,
    modalidad_entrega TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (STRFTIME('%Y-%m-%dT%H:%M:%SZ','now')),
    ip_cliente TEXT,
    user_agent TEXT
);
CREATE INDEX IF NOT EXISTS idx_promo_reg_created ON promo_registros (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_promo_reg_posicion ON promo_registros (posicion_orden_ganador);
CREATE INDEX IF NOT EXISTS idx_promo_reg_bogota ON promo_registros (es_bogota_direccion);
CREATE INDEX IF NOT EXISTS idx_promo_reg_qr ON promo_registros (qr_uuid);

CREATE TABLE IF NOT EXISTS promo_auditoria_admin (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    admin_id INTEGER NOT NULL,
    accion TEXT NOT NULL,
    detalles TEXT,
    created_at TEXT NOT NULL DEFAULT (STRFTIME('%Y-%m-%dT%H:%M:%SZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_promo_aud_created ON promo_auditoria_admin (created_at DESC);

CREATE TABLE IF NOT EXISTS promo_sorteo_lock (
    id INTEGER PRIMARY KEY,
    dummy INTEGER NOT NULL DEFAULT 0
);
"""


def init_promo_db_tables_and_seeds():
    with get_db_conn() as conn:
        cur = conn.cursor()
        if DB_ENGINE == "POSTGRES":
            cur.execute(_PROMO_SQL_CREATE_POSTGRES)
            conn.commit()
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO promo_admin_users (username, password_hash) "
                "SELECT %s, %s WHERE NOT EXISTS (SELECT 1 FROM promo_admin_users WHERE username = %s)",
                ("ilv1921", _PROMO_ILV1921_BCRYPT_HASH, "ilv1921"),
            )
            cur.execute(
                "INSERT INTO promo_config (id, max_ganadores, estado_abierto, titulo_premio, desc_premio, dir_fuera_bogota, updated_at) "
                "SELECT 1, 1, TRUE, 'Botella Aguardiente Blanco del Valle Fiesta', NULL, 'Cra. 74a #51a-87, Bogotá', NOW() "
                "WHERE NOT EXISTS (SELECT 1 FROM promo_config WHERE id = 1)"
            )
            cur.execute(
                "INSERT INTO promo_sorteo_lock (id, dummy) SELECT 1, 0 WHERE NOT EXISTS (SELECT 1 FROM promo_sorteo_lock WHERE id = 1)"
            )
            conn.commit()
        else:
            cur.executescript(_PROMO_SQL_CREATE_SQLITE)
            conn.commit()
            cur = conn.cursor()
            cur.execute(
                "INSERT OR IGNORE INTO promo_admin_users (username, password_hash) VALUES (?, ?)",
                ("ilv1921", _PROMO_ILV1921_BCRYPT_HASH),
            )
            cur.execute(
                "INSERT OR IGNORE INTO promo_config (id, max_ganadores, estado_abierto, titulo_premio, desc_premio, dir_fuera_bogota, updated_at) "
                "VALUES (1, 1, 1, 'Botella Aguardiente Blanco del Valle Fiesta', NULL, 'Cra. 74a #51a-87, Bogotá', STRFTIME('%Y-%m-%dT%H:%M:%SZ','now'))"
            )
            cur.execute(
                "INSERT OR IGNORE INTO promo_sorteo_lock (id, dummy) VALUES (1, 0)"
            )
            conn.commit()


# ================= AUTENTICACIÓN JWT ADMIN =================
_JWT_SECRET = os.getenv("JWT_SECRET", os.urandom(32).hex())
_JWT_ALGORITHM = "HS256"
_JWT_EXPIRY_HOURS = 24


def _promo_hash_password(plain: str) -> str:
    import bcrypt as _bcrypt
    return _bcrypt.hashpw(plain.encode("utf-8"), _bcrypt.gensalt(rounds=12)).decode("utf-8")


def _promo_verify_password(plain: str, hashed: str) -> bool:
    import bcrypt as _bcrypt
    try:
        return _bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


def _promo_create_access_token(admin_id: int, username: str) -> str:
    from jose import jwt as _jose_jwt
    now = datetime.now(timezone.utc)
    expire = now + _promo_timedelta(hours=_JWT_EXPIRY_HOURS)
    payload = {
        "sub": str(admin_id),
        "username": username,
        "iat": int(now.timestamp()),
        "exp": int(expire.timestamp()),
        "type": "admin_access",
    }
    return _jose_jwt.encode(payload, _JWT_SECRET, algorithm=_JWT_ALGORITHM)


def _promo_decode_token(token: str) -> dict | None:
    from jose import jwt as _jose_jwt, JWTError as _JWTError
    try:
        return _jose_jwt.decode(token, _JWT_SECRET, algorithms=[_JWT_ALGORITHM])
    except _JWTError:
        return None


def _promo_get_admin_from_db(username: str) -> dict | None:
    with get_db_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id, username, password_hash FROM promo_admin_users WHERE username = %s" if DB_ENGINE == "POSTGRES" else "SELECT id, username, password_hash FROM promo_admin_users WHERE username = ?", (username,))
        row = cur.fetchone()
        if row is None:
            return None
        return {"id": row[0], "username": row[1], "password_hash": row[2]}


def _promo_insert_auditoria(admin_id: int, accion: str, detalles: dict | None = None):
    with get_db_conn() as conn:
        cur = conn.cursor()
        det_json = json.dumps(detalles or {}, ensure_ascii=False)
        if DB_ENGINE == "POSTGRES":
            cur.execute(
                "INSERT INTO promo_auditoria_admin (admin_id, accion, detalles) VALUES (%s, %s, %s::jsonb)",
                (admin_id, accion, det_json),
            )
            conn.commit()
        else:
            cur.execute(
                "INSERT INTO promo_auditoria_admin (admin_id, accion, detalles) VALUES (?, ?, ?)",
                (admin_id, accion, det_json),
            )
            conn.commit()


# ================= DEPENDENCY AUTH ADMIN (HTTP Bearer) =================
def _promo_extract_bearer(request: Request) -> str | None:
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:].strip()
    return None


def get_current_admin(request: Request):
    token = _promo_extract_bearer(request)
    if not token:
        raise HTTPException(status_code=401, detail="No autorizado: falta token Bearer")
    decoded = _promo_decode_token(token)
    if not decoded:
        raise HTTPException(status_code=401, detail="Token inválido o expirado")
    try:
        admin_id = int(decoded.get("sub", "0"))
        username = decoded.get("username", "")
    except Exception:
        raise HTTPException(status_code=401, detail="Token malformado")
    with get_db_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id, username FROM promo_admin_users WHERE id = %s" if DB_ENGINE == "POSTGRES" else "SELECT id, username FROM promo_admin_users WHERE id = ?", (admin_id,))
        row = cur.fetchone()
        if row is None:
            raise HTTPException(status_code=401, detail="Admin no existe en DB")
        return {"id": row[0], "username": row[1]}


# ================= HELPERS VARIOS PROMO =================
def _promo_es_bogota(ciudad: str, direccion: str) -> bool:
    ciudad_norm = (ciudad or "").strip().lower()
    bogota_re = _promo_re.compile(r"bogot[aá]|santaf[eé]\s+de\s+bogot[aá]|sta\s+fe\s+de\s+bogota", _promo_re.IGNORECASE)
    if bogota_re.search(ciudad_norm):
        return True
    dir_norm = (direccion or "").strip().lower()
    dir_re = _promo_re.compile(r"(cra\.?|carrera|cll\.?|calle|kr\.?)\s*\d", _promo_re.IGNORECASE)
    if dir_re.search(dir_norm) and bogota_re.search(ciudad_norm):
        return True
    if dir_re.search(dir_norm) and ("bogota" in ciudad_norm or "bogotá" in ciudad_norm):
        return True
    return False


def _promo_row_to_dict(row, columns: list[str]) -> dict:
    if row is None:
        return None
    return {columns[i]: (row[i] if i < len(row) else None) for i in range(len(columns))}


def _promo_fetch_all_to_dicts(cur, columns: list[str]) -> list[dict]:
    rows = cur.fetchall()
    return [_promo_row_to_dict(r, columns) for r in rows]


# ================= PYDANTIC MODELS PARA NUEVOS ENDPOINTS =================
class PromoQrValidarReq(BaseModel):
    qr_uuid: str


class PromoAceptacionReq(BaseModel):
    qr_uuid: str
    acepta_terminos: bool
    acepta_habeas: bool


class PromoRegistroReq(BaseModel):
    qr_uuid: str
    nombres_apellidos: str
    celular: str | None = None
    telefono_fijo: str | None = None
    celular_confirmacion: str | None = None
    correo_electronico: str
    direccion: str
    barrio: str | None = None
    municipio: str | None = None
    ciudad: str
    acepta_terminos_at_iso: str
    acepta_habeas_at_iso: str


class AdminLoginReq(BaseModel):
    username: str
    password: str


class AdminConfigUpdateReq(BaseModel):
    max_ganadores: int | None = None
    estado_abierto: bool | None = None
    titulo_premio: str | None = None
    desc_premio: str | None = None
    dir_fuera_bogota: str | None = None


class AdminRegistroUpdateReq(BaseModel):
    nombres_apellidos: str | None = None
    celular: str | None = None
    telefono_fijo: str | None = None
    celular_confirmacion: str | None = None
    correo_electronico: str | None = None
    direccion: str | None = None
    barrio: str | None = None
    municipio: str | None = None
    ciudad: str | None = None
    posicion_orden_ganador: int | None = None
    modalidad_entrega: str | None = None


class AdminQrGenerarReq(BaseModel):
    cantidad: int
    size_px: int = 512
    formato: str = "png"


# ================= ENDPOINTS PÚBLICOS DE PROMOCIÓN =================

# A) POST /api/promo/qr/validar
@app.post("/api/promo/qr/validar")
def promo_qr_validar(req: PromoQrValidarReq):
    qr_uuid = (req.qr_uuid or "").strip()
    if not qr_uuid:
        raise HTTPException(status_code=400, detail="qr_uuid es requerido")
    with get_db_conn() as conn:
        cur = conn.cursor()
        cols = ["id", "uuid_qr", "id_humano", "size_px", "formato", "usado_registro_id"]
        sql = "SELECT id, uuid_qr, id_humano, size_px, formato, usado_registro_id FROM promo_qr_codes WHERE uuid_qr = %s" if DB_ENGINE == "POSTGRES" else "SELECT id, uuid_qr, id_humano, size_px, formato, usado_registro_id FROM promo_qr_codes WHERE uuid_qr = ?"
        cur.execute(sql, (qr_uuid,))
        row = cur.fetchone()
        if row is None:
            return {
                "valido": False,
                "usado": False,
                "mensaje": "QR no encontrado en el sistema",
                "size_px": 0,
                "id_humano": "",
            }
        usado = row[5] is not None
        return {
            "valido": True,
            "usado": usado,
            "mensaje": ("QR ya utilizado" if usado else "QR válido y listo para usar"),
            "size_px": int(row[3] or 512),
            "id_humano": str(row[2] or ""),
        }


# B) POST /api/promo/aceptacion
@app.post("/api/promo/aceptacion")
def promo_aceptacion(req: PromoAceptacionReq):
    server_ts = datetime.now(timezone.utc)
    return {
        "ok": True,
        "server_timestamp_iso": server_ts.isoformat(),
    }


# C) POST /api/promo/registro (TRANSACCIÓN ATÓMICA FIFO)
@app.post("/api/promo/registro")
async def promo_registro(req: PromoRegistroReq, request: Request):
    qr_uuid = (req.qr_uuid or "").strip()
    if not qr_uuid:
        raise HTTPException(status_code=400, detail="qr_uuid requerido")
    if not req.nombres_apellidos or not req.correo_electronico or not req.direccion or not req.ciudad:
        raise HTTPException(status_code=400, detail="Campos obligatorios faltantes")

    try:
        ip_cliente = request.headers.get("x-forwarded-for") or request.headers.get("x-real-ip") or getattr(request.client, "host", None)
        if isinstance(ip_cliente, str) and "," in ip_cliente:
            ip_cliente = ip_cliente.split(",")[0].strip()
    except Exception:
        ip_cliente = None
    user_agent = (request.headers.get("user-agent") or "")[:1024]

    es_bogota = _promo_es_bogota(req.ciudad, req.direccion)
    modalidad = "DOMICILIO_BTA" if es_bogota else "RECOGER_CRA74"

    acepta_t_at = datetime.fromisoformat(req.acepta_terminos_at_iso.replace("Z", "+00:00")) if req.acepta_terminos_at_iso else datetime.now(timezone.utc)
    acepta_h_at = datetime.fromisoformat(req.acepta_habeas_at_iso.replace("Z", "+00:00")) if req.acepta_habeas_at_iso else datetime.now(timezone.utc)

    with get_db_conn() as conn:
        conn.autocommit = False
        try:
            cur = conn.cursor()
            if DB_ENGINE == "POSTGRES":
                cur.execute("BEGIN")
                cur.execute("SELECT id, uuid_qr, id_humano, usado_registro_id FROM promo_qr_codes WHERE uuid_qr = %s", (qr_uuid,))
            else:
                cur.execute("BEGIN IMMEDIATE")
                cur.execute("SELECT id, uuid_qr, id_humano, usado_registro_id FROM promo_qr_codes WHERE uuid_qr = ?", (qr_uuid,))
            qr_row = cur.fetchone()
            if qr_row is None:
                if DB_ENGINE != "POSTGRES":
                    conn.rollback()
                raise HTTPException(status_code=404, detail="QR no encontrado")
            qr_id = qr_row[0]
            if qr_row[3] is not None:
                if DB_ENGINE != "POSTGRES":
                    conn.rollback()
                raise HTTPException(status_code=409, detail="Este QR ya fue utilizado en un registro")

            if DB_ENGINE == "POSTGRES":
                cur.execute("SELECT dummy FROM promo_sorteo_lock WHERE id = 1 FOR UPDATE")
                cur.execute("SELECT id, max_ganadores, estado_abierto, dir_fuera_bogota, titulo_premio FROM promo_config WHERE id = 1 FOR UPDATE")
            else:
                cur.execute("SELECT dummy FROM promo_sorteo_lock WHERE id = 1")
                cur.execute("SELECT id, max_ganadores, estado_abierto, dir_fuera_bogota, titulo_premio FROM promo_config WHERE id = 1")
            cfg_row = cur.fetchone()
            if cfg_row is None:
                if DB_ENGINE != "POSTGRES":
                    conn.rollback()
                raise HTTPException(status_code=500, detail="Configuración no inicializada")

            estado_abierto = bool(cfg_row[2]) if DB_ENGINE == "POSTGRES" else (int(cfg_row[2]) == 1)
            if not estado_abierto:
                if DB_ENGINE != "POSTGRES":
                    conn.rollback()
                raise HTTPException(status_code=423, detail="Promoción cerrada temporalmente")

            max_gan = int(cfg_row[1] or 1)
            dir_fuera = str(cfg_row[3] or "Cra. 74a #51a-87, Bogotá")
            titulo_premio = str(cfg_row[4] or "Botella Aguardiente Blanco del Valle Fiesta")

            count_sql = "SELECT COUNT(*) FROM promo_registros WHERE posicion_orden_ganador IS NOT NULL"
            cur.execute(count_sql)
            count_gan = int(cur.fetchone()[0] or 0)

            posicion_ganador = None
            if count_gan < max_gan:
                posicion_ganador = count_gan + 1

            cols_ins = [
                "posicion_orden_ganador", "qr_id", "qr_uuid",
                "acepta_terminos", "acepta_habeas", "acepta_terminos_at", "acepta_habeas_at",
                "nombres_apellidos", "celular", "telefono_fijo", "celular_confirmacion",
                "correo_electronico", "direccion", "barrio", "municipio", "ciudad",
                "es_bogota_direccion", "modalidad_entrega", "ip_cliente", "user_agent",
            ]
            if DB_ENGINE == "POSTGRES":
                placeholders = ", ".join(["%s"] * len(cols_ins))
                sql_ins = f"INSERT INTO promo_registros ({', '.join(cols_ins)}) VALUES ({placeholders}) RETURNING id"
            else:
                placeholders = ", ".join(["?"] * len(cols_ins))
                sql_ins = f"INSERT INTO promo_registros ({', '.join(cols_ins)}) VALUES ({placeholders})"
            values = (
                posicion_ganador, qr_id, qr_uuid,
                bool(req.acepta_terminos), bool(req.acepta_habeas), acepta_t_at, acepta_h_at,
                req.nombres_apellidos, req.celular, req.telefono_fijo, req.celular_confirmacion,
                req.correo_electronico, req.direccion, req.barrio, req.municipio, req.ciudad,
                es_bogota, modalidad, ip_cliente, user_agent,
            )
            cur.execute(sql_ins, values)
            if DB_ENGINE == "POSTGRES":
                new_id = cur.fetchone()[0]
            else:
                new_id = cur.lastrowid

            if DB_ENGINE == "POSTGRES":
                cur.execute(
                    "UPDATE promo_qr_codes SET usado_registro_id = %s, usado_at = NOW() WHERE id = %s AND usado_registro_id IS NULL",
                    (new_id, qr_id),
                )
            else:
                cur.execute(
                    "UPDATE promo_qr_codes SET usado_registro_id = ?, usado_at = STRFTIME('%Y-%m-%dT%H:%M:%SZ','now') WHERE id = ? AND usado_registro_id IS NULL",
                    (new_id, qr_id),
                )
            if cur.rowcount != 1:
                conn.rollback()
                raise HTTPException(status_code=409, detail="QR concurrentemente utilizado")

            conn.commit()

            ganador = posicion_ganador is not None
            mensaje_agradecimiento = (
                f"¡FELICITACIONES! Eres el ganador #{posicion_ganador} de {titulo_premio}. "
                f"{'Te lo enviaremos a tu domicilio en Bogotá.' if es_bogota else f'Retíralo en {dir_fuera}.'}"
            ) if ganador else (
                f"Gracias por participar, {req.nombres_apellidos}. "
                f"No fuiste ganador esta vez, pero sigue disfrutando Aguardiente Blanco del Valle."
            )
            return {
                "registro_id": int(new_id),
                "ganador": ganador,
                "posicion_orden_ganador": posicion_ganador,
                "es_bogota": es_bogota,
                "modalidad_entrega": modalidad,
                "direccion_recoger_cra74": dir_fuera,
                "mensaje_agradecimiento": mensaje_agradecimiento,
                "nombres_apellidos": req.nombres_apellidos,
            }
        except HTTPException:
            raise
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            raise HTTPException(status_code=500, detail=f"Error registro: {str(e)}")


# D) GET /api/promo/agradecimiento/{registro_id}
@app.get("/api/promo/agradecimiento/{registro_id}")
def promo_agradecimiento(registro_id: int):
    with get_db_conn() as conn:
        cur = conn.cursor()
        cols = [
            "id", "posicion_orden_ganador", "qr_uuid", "nombres_apellidos",
            "celular", "correo_electronico", "direccion", "ciudad",
            "es_bogota_direccion", "modalidad_entrega", "created_at",
        ]
        sql = "SELECT id, posicion_orden_ganador, qr_uuid, nombres_apellidos, celular, correo_electronico, direccion, ciudad, es_bogota_direccion, modalidad_entrega, created_at FROM promo_registros WHERE id = %s" if DB_ENGINE == "POSTGRES" else "SELECT id, posicion_orden_ganador, qr_uuid, nombres_apellidos, celular, correo_electronico, direccion, ciudad, es_bogota_direccion, modalidad_entrega, created_at FROM promo_registros WHERE id = ?"
        cur.execute(sql, (registro_id,))
        row = cur.fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Registro no encontrado")
        d = _promo_row_to_dict(row, cols)

        cur.execute("SELECT dir_fuera_bogota, titulo_premio, max_ganadores FROM promo_config WHERE id = 1")
        cfg = cur.fetchone()
        dir_fuera = str(cfg[0] or "Cra. 74a #51a-87, Bogotá")
        titulo_premio = str(cfg[1] or "Botella Aguardiente Blanco del Valle Fiesta")

        es_bogota = bool(d["es_bogota_direccion"]) if DB_ENGINE == "POSTGRES" else (int(d["es_bogota_direccion"]) == 1)
        ganador = d["posicion_orden_ganador"] is not None
        mensaje_agradecimiento = (
            f"¡FELICITACIONES! Eres el ganador #{d['posicion_orden_ganador']} de {titulo_premio}. "
            f"{'Te lo enviaremos a tu domicilio en Bogotá.' if es_bogota else f'Retíralo en {dir_fuera}.'}"
        ) if ganador else (
            f"Gracias por participar, {d['nombres_apellidos']}. "
            f"No fuiste ganador esta vez, pero sigue disfrutando Aguardiente Blanco del Valle."
        )
        return {
            "registro_id": int(d["id"]),
            "ganador": ganador,
            "posicion_orden_ganador": d["posicion_orden_ganador"],
            "es_bogota": es_bogota,
            "modalidad_entrega": d["modalidad_entrega"],
            "direccion_recoger_cra74": dir_fuera,
            "mensaje_agradecimiento": mensaje_agradecimiento,
            "nombres_apellidos": d["nombres_apellidos"],
            "details": {
                "qr_uuid": d["qr_uuid"],
                "celular": d["celular"],
                "correo_electronico": d["correo_electronico"],
                "direccion": d["direccion"],
                "ciudad": d["ciudad"],
                "created_at": d["created_at"],
            },
        }


# ================= ENDPOINTS ADMIN =================

# E) POST /api/admin/login
@app.post("/api/admin/login")
def admin_login(req: AdminLoginReq):
    username = (req.username or "").strip()
    password = req.password or ""
    if not username or not password:
        raise HTTPException(status_code=400, detail="username y password requeridos")
    admin = _promo_get_admin_from_db(username)
    if admin is None:
        raise HTTPException(status_code=401, detail="Credenciales inválidas")
    if not _promo_verify_password(password, admin["password_hash"]):
        raise HTTPException(status_code=401, detail="Credenciales inválidas")
    token = _promo_create_access_token(int(admin["id"]), admin["username"])
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": 86400,
        "username": admin["username"],
    }


# F) GET /api/admin/config
@app.get("/api/admin/config")
def admin_get_config(admin: dict = _promo_Depends(get_current_admin)):
    with get_db_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id, max_ganadores, estado_abierto, titulo_premio, desc_premio, dir_fuera_bogota, updated_at FROM promo_config WHERE id = 1")
        row = cur.fetchone()
        if row is None:
            raise HTTPException(status_code=500, detail="Config no inicializada")
        cfg = {
            "id": row[0],
            "max_ganadores": int(row[1] or 1),
            "estado_abierto": bool(row[2]) if DB_ENGINE == "POSTGRES" else (int(row[2]) == 1),
            "titulo_premio": row[3],
            "desc_premio": row[4],
            "dir_fuera_bogota": row[5],
            "updated_at": row[6],
        }
        return cfg


# G) PUT /api/admin/config
@app.put("/api/admin/config")
def admin_update_config(req: AdminConfigUpdateReq, admin: dict = _promo_Depends(get_current_admin)):
    with get_db_conn() as conn:
        cur = conn.cursor()
        updates = []
        params = []
        if req.max_ganadores is not None:
            updates.append("max_ganadores = %s" if DB_ENGINE == "POSTGRES" else "max_ganadores = ?")
            params.append(int(req.max_ganadores))
        if req.estado_abierto is not None:
            updates.append("estado_abierto = %s" if DB_ENGINE == "POSTGRES" else "estado_abierto = ?")
            params.append(req.estado_abierto if DB_ENGINE == "POSTGRES" else (1 if req.estado_abierto else 0))
        if req.titulo_premio is not None:
            updates.append("titulo_premio = %s" if DB_ENGINE == "POSTGRES" else "titulo_premio = ?")
            params.append(req.titulo_premio)
        if req.desc_premio is not None:
            updates.append("desc_premio = %s" if DB_ENGINE == "POSTGRES" else "desc_premio = ?")
            params.append(req.desc_premio)
        if req.dir_fuera_bogota is not None:
            updates.append("dir_fuera_bogota = %s" if DB_ENGINE == "POSTGRES" else "dir_fuera_bogota = ?")
            params.append(req.dir_fuera_bogota)
        if not updates:
            return {"ok": True, "updated": False, "mensaje": "Sin cambios"}
        updates.append("updated_at = NOW()" if DB_ENGINE == "POSTGRES" else "updated_at = STRFTIME('%Y-%m-%dT%H:%M:%SZ','now')")
        sql = f"UPDATE promo_config SET {', '.join(updates)} WHERE id = 1"
        if DB_ENGINE == "POSTGRES":
            cur.execute(sql, tuple(params))
        else:
            cur.execute(sql, params)
        conn.commit()
    _promo_insert_auditoria(int(admin["id"]), "UPDATE_CONFIG", req.model_dump(exclude_none=True))
    return {"ok": True, "updated": True}


# H) GET /api/admin/registros
@app.get("/api/admin/registros")
def admin_list_registros(
    page: int = 1,
    per_page: int = 100,
    sort: str = "created_at_asc",
    filtro_ciudad: str | None = None,
    filtro_es_bogota: bool | None = None,
    filtro_ganador: bool | None = None,
    admin: dict = _promo_Depends(get_current_admin),
):
    page = max(1, int(page or 1))
    per_page = max(1, min(500, int(per_page or 100)))
    offset = (page - 1) * per_page

    base_where = []
    params = []
    if filtro_ciudad:
        base_where.append("ciudad ILIKE %s" if DB_ENGINE == "POSTGRES" else "ciudad LIKE ?")
        params.append(f"%{filtro_ciudad}%")
    if filtro_es_bogota is not None:
        v = 1 if filtro_es_bogota else 0
        base_where.append("es_bogota_direccion = %s" if DB_ENGINE == "POSTGRES" else "es_bogota_direccion = ?")
        params.append(v if DB_ENGINE == "POSTGRES" else v)
    if filtro_ganador is not None:
        if filtro_ganador:
            base_where.append("posicion_orden_ganador IS NOT NULL")
        else:
            base_where.append("posicion_orden_ganador IS NULL")

    where_sql = f" WHERE {' AND '.join(base_where)}" if base_where else ""

    sort_map = {
        "created_at_asc": "created_at ASC",
        "created_at_desc": "created_at DESC",
        "posicion_asc": "posicion_orden_ganador ASC NULLS LAST, created_at DESC" if DB_ENGINE == "POSTGRES" else "CASE WHEN posicion_orden_ganador IS NULL THEN 1 ELSE 0 END, posicion_orden_ganador ASC, created_at DESC",
        "posicion_desc": "posicion_orden_ganador DESC NULLS LAST, created_at DESC" if DB_ENGINE == "POSTGRES" else "posicion_orden_ganador DESC, created_at DESC",
        "nombre_asc": "nombres_apellidos ASC",
    }
    order_sql = sort_map.get(sort, sort_map["created_at_asc"])

    cols = [
        "id", "posicion_orden_ganador", "qr_id", "qr_uuid",
        "acepta_terminos", "acepta_habeas", "acepta_terminos_at", "acepta_habeas_at",
        "nombres_apellidos", "celular", "telefono_fijo", "celular_confirmacion",
        "correo_electronico", "direccion", "barrio", "municipio", "ciudad",
        "es_bogota_direccion", "modalidad_entrega", "created_at", "ip_cliente", "user_agent",
    ]
    cols_str = ", ".join(cols)

    with get_db_conn() as conn:
        cur = conn.cursor()
        cur.execute(f"SELECT COUNT(*) FROM promo_registros{where_sql}", tuple(params) if DB_ENGINE == "POSTGRES" else params)
        total = int(cur.fetchone()[0] or 0)

        ph = "%s" if DB_ENGINE == "POSTGRES" else "?"
        limit_sql = f" LIMIT {ph} OFFSET {ph}"
        qp = list(params) + [per_page, offset]
        cur.execute(
            f"SELECT {cols_str} FROM promo_registros{where_sql} ORDER BY {order_sql}{limit_sql}",
            tuple(qp) if DB_ENGINE == "POSTGRES" else qp,
        )
        items = _promo_fetch_all_to_dicts(cur, cols)
        for it in items:
            if "es_bogota_direccion" in it:
                it["es_bogota_direccion"] = bool(it["es_bogota_direccion"]) if DB_ENGINE == "POSTGRES" else (int(it["es_bogota_direccion"] or 0) == 1)
            if "acepta_terminos" in it:
                it["acepta_terminos"] = bool(it["acepta_terminos"]) if DB_ENGINE == "POSTGRES" else (int(it["acepta_terminos"] or 0) == 1)
            if "acepta_habeas" in it:
                it["acepta_habeas"] = bool(it["acepta_habeas"]) if DB_ENGINE == "POSTGRES" else (int(it["acepta_habeas"] or 0) == 1)
    return {
        "total": total,
        "page": page,
        "per_page": per_page,
        "items": items,
    }


# I) PUT /api/admin/registros/{id}
@app.put("/api/admin/registros/{id}")
def admin_update_registro(id: int, req: AdminRegistroUpdateReq, admin: dict = _promo_Depends(get_current_admin)):
    with get_db_conn() as conn:
        cur = conn.cursor()
        updates = []
        params = []
        ph = "%s" if DB_ENGINE == "POSTGRES" else "?"
        data = req.model_dump(exclude_none=True)
        for k, v in data.items():
            if k == "ciudad":
                continue
            if k == "es_bogota_direccion":
                continue
            updates.append(f"{k} = {ph}")
            if isinstance(v, bool) and DB_ENGINE != "POSTGRES":
                params.append(1 if v else 0)
            else:
                params.append(v)
        if "ciudad" in data or "direccion" in data:
            cur.execute(f"SELECT ciudad, direccion FROM promo_registros WHERE id = {ph}", (id,) if DB_ENGINE == "POSTGRES" else [id])
            row = cur.fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="Registro no encontrado")
            c = data.get("ciudad", row[0])
            d = data.get("direccion", row[1])
            es_b = _promo_es_bogota(c or "", d or "")
            mod = "DOMICILIO_BTA" if es_b else "RECOGER_CRA74"
            if "modalidad_entrega" not in data:
                updates.append(f"modalidad_entrega = {ph}")
                params.append(mod)
            updates.append(f"es_bogota_direccion = {ph}")
            params.append(es_b if DB_ENGINE == "POSTGRES" else (1 if es_b else 0))
        if not updates:
            return {"ok": True, "updated": False}
        params.append(id)
        sql = f"UPDATE promo_registros SET {', '.join(updates)} WHERE id = {ph}"
        cur.execute(sql, tuple(params) if DB_ENGINE == "POSTGRES" else params)
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Registro no encontrado")
        conn.commit()
    _promo_insert_auditoria(int(admin["id"]), "UPDATE_REGISTRO", {"id": id, **data})
    return {"ok": True, "updated": True, "id": id}


# J) DELETE /api/admin/registros/{id} (RENUMERACIÓN ATÓMICA)
@app.delete("/api/admin/registros/{id}")
def admin_delete_registro(id: int, admin: dict = _promo_Depends(get_current_admin)):
    with get_db_conn() as conn:
        conn.autocommit = False
        try:
            cur = conn.cursor()
            ph = "%s" if DB_ENGINE == "POSTGRES" else "?"
            if DB_ENGINE == "POSTGRES":
                cur.execute("BEGIN")
                cur.execute(f"SELECT id, posicion_orden_ganador FROM promo_registros WHERE id = {ph} FOR UPDATE", (id,))
            else:
                cur.execute("BEGIN IMMEDIATE")
                cur.execute(f"SELECT id, posicion_orden_ganador FROM promo_registros WHERE id = {ph}", (id,))
            row = cur.fetchone()
            if row is None:
                if DB_ENGINE != "POSTGRES":
                    conn.rollback()
                raise HTTPException(status_code=404, detail="Registro no encontrado")
            posicion_eliminado = row[1]
            cur.execute(f"DELETE FROM promo_registros WHERE id = {ph}", (id,))
            cur.execute(f"UPDATE promo_qr_codes SET usado_registro_id = NULL, usado_at = NULL WHERE usado_registro_id = {ph}", (id,))

            recalculated = 0
            if posicion_eliminado is not None:
                if DB_ENGINE == "POSTGRES":
                    cur.execute(
                        f"UPDATE promo_registros SET posicion_orden_ganador = posicion_orden_ganador - 1 WHERE posicion_orden_ganador > {ph} ORDER BY posicion_orden_ganador ASC",
                        (posicion_eliminado,),
                    )
                else:
                    cur.execute(
                        f"UPDATE promo_registros SET posicion_orden_ganador = posicion_orden_ganador - 1 WHERE posicion_orden_ganador > {ph}",
                        (posicion_eliminado,),
                    )
                recalculated = cur.rowcount or 0
            conn.commit()
        except HTTPException:
            raise
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            raise HTTPException(status_code=500, detail=f"Error delete: {str(e)}")
    _promo_insert_auditoria(int(admin["id"]), "DELETE_REGISTRO", {"id": id, "posicion_eliminada": posicion_eliminado})
    return {
        "ok": True,
        "deleted_id": id,
        "deleted_position": posicion_eliminado,
        "positions_recalculated_count": int(recalculated or 0),
    }


# K) GET /api/admin/registros/xlsx
@app.get("/api/admin/registros/xlsx")
def admin_registros_xlsx(admin: dict = _promo_Depends(get_current_admin)):
    import openpyxl as _xl
    from openpyxl.styles import Font as _XlFont

    wb = _xl.Workbook()
    ws = wb.active
    ws.title = "Registros Promo"
    headers = [
        "Posición", "Fecha Registro", "QR Usado", "Nombres y Apellidos",
        "Celular", "Teléfono Fijo", "Correo", "Dirección", "Barrio",
        "Municipio", "Ciudad", "Es Bogotá?", "Modalidad Entrega",
        "Aceptó Términos?", "Aceptó Habeas Data?", "IP", "User Agent",
    ]
    ws.append(headers)
    for cell in ws[1]:
        cell.font = _XlFont(bold=True)

    cols = [
        "posicion_orden_ganador", "created_at", "qr_uuid", "nombres_apellidos",
        "celular", "telefono_fijo", "correo_electronico", "direccion", "barrio",
        "municipio", "ciudad", "es_bogota_direccion", "modalidad_entrega",
        "acepta_terminos", "acepta_habeas", "ip_cliente", "user_agent",
    ]
    cols_str = ", ".join(cols)
    with get_db_conn() as conn:
        cur = conn.cursor()
        cur.execute(f"SELECT {cols_str} FROM promo_registros ORDER BY COALESCE(posicion_orden_ganador, 999999999) ASC, created_at ASC")
        rows = cur.fetchall()
        for r in rows:
            d = _promo_row_to_dict(r, cols)
            es_bog = bool(d["es_bogota_direccion"]) if DB_ENGINE == "POSTGRES" else (int(d["es_bogota_direccion"] or 0) == 1)
            acc_t = bool(d["acepta_terminos"]) if DB_ENGINE == "POSTGRES" else (int(d["acepta_terminos"] or 0) == 1)
            acc_h = bool(d["acepta_habeas"]) if DB_ENGINE == "POSTGRES" else (int(d["acepta_habeas"] or 0) == 1)
            ws.append([
                d["posicion_orden_ganador"] if d["posicion_orden_ganador"] is not None else "",
                d["created_at"],
                d["qr_uuid"],
                d["nombres_apellidos"],
                d["celular"] or "",
                d["telefono_fijo"] or "",
                d["correo_electronico"],
                d["direccion"],
                d["barrio"] or "",
                d["municipio"] or "",
                d["ciudad"],
                ("SÍ" if es_bog else "NO"),
                d["modalidad_entrega"],
                ("SÍ" if acc_t else "NO"),
                ("SÍ" if acc_h else "NO"),
                d["ip_cliente"] or "",
                (d["user_agent"] or "")[:200],
            ])

    for col_idx, _ in enumerate(headers, start=1):
        max_len = 15
        for row in ws.iter_rows(min_col=col_idx, max_col=col_idx, values_only=True):
            val = row[0]
            if val is not None:
                max_len = max(max_len, min(50, len(str(val)) + 2))
        ws.column_dimensions[_xl.utils.get_column_letter(col_idx)].width = max_len

    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    fname = f"abv-fiesta-promocion-{ts}.xlsx"
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    _promo_insert_auditoria(int(admin["id"]), "EXPORT_XLSX", {"filename": fname, "total_rows": len(rows)})
    return FileResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=fname,
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


# L) POST /api/admin/qr/generar
@app.post("/api/admin/qr/generar")
async def admin_qr_generar(req: AdminQrGenerarReq, request: Request, admin: dict = _promo_Depends(get_current_admin)):
    cantidad = int(req.cantidad or 0)
    if cantidad < 1 or cantidad > 5000:
        raise HTTPException(status_code=400, detail="cantidad debe estar entre 1 y 5000")
    size_px = int(req.size_px or 512)
    if size_px < 256 or size_px > 2048:
        raise HTTPException(status_code=400, detail="size_px debe estar entre 256 y 2048")
    formato = (req.formato or "png").lower()
    if formato not in ("png", "svg"):
        raise HTTPException(status_code=400, detail="formato debe ser 'png' o 'svg'")

    scheme = request.base_url.scheme
    host_hdr = request.headers.get("host", "")
    frontend_base_url = f"{scheme}://{host_hdr}" if host_hdr else str(request.base_url).rstrip("/")
    if not frontend_base_url.endswith("/"):
        frontend_base_url += "/"

    import qrcode as _qrcode
    alphabet = _promo_string.ascii_uppercase + _promo_string.digits
    created_items = []

    with get_db_conn() as conn:
        cur = conn.cursor()
        for _ in range(cantidad):
            while True:
                qr_uuid = str(uuid.uuid4())
                cur.execute("SELECT 1 FROM promo_qr_codes WHERE uuid_qr = %s" if DB_ENGINE == "POSTGRES" else "SELECT 1 FROM promo_qr_codes WHERE uuid_qr = ?", (qr_uuid,))
                if cur.fetchone() is None:
                    break
            while True:
                id_humano = "".join(_promo_random.choices(alphabet, k=9))
                cur.execute("SELECT 1 FROM promo_qr_codes WHERE id_humano = %s" if DB_ENGINE == "POSTGRES" else "SELECT 1 FROM promo_qr_codes WHERE id_humano = ?", (id_humano,))
                if cur.fetchone() is None:
                    break
            url_full = f"{frontend_base_url}ganador?qr={qr_uuid}"
            sql = "INSERT INTO promo_qr_codes (uuid_qr, id_humano, size_px, formato, creado_admin_id) VALUES (%s, %s, %s, %s, %s) RETURNING id" if DB_ENGINE == "POSTGRES" else "INSERT INTO promo_qr_codes (uuid_qr, id_humano, size_px, formato, creado_admin_id) VALUES (?, ?, ?, ?, ?)"
            params = (qr_uuid, id_humano, size_px, formato, int(admin["id"]))
            cur.execute(sql, params)
            if DB_ENGINE == "POSTGRES":
                new_id = cur.fetchone()[0]
            else:
                new_id = cur.lastrowid

            if formato == "png":
                qr = _qrcode.QRCode(
                    version=None,
                    error_correction=_qrcode.constants.ERROR_CORRECT_H,
                    box_size=max(1, size_px // 30),
                    border=4,
                )
                qr.add_data(url_full)
                qr.make(fit=True)
                img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
                img = img.resize((size_px, size_px), Image.LANCZOS if hasattr(Image, "LANCZOS") else Image.Resampling.LANCZOS)
                qbuf = io.BytesIO()
                img.save(qbuf, format="PNG")
                qbuf.seek(0)
                b64 = "data:image/png;base64," + base64.b64encode(qbuf.getvalue()).decode("ascii")
                created_items.append({
                    "id": int(new_id),
                    "qr_uuid": qr_uuid,
                    "id_humano": id_humano,
                    "size_px": size_px,
                    "url": url_full,
                    "data_url_png_b64": b64,
                })
            else:
                qr = _qrcode.QRCode(
                    version=None,
                    error_correction=_qrcode.constants.ERROR_CORRECT_H,
                    box_size=max(1, size_px // 30),
                    border=4,
                )
                qr.add_data(url_full)
                qr.make(fit=True)
                from qrcode.image.svg import SvgPathImage as _SvgPathImage
                svg_img = qr.make_image(image_factory=_SvgPathImage)
                import io as _io
                sbuf = _io.BytesIO()
                svg_img.save(sbuf)
                svg_text = sbuf.getvalue().decode("utf-8")
                created_items.append({
                    "id": int(new_id),
                    "qr_uuid": qr_uuid,
                    "id_humano": id_humano,
                    "size_px": size_px,
                    "url": url_full,
                    "svg_text": svg_text,
                })
        conn.commit()

    _promo_insert_auditoria(int(admin["id"]), "GENERAR_QR", {"cantidad": cantidad, "size_px": size_px, "formato": formato})
    return {
        "created_count": len(created_items),
        "items": created_items,
    }


# M) GET /api/admin/qr/list
@app.get("/api/admin/qr/list")
def admin_qr_list(
    usado: bool | None = None,
    page: int = 1,
    per_page: int = 100,
    admin: dict = _promo_Depends(get_current_admin),
):
    page = max(1, int(page or 1))
    per_page = max(1, min(1000, int(per_page or 100)))
    offset = (page - 1) * per_page
    where = []
    params = []
    ph = "%s" if DB_ENGINE == "POSTGRES" else "?"
    if usado is not None:
        if usado:
            where.append("usado_registro_id IS NOT NULL")
        else:
            where.append("usado_registro_id IS NULL")
    where_sql = f" WHERE {' AND '.join(where)}" if where else ""

    cols = ["id", "uuid_qr", "id_humano", "size_px", "formato", "usado_registro_id", "usado_at", "creado_admin_id", "created_at"]
    cols_str = ", ".join(cols)
    with get_db_conn() as conn:
        cur = conn.cursor()
        cur.execute(f"SELECT COUNT(*) FROM promo_qr_codes{where_sql}", tuple(params) if DB_ENGINE == "POSTGRES" else params)
        total = int(cur.fetchone()[0] or 0)
        qp = list(params) + [per_page, offset]
        cur.execute(
            f"SELECT {cols_str} FROM promo_qr_codes{where_sql} ORDER BY id DESC LIMIT {ph} OFFSET {ph}",
            tuple(qp) if DB_ENGINE == "POSTGRES" else qp,
        )
        items = _promo_fetch_all_to_dicts(cur, cols)
    return {"total": total, "page": page, "per_page": per_page, "items": items}


# N) GET /api/admin/auditoria
@app.get("/api/admin/auditoria")
def admin_auditoria(
    page: int = 1,
    per_page: int = 100,
    admin: dict = _promo_Depends(get_current_admin),
):
    page = max(1, int(page or 1))
    per_page = max(1, min(500, int(per_page or 100)))
    offset = (page - 1) * per_page
    ph = "%s" if DB_ENGINE == "POSTGRES" else "?"
    cols = ["id", "admin_id", "accion", "detalles", "created_at"]
    cols_str = ", ".join(cols)
    with get_db_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM promo_auditoria_admin")
        total = int(cur.fetchone()[0] or 0)
        cur.execute(
            f"SELECT {cols_str} FROM promo_auditoria_admin ORDER BY created_at DESC, id DESC LIMIT {ph} OFFSET {ph}",
            (per_page, offset) if DB_ENGINE == "POSTGRES" else [per_page, offset],
        )
        rows = cur.fetchall()
        items = []
        for r in rows:
            d = _promo_row_to_dict(r, cols)
            det = d.get("detalles")
            if det:
                try:
                    if isinstance(det, str):
                        d["detalles"] = json.loads(det)
                except Exception:
                    pass
            items.append(d)
    return {"total": total, "page": page, "per_page": per_page, "items": items}

