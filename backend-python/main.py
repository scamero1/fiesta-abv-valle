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
def _alpha_erode(alpha_pil: Image.Image, radius_px: int = 1) -> Image.Image:
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
    min_area_ratio: float = 0.08,
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
    alpha_eroded_1 = _alpha_erode(alpha_pil, radius_px=1)
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
    n_pers = _detect_n_personas_from_components(alpha_crop_arr, min_area_ratio=0.08)
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
