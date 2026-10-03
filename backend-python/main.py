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
from pydantic import BaseModel, Field, field_validator, model_validator
from typing import Any
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


def _clean_env_str(raw, *, strip_slash_end=False, is_url_like=False):
    """Limpiador UNIVERSAL anti-backticks / comillas / espacios para Railway env vars.

    Railway NO limpia los valores de variables al copiar/pegar desde Markdown.
    Si el usuario pega `https://dominio` con backticks incluidos, el valor
    queda con el backtick como LITERAL parte del dominio → DNS falla instantáneo.

    Limpia AUTOMÁTICAMENTE:
      - backticks ` , comillas dobles " , comillas simples ' , espacios, tabs,
        non-break-space (U+00A0) al INICIO y al FIN del valor.
      - si strip_slash_end=True: quita slashes / finales duplicados.
      - is_url_like=True: hace trim de ambos extremos y strip slash.
    """
    if raw is None:
        return ""
    s = str(raw)
    s = s.lstrip(" \t\r\n\f\v\u00A0`\"'")
    s = s.rstrip(" \t\r\n\f\v\u00A0`\"'")
    if strip_slash_end or is_url_like:
        s = s.rstrip("/")
    return s


# ====== DATABASE (PostgreSQL vía Private Network / fallback SQLite) ======
DATABASE_URL = _clean_env_str(os.environ.get("DATABASE_URL", ""))
# ⚠️ Railway inyecta DATABASE_URL automáticamente AL ATTACHAR LA DB VÍA PRIVATE NETWORKING.
# El host público proxy.rlwy.net es válido (egress costs billable), pero si el usuario NO tiene
# opción "Attach Database" en Railway UI (solo dispone del URL público), lo aceptamos igualmente.
# Host interno recomendado (gratis, 0 egress): *.railway.internal en puerto 5432.
#
# IMPORTANTE SSL: Railway proxy público proxy.rlwy.net REQUIERE sslmode=require OBLIGATORIO.
# Si el usuario no lo agrega manualmente, falla con "invalid response to SSL negotiation: H".
# Solución: normalizamos AUTOMÁTICAMENTE el URL agregando ?sslmode=require cuando:
#   (a) el URL NO trae ningún param sslmode, O
#   (b) el host contiene .railway. (proxy público o Private Network)
def _normalizar_pg_url_con_ssl(raw_url: str) -> str:
    """Agrega sslmode=require a un URL PostgreSQL si no lo tiene o si es Railway.
    Retorna el URL listo para psycopg3."""
    if not raw_url:
        return raw_url
    u = str(raw_url).strip()
    # Permitir al usuario sobreescribir explícitamente: si ya hay sslmode=X dejarlo
    try:
        from urllib.parse import urlparse, parse_qsl, urlencode, urlunparse
    except Exception:
        # Si urllib no sirve, fallback simple por string:
        if "sslmode=" not in u:
            sep = "&" if ("?" in u) else "?"
            return u + sep + "sslmode=require"
        return u
    try:
        parsed = urlparse(u)
        # Si no es postgres, retornar igual
        if parsed.scheme not in ("postgres", "postgresql", "postgres+psycopg", "postgresql+psycopg"):
            return u
        params = dict(parse_qsl(parsed.query, keep_blank_values=True))
        host = (parsed.hostname or "").lower()
        es_railway = ("railway" in host) or ("proxy.rlwy.net" in host)
        sslmode_user = params.get("sslmode", None)
        if sslmode_user is None or sslmode_user.strip() == "":
            # Usuario NO puso sslmode; Railway requiere sslmode=require
            params["sslmode"] = "require"
        elif es_railway and sslmode_user.lower() in ("disable", "allow", "prefer"):
            # Usuario puso un sslmode incompatible con Railway: sobreescribimos a require
            params["sslmode"] = "require"
        # RAILWAY ESPECIAL: algunos proxies públicos Railway NO soportan GSS (Kerberos) ni
        # channel_binding SCRAM-SHA-256-PLUS. Para evitar fallos por handshake extendido
        # forzamos gssencmode=disable y channel_binding=disable automáticamente en Railway.
        if es_railway:
            if not params.get("gssencmode"):
                params["gssencmode"] = "disable"
            if not params.get("channel_binding"):
                params["channel_binding"] = "disable"
            if not params.get("target_session_attrs"):
                params["target_session_attrs"] = "read-write"
        # Reconstrir URL
        new_query = urlencode(params)
        rebuilt = parsed._replace(query=new_query)
        return urlunparse(rebuilt)
    except Exception:
        # Fallback simple
        if "sslmode=" not in u:
            sep = "&" if ("?" in u) else "?"
            return u + sep + "sslmode=require"
        return u

_pg_is_public_proxy = False
_diff_params = False
if DATABASE_URL:
    # Detectar Railway público ANTES de normalizar
    _pg_is_public_proxy = bool("proxy.rlwy.net" in DATABASE_URL)
    if _pg_is_public_proxy:
        print("[DB] ℹ️ Info: DATABASE_URL apunta a host público Railway proxy.rlwy.net (egress billable). "
              "Se usará PostgreSQL vía URL pública. Recomendación: Attach Database vía UI Railway para "
              "Private Network *.railway.internal (0 costo).")
    # Normalizar SSL MODE siempre (agrega sslmode=require si faltaba)
    try:
        _DATABASE_URL_ORIG = DATABASE_URL
        DATABASE_URL = _normalizar_pg_url_con_ssl(DATABASE_URL)
        _diff_params = bool(DATABASE_URL != _DATABASE_URL_ORIG)
    except Exception:
        _diff_params = False
    # Log info SSL modificado
    if _diff_params and DATABASE_URL.startswith("postgres"):
        print("[DB] 🔐 SSL Auto: agregado sslmode=require al DATABASE_URL (Railway proxy lo requiere).")
    elif not _diff_params and DATABASE_URL.startswith("postgres") and "sslmode=" in DATABASE_URL:
        try:
            from urllib.parse import urlparse, parse_qsl
            _p = urlparse(DATABASE_URL)
            _params = dict(parse_qsl(_p.query))
            _mode = (_params.get("sslmode") or "").lower()
            print(f"[DB] 🔐 SSL: DATABASE_URL trae sslmode={_mode!r} (usaré ese).")
        except Exception:
            pass

DB_ENGINE = "POSTGRES" if (HAS_PSYCOPG and DATABASE_URL and DATABASE_URL.startswith("postgres")) else "SQLITE"
SQLITE_PATH = os.path.join(BASE_DIR, "fotos-local.sqlite3")


def _pg_connect_ssl_fallback(url_base: str, **extra_kwargs):
    """Conecta a PostgreSQL probando 3 configuraciones SSL en orden.
    Railway proxy público usualmente requiere sslmode=require.
    Fallback chain:
      1) sslmode=require (para Railway)
      2) sslmode=verify-ca (si el user trajo CA)
      3) sslmode=disable / sin param
    Devuelve la conexión psycopg abierta o lanza la ÚLTIMA excepción capturada."""
    if not HAS_PSYCOPG:
        raise RuntimeError("psycopg3 no está disponible; verifica requirements.")
    def _append_sslmode(url, mode):
        try:
            from urllib.parse import urlparse, parse_qsl, urlencode, urlunparse
            parsed = urlparse(url)
            params = dict(parse_qsl(parsed.query, keep_blank_values=True))
            params["sslmode"] = mode
            return urlunparse(parsed._replace(query=urlencode(params)))
        except Exception:
            sep = "?" if "?" not in url else "&"
            # Quitar sslmode anterior si lo tiene por string simple
            base = url
            if "sslmode=" in base:
                import re as _re
                base = _re.sub(r"[?&]sslmode=[^&]*", "", base)
                if not "?" in base:
                    base = base + "?"
                    sep = ""
            return base + (sep if sep else "&") + f"sslmode={mode}"
    attempts = []
    # Orden intentos: require (Railway default) → verify-full → prefer → disable
    ssl_order = ["require", "verify-ca", "prefer", "disable"]
    last_exc = None
    for mode in ssl_order:
        url_tried = _append_sslmode(url_base or "", mode)
        try:
            conn = psycopg.connect(
                url_tried,
                autocommit=False,
                connect_timeout=18,
                **extra_kwargs
            )
            print(f"[DB] ✅ Conectado PostgreSQL OK con sslmode={mode!r}.")
            return conn
        except Exception as e:
            msg = str(e)
            attempts.append((mode, type(e).__name__, msg[:240]))
            last_exc = e
            # Short-circuit INTELIGENTE: NO probar resto modos si el error es
            # "no es un servidor PostgreSQL real responde HTTP / puerto cerrado / auth fail"
            _msg_low = msg.lower()
            _es_http_resp = (
                "received invalid response to ssl negotiation: h" in _msg_low or
                "expected authentication request from server, but received h" in _msg_low or
                ("received h" in _msg_low and "ssl" in _msg_low)
            )
            if _es_http_resp:
                print("[DB] 🚨 PROBLEMA DETECTADO: el host:port NO es un PostgreSQL Railway válido "
                      "(contesta HTTP, no PG protocol). Seguramente el Connection String (DATABASE_URL) es VIEJO. "
                      "Solución: entra a Railway → Database → Settings → Connect → Copy el Connection URL NUEVO. "
                      "NO pegues backticks/comillas dentro del valor.")
                # No tiene sentido probar el resto de sslmodes
                break
            _es_ssl = ("ssl" in _msg_low or "SSL negotiation" in msg or "sslmode" in msg or "certificate" in _msg_low or "tlsv" in _msg_low)
            if not _es_ssl and (
                "password authentication" in _msg_low or "role" in _msg_low or
                "does not exist" in _msg_low or "pg_hba" in _msg_low or
                "timeout expired" in _msg_low or "could not translate host" in _msg_low or
                "connection refused" in _msg_low or "network is unreachable" in _msg_low
            ):
                # Auth / DNS / timeout / cerrado: 1er intento falló resto igual
                break
    # Si llegamos aquí: todos los intentos fallaron
    err_log = " | ".join([f"[{m}] {t}: {s[:90]}" for (m, t, s) in attempts])
    print(f"[DB] ❌ Falló PostgreSQL en TODOS los sslmode. Intentos: {err_log}")
    # Aviso final troubleshooting
    print("[DB] 🧰 Troubleshooting DATABASE_URL Railway: (1) abre la DB en Railway → Settings → Connect → "
          "Public Network → Copy 'Connection URL' (no el de Private si no tienes Attach DB). "
          "(2) En Backend Variables → DATABASE_URL → NEW/Edit → PEGA SIN ESPACIOS SIN COMILLAS SIN BACKTICKS. "
          "(3) Redeploy manual.")
    if last_exc is not None:
        raise last_exc
    raise RuntimeError("No se pudo conectar a PostgreSQL (fallback chain agotada).")

@contextmanager
def get_db_conn():
    conn = None
    commited_or_rollbacked = False
    try:
        if DB_ENGINE == "POSTGRES":
            # NOTA: psycopg3 autocommit=False inicia una transacción IMPLÍCITA al primer statement.
            # NUNCA llames cur.execute("BEGIN") manualmente; eso rompe psycopg con "cannot start a
            # transaction within a transaction". El caller es responsable de llamar conn.commit()
            # o conn.rollback() para sus transacciones propias SERIALIZABLE / FOR UPDATE.
            #
            # Railway proxy requiere SSL; usamos cadena multi-attempt con fallback chain.
            conn = _pg_connect_ssl_fallback(DATABASE_URL)
        else:
            conn = sqlite3.connect(SQLITE_PATH, isolation_level=None, timeout=30)
            conn.row_factory = sqlite3.Row
        yield conn
        # === SALIDA CLEAN SIN EXCEPCIÓN ===
        # (Solo commit automático si el caller NO lo hizo explícitamente para SQLITE.
        #  Postgres NO requiere commit aquí si el caller ya hizo commit; pero lo hacemos idempotente en finally.)
        if DB_ENGINE != "POSTGRES" and not commited_or_rollbacked:
            try:
                conn.commit()
            except Exception:
                pass
    finally:
        if conn is not None:
            # PostgreSQL: si la conexión sigue con tx abierta (caller olvidó commit/rollback)
            # hacemos ROLLBACK para evitar idle in transaction en pg_stat_activity y leaks.
            if DB_ENGINE == "POSTGRES":
                try:
                    conn.rollback()
                except Exception:
                    pass
            else:
                # SQLite: rollback seguro (commit ya se hizo en yield exit path si no hubo error).
                try:
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
    version="2.2.0",
)

def _cors_allow_list_from_env():
    """Return a set[str] with ALL allowed origins normalized (scheme+netloc only)."""
    origins = set()
    # 1. FRONTEND_URL principal (si existe)
    fu = _clean_env_str(os.environ.get("FRONTEND_URL") or "", strip_slash_end=True)
    if fu:
        origins.add(fu)
    # 1-BIS: VITE_PUBLIC_URL (seteado automáticamente por Railway en servicio Frontend.
    # Si el user se confundió y lo copió/pegó también al servicio Backend, lo usamos.)
    vpu = _clean_env_str(os.environ.get("VITE_PUBLIC_URL") or "", strip_slash_end=True)
    if vpu:
        origins.add(vpu)
    # 1-TER: VITE_BACKEND_URL pegado en backend por error user (no usamos valor como
    # origin frontend PERO si contiene .railway.app lo agregamos igual fallback 0 errores).
    vbu = _clean_env_str(os.environ.get("VITE_BACKEND_URL") or "", strip_slash_end=True)
    if vbu and ("up.railway.app" in vbu.lower() or ".railway.app" in vbu.lower()):
        origins.add(vbu)
    # 2. Allowlist configurable por Railway Variables:
    al_env = _clean_env_str(
        os.environ.get("CORS_ALLOW_ORIGINS") or os.environ.get("VITE_ALLOW_ORIGINS") or ""
    )
    if al_env:
        for part in al_env.split(","):
            p = _clean_env_str(part, strip_slash_end=True)
            if p:
                origins.add(p)
    # 3. Known dev domains (localhost 5173/4173/3000 + mobile webviews):
    for dev in [
        "http://localhost:5173", "http://localhost:4173", "http://127.0.0.1:5173",
        "http://127.0.0.1:4173", "http://localhost:3000",
        "capacitor://localhost", "http://localhost", "ionic://localhost",
    ]:
        origins.add(dev)
    # 4. Backend mismo dominio (por si algún endpoint es llamado same-origin):
    be_own = _clean_env_str(
        os.environ.get("BACKEND_PUBLIC_URL") or os.environ.get("RAILWAY_PUBLIC_DOMAIN") or "",
        strip_slash_end=True,
    )
    if be_own:
        origins.add(be_own)
    # Normalizar todo a scheme://netloc minúsculas sin trailing slash
    normalized = set()
    for o in origins:
        o = o.strip()
        if not o:
            continue
        try:
            from urllib.parse import urlparse as _urlparse_norm
            _p = _urlparse_norm(o)
            if _p.scheme and _p.netloc:
                normalized.add(f"{_p.scheme.lower()}://{_p.netloc.lower()}")
                continue
        except Exception:
            pass
        normalized.add(o.rstrip("/").lower())
    return normalized

CORS_ALLOW_SET = _cors_allow_list_from_env()

def _cors_origin_allowed(request_origin):
    """MODO DEFENSA TOTAL: SIEMPRE permitimos cualquier origin válido (http/https/ionic/capacitor).
    Razonamiento seguridad: TODOS los endpoints privados usan JWT Bearer Token guardado en
    localStorage (NO cookies third-party), así que un atacante cross-origin NO puede robar/incluir
    el token sin credenciales. Permitir todos los origins elimina 100% los bugs CORS de Railway
    servicios separados y Chrome WebView TCL."""
    if not request_origin:
        return (True, None)
    raw = (request_origin or "").strip()
    # 1) Allowlist exacta (para logs consistentes con config Railway Variables):
    norm_in = None
    try:
        from urllib.parse import urlparse as _u
        _p = _u(raw)
        if _p.scheme and _p.netloc:
            norm_in = f"{_p.scheme.lower()}://{_p.netloc.lower()}"
    except Exception:
        norm_in = raw.rstrip("/").lower()
    if norm_in in CORS_ALLOW_SET:
        return (True, raw)
    # 2) Substrings conocidos (Railway, local, IPs LAN, hosting popular):
    haystack = (norm_in or raw).lower()
    for perm in (".up.railway.app", ".railway.app", "localhost", "127.0.0.1",
                 "web-dev-server", "192.168.", "10.0.2.2", "ngrok",
                 ".app", ".dev", ".site", ".page", ".netlify.app", ".vercel.app",
                 ".fly.dev", ".herokuapp.com", ".onrender.com"):
        if perm in haystack:
            return (True, raw)
    # 3) BRUTO TOTAL DEFENSA: Si origin es scheme valido http/https/capacitor/ionic → PERMITIDO.
    try:
        from urllib.parse import urlparse as _u2
        _p = _u2(raw)
        if _p.scheme in ("http", "https", "capacitor", "ionic") and _p.netloc:
            return (True, raw)
    except Exception:
        pass
    return (True, raw)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
    max_age=86400,
)

from fastapi.exceptions import RequestValidationError
from fastapi.encoders import jsonable_encoder


@app.exception_handler(RequestValidationError)
async def _handler_validation_error_legible(request: Request, exc: RequestValidationError):
    """Intercepta el HTTP 422 nativo de Pydantic/FastAPI.
    Pydantic envía por defecto {"detail": [ {loc,msg,type}, ... ]} — array de objetos.
    El front a veces hace `${data.detail}` directamente → "[object Object],[object Object]" ilegible.

    Solución: convertimos detail a UNA SOLA LÍNEA DE TEXTO concatenada (máx 800 chars)
    + guardamos los errores completos en key `validation_errors` (array original) para
    debug avanzado si el front lo necesita."""
    errs = list(exc.errors() or [])
    # Construir detalle legible:
    lineas = []
    for i, er in enumerate(errs[:8]):
        try:
            loc = er.get("loc")
            if isinstance(loc, (list, tuple)):
                loc_str = ".".join(str(x) for x in loc if str(x) != "body")
            else:
                loc_str = str(loc or "")
            msg = str(er.get("msg") or er or "error")
            ty = str(er.get("type") or "")
            lineas.append(f"[{i+1}] {loc_str or ty}: {msg}")
        except Exception:
            lineas.append(str(er))
    detalle_corto = " · ".join(lineas)
    if len(detalle_corto) > 900:
        detalle_corto = detalle_corto[:896] + " ..."
    try:
        path = request.url.path
        origin = request.headers.get("origin") or ""
        print(f"[REQ-422] POST {path} | origin={origin!r} | n_errors={len(errs)} | detalle={detalle_corto[:160]!r}")
    except Exception:
        pass
    content = jsonable_encoder({
        "detail": detalle_corto or "Validación fallida (revisa los campos)",
        "validation_errors": errs,
        "campo_primer_error": (
            ".".join(str(x) for x in (errs[0].get("loc") or []) if str(x) != "body")
            if errs else None
        ),
    })
    return JSONResponse(status_code=422, content=content)


@app.exception_handler(Exception)
async def _handler_exception_global_traceback(request: Request, exc: Exception):
    """Captura TODAS las exceptions no manejadas y escribe traceback COMPLETO a
    stderr Railway logs. Sin esto FastAPI solo dice 'HTTP 500' sin causa visible.
    Devuelve JSON con detalle y primeras 20 líneas del traceback para el front."""
    import traceback as _tb
    import sys as _sys
    import io as _io
    try:
        _path = request.url.path
        _method = request.method
        _origin = request.headers.get("origin", "") or ""
        print(f"[REQ-500] {_method} {_path} | origin={_origin!r} | exc_type={type(exc).__name__} | exc_msg={str(exc)[:200]!r}",
              file=_sys.stderr)
        _buf = _io.StringIO()
        _tb.print_exc(file=_buf)
        _tb_str = _buf.getvalue()
        _sys.stderr.write(_tb_str)
        _sys.stderr.flush()
        _tb_lines = [ln.rstrip() for ln in _tb_str.splitlines() if ln.strip()]
        _tb_preview = _tb_lines[-20:] if len(_tb_lines) > 20 else _tb_lines
    except Exception as _inner:
        _tb_lines = []
        _tb_preview = [f"[traceback-capture-failed: {_inner}]"]
    content = jsonable_encoder({
        "detail": (f"Error interno del servidor: {type(exc).__name__} — " + (str(exc)[:300] if str(exc) else "(sin mensaje)")),
        "error_type": type(exc).__name__,
        "traceback_lines": _tb_preview,
        "httpStatus": 500,
    })
    return JSONResponse(status_code=500, content=content)


@app.middleware("http")
async def _promo_override_cors_headers_dynamic(request: Request, call_next):
    origin = request.headers.get("origin") or None
    response = await call_next(request)
    allow_ok, echo = _cors_origin_allowed(origin)
    if allow_ok and echo:
        response.headers["access-control-allow-origin"] = echo
        response.headers["access-control-allow-credentials"] = "false"
        response.headers["access-control-expose-headers"] = "*"
        response.headers["access-control-max-age"] = "86400"
        vary = response.headers.get("vary", "")
        varies = [v.strip() for v in vary.split(",") if v.strip()]
        if "Origin" not in varies:
            varies.append("Origin")
        response.headers["vary"] = ", ".join(varies)
    elif not allow_ok and origin:
        for hdr in ("access-control-allow-origin", "access-control-expose-headers",
                    "access-control-allow-credentials", "access-control-max-age"):
            if hdr in response.headers:
                del response.headers[hdr]
    if (not origin) and ("access-control-allow-origin" not in response.headers):
        response.headers["access-control-allow-origin"] = "*"
        response.headers["access-control-expose-headers"] = "*"
        response.headers["access-control-max-age"] = "86400"
    return response


@app.middleware("http")
async def _promo_log_cors_and_trace_headers(request: Request, call_next):
    method = request.method
    path = request.url.path
    origin = request.headers.get("origin") or request.headers.get("Origin") or ""
    referer = request.headers.get("referer") or request.headers.get("Referer") or ""
    host = request.headers.get("host") or request.headers.get("Host") or ""
    try:
        response = await call_next(request)
    except Exception as e:
        print(f"[REQ-500] {method} {path} | origin={origin!r} host={host!r} ref={referer!r} | EXC={type(e).__name__}: {e}")
        raise
    if (method == "POST" and ("/api/admin" in path or "/api/promo" in path)) or "/debug/" in path or path == "/health" or path == "/cors-test":
        print(
            f"[REQ] {method} {path} HTTP {response.status_code} | "
            f"origin={origin!r} host={host!r} ref={referer!r} | "
            f"cors_allow={_cors_origin_allowed(origin or '')[0]}"
        )
    return response


@app.middleware("http")
async def _cors_intercept_preflight_options_NUCLEAR(request: Request, call_next):
    """MIDDLEWARE MÁS SEGURO PARA CORS EN 2 SERVICIOS RAILWAY SEPARADOS.
    ======= NIVEL: NUCLEAR (ÚLTIMA DEFENSA ANTES DE HTTP 500) =======
    Starlette CORSMiddleware base a veces responde al preflight OPTIONS con wildcard
    y luego Chrome Android/WebView TCL bloquea fetch con TypeError Failed to fetch.

    SOLUCIÓN: si method == 'OPTIONS' y existe header Origin:
      - INTERCEPTO DIRECTAMENTE, NUNCA llamo call_next() = el CORSMiddleware base
        y otros middlewares NO pueden modificar headers CORS de respuesta.
      - Contesto Response(status_code=204, content=b'') con headers de MI helper
        _cors_origin_allowed():
            access-control-allow-origin: <ORIGIN EXACTO si permitido>
            access-control-allow-methods: GET,HEAD,POST,PUT,PATCH,DELETE,OPTIONS
            access-control-allow-headers: *
            access-control-expose-headers: *
            access-control-max-age: 86400
            access-control-allow-credentials: false
            vary: Origin
    Así el navegador SIEMPRE recibe 204 + origin exacto y NO bloquea nada.

    (El resto de middlewares siguen intactos por redundancia: si un cliente no envía
     preflight OPTIONS por ser simple request, los otros middlewares igual agregan
     los headers CORS correctos en la response.)
    """
    method = request.method
    origin = request.headers.get("origin") or None
    path = request.url.path
    if method == "OPTIONS" and origin:
        allow_ok, echo = _cors_origin_allowed(origin)
        print(f"[CORS-PREFLIGHT] OPTIONS {path} | origin={origin!r} allow={allow_ok} echo={echo!r}")
        if allow_ok and echo:
            headers = {
                "access-control-allow-origin": echo,
                "access-control-allow-methods": "GET,HEAD,POST,PUT,PATCH,DELETE,OPTIONS",
                "access-control-allow-headers": request.headers.get("access-control-request-headers") or "*",
                "access-control-expose-headers": "*",
                "access-control-max-age": "86400",
                "access-control-allow-credentials": "false",
                "vary": "Origin",
                "content-length": "0",
            }
            return Response(status_code=204, content=b"", headers=headers)
        else:
            headers = {"vary": "Origin", "content-length": "0"}
            return Response(status_code=403, content=b"cors blocked origin", headers=headers)
    # Caso normal: GET / POST / etc — pasa al siguiente middleware en la cadena
    return await call_next(request)


@app.get("/cors-test")
def cors_test_simple(request: Request):
    origin = request.headers.get("origin") or ""
    allow_ok, echo = _cors_origin_allowed(origin or None)
    return {
        "ok": True,
        "cors": "OK (si puedes ver este JSON, backend Python Railway está UP)",
        "method": "GET",
        "request_host": request.headers.get("host"),
        "request_origin": origin,
        "request_origin_permitido": bool(allow_ok),
        "request_origin_echo": echo,
        "cors_allow_list": sorted(list(CORS_ALLOW_SET))[:50],
        "FRONTEND_URL_config_raw": os.environ.get("FRONTEND_URL") or "",
        "FRONTEND_URL_config_USADO_EFECTIVAMENTE": _clean_env_str(
            os.environ.get("FRONTEND_URL") or "", strip_slash_end=True
        ),
        "backticks_limpiados_automaticamente": (
            (os.environ.get("FRONTEND_URL") or "")
            !=
            _clean_env_str(os.environ.get("FRONTEND_URL") or "", strip_slash_end=True)
        ),
        "CORS_ALLOW_ORIGINS_env": os.environ.get("CORS_ALLOW_ORIGINS") or "",
        "request_user_agent": (request.headers.get("user-agent") or "")[:120],
        "server_time_utc": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/api/promo/debug/cors-check-detallado")
def cors_debug_detallado(request: Request):
    origin = request.headers.get("origin") or request.headers.get("Origin") or ""
    referer = request.headers.get("referer") or ""
    allow_ok, echo = _cors_origin_allowed(origin or None)
    probable_front = ""
    try:
        if referer:
            from urllib.parse import urlparse as _upp
            _pr = _upp(referer)
            if _pr.scheme and _pr.netloc:
                probable_front = f"{_pr.scheme.lower()}://{_pr.netloc.lower()}"
    except Exception:
        probable_front = ""
    recomendaciones = [
        "SERVICIO 1 (Backend Python) → Variables → Add: FRONTEND_URL = https://front-production-3d2a.up.railway.app SIN / al final",
        "SERVICIO 2 (Frontend Vite Static) → Variables → Add: VITE_BACKEND_URL = https://fiesta-abv-valle-production.up.railway.app SIN / al final!",
        "Redeploy AMBOS servicios triangular ⏯ Latest Commit en Railway.",
        "TCL Chrome: Ritual Nuclear: Ajustes → Apps → Chrome → Almacenamiento → BORRAR ALMACENAMIENTO. Cerrar Chrome, reabrir PWA.",
    ]
    return {
        "ok": True,
        "resumen": ("OK CORS ✅" if allow_ok else "🛑 CORS BLOQUEADO"),
        "origin_entrante": origin,
        "origin_permitido": echo,
        "referer": referer,
        "probable_frontend_desde_referer": probable_front,
        "allowlist_actual": sorted(list(CORS_ALLOW_SET)),
        "FRONTEND_URL_env": os.environ.get("FRONTEND_URL") or "",
        "CORS_ALLOW_ORIGINS_env": os.environ.get("CORS_ALLOW_ORIGINS") or "",
        "recomendaciones_railway": recomendaciones,
        "server_time_utc": datetime.now(timezone.utc).isoformat(),
    }


@app.on_event("startup")
def startup_init_db_and_model():
    _pg_note = ""
    if DB_ENGINE == "POSTGRES":
        _pg_note = f" | PublicProxy={_pg_is_public_proxy} (egress billable · recomendado .railway.internal si UI Attach DB disponible)"
    print(f"[startup] engine={DB_ENGINE} (DATABASE_URL_set={bool(DATABASE_URL)}){_pg_note} | IA model={MODEL_NAME} | CPU only")
    _fu_raw = os.environ.get("FRONTEND_URL") or ""
    _fu_clean = _clean_env_str(_fu_raw, strip_slash_end=True)
    _fu_limpio = bool(_fu_raw != _fu_clean)
    print(
        f"[startup-CONFIG-VARS] "
        f"FRONTEND_URL_env_raw={_fu_raw[:90]!r} | "
        f"FRONTEND_URL_USADO={_fu_clean[:90]!r} | "
        f"backticks_limpiados_auto={_fu_limpio} | "
        f"CORS_ALLOW_ORIGINS_env={ (os.environ.get('CORS_ALLOW_ORIGINS') or '')[:120]!r} | "
        f"JWT_SECRET_set={bool(os.environ.get('JWT_SECRET'))} | "
        f"BACKEND_PUBLIC_URL_env={ (os.environ.get('BACKEND_PUBLIC_URL') or '')[:80]!r} | "
        f"STORAGE_DIR={STORAGE_DIR}"
    )
    if _fu_limpio:
        print("[startup-ADVERTENCIA ⚠️] 🚨 FRONTEND_URL contenía backticks/comillas al pegar desde Markdown. "
              "El CÓDIGO lo limpió AUTOMÁTICAMENTE, pero ARRÉGLALO en Railway Variables para evitar futuros problemas: "
              "edita la variable FRONTEND_URL y borra los backticks ` y comillas que la envuelven.")
    # ====== ADVERTENCIA CRÍTICA SI ESTAMOS EN SQLITE SIN VOLUMEN PERSISTENTE EN RAILWAY ======
    if DB_ENGINE == "SQLITE":
        print("=" * 78)
        print("[startup-WARNING ⚠️⚠️⚠️ ] DB_SQLITE_LOCAL = LOS DATOS SE BORRAN CADA REDEPLOY RAILWAY!")
        print(
            "[startup-WARNING] No tienes PostgreSQL attachado al servicio ni VOLUMEN PERSISTENTE.\n"
            "[startup-WARNING] Solucion recomendada 1 (99% fiabilidad GRATIS sin volumen):\n"
            "   Railway Dashboard → Proyecto Fiesta → NEW → Database → PostgreSQL → Create.\n"
            "   Luego entra a la Database → Settings → Connect → Private Networking → Copy link postgres://...\n"
            "   → NO LO PEGUES MANUALMENTE: entra a Servicio1 (backend) → Settings → Attach Database\n"
            "   → Selecciona la PostgreSQL que acabas de crear. Railway setea DATABASE_URL automáticamente\n"
            "   y todos los redeploys MANTIENEN LOS DATOS (QRs, registros, admin). 0 costo, 0 egress.\n"
            "[startup-WARNING] Solucion alternativa 2 (SQLite + VOLUMEN Railway pago bajo):\n"
            "   Servicio1 → Settings → Volumes → Add Volume, Mount Path = /app/backend-python\n"
            "   → guarda el archivo fotos-local.sqlite3 en disco persistente. Costo ~$0.25/mes 1GB.\n"
            "[startup-WARNING] Sin estas 2 soluciones → cada Redeploy / restart proceso BORRA los QRs y registros."
        )
        print("=" * 78)
    if not (os.environ.get("FRONTEND_URL") or "").strip():
        print(
            "[startup-WARNING] Falta Railway var FRONTEND_URL en Servicio1 Backend.\n"
            "   Valor esperado: https://front-production-3d2a.up.railway.app  (TU dominio frontend SIN / final)."
        )
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
    # ====== IMPRIMIR CONTEOS TABLAS AL INICIAR (diagnóstico QRs perdidos) ======
    try:
        tablas_count = {}
        with get_db_conn() as conn:
            cur = conn.cursor()
            for t in [
                "promo_qr_codes", "promo_registros", "promo_config",
                "promo_admin_users", "promo_sorteo_lock", "promo_auditoria",
            ]:
                try:
                    if DB_ENGINE == "POSTGRES":
                        cur.execute(f"SELECT COUNT(*) FROM {t}")
                    else:
                        cur.execute(f"SELECT COUNT(*) FROM {t}")
                    row = cur.fetchone()
                    tablas_count[t] = int(row[0]) if row else 0
                except Exception as e_tab:
                    tablas_count[t] = f"ERR: {type(e_tab).__name__}"
        print(f"[startup-COUNTS-DB] Conteos tablas promo: {json.dumps(tablas_count, ensure_ascii=False, default=str)}")
        if tablas_count.get("promo_qr_codes", 0) == 0:
            print(
                "[startup-COUNTS-DB-WARNING] promo_qr_codes = 0 filas. Si esperabas QRs generados:\n"
                "   → (a) Es SQLite sin persistencia + redeploy reciente (se borraron).\n"
                "   → (b) Es PostgreSQL nuevo attachado sin migrar datos del SQLite viejo."
            )
    except Exception as e:
        print(f"[startup-COUNTS-DB] No pudo leer conteos: {type(e).__name__}: {e}")

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
    tamano_cm REAL,
    dpi INTEGER DEFAULT 300,
    unidad VARCHAR(16) DEFAULT 'pixeles',
    formato TEXT NOT NULL DEFAULT 'png',
    habilitado BOOLEAN NOT NULL DEFAULT TRUE,
    inhabilitado_por_id INTEGER,
    inhabilitado_at TIMESTAMPTZ,
    usado_registro_id BIGINT,
    usado_at TIMESTAMPTZ,
    creado_admin_id INTEGER,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_promo_qr_uuid ON promo_qr_codes (uuid_qr);
CREATE INDEX IF NOT EXISTS idx_promo_qr_usado ON promo_qr_codes (usado_registro_id);
CREATE INDEX IF NOT EXISTS idx_promo_qr_habilitado ON promo_qr_codes (habilitado);

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

-- ================= NUEVA TABLA BLOQUEO NUCLEAR ANTI-BORRADO (PostgreSQL) =================
-- 1 fila (id=1) con UUID única del deploy inicial + MÁXIMO HISTÓRICO QRs/registros
-- para detectar inmediatamente si hubo una pérdida de datos accidental.
-- NUNCA se modifica el UUID después de creado. Los counts MAX solo CRECEN.
CREATE TABLE IF NOT EXISTS promo_permanent_data_guard (
    id INTEGER PRIMARY KEY,
    db_uuid TEXT NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    max_qr_codes_ever BIGINT NOT NULL DEFAULT 0,
    max_registros_ever BIGINT NOT NULL DEFAULT 0,
    max_auditoria_ever BIGINT NOT NULL DEFAULT 0,
    last_check_at TIMESTAMPTZ,
    last_check_status TEXT,
    last_note TEXT
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
    tamano_cm REAL,
    dpi INTEGER DEFAULT 300,
    unidad TEXT DEFAULT 'pixeles',
    formato TEXT NOT NULL DEFAULT 'png',
    habilitado INTEGER NOT NULL DEFAULT 1,
    inhabilitado_por_id INTEGER,
    inhabilitado_at TEXT,
    usado_registro_id INTEGER,
    usado_at TEXT,
    creado_admin_id INTEGER,
    created_at TEXT NOT NULL DEFAULT (STRFTIME('%Y-%m-%dT%H:%M:%SZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_promo_qr_uuid ON promo_qr_codes (uuid_qr);
CREATE INDEX IF NOT EXISTS idx_promo_qr_usado ON promo_qr_codes (usado_registro_id);
CREATE INDEX IF NOT EXISTS idx_promo_qr_habilitado ON promo_qr_codes (habilitado);

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

-- ================= NUEVA TABLA BLOQUEO NUCLEAR ANTI-BORRADO (SQLite) =================
-- 1 fila (id=1) con UUID única del deploy inicial + MÁXIMO HISTÓRICO QRs/registros
CREATE TABLE IF NOT EXISTS promo_permanent_data_guard (
    id INTEGER PRIMARY KEY,
    db_uuid TEXT UNIQUE NOT NULL,
    created_at TEXT NOT NULL DEFAULT (STRFTIME('%Y-%m-%dT%H:%M:%SZ','now')),
    max_qr_codes_ever INTEGER NOT NULL DEFAULT 0,
    max_registros_ever INTEGER NOT NULL DEFAULT 0,
    max_auditoria_ever INTEGER NOT NULL DEFAULT 0,
    last_check_at TEXT,
    last_check_status TEXT,
    last_note TEXT
);
"""


def init_promo_db_tables_and_seeds():
    with get_db_conn() as conn:
        cur = conn.cursor()
        if DB_ENGINE == "POSTGRES":
            cur.execute(_PROMO_SQL_CREATE_POSTGRES)
            conn.commit()
            # ALTER TABLE idempotentes para deploys EXISTENTES (antes no estaban estas cols)
            # En Postgres IF NOT EXISTS ADD COLUMN existe desde PG 9.6+, Railway 14/15/16 OK.
            _alter_cols_pg = [
                "ALTER TABLE promo_qr_codes ADD COLUMN IF NOT EXISTS tamano_cm REAL",
                "ALTER TABLE promo_qr_codes ADD COLUMN IF NOT EXISTS dpi INTEGER DEFAULT 300",
                "ALTER TABLE promo_qr_codes ADD COLUMN IF NOT EXISTS unidad VARCHAR(16) DEFAULT 'pixeles'",
                "ALTER TABLE promo_qr_codes ADD COLUMN IF NOT EXISTS habilitado BOOLEAN NOT NULL DEFAULT TRUE",
                "ALTER TABLE promo_qr_codes ADD COLUMN IF NOT EXISTS inhabilitado_por_id INTEGER",
                "ALTER TABLE promo_qr_codes ADD COLUMN IF NOT EXISTS inhabilitado_at TIMESTAMPTZ",
            ]
            for alter in _alter_cols_pg:
                try:
                    cur = conn.cursor(); cur.execute(alter); conn.commit()
                except Exception:
                    pass
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
            # SQLite ALTER TABLE ADD COLUMN (no hay IF NOT EXISTS pre-3.35; así que try/except por columna)
            _alter_cols_sqlite = [
                ("tamano_cm", "REAL"),
                ("dpi", "INTEGER DEFAULT 300"),
                ("unidad", "TEXT DEFAULT 'pixeles'"),
                ("habilitado", "INTEGER NOT NULL DEFAULT 1"),
                ("inhabilitado_por_id", "INTEGER"),
                ("inhabilitado_at", "TEXT"),
            ]
            for col, defn in _alter_cols_sqlite:
                try:
                    cur = conn.cursor(); cur.execute(f"ALTER TABLE promo_qr_codes ADD COLUMN {col} {defn}"); conn.commit()
                except Exception:
                    # columna ya existia, ignorar
                    pass
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
        # ========== BLOQUEO NUCLEAR ANTI-BORRADO (al final de los seeds) ==========
        # 1. Contar QRs / registros / auditoría ACTUALES
        cur = conn.cursor()
        try:
            if DB_ENGINE == "POSTGRES":
                cur.execute("SELECT COUNT(*) FROM promo_qr_codes")
            else:
                cur.execute("SELECT COUNT(*) FROM promo_qr_codes")
            _count_qr_now = int(cur.fetchone()[0] or 0)
            cur.execute(
                "SELECT COUNT(*) FROM promo_registros" if DB_ENGINE == "POSTGRES" else
                "SELECT COUNT(*) FROM promo_registros"
            )
            _count_reg_now = int(cur.fetchone()[0] or 0)
            cur.execute(
                "SELECT COUNT(*) FROM promo_auditoria_admin" if DB_ENGINE == "POSTGRES" else
                "SELECT COUNT(*) FROM promo_auditoria_admin"
            )
            _count_aud_now = int(cur.fetchone()[0] or 0)
        except Exception as e_count:
            print(f"[PERMANENCIA] ⚠️ No se pudo conteo inicial: {e_count}")
            _count_qr_now = _count_reg_now = _count_aud_now = 0
        # 2. Leer fila guard id=1 si existe
        try:
            if DB_ENGINE == "POSTGRES":
                cur.execute(
                    "SELECT id, db_uuid, max_qr_codes_ever, max_registros_ever, max_auditoria_ever "
                    "FROM promo_permanent_data_guard WHERE id = %s", (1,)
                )
            else:
                cur.execute(
                    "SELECT id, db_uuid, max_qr_codes_ever, max_registros_ever, max_auditoria_ever "
                    "FROM promo_permanent_data_guard WHERE id = ?", (1,)
                )
            _guard_row = cur.fetchone()
        except Exception as e_g:
            print(f"[PERMANENCIA] ⚠️ Tabla guard no se leyó: {e_g}")
            _guard_row = None
        now_ts_iso = datetime.now(timezone.utc).isoformat()
        if _guard_row is None:
            # 3a. PRIMERA VEZ: Crear UUID e inicializar max counts
            import uuid as _uuid_mod
            _new_uuid = str(_uuid_mod.uuid4())
            _new_max_qr = _count_qr_now
            _new_max_reg = _count_reg_now
            _new_max_aud = _count_aud_now
            status_init = f"PRIMER-SEED qrs={_new_max_qr} regs={_new_max_reg}"
            _bind_init = (
                1, _new_uuid, _new_max_qr, _new_max_reg, _new_max_aud,
                now_ts_iso, "OK_INIT", status_init,
            )
            try:
                if DB_ENGINE == "POSTGRES":
                    cur.execute(
                        "INSERT INTO promo_permanent_data_guard "
                        "(id, db_uuid, max_qr_codes_ever, max_registros_ever, max_auditoria_ever, "
                        " last_check_at, last_check_status, last_note) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s) "
                        "ON CONFLICT (id) DO NOTHING",
                        _bind_init,
                    )
                else:
                    cur.execute(
                        "INSERT OR IGNORE INTO promo_permanent_data_guard "
                        "(id, db_uuid, max_qr_codes_ever, max_registros_ever, max_auditoria_ever, "
                        " last_check_at, last_check_status, last_note) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        _bind_init,
                    )
                conn.commit()
                print(f"[PERMANENCIA] ✅ Bloqueo Nuclear inicializado NUEVO: db_uuid={_new_uuid[:12]}… max_qr_ever={_new_max_qr} max_reg_ever={_new_max_reg}.")
            except Exception as e_ins:
                print(f"[PERMANENCIA] ⚠️ No se pudo crear guard init: {e_ins}")
        else:
            # 3b. YA EXISTE EL GUARD: Comparar counts y detectar PÉRDIDA DE DATOS
            _guard_id = int(_guard_row[0] or 0)
            _guard_uuid = str(_guard_row[1] or "")
            _max_qr_ever = int(_guard_row[2] or 0)
            _max_reg_ever = int(_guard_row[3] or 0)
            _max_aud_ever = int(_guard_row[4] or 0)
            _perdida_qr = (_count_qr_now < _max_qr_ever)
            _perdida_reg = (_count_reg_now < _max_reg_ever)
            _perdida = _perdida_qr or _perdida_reg
            if _perdida:
                # LÍNEA ROJA: PÉRDIDA DETECTADA
                _detail_parts = []
                if _perdida_qr:
                    _detail_parts.append(f"QRs: {_count_qr_now} < {_max_qr_ever} (PERDIDOS {_max_qr_ever-_count_qr_now})")
                if _perdida_reg:
                    _detail_parts.append(f"REGS: {_count_reg_now} < {_max_reg_ever} (PERDIDOS {_max_reg_ever-_count_reg_now})")
                _detalle = " · ".join(_detail_parts)
                print("=" * 80)
                print(f"[PERMANENCIA] 🔴🚨🚨 PÉRDIDA DE DATOS DETECTADA ANTES DE SEEDS: {_detalle}")
                print(f"[PERMANENCIA] 🔴 Guard db_uuid={_guard_uuid[:16]}…")
                print(f"[PERMANENCIA] 🔴 DB Engine: {DB_ENGINE}. DATABASE_URL_set={bool(DATABASE_URL)}.")
                if DB_ENGINE == "SQLITE":
                    print(f"[PERMANENCIA] 🔴 ESTAS EN SQLITE SIN VOLUMEN: Cada redeploy BORRA TODO. "
                          f"Hay que crear PostgreSQL + Attach Database / volumen Railway (instrucciones).")
                else:
                    print(f"[PERMANENCIA] 🔴 ESTAS EN PostgreSQL: Seguramente cambiaste de DATABASE_URL y "
                          f"perdiste la BD anterior. Revisa Railway Servicio1 → Variables → DATABASE_URL.")
                print("=" * 80)
                status_final = "PerdidaDatosDetectada"
                note_final = (f"WARN {_detalle}")[:250]
            else:
                status_final = "OK_Persiste"
                note_final = f"SIN_PERDIDA qr_now={_count_qr_now}/≥{_max_qr_ever} reg={_count_reg_now}/≥{_max_reg_ever}"
                print(f"[PERMANENCIA] ✅ NO_HUBO_PÉRDIDA: db_uuid={_guard_uuid[:12]}… | "
                      f"QRs: {_count_qr_now} (≥max_ever={_max_qr_ever}) | "
                      f"REGS: {_count_reg_now} (≥max_ever={_max_reg_ever}).")
            # 4. Actualizar los MAX para que SOLO CREZCAN (nunca decrezcan)
            new_max_qr = max(_max_qr_ever, _count_qr_now)
            new_max_reg = max(_max_reg_ever, _count_reg_now)
            new_max_aud = max(_max_aud_ever, _count_aud_now)
            try:
                if DB_ENGINE == "POSTGRES":
                    cur.execute(
                        "UPDATE promo_permanent_data_guard SET "
                        "max_qr_codes_ever = %s, "
                        "max_registros_ever = %s, "
                        "max_auditoria_ever = %s, "
                        "last_check_at = %s, "
                        "last_check_status = %s, "
                        "last_note = %s "
                        "WHERE id = %s",
                        (new_max_qr, new_max_reg, new_max_aud, now_ts_iso, status_final, note_final, 1),
                    )
                else:
                    cur.execute(
                        "UPDATE promo_permanent_data_guard SET "
                        "max_qr_codes_ever = ?, "
                        "max_registros_ever = ?, "
                        "max_auditoria_ever = ?, "
                        "last_check_at = ?, "
                        "last_check_status = ?, "
                        "last_note = ? "
                        "WHERE id = ?",
                        (new_max_qr, new_max_reg, new_max_aud, now_ts_iso, status_final, note_final, 1),
                    )
                conn.commit()
            except Exception as e_up:
                print(f"[PERMANENCIA] ⚠️ No se actualizó guard: {e_up}")


def _promo_get_permanent_data_guard():
    """Devuelve dict con estado del bloqueo nuclear anti-borrado (o None si no existe)."""
    try:
        with get_db_conn() as conn:
            cur = conn.cursor()
            if DB_ENGINE == "POSTGRES":
                cur.execute(
                    "SELECT id, db_uuid, created_at, max_qr_codes_ever, max_registros_ever, "
                    "max_auditoria_ever, last_check_at, last_check_status, last_note "
                    "FROM promo_permanent_data_guard WHERE id = %s", (1,)
                )
            else:
                cur.execute(
                    "SELECT id, db_uuid, created_at, max_qr_codes_ever, max_registros_ever, "
                    "max_auditoria_ever, last_check_at, last_check_status, last_note "
                    "FROM promo_permanent_data_guard WHERE id = ?", (1,)
                )
            row = cur.fetchone()
            if row is None:
                return None
            # Conteos NOW para comparar vs max_ever
            cur.execute("SELECT COUNT(*) FROM promo_qr_codes")
            c_qr = int(cur.fetchone()[0] or 0)
            cur.execute("SELECT COUNT(*) FROM promo_registros")
            c_reg = int(cur.fetchone()[0] or 0)
            cur.execute("SELECT COUNT(*) FROM promo_auditoria_admin")
            c_aud = int(cur.fetchone()[0] or 0)
            max_qr = int(row[3] or 0)
            max_reg = int(row[4] or 0)
            max_aud = int(row[5] or 0)
            return {
                "db_uuid": str(row[1] or ""),
                "created_at": str(row[2] or ""),
                "max_qr_codes_ever": max_qr,
                "max_registros_ever": max_reg,
                "max_auditoria_ever": max_aud,
                "last_check_at": str(row[6] or ""),
                "last_check_status": str(row[7] or ""),
                "last_note": str(row[8] or ""),
                "counts_now": {
                    "promo_qr_codes": c_qr,
                    "promo_registros": c_reg,
                    "promo_auditoria_admin": c_aud,
                },
                "permanencia_ok_qr": c_qr >= max_qr,
                "permanencia_ok_registros": c_reg >= max_reg,
                "perdida_detectada": (c_qr < max_qr) or (c_reg < max_reg),
                "diferencia_qr": (max_qr - c_qr) if (c_qr < max_qr) else 0,
                "diferencia_registros": (max_reg - c_reg) if (c_reg < max_reg) else 0,
            }
    except Exception:
        return None


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
    model_config = {"extra": "allow"}
    qr_uuid: str
    acepta_terminos: bool = False
    acepta_habeas: bool = False

    @model_validator(mode="before")
    @classmethod
    def _normalizar_booleans_aceptacion(cls, data: Any) -> Any:
        """El front a veces no envía los checkboxes o envía strings 'on'/'1'/'true'.
        Normalizamos todo a bool y defaults False si faltan."""
        if not isinstance(data, dict):
            return data
        d = dict(data)
        for campo in ("acepta_terminos", "acepta_habeas"):
            v = d.get(campo, None)
            if v is None or v == "" or (isinstance(v, float) and v != v):
                d[campo] = False
            elif isinstance(v, bool):
                pass
            elif isinstance(v, (int, float)):
                d[campo] = bool(v)
            elif isinstance(v, str):
                s = v.strip().lower()
                d[campo] = s in ("1", "true", "t", "yes", "y", "si", "s", "on", "acepto", "aceptar")
            else:
                try:
                    d[campo] = bool(v)
                except Exception:
                    d[campo] = False
        return d


class PromoRegistroReq(BaseModel):
    model_config = {"extra": "allow"}  # permitir campos extra por si el front manda nombres legacy

    qr_uuid: str
    nombres_apellidos: str
    celular: str | None = None
    telefono_fijo: str | None = None
    celular_confirmacion: str | None = None
    correo_electronico: str
    direccion: str
    barrio: str | None = None
    municipio: str | None = None
    # ========== CAMBIOS USER 03/10/2026 ==========
    # Ciudad: OPCIONAL en el schema; DEFAULT = "Bogotá D.C." si no llega nada
    # (ya no la ingresa el usuario en formulario; la envía el front hardcodeado).
    ciudad: str = "Bogotá D.C."
    # vive_bogota: SI/NO que envía el formulario registro (radiobuttons).
    # Si llega => PREVALECE sobre el auto-detect de _promo_es_bogota (determina entrega domicilio o recoger Cra74a).
    # Si NO llega (registro admin manual), fallback a la detección automática de siempre (no rompemos nada).
    vive_bogota: bool | None = None
    # ========= END CAMBIOS 03/10/2026 =========
    # ========= NUEVOS campos booleans de aceptación (EL FALLO era que NO existían, se usaban en INSERT) =========
    acepta_terminos: bool = False
    acepta_habeas: bool = False
    acepta_terminos_at_iso: str = ""
    acepta_habeas_at_iso: str = ""

    @model_validator(mode="before")
    @classmethod
    def _compatibilizar_nombres_campos_front_legacy(cls, data: Any) -> Any:
        """El front a veces envía nombres antiguos (sin _iso final o confirmar_celular),
        ni envía los booleans acepta_* (solo los timestamps).
        Renombramos aquí ANTES de que Pydantic valide campos obligatorios, para
        evitar el HTTP 422 por diferencias de nombres entre versiones y el 500 AttributeError por field missing."""
        if not isinstance(data, dict):
            return data
        # Clonamos para no mutar el input original
        d = dict(data)

        # ===== 0) PRIMERO: Normalizar los BOOLEANS acepta_terminos/acepta_habeas (igual que PromoAceptacionReq)
        #     El front a veces manda string 'on'/'1'/'' o no lo manda en absoluto.
        for campo in ("acepta_terminos", "acepta_habeas", "vive_bogota"):
            v = d.get(campo, None)
            if v is None or v == "" or (isinstance(v, float) and v != v):
                d[campo] = False if campo != "vive_bogota" else None
            elif isinstance(v, bool):
                pass
            elif isinstance(v, (int, float)):
                d[campo] = bool(v)
            elif isinstance(v, str):
                s = v.strip().lower()
                if campo == "vive_bogota":
                    # Radiobuttons front: "si"/"no" (string). Convertir a bool explícito.
                    if s in ("1", "true", "t", "yes", "y", "si", "s", "on", "acepto", "aceptar", "ok", "verdadero", "bogota", "bogotá", "esta en bogota"):
                        d[campo] = True
                    elif s in ("0", "false", "f", "no", "n", "off", "falso", "fuera", "fuera de bogota", "fuera de bogotá"):
                        d[campo] = False
                    else:
                        d[campo] = None  # desconocido => fallback auto
                else:
                    d[campo] = s in ("1", "true", "t", "yes", "y", "si", "s", "on", "acepto", "aceptar", "ok", "verdadero")
            else:
                try:
                    d[campo] = bool(v)
                except Exception:
                    d[campo] = False if campo != "vive_bogota" else None

        # 1) Timestamp términos y condiciones: acepta_terminos_at (legacy) → acepta_terminos_at_iso
        if not d.get("acepta_terminos_at_iso") and d.get("acepta_terminos_at"):
            d["acepta_terminos_at_iso"] = str(d["acepta_terminos_at"])
        # 2) Timestamp habeas data: acepta_habeas_at (legacy) → acepta_habeas_at_iso
        if not d.get("acepta_habeas_at_iso") and d.get("acepta_habeas_at"):
            d["acepta_habeas_at_iso"] = str(d["acepta_habeas_at"])

        # 2b) INFERENCIA SMART: Si no mandó boolean acepta_terminos PERO SÍ HAY TIMESTAMP (acepta_*_at_iso no vacío),
        #     asumir que el usuario SÍ aceptó (porque timestamp generado en front cuando hace clic checkbox).
        _t_at = (d.get("acepta_terminos_at_iso") or "").strip()
        _h_at = (d.get("acepta_habeas_at_iso") or "").strip()
        if _t_at and not d.get("acepta_terminos"):
            d["acepta_terminos"] = True
        if _h_at and not d.get("acepta_habeas"):
            d["acepta_habeas"] = True

        # 3) Confirmación celular: confirmar_celular (front form name) → celular_confirmacion (pydantic)
        if (not d.get("celular_confirmacion")) and d.get("confirmar_celular"):
            d["celular_confirmacion"] = str(d["confirmar_celular"])
        # 4) Si celular_confirmacion sigue None y confirmar_celular tampoco,
        # pero hay celular, lo duplicamos para evitar errores triviales en usuarios
        # que NO tienen campo confirmar_celular (registro administrativo rápido).
        if (not d.get("celular_confirmacion")) and d.get("celular"):
            d["celular_confirmacion"] = str(d["celular"])

        # 5) Si acepta_* siguen vacíos, rellenamos con hora actual UTC.
        if not d.get("acepta_terminos_at_iso"):
            d["acepta_terminos_at_iso"] = datetime.now(timezone.utc).isoformat()
        if not d.get("acepta_habeas_at_iso"):
            d["acepta_habeas_at_iso"] = datetime.now(timezone.utc).isoformat()
        # 6) Trim de los campos string principales:
        for k in ("qr_uuid", "nombres_apellidos", "celular", "telefono_fijo",
                  "celular_confirmacion", "correo_electronico", "direccion",
                  "barrio", "municipio", "ciudad", "acepta_terminos_at_iso",
                  "acepta_habeas_at_iso"):
            if isinstance(d.get(k), str):
                d[k] = d[k].strip()
                # Convertir string vacío → None en los opcionales.
                if d[k] == "" and k in ("celular", "telefono_fijo", "celular_confirmacion", "barrio", "municipio"):
                    d[k] = None
        return d

    @field_validator("nombres_apellidos")
    @classmethod
    def _v_nombres(cls, v):
        s = (v or "").strip()
        if len(s) < 2:
            raise ValueError("nombres_apellidos minimo 2 caracteres")
        if len(s) > 160:
            return s[:160]
        return s

    @field_validator("correo_electronico")
    @classmethod
    def _v_correo(cls, v):
        s = (v or "").strip().lower()
        if len(s) < 6 or "@" not in s or "." not in s.split("@")[-1]:
            raise ValueError("correo_electronico formato invalido (falta @ o .dominio)")
        if len(s) > 180:
            return s[:180]
        return s

    @field_validator("celular", "telefono_fijo", "celular_confirmacion")
    @classmethod
    def _v_tel(cls, v, info):
        if v is None:
            return None
        s = "".join(ch for ch in str(v) if ch.isdigit())
        if info.field_name == "telefono_fijo":
            if not (7 <= len(s) <= 15):
                # No levantamos error por telefono_fijo porque es opcional; limpiamos
                # a None si es inválido para no guardar basura.
                return None
            return s[:15]
        # celular / celular_confirmacion
        if len(s) < 7:
            return None  # 10 digits Colombia, pero aceptamos ≥7 internacional
        if len(s) > 15:
            return s[:15]
        return s

    @field_validator("direccion")
    @classmethod
    def _v_direccion(cls, v):
        s = (v or "").strip()
        if len(s) < 5:
            raise ValueError("direccion minimo 5 caracteres")
        if len(s) > 240:
            return s[:240]
        return s

    @field_validator("ciudad")
    @classmethod
    def _v_ciudad(cls, v):
        s = (v or "").strip()
        if len(s) < 2:
            raise ValueError("ciudad minimo 2 caracteres")
        if len(s) > 120:
            return s[:120]
        return s

    @field_validator("barrio", "municipio")
    @classmethod
    def _v_texto_corto(cls, v):
        if v is None:
            return None
        s = (v or "").strip()
        if s == "":
            return None
        if len(s) > 120:
            return s[:120]
        return s


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
    # Modo LEGACY (compatible con viejos frontends): si `size_px` > 0,
    # se usa directamente en pixeles (como era antes).
    size_px: int | None = None
    # Modo NUEVO: unidad = 'pixeles' o 'centimetros' ('cm' tambien valido)
    unidad: str = "pixeles"
    # Valor decimal. Si unidad='centimetros' → cm, si 'pixeles' → px (entero)
    tamano_valor: float | None = None
    # DPI a usar cuando unidad=cm. 300 default = calidad impresora normal/fotografia.
    dpi: int = 300
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
        ph = "%s" if DB_ENGINE == "POSTGRES" else "?"
        sql = (
            "SELECT id, uuid_qr, id_humano, size_px, formato, usado_registro_id, habilitado, usado_at "
            "FROM promo_qr_codes WHERE uuid_qr = %s"
            if DB_ENGINE == "POSTGRES"
            else "SELECT id, uuid_qr, id_humano, size_px, formato, usado_registro_id, habilitado, usado_at "
                 "FROM promo_qr_codes WHERE uuid_qr = ?"
        )
        cur.execute(sql, (qr_uuid,))
        row = cur.fetchone()
        if row is None:
            return {
                "valido": False,
                "usado": False,
                "habilitado": False,
                "estado": "no_existe",
                "mensaje": "QR no encontrado en el sistema. Pide un código nuevo en el puesto del evento.",
                "mensaje_titulo": "QR inválido",
                "size_px": 0,
                "id_humano": "",
                "usado_registro_id": None,
                "usado_at_iso": None,
                "ganador_nombre": None,
                "ganador_celular": None,
                "ganador_ciudad": None,
            }
        usado_registro_id = row[5]
        usado = usado_registro_id is not None
        habil_blob = row[6]
        habilitado = (
            bool(habil_blob) if DB_ENGINE == "POSTGRES" else (int(habil_blob) == 1 if habil_blob is not None else True)
        )
        size_px = int(row[3] or 512)
        id_humano = str(row[2] or "")
        usado_at_iso = None
        ganador_nombre = None
        ganador_celular = None
        ganador_ciudad = None
        if usado:
            try:
                _ua = row[7]
                if _ua is not None:
                    usado_at_iso = _ua.isoformat() if hasattr(_ua, "isoformat") else str(_ua)
            except Exception:
                pass
            cur.execute(
                f"SELECT nombres_apellidos, celular, ciudad, created_at FROM promo_registros WHERE id = {ph}",
                (usado_registro_id,) if DB_ENGINE == "POSTGRES" else [usado_registro_id],
            )
            rg = cur.fetchone()
            if rg is not None:
                ganador_nombre = str(rg[0] or "")
                ganador_celular = str(rg[1] or "")
                ganador_ciudad = str(rg[2] or "")
                if usado_at_iso is None:
                    try:
                        _ca = rg[3]
                        if _ca is not None:
                            usado_at_iso = _ca.isoformat() if hasattr(_ca, "isoformat") else str(_ca)
                    except Exception:
                        pass
        if not habilitado:
            return {
                "valido": False,
                "usado": usado,
                "habilitado": False,
                "estado": "inhabilitado",
                "mensaje_titulo": "QR inhabilitado",
                "mensaje": (
                    "Este código QR fue inhabilitado por el administrador del evento y ya no se puede usar. "
                    "Por favor solicita un QR nuevo en el puesto de Aguardiente Blanco del Valle."
                ),
                "size_px": size_px,
                "id_humano": id_humano,
                "usado_registro_id": usado_registro_id,
                "usado_at_iso": usado_at_iso,
                "ganador_nombre": ganador_nombre,
                "ganador_celular": ganador_celular,
                "ganador_ciudad": ganador_ciudad,
            }
        if usado:
            # User VERBATIM 03/10/2026: TITULO SOLO = "QR YA UTILIZADA". NADA MÁS.
            # Eliminar: frase gigante "Este código QR YA FUE UTILIZADO para registrar un ganador...
            # Cada persona tiene un QR único al momento de ganar."
            # Conservar solo: nombre ganador, hora registro Bogotá, ciudad. Pedir QR nuevo puesto.
            partes = []
            if ganador_nombre:
                partes.append(f"Reclamado por: {ganador_nombre}.")
            if usado_at_iso:
                try:
                    _dh = datetime.fromisoformat(usado_at_iso.replace("Z", "+00:00"))
                    if _dh.tzinfo is None:
                        _dh = _dh.replace(tzinfo=timezone.utc)
                    from datetime import timedelta
                    col = _dh.astimezone(timezone(timedelta(hours=-5)))
                    partes.append(f"Hora registro (Bogotá): {col.strftime('%d/%m/%Y %I:%M %p')}.")
                except Exception:
                    pass
            if ganador_ciudad:
                partes.append(f"Ciudad: {ganador_ciudad}.")
            extra = (" " + " ".join(partes)) if partes else ""
            return {
                "valido": False,
                "usado": True,
                "habilitado": True,
                "estado": "ya_usado",
                # ============ USER 03/10: TÍTULO EXACTO "QR YA UTILIZADA", NADA MÁS. ============
                "mensaje_titulo": "QR YA UTILIZADA",
                "mensaje": (
                    extra.strip()
                    + (" Pide un código QR NUEVO en el puesto del evento." if extra else "Pide un código QR NUEVO en el puesto del evento.")
                ).strip(),
                "size_px": size_px,
                "id_humano": id_humano,
                "usado_registro_id": usado_registro_id,
                "usado_at_iso": usado_at_iso,
                "ganador_nombre": ganador_nombre,
                "ganador_celular": ganador_celular,
                "ganador_ciudad": ganador_ciudad,
            }
        return {
            "valido": True,
            "usado": False,
            "habilitado": True,
            "estado": "listo",
            "mensaje_titulo": "¡Felicidades!",
            "mensaje": "QR válido y listo para reclamar tu premio.",
            "size_px": size_px,
            "id_humano": id_humano,
            "usado_registro_id": None,
            "usado_at_iso": None,
            "ganador_nombre": None,
            "ganador_celular": None,
            "ganador_ciudad": None,
        }


# B) POST /api/promo/aceptacion
@app.post("/api/promo/aceptacion")
def promo_aceptacion(req: PromoAceptacionReq):
    qr_uuid = (req.qr_uuid or "").strip()
    server_ts = datetime.now(timezone.utc)
    # Validación PREVIA: si QR NO EXISTE / INHABILITADO / YA USADO, no aceptar nada
    # User idea: un QR usado = link bloqueado (no permitir seguir flujo)
    if qr_uuid:
        with get_db_conn() as conn:
            cur = conn.cursor()
            ph = "%s" if DB_ENGINE == "POSTGRES" else "?"
            if DB_ENGINE == "POSTGRES":
                cur.execute(
                    "SELECT id, usado_registro_id, habilitado FROM promo_qr_codes WHERE uuid_qr = %s",
                    (qr_uuid,),
                )
            else:
                cur.execute(
                    "SELECT id, usado_registro_id, habilitado FROM promo_qr_codes WHERE uuid_qr = ?",
                    (qr_uuid,),
                )
            qr_row = cur.fetchone()
            if qr_row is None:
                raise HTTPException(status_code=404, detail="QR no encontrado")
            if DB_ENGINE == "POSTGRES":
                qr_hab = bool(qr_row[2])
            else:
                qr_hab = (int(qr_row[2]) == 1 if qr_row[2] is not None else True)
            if not qr_hab:
                raise HTTPException(
                    status_code=410,
                    detail="QR inhabilitado por el administrador. Pide un código nuevo en el puesto del evento.",
                )
            if qr_row[1] is not None:
                raise HTTPException(
                    status_code=409,
                    detail="QR ya utilizado: este premio ya fue reclamado por otra persona. Cada QR solo permite 1 ganador.",
                )
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

    # ========== CAMBIO USER 03/10: ¿Vives en Bogotá? = modalidad entrega.
    # Si el formulario envía `vive_bogota` bool (radiobuttons Si/No), PREVALECE sobre la detección automática.
    # Si `vive_bogota` es None (no llegó el campo, por ejemplo registro admin), hacemos fallback al
    # _promo_es_bogota original para NO ROMPER la inserción en base de datos (es_bogota_direccion NOT NULL).
    if isinstance(req.vive_bogota, bool):
        es_bogota = bool(req.vive_bogota)
    else:
        es_bogota = _promo_es_bogota(req.ciudad, req.direccion)
    modalidad = "DOMICILIO_BTA" if es_bogota else "RECOGER_CRA74"

    acepta_t_at = datetime.fromisoformat(req.acepta_terminos_at_iso.replace("Z", "+00:00")) if req.acepta_terminos_at_iso else datetime.now(timezone.utc)
    acepta_h_at = datetime.fromisoformat(req.acepta_habeas_at_iso.replace("Z", "+00:00")) if req.acepta_habeas_at_iso else datetime.now(timezone.utc)

    with get_db_conn() as conn:
        conn.autocommit = False
        try:
            cur = conn.cursor()
            if DB_ENGINE == "POSTGRES":
                cur.execute("SELECT id, uuid_qr, id_humano, usado_registro_id, habilitado FROM promo_qr_codes WHERE uuid_qr = %s", (qr_uuid,))
            else:
                cur.execute("BEGIN IMMEDIATE")
                cur.execute("SELECT id, uuid_qr, id_humano, usado_registro_id, habilitado FROM promo_qr_codes WHERE uuid_qr = ?", (qr_uuid,))
            qr_row = cur.fetchone()
            if qr_row is None:
                try:
                    conn.rollback()
                except Exception:
                    pass
                raise HTTPException(status_code=404, detail="QR no encontrado")
            qr_id = qr_row[0]
            if qr_row[3] is not None:
                try:
                    conn.rollback()
                except Exception:
                    pass
                raise HTTPException(status_code=409, detail="Este QR ya fue utilizado en un registro")
            qr_hab_raw = qr_row[4]
            qr_habilitado = (
                bool(qr_hab_raw) if DB_ENGINE == "POSTGRES" else (int(qr_hab_raw) == 1 if qr_hab_raw is not None else True)
            )
            if not qr_habilitado:
                try:
                    conn.rollback()
                except Exception:
                    pass
                raise HTTPException(
                    status_code=410,
                    detail="Este QR fue inhabilitado por el administrador. Por favor solicita un código nuevo en el puesto del evento.",
                )

            # ===== MODO EVENTO: TODOS LOS QR = GANADORES (sin límite, sin cupo) =====
            # Se elimina lógica FIFO SERIALIZABLE + promo_sorteo_lock FOR UPDATE + chequeo max_ganadores.
            # User VERBATIM: "todod lso qr que se generen son gaandores porfa"
            # Siempre asignamos posicion_orden_ganador secuencial (para trazabilidad admin)
            # pero SIN NINGÚN TOPE = TODOS GANAN.
            cur.execute(
                "SELECT id, max_ganadores, estado_abierto, dir_fuera_bogota, titulo_premio FROM promo_config WHERE id = %s"
                if DB_ENGINE == "POSTGRES"
                else "SELECT id, max_ganadores, estado_abierto, dir_fuera_bogota, titulo_premio FROM promo_config WHERE id = ?",
                (1,),
            )
            cfg_row = cur.fetchone()
            if cfg_row is None:
                try:
                    conn.rollback()
                except Exception:
                    pass
                raise HTTPException(status_code=500, detail="Configuración no inicializada")

            estado_abierto = bool(cfg_row[2]) if DB_ENGINE == "POSTGRES" else (int(cfg_row[2]) == 1)
            if not estado_abierto:
                try:
                    conn.rollback()
                except Exception:
                    pass
                raise HTTPException(status_code=423, detail="Promoción cerrada temporalmente")

            # max_gan se IGNORA completamente (no hay tope). Solo lo leemos por compatibilidad config.
            dir_fuera = str(cfg_row[3] or "Cra. 74a #51a-87, Bogotá")
            titulo_premio = str(cfg_row[4] or "Botella Aguardiente Blanco del Valle Fiesta")

            # Conteo para posición secuencial TRAZABILIDAD (no es tope, solo para saber qué # ganador eres)
            count_sql = "SELECT COUNT(*) FROM promo_registros WHERE posicion_orden_ganador IS NOT NULL"
            cur.execute(count_sql)
            count_gan = int(cur.fetchone()[0] or 0)

            # === TODOS GANAN === Asignamos posición SIEMPRE, sin if count<max
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
                try:
                    conn.rollback()
                except Exception:
                    pass
                raise HTTPException(status_code=409, detail="QR concurrentemente utilizado")

            conn.commit()

            # GANADOR SIEMPRE = True (nunca "no ganaste")
            ganador = True
            mensaje_agradecimiento = (
                f"¡FELICITACIONES! Eres el ganador #{posicion_ganador} de {titulo_premio}. "
                f"{'Te lo enviaremos a tu domicilio en Bogotá.' if es_bogota else f'Retíralo en {dir_fuera}.'}"
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
        # MODO EVENTO: TODOS LOS REGISTROS = GANADORES (user VERBATIM: todo QR generado es ganador)
        # Si posicion_orden_ganador es NULL por algún registro legacy, asignamos contando+1 inline
        if d["posicion_orden_ganador"] is None:
            cur.execute("SELECT COUNT(*) FROM promo_registros WHERE posicion_orden_ganador IS NOT NULL")
            _posicion_fallback = int((cur.fetchone() or [0])[0] or 0) + 1
            d["posicion_orden_ganador"] = _posicion_fallback
        ganador = True
        mensaje_agradecimiento = (
            f"¡FELICITACIONES! Eres el ganador #{d['posicion_orden_ganador']} de {titulo_premio}. "
            f"{'Te lo enviaremos a tu domicilio en Bogotá.' if es_bogota else f'Retíralo en {dir_fuera}.'}"
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


# =====================================================================
# E-BIS) ENDPOINTS AUXILIARES DEBUG / HEALTHCHECK PROMOCION (SIN AUTH)
# Estos SOLO se usan 1 vez en deploy para asegurarse tablas y admin OK.
# =====================================================================

@app.get("/api/promo/debug/health")
def promo_debug_health(request: Request):
    """Healthcheck simple sistema promocion: estado tablas, admin existe, + CONTEOS filas para diagnosticar QRs perdidos."""
    out = {"db_engine": DB_ENGINE, "ok": True, "checks": {}, "counts": {}}
    # Variables entorno mostradas sin secrets (para diagnosticar CORS)
    _fu_raw = os.environ.get("FRONTEND_URL") or ""
    _fu_clean = _clean_env_str(_fu_raw, strip_slash_end=True)
    out["env"] = {
        "FRONTEND_URL_config_raw": _fu_raw[:120],
        "FRONTEND_URL_config_USADO_EFECTIVAMENTE": _fu_clean[:120],
        "backticks_limpiados_automaticamente": bool(_fu_raw != _fu_clean),
        "CORS_ALLOW_ORIGINS_env_raw": (os.environ.get("CORS_ALLOW_ORIGINS") or "")[:160],
        "CORS_ALLOW_ORIGINS_env_USADO_EFECTIVAMENTE":
            _clean_env_str(os.environ.get("CORS_ALLOW_ORIGINS") or "")[:160],
        "JWT_SECRET_SET": bool(os.environ.get("JWT_SECRET")),
        "BACKEND_PUBLIC_URL_env": (os.environ.get("BACKEND_PUBLIC_URL") or "")[:80],
    }
    # CORS info
    origin = (request.headers.get("origin") or "") or None
    allow_ok, echo = _cors_origin_allowed(origin)
    out["cors"] = {
        "origin_entrante": origin,
        "permitido": bool(allow_ok),
        "echo_origin": echo,
    }
    try:
        init_promo_db_tables_and_seeds()
        out["checks"]["init_seeds_idempotent"] = True
    except Exception as e:
        out["checks"]["init_seeds_idempotent"] = False
        out["error_init"] = str(e)
        out["ok"] = False
    tablas = ["promo_admin_users", "promo_config", "promo_qr_codes",
              "promo_registros", "promo_auditoria_admin", "promo_sorteo_lock"]
    with get_db_conn() as conn:
        cur = conn.cursor()
        for t in tablas:
            try:
                if DB_ENGINE == "POSTGRES":
                    cur.execute(f"SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = %s)", (t,))
                    existe = bool(cur.fetchone()[0])
                else:
                    cur.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name = ?", (t,))
                    existe = cur.fetchone() is not None
                out["checks"][f"tabla_{t}"] = existe
                if not existe:
                    out["ok"] = False
                else:
                    # COUNT filas para diagnosticar QRs perdidos
                    try:
                        cur.execute(f"SELECT COUNT(*) FROM {t}")
                        row = cur.fetchone()
                        out["counts"][t] = int(row[0]) if row else 0
                    except Exception:
                        out["counts"][t] = None
            except Exception as e:
                out["checks"][f"tabla_{t}"] = False
                out[f"error_tabla_{t}"] = str(e)
                out["ok"] = False
        # admin ilv1921
        try:
            admin = _promo_get_admin_from_db("ilv1921")
            out["checks"]["admin_ilv1921_exists"] = admin is not None
            if admin is None:
                out["ok"] = False
                out["reseed_url"] = "/api/promo/debug/reseed-admin (GET, solo 1 vez)"
            else:
                out["checks"]["admin_bcrypt_len"] = len(admin["password_hash"])
                out["checks"]["admin_password_verify_Fiesta2026_Valle"] = bool(
                    _promo_verify_password("Fiesta2026!Valle", admin["password_hash"])
                )
        except Exception as e:
            out["checks"]["admin_ilv1921_exists"] = False
            out["error_admin"] = str(e)
            out["ok"] = False
    # config
    try:
        with get_db_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT id, max_ganadores, estado_abierto FROM promo_config WHERE id = 1")
            r = cur.fetchone()
            out["checks"]["config_id1_exists"] = r is not None
            if r is not None:
                out["config"] = {"max_ganadores": int(r[1]), "estado_abierto": bool(r[2]) if DB_ENGINE=="POSTGRES" else (int(r[2])==1)}
    except Exception:
        out["checks"]["config_id1_exists"] = False
        out["ok"] = False
    # DB WARNINGS
    if DB_ENGINE == "SQLITE":
        out["db_warning"] = (
            "⚠️ ESTAS EN SQLITE LOCAL: CADA REDEPLOY EN RAILWAY BORRA TODOS LOS QRs Y REGISTROS. "
            "Solución recomendada: Railway Dashboard → NEW → Database → PostgreSQL → Create → "
            "luego en Servicio1 Backend → Settings → Attach Database → selecciona la PostgreSQL "
            "(0 costo, 0 egress Private Networking). Datos permanentes."
        )
        out["db_warning_alt_volumen"] = (
            "Opcion alternativa mas barata: Servicio1 → Settings → Volumes → Add Volume, "
            "Mount Path = /app/backend-python (guarda SQLite en disco persistente)."
        )
    if out["counts"].get("promo_qr_codes") == 0:
        out["qr_0_filas_warning"] = (
            "promo_qr_codes = 0 filas. Si esperabas códigos: se borraron en redeploy anterior "
            "por SQLite sin persistencia, o es PostgreSQL DB nueva attachada recien."
        )
    # ===== NUEVO: Informe permanencia BLOQUEO NUCLEAR =====
    try:
        guard = _promo_get_permanent_data_guard()
    except Exception:
        guard = None
    if guard is None:
        out["persistencia"] = {
            "ok": False,
            "status": "NO_GUARD_INITIALIZED",
            "note": "No se ha inicializado tabla promo_permanent_data_guard. Redesplegar o invocar init."
        }
    else:
        out["persistencia"] = {
            "ok": True,
            "db_uuid_prefix": (guard["db_uuid"] or "")[:14] + ("…" if guard["db_uuid"] and len(guard["db_uuid"]) > 14 else ""),
            "guard_created_at": guard["created_at"],
            "permanencia_qr_vs_max_ever": guard["permanencia_ok_qr"],
            "permanencia_registros_vs_max_ever": guard["permanencia_ok_registros"],
            "hubo_perdida_datos_detectada": guard["perdida_detectada"],
            "perdidos_qr": guard["diferencia_qr"],
            "perdidos_registros": guard["diferencia_registros"],
            "last_check_status_guard": guard["last_check_status"],
            "last_check_guard_at": guard["last_check_at"],
            "max_ever_registrados": {
                "qr_codes": guard["max_qr_codes_ever"],
                "registros": guard["max_registros_ever"],
            },
            "actual_registrados": guard["counts_now"],
        }
    return out


@app.get("/api/promo/debug/persistencia")
def promo_debug_persistencia(request: Request):
    """VERIFICACIÓN 1 CLIC PERMANENCIA QR/REGISTROS.
    Devuelve: DB engine actual + estado Bloqueo Nuclear Anti-Borrado (promo_permanent_data_guard) +
    conteo QRs ahora vs MAX_QUE_TUVIMOS_NUNCA para confirmar NO HUBO PÉRDIDA."""
    res = {
        "db_engine": DB_ENGINE,
        "database_url_set": bool(DATABASE_URL),
        "database_host_redacted": "",
        "permanent_guard_exists": False,
        "permanencia_total_ok": False,
        "recomendaciones": [],
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
    }
    # Información DB sin exponer password/URL
    try:
        from urllib.parse import urlparse
        if DATABASE_URL:
            parsed = urlparse(DATABASE_URL)
            _host = (parsed.hostname or "")[:40]
            _port = parsed.port
            res["database_host_redacted"] = f"{_host}:{_port}" if _port else _host
            res["database_scheme"] = parsed.scheme or ""
    except Exception:
        pass
    # Ejecutar init una vez (si no se ejecutó startup) para asegurar tabla guard:
    _init_err = None
    try:
        init_promo_db_tables_and_seeds()
        res["init_tables_ok"] = True
    except Exception as e_init:
        res["init_tables_ok"] = False
        _init_err = f"{type(e_init).__name__}: {str(e_init)[:200]}"
        res["init_error"] = _init_err
    # Leer guard y conteos actuales
    guard = None
    try:
        guard = _promo_get_permanent_data_guard()
    except Exception as e_g:
        res["guard_read_error"] = f"{type(e_g).__name__}: {str(e_g)[:180]}"
    if guard is None:
        res["recomendaciones"].append(
            "⚠️ Guard NO inicializado. (1) Asegurarse DB_POSTGRES atachada correctamente. "
            "(2) Volver a dar clic Redeploy. (3) Refresh esta URL."
        )
    else:
        res["permanent_guard_exists"] = True
        res["guard"] = {
            "db_uuid": guard["db_uuid"],
            "created_at": guard["created_at"],
            "last_check_at": guard["last_check_at"],
            "last_check_status": guard["last_check_status"],
            "last_note": guard["last_note"],
        }
        res["conteos"] = {
            "max_ever_qrs": guard["max_qr_codes_ever"],
            "max_ever_registros": guard["max_registros_ever"],
            "max_ever_auditoria": guard["max_auditoria_ever"],
            "actual_qrs": guard["counts_now"]["promo_qr_codes"],
            "actual_registros": guard["counts_now"]["promo_registros"],
            "actual_auditoria": guard["counts_now"]["promo_auditoria_admin"],
        }
        res["permanencia_qr_vs_max"] = guard["permanencia_ok_qr"]
        res["permanencia_registros_vs_max"] = guard["permanencia_ok_registros"]
        res["permanencia_total_ok"] = (not guard["perdida_detectada"])
        if guard["perdida_detectada"]:
            res["estado"] = "🚨 PÉRDIDA DE DATOS DETECTADA"
            res["recomendaciones"].append(
                f"🔴 QRs PERDIDOS: {guard['diferencia_qr']} · REGISTROS PERDIDOS: {guard['diferencia_registros']}"
            )
            if DB_ENGINE == "SQLITE":
                res["recomendaciones"].append(
                    "⚠️ ESTAS EN SQLITE SIN VOLUMEN PERSISTENTE. Los datos se BORRAN en cada redeploy Railway. "
                    "SOLUCIÓN: (A) Railway → NEW → PostgreSQL → Create → Backend Servicio1 → Settings → Attach DB. "
                    "(B) O Railway Backend → Settings → Volumes → Add Volume → Mount Path=/app/backend-python (≈$0.25/mes)."
                )
            else:
                res["recomendaciones"].append(
                    "⚠️ ESTAS EN PostgreSQL y hubo pérdida: Seguramente cambiaste de variable DATABASE_URL y atachaste una BD NUEVA. "
                    "Revisa en Railway Backend → Variables → DATABASE_URL sea el URL de la BD ANTERIOR donde estaban los QRs originales."
                )
        else:
            res["estado"] = "✅ PERMANENCIA TOTAL ASEGURADA (sin pérdida)"
    # Recomendaciones base según engine
    if DB_ENGINE == "SQLITE":
        res["engine_warning"] = (
            "🛑 ESTAS EN SQLITE LOCAL SIN VOLUMEN: CADA REDEPLOY BORRA TODO. NO PARA EVENTOS."
        )
        if not res["database_url_set"]:
            res["recomendaciones"].append(
                "1) Crear PostgreSQL en Railway (NEW → Database → PostgreSQL). 2) Copiar Connection URL. "
                "3) Backend Servicio1 → Variables → NEW → DATABASE_URL = URL pegada. 4) Redeploy."
            )
    else:
        res["engine_note"] = "🟢 PostgreSQL gestionado Railway: datos permanentes por diseño (incluye backups y disco persistente)."
    return res


@app.get("/api/promo/debug/reseed-admin")
def promo_debug_reseed_admin():
    """SOLUCION CREDENCIALES INVALIDAS: se llama UNA VEZ con GET (cualquier navegador).
    Borra admin ilv1921 si existe y lo vuelve a insertar con hash bcrypt CORRECTO
    de 'Fiesta2026!Valle'. Tambien reinserta config + lock si se perdieron.
    IDEMPOTENTE."""
    acciones = []
    with get_db_conn() as conn:
        cur = conn.cursor()
        # Asegurar tablas existan (por si el startup no corrió)
        try:
            init_promo_db_tables_and_seeds()
            acciones.append("init_promo_db_tables_and_seeds OK (idempotente)")
        except Exception as e:
            raise HTTPException(500, detail=f"Fallo init: {e}")

        # 1) BORRAR y REINSERTAR admin ilv1921
        if DB_ENGINE == "POSTGRES":
            cur.execute("DELETE FROM promo_admin_users WHERE username = %s", ("ilv1921",))
            cur.execute(
                "INSERT INTO promo_admin_users (username, password_hash) VALUES (%s, %s)",
                ("ilv1921", _PROMO_ILV1921_BCRYPT_HASH),
            )
        else:
            cur.execute("DELETE FROM promo_admin_users WHERE username = ?", ("ilv1921",))
            cur.execute(
                "INSERT INTO promo_admin_users (username, password_hash) VALUES (?, ?)",
                ("ilv1921", _PROMO_ILV1921_BCRYPT_HASH),
            )
        acciones.append("admin ilv1921 RE-INSERTADO (hash bcrypt correcto Fiesta2026!Valle)")

        # 2) Config si no existe
        if DB_ENGINE == "POSTGRES":
            cur.execute("SELECT 1 FROM promo_config WHERE id = 1")
            if cur.fetchone() is None:
                cur.execute(
                    "INSERT INTO promo_config (id, max_ganadores, estado_abierto, titulo_premio, dir_fuera_bogota, updated_at) "
                    "VALUES (1, 1, TRUE, 'Botella Aguardiente Blanco del Valle Fiesta', 'Cra. 74a #51a-87, Bogotá', NOW())"
                )
                acciones.append("promo_config id=1 insertada (sino existía)")
            cur.execute("SELECT 1 FROM promo_sorteo_lock WHERE id = 1")
            if cur.fetchone() is None:
                cur.execute("INSERT INTO promo_sorteo_lock (id, dummy) VALUES (1, 0)")
                acciones.append("promo_sorteo_lock id=1 insertado")
        else:
            cur.execute("SELECT 1 FROM promo_config WHERE id = 1")
            if cur.fetchone() is None:
                cur.execute(
                    "INSERT INTO promo_config (id, max_ganadores, estado_abierto, titulo_premio, dir_fuera_bogota, updated_at) "
                    "VALUES (1, 1, 1, 'Botella Aguardiente Blanco del Valle Fiesta', 'Cra. 74a #51a-87, Bogotá', STRFTIME('%Y-%m-%dT%H:%M:%SZ','now'))"
                )
                acciones.append("promo_config id=1 insertada")
            cur.execute("SELECT 1 FROM promo_sorteo_lock WHERE id = 1")
            if cur.fetchone() is None:
                cur.execute("INSERT INTO promo_sorteo_lock (id, dummy) VALUES (1, 0)")
                acciones.append("promo_sorteo_lock id=1 insertado")
        conn.commit()

        # 3) Verificar admin recien insertado y password valido
        admin = _promo_get_admin_from_db("ilv1921")
        ok = False
        if admin is not None:
            ok = _promo_verify_password("Fiesta2026!Valle", admin["password_hash"])
    return {
        "ok": True,
        "acciones_realizadas": acciones,
        "login_admin": {
            "url": "/admin",
            "username": "ilv1921",
            "password": "Fiesta2026!Valle",
            "hash_correcto_verificado": ok,
        },
        "proximo_paso": "Cargar /admin en el browser y loguearte. Si falla, revisa Railway redeploy SHA nuevo.",
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
            # ========= ALIAS FRONTEND-COMPATIBLES =========
            # AdminDashboard.jsx Tab2 lee: r.posicion  (backend envía posicion_orden_ganador → alias)
            # AdminDashboard.jsx Tab2 lee: r.fecha_registro (backend envía created_at → alias)
            # AdminDashboard.jsx Tab2 lee: r.ganador  (columna "Ganó?" en la tabla → siempre True modo evento pero envía explícito)
            # AdminDashboard.jsx Tab2 lee: r.correo (lo mismo)
            # AdminDashboard.jsx Tab2 lee: r.nombres (lo mismo)
            # AdminDashboard.jsx Tab2 lee: r.modalidad  (lo mismo)
            # AdminDashboard.jsx Tab2 lee: r.registro_id  (lo mismo, id → alias)
            # AdminDashboard.jsx Tab2 lee: r.fecha  (lo mismo)
            # AdminDashboard.jsx Tab2 lee: r.pos | r.numero (fallbacks extras)
            if "posicion_orden_ganador" in it:
                it["posicion"] = it["posicion_orden_ganador"]
                it["pos"] = it["posicion_orden_ganador"]
                it["numero"] = it["posicion_orden_ganador"]
            if "created_at" in it:
                it["fecha_registro"] = it["created_at"]
                it["fecha"] = it["created_at"]
            if "id" in it:
                it["registro_id"] = it["id"]
            it["ganador"] = (it.get("posicion_orden_ganador") is not None)
            if "correo_electronico" in it:
                it["correo"] = it["correo_electronico"]
            if "nombres_apellidos" in it:
                it["nombres"] = it["nombres_apellidos"]
            if "modalidad_entrega" in it:
                it["modalidad"] = it["modalidad_entrega"]
    # Alias triple de retrocompatibilidad:
    #   items      = clave OFICIAL (por naming consistente con /api/admin/qr/list que usa items)
    #   registros  = alias clave esperada por algunas versiones antiguas de AdminDashboard TAB2
    #   data       = alias fallback genérico
    # Así no se rompe si el frontend busca una u otra key (fix error "no salen las personas registradas"
    # cuando el frontend buscaba d.registros pero el backend solo enviaba d.items).
    return {
        "total": total,
        "page": page,
        "per_page": per_page,
        "items": items,
        "registros": items,
        "data": items,
    }


# I) PUT /api/admin/registros/{id}
@app.put("/api/admin/registros/{id}")
def admin_update_registro(id: int, req: AdminRegistroUpdateReq, admin: dict = _promo_Depends(get_current_admin)):
    with get_db_conn() as conn:
        conn.autocommit = False
        try:
            cur = conn.cursor()
            updates = []
            params = []
            ph = "%s" if DB_ENGINE == "POSTGRES" else "?"
            data = req.model_dump(exclude_none=True)

            # ========= BUG FIX UPDATE: Primero agregamos TODOS los campos del modelo =========
            # El bug anterior: k==ciudad y k==es_bogota_direccion siempre hacian continue.
            # Resultado: updates quedaba vacio si solo modificaba nombres/celular (sin ciudad/dir)
            # y NO SE ACTUALIZABA NADA.
            # Ahora: TODO campo editable se agrega PRIMERO a updates.
            # Luego SI cambian ciudad/direccion RECALCULAMOS y sobreescribimos si hace falta.
            ALLOWED_FIELDS = {
                "nombres_apellidos", "celular", "telefono_fijo", "celular_confirmacion",
                "correo_electronico", "direccion", "barrio", "municipio", "ciudad",
                "posicion_orden_ganador", "modalidad_entrega", "es_bogota_direccion",
                "acepta_terminos", "acepta_habeas",
            }
            for k, v in data.items():
                if k not in ALLOWED_FIELDS:
                    continue
                updates.append(f"{k} = {ph}")
                if isinstance(v, bool) and DB_ENGINE != "POSTGRES":
                    params.append(1 if v else 0)
                else:
                    params.append(v)

            # SI cambiaron ciudad O direccion: volvemos a calcular es_bogota_direccion y modalidad.
            if "ciudad" in data or "direccion" in data:
                if DB_ENGINE == "POSTGRES":
                    cur.execute(f"SELECT ciudad, direccion FROM promo_registros WHERE id = {ph}", (id,))
                else:
                    cur.execute(f"SELECT ciudad, direccion FROM promo_registros WHERE id = {ph}", [id])
                row = cur.fetchone()
                if row is None:
                    raise HTTPException(status_code=404, detail="Registro no encontrado")
                c = data.get("ciudad", row[0])
                d = data.get("direccion", row[1])
                es_b = _promo_es_bogota(c or "", d or "")
                mod = "DOMICILIO_BTA" if es_b else "RECOGER_CRA74"

                # Solo agregamos si NO se enviaron explícitamente desde el front
                if "es_bogota_direccion" not in data:
                    updates.append(f"es_bogota_direccion = {ph}")
                    params.append(es_b if DB_ENGINE == "POSTGRES" else (1 if es_b else 0))
                if "modalidad_entrega" not in data:
                    updates.append(f"modalidad_entrega = {ph}")
                    params.append(mod)

            if not updates:
                # No hay fields para actualizar = 0 cambios. Devolvemos ok (sin error)
                return {"ok": True, "updated": False, "motivo": "no_fields_changed"}

            params.append(id)
            sql = f"UPDATE promo_registros SET {', '.join(updates)} WHERE id = {ph}"
            cur.execute(sql, tuple(params) if DB_ENGINE == "POSTGRES" else params)
            if cur.rowcount == 0:
                raise HTTPException(status_code=404, detail="Registro no encontrado")
            conn.commit()
        except HTTPException:
            try:
                conn.rollback()
            except Exception:
                pass
            raise
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            raise HTTPException(status_code=500, detail=f"Error update: {str(e)}")
    _promo_insert_auditoria(int(admin["id"]), "UPDATE_REGISTRO", {"id": id, **data})
    return {"ok": True, "updated": True, "id": id, "fields_updated_count": len([u for u in updates if not u.startswith("es_bogota") and not u.startswith("modalidad")]) + (1 if any(u.startswith("es_bogota") for u in updates) else 0) + (1 if any(u.startswith("modalidad") for u in updates) else 0)}


# J) DELETE /api/admin/registros/{id} (RENUMERACIÓN ATÓMICA)
@app.delete("/api/admin/registros/{id}")
def admin_delete_registro(id: int, admin: dict = _promo_Depends(get_current_admin)):
    with get_db_conn() as conn:
        conn.autocommit = False
        posicion_eliminado = None
        recalculated = 0
        try:
            cur = conn.cursor()
            ph = "%s" if DB_ENGINE == "POSTGRES" else "?"
            if DB_ENGINE == "SQLITE":
                cur.execute("BEGIN IMMEDIATE")
            # PostgreSQL con autocommit=False YA inicia transacción automáticamente.
            # NUNCA ejecutar BEGIN manual; causa "cannot start a transaction within a transaction".
            if DB_ENGINE == "POSTGRES":
                cur.execute(f"SELECT id, posicion_orden_ganador FROM promo_registros WHERE id = {ph} FOR UPDATE", (id,))
            else:
                cur.execute(f"SELECT id, posicion_orden_ganador FROM promo_registros WHERE id = {ph}", (id,))
            row = cur.fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="Registro no encontrado")
            posicion_eliminado = row[1]
            cur.execute(f"DELETE FROM promo_registros WHERE id = {ph}", (id,))
            cur.execute(f"UPDATE promo_qr_codes SET usado_registro_id = NULL, usado_at = NULL WHERE usado_registro_id = {ph}", (id,))

            recalculated = 0
            if posicion_eliminado is not None:
                # PostgreSQL NO SOPORTA ORDER BY dentro de UPDATE ... WHERE sin FROM LATERAL.
                # La resta posicion_orden_ganador = posicion_orden_ganador - 1 es conmutativa:
                # da EXACTAMENTE el mismo resultado final sin importar el orden de ejecución fila.
                # Quitar ORDER BY evita el error de sintaxis:
                #   "syntax error at or near 'ORDER' ... UPDATE promo_registros SET ... WHERE ... > $1 ORDER BY p..."
                # Mismo código para SQLite/POSTGRES porque ambos aceptan UPDATE sin ORDER BY aquí.
                cur.execute(
                    f"UPDATE promo_registros SET posicion_orden_ganador = posicion_orden_ganador - 1 WHERE posicion_orden_ganador > {ph}",
                    (posicion_eliminado,),
                )
                recalculated = cur.rowcount or 0
            conn.commit()
        except HTTPException:
            try:
                conn.rollback()
            except Exception:
                pass
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
    # FIX: Import openpyxl CON try-except global para evitar 500 si no está instalado en Railway
    try:
        import openpyxl as _xl
        from openpyxl.styles import Font as _XlFont
    except Exception as _e_xl:
        raise HTTPException(
            status_code=500,
            detail=f"Librería openpyxl no disponible en el servidor. Error interno: {str(_e_xl)}",
        )
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
    rows_returned = 0
    with get_db_conn() as conn:
        cur = conn.cursor()
        cur.execute(f"SELECT {cols_str} FROM promo_registros ORDER BY COALESCE(posicion_orden_ganador, 999999999) ASC, created_at ASC")
        rows = cur.fetchall()
        rows_returned = len(rows)
        for r in rows:
            d = _promo_row_to_dict(r, cols)
            es_bog = bool(d["es_bogota_direccion"]) if DB_ENGINE == "POSTGRES" else (int(d["es_bogota_direccion"] or 0) == 1)
            acc_t = bool(d["acepta_terminos"]) if DB_ENGINE == "POSTGRES" else (int(d["acepta_terminos"] or 0) == 1)
            acc_h = bool(d["acepta_habeas"]) if DB_ENGINE == "POSTGRES" else (int(d["acepta_habeas"] or 0) == 1)
            # FIX: Todos los string fields con fallback or "" para que None no crashee openpyxl/len
            ws.append([
                d.get("posicion_orden_ganador") if d.get("posicion_orden_ganador") is not None else "",
                d.get("created_at") if d.get("created_at") is not None else "",
                d.get("qr_uuid") or "",
                d.get("nombres_apellidos") or "",
                d.get("celular") or "",
                d.get("telefono_fijo") or "",
                d.get("correo_electronico") or "",  # FIX: antes d["correo_electronico"] crasheaba si NULL
                d.get("direccion") or "",
                d.get("barrio") or "",
                d.get("municipio") or "",
                d.get("ciudad") or "",
                ("SÍ" if es_bog else "NO"),
                d.get("modalidad_entrega") or "",
                ("SÍ" if acc_t else "NO"),
                ("SÍ" if acc_h else "NO"),
                d.get("ip_cliente") or "",
                (str(d.get("user_agent") or "")[:200]),
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
    _promo_insert_auditoria(int(admin["id"]), "EXPORT_XLSX", {"filename": fname, "total_rows": rows_returned})
    # IMPORTANTE: FastAPI FileResponse() SOLO acepta path=STRING (ruta a archivo FÍSICO en disco).
    # Si le pasas un io.BytesIO() lanza TypeError: "expected str, bytes or os.PathLike object, not _io.BytesIO".
    # El error 500 resultante hacía que el frontend mostrara mensaje genérico "Error descargando Excel.
    # Revisa que el backend Python esté encendido y autenticado".
    # CORRECTO: usar StreamingResponse(iter([bytes_buf]), media_type, headers) para data en memoria.
    # Incluimos ambos filename (RFC5987 filename*=UTF-8'' + filename= compat navegadores antiguos).
    from urllib.parse import quote as _urlquote
    fname_ascii = fname.encode('ascii', errors='ignore').decode('ascii') or "registros.xlsx"
    fname_utf8_quoted = _urlquote(fname, safe="")
    content_disposition = (
        f'attachment; filename="{fname_ascii}"; filename*=UTF-8\'\'{fname_utf8_quoted}'
    )
    media_type_xlsx = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type=media_type_xlsx,
        headers={
            "Content-Disposition": content_disposition,
            "Content-Length": str(len(buf.getvalue())),
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
        },
    )


# L) POST /api/admin/qr/generar
@app.post("/api/admin/qr/generar")
async def admin_qr_generar(req: AdminQrGenerarReq, request: Request, admin: dict = _promo_Depends(get_current_admin)):
    cantidad = int(req.cantidad or 0)
    if cantidad < 1 or cantidad > 5000:
        raise HTTPException(status_code=400, detail="cantidad debe estar entre 1 y 5000")
    formato = (req.formato or "png").lower()
    if formato not in ("png", "svg"):
        raise HTTPException(status_code=400, detail="formato debe ser 'png' o 'svg'")

    # ============ CALCULAR SIZE_PX =============
    unidad_entrada = (req.unidad or "pixeles").strip().lower()
    if unidad_entrada in ("cm", "centimetros", "centímetros", "centimetro", "centímetro"):
        unidad = "centimetros"
    elif unidad_entrada in ("px", "pixeles", "píxeles", "pixel", "píxel"):
        unidad = "pixeles"
    else:
        # Modo legacy para frontends antiguos:
        if req.tamano_valor is None and req.size_px is not None:
            unidad = "pixeles"
        else:
            unidad = unidad_entrada if unidad_entrada else "pixeles"

    dpi = int(req.dpi or 300)
    dpi = max(72, min(1200, dpi))

    tamano_cm_guardar = None
    tamano_valor_float = None
    if req.tamano_valor is not None:
        try:
            tamano_valor_float = float(req.tamano_valor)
        except Exception:
            tamano_valor_float = None

    size_px = None
    if req.size_px is not None:
        size_px = int(req.size_px)

    if size_px is None and tamano_valor_float is not None and tamano_valor_float > 0:
        if unidad == "centimetros":
            # FÓRMULA OFICIAL: px = (cm * dpi) / 2.54 (1 inch = 2.54 cm)
            size_px = int(round((tamano_valor_float * dpi) / 2.54))
            tamano_cm_guardar = float(tamano_valor_float)
        else:
            # unidad = pixeles, tamano_valor es el tamaño en pixeles (puede ser decimal, lo redondeamos)
            size_px = int(round(tamano_valor_float))
            tamano_cm_guardar = None
    if size_px is None:
        size_px = 512
    # Clamp
    size_px = max(256, min(2048, int(size_px)))

    scheme = request.base_url.scheme
    host_hdr = request.headers.get("host", "")
    origin_hdr = _clean_env_str(request.headers.get("origin") or "")
    frontend_url_env = _clean_env_str(os.environ.get("FRONTEND_URL") or "", strip_slash_end=True)
    frontend_base_url = None
    if frontend_url_env:
        # Acepta valor con o sin barra final, con o sin /ganador/registro etc.
        frontend_base_url = frontend_url_env
    elif origin_hdr:
        # Origin = "https://frontend.railway.app" sin path final (estándar HTTP spec)
        try:
            from urllib.parse import urlparse as _urlparse
            _p = _urlparse(origin_hdr)
            if _p.scheme and _p.netloc:
                frontend_base_url = f"{_p.scheme}://{_p.netloc}"
        except Exception:
            frontend_base_url = origin_hdr.rstrip("/")
    if not frontend_base_url:
        frontend_base_url = f"{scheme}://{host_hdr}" if host_hdr else str(request.base_url).rstrip("/")
    frontend_base_url = frontend_base_url.rstrip("/") + "/"

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
            if DB_ENGINE == "POSTGRES":
                sql = (
                    "INSERT INTO promo_qr_codes "
                    "(uuid_qr, id_humano, size_px, tamano_cm, dpi, unidad, formato, "
                    "habilitado, creado_admin_id) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id"
                )
                params = (
                    qr_uuid, id_humano, size_px, tamano_cm_guardar, dpi, unidad, formato,
                    True, int(admin["id"]),
                )
                cur.execute(sql, params)
                new_id = cur.fetchone()[0]
            else:
                sql = (
                    "INSERT INTO promo_qr_codes "
                    "(uuid_qr, id_humano, size_px, tamano_cm, dpi, unidad, formato, "
                    "habilitado, creado_admin_id) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"
                )
                params = (
                    qr_uuid, id_humano, size_px, tamano_cm_guardar, dpi, unidad, formato,
                    1, int(admin["id"]),
                )
                cur.execute(sql, params)
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
                # 🔴 Guardar metadata DPI en el PNG (chunk pHYs) para que la impresora
                # NO reduzca 5cm a 2cm al imprimir. Pillow guarda DPI como tupla (dpi_x,dpi_y).
                try:
                    img.info["dpi"] = (int(dpi), int(dpi))
                except Exception:
                    pass
                qbuf = io.BytesIO()
                img.save(qbuf, format="PNG", dpi=(int(dpi), int(dpi)))
                qbuf.seek(0)
                b64 = "data:image/png;base64," + base64.b64encode(qbuf.getvalue()).decode("ascii")
                created_items.append({
                    "id": int(new_id),
                    "qr_uuid": qr_uuid,
                    "id_humano": id_humano,
                    "size_px": size_px,
                    "tamano_cm": tamano_cm_guardar,
                    "dpi": dpi,
                    "unidad": unidad,
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
                    "tamano_cm": tamano_cm_guardar,
                    "dpi": dpi,
                    "unidad": unidad,
                    "url": url_full,
                    "svg_text": svg_text,
                })
        conn.commit()

    _promo_insert_auditoria(int(admin["id"]), "GENERAR_QR", {
        "cantidad": cantidad,
        "size_px": size_px,
        "tamano_cm": tamano_cm_guardar,
        "dpi": dpi,
        "unidad": unidad,
        "formato": formato,
    })
    return {
        "created_count": len(created_items),
        "size_px_final": size_px,
        "tamano_cm_final": tamano_cm_guardar,
        "dpi_final": dpi,
        "unidad_final": unidad,
        "items": created_items,
    }


# M) GET /api/admin/qr/list
@app.get("/api/admin/qr/list")
def admin_qr_list(
    usado: bool | None = None,
    habilitado: bool | None = None,
    q: str | None = None,
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
        where.append("usado_registro_id IS NOT NULL" if usado else "usado_registro_id IS NULL")
    if habilitado is not None:
        if DB_ENGINE == "POSTGRES":
            where.append(f"habilitado = {ph}")
            params.append(bool(habilitado))
        else:
            where.append(f"habilitado = {ph}")
            params.append(1 if habilitado else 0)
    if q:
        q = (q or "").strip()
        if q:
            where.append(f"(uuid_qr LIKE {ph} OR id_humano LIKE {ph} OR COALESCE(CAST(id AS TEXT), '') LIKE {ph})")
            like = f"%{q}%"
            params += [like, like, like]
    where_sql = f" WHERE {' AND '.join(where)}" if where else ""

    cols = [
        "id", "uuid_qr", "id_humano", "size_px", "tamano_cm", "dpi", "unidad",
        "formato", "habilitado", "inhabilitado_por_id", "inhabilitado_at",
        "usado_registro_id", "usado_at", "creado_admin_id", "created_at",
    ]
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
        # Normalizar booleano habilitado para SQLite (1/0)
        for it in items:
            if DB_ENGINE == "POSTGRES":
                it["habilitado"] = bool(it.get("habilitado", True))
            else:
                raw = it.get("habilitado")
                it["habilitado"] = True if raw is None else (int(raw) == 1)
            if it.get("usado_registro_id") is None:
                it["usado"] = False
            else:
                it["usado"] = True
            if it.get("tamano_cm"):
                try:
                    it["tamano_cm"] = float(it["tamano_cm"])
                except Exception:
                    pass
            if it.get("dpi"):
                try:
                    it["dpi"] = int(it["dpi"])
                except Exception:
                    pass
    return {"total": total, "page": page, "per_page": per_page, "items": items}


class AdminQrPatchReq(BaseModel):
    """PATCH /api/admin/qr/:id_or_uuid — para habilitar/inhabilitar/edit individual."""
    habilitado: bool | None = None
    # Opcionalmente el admin puede cambiar el tamaño de un QR generado (si no fue usado):
    tamano_cm: float | None = None
    size_px: int | None = None
    dpi: int | None = None
    unidad: str | None = None
    nota: str | None = None  # solo auditoria


def _promo_resolver_qr_identifier(cur, ph, id_or_uuid):
    """Dado un 'id_or_uuid' (integer id OR uuid_qr OR id_humano) devuelve row completa QR o None."""
    cols = [
        "id", "uuid_qr", "id_humano", "size_px", "tamano_cm", "dpi", "unidad",
        "formato", "habilitado", "inhabilitado_por_id", "inhabilitado_at",
        "usado_registro_id", "usado_at", "creado_admin_id", "created_at",
    ]
    cols_str = ", ".join(cols)
    # Primero intentar como integer id
    qr_id_int = None
    try:
        qr_id_int = int(id_or_uuid)
    except Exception:
        qr_id_int = None
    if qr_id_int is not None:
        cur.execute(f"SELECT {cols_str} FROM promo_qr_codes WHERE id = {ph}", (qr_id_int,))
        row = cur.fetchone()
        if row is not None:
            return _promo_row_to_dict(row, cols)
    # Luego intentar por uuid_qr exacto o id_humano exacto
    s = str(id_or_uuid).strip()
    cur.execute(f"SELECT {cols_str} FROM promo_qr_codes WHERE uuid_qr = {ph} OR id_humano = {ph}", (s, s))
    row = cur.fetchone()
    if row is not None:
        return _promo_row_to_dict(row, cols)
    return None


# M)bis PATCH /api/admin/qr/{id_or_uuid}  (inhabilitar / rehabilitar / editar tamaño)
@app.patch("/api/admin/qr/{id_or_uuid}")
def admin_qr_patch(id_or_uuid, req: AdminQrPatchReq, admin: dict = _promo_Depends(get_current_admin)):
    with get_db_conn() as conn:
        cur = conn.cursor()
        ph = "%s" if DB_ENGINE == "POSTGRES" else "?"
        qr = _promo_resolver_qr_identifier(cur, ph, id_or_uuid)
        if qr is None:
            raise HTTPException(status_code=404, detail="QR no encontrado")
        usado = qr.get("usado_registro_id") is not None
        # Actualizaciones posibles
        set_clauses = []
        params = []
        # ============ 1) HABILITAR / INHABILITAR ============
        if req.habilitado is not None:
            hab_new = bool(req.habilitado)
            hab_prev = bool(qr.get("habilitado", True)) if DB_ENGINE == "POSTGRES" else (int(qr.get("habilitado", 1)) == 1)
            if hab_new != hab_prev:
                if DB_ENGINE == "POSTGRES":
                    set_clauses.append("habilitado = %s")
                    params.append(hab_new)
                    if not hab_new:
                        set_clauses.append("inhabilitado_por_id = %s")
                        params.append(int(admin["id"]))
                        set_clauses.append("inhabilitado_at = NOW()")
                    else:
                        set_clauses.append("inhabilitado_por_id = NULL")
                        set_clauses.append("inhabilitado_at = NULL")
                else:
                    set_clauses.append("habilitado = ?")
                    params.append(1 if hab_new else 0)
                    if not hab_new:
                        set_clauses.append("inhabilitado_por_id = ?")
                        params.append(int(admin["id"]))
                        set_clauses.append("inhabilitado_at = ?")
                        params.append(datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"))
                    else:
                        set_clauses.append("inhabilitado_por_id = NULL")
                        set_clauses.append("inhabilitado_at = NULL")
        # ============ 2) TAMAÑO (solo si NO fue usado) ============
        if not usado and (req.size_px is not None or req.tamano_cm is not None or req.dpi is not None or req.unidad is not None):
            # Recalcular size_px final
            unidad = (req.unidad or qr.get("unidad") or "pixeles").lower()
            if unidad in ("cm", "centimetros", "centímetros", "centimetro", "centímetro"):
                unidad = "centimetros"
            else:
                unidad = "pixeles"
            dpi = qr.get("dpi") or 300
            if req.dpi is not None:
                dpi = int(req.dpi)
            dpi = max(72, min(1200, dpi))
            tamano_cm = qr.get("tamano_cm")
            if req.tamano_cm is not None:
                tamano_cm = float(req.tamano_cm)
            # Calcular size_px
            if req.size_px is not None:
                size_px_new = int(req.size_px)
                # Si la unidad era cm y no me pasaron tamano_cm + pasaron size_px, cambiar a pixeles modo legacy
                if tamano_cm is None:
                    unidad = "pixeles"
                    tamano_cm = None
            elif tamano_cm is not None and unidad == "centimetros":
                size_px_new = int(round((float(tamano_cm) * dpi) / 2.54))
            else:
                size_px_new = int(qr.get("size_px") or 512)
            size_px_new = max(256, min(2048, size_px_new))
            if DB_ENGINE == "POSTGRES":
                set_clauses += ["unidad = %s", "dpi = %s", "tamano_cm = %s", "size_px = %s"]
                params += [unidad, dpi, tamano_cm, size_px_new]
            else:
                set_clauses += ["unidad = ?", "dpi = ?", "tamano_cm = ?", "size_px = ?"]
                params += [unidad, dpi, tamano_cm, size_px_new]
        if not set_clauses:
            # No hay nada que actualizar
            with get_db_conn() as conn2:
                cur2 = conn2.cursor()
                qr = _promo_resolver_qr_identifier(cur2, ph, id_or_uuid) or qr
            return {"ok": True, "actualizado": False, "qr": qr}
        # ======== EJECUTAR UPDATE ========
        if DB_ENGINE == "POSTGRES":
            set_clauses.append("id = %s")
            params.append(int(qr["id"]))
            sql = f"UPDATE promo_qr_codes SET {', '.join(set_clauses[:-1])} WHERE id = %s"
            cur.execute(sql, params)
        else:
            sql = f"UPDATE promo_qr_codes SET {', '.join(set_clauses)} WHERE id = {ph}"
            params.append(int(qr["id"]))
            cur.execute(sql, params)
        conn.commit()
        # Auditoria
        _promo_insert_auditoria(int(admin["id"]), "PATCH_QR", {
            "qr_id": qr.get("id"),
            "qr_uuid": qr.get("uuid_qr"),
            "cambios_solicitados": req.model_dump(),
            "nota": req.nota,
        })
        # Devolver QR actualizado
        cur2 = conn.cursor()
        qr2 = _promo_resolver_qr_identifier(cur2, ph, id_or_uuid)
    return {"ok": True, "actualizado": True, "qr": qr2}


# M)ter DELETE /api/admin/qr/{id_or_uuid}  (eliminar QR de la base, incluso usado)
@app.delete("/api/admin/qr/{id_or_uuid}")
def admin_qr_delete(id_or_uuid, admin: dict = _promo_Depends(get_current_admin)):
    qr = None
    qr_id = None
    with get_db_conn() as conn:
        conn.autocommit = False
        try:
            cur = conn.cursor()
            ph = "%s" if DB_ENGINE == "POSTGRES" else "?"
            if DB_ENGINE == "SQLITE":
                cur.execute("BEGIN IMMEDIATE")
            qr = _promo_resolver_qr_identifier(cur, ph, id_or_uuid)
            if qr is None:
                raise HTTPException(status_code=404, detail="QR no encontrado")
            qr_id = int(qr["id"])

            # ===== INTEGRIDAD FK promo_registros.qr_id → promo_qr_codes(id) =====
            # La columna promo_registros.qr_id es NOT NULL + FOREIGN KEY REAL al QR.
            # Si el QR YA FUE USADO (hay un ganador registrado con él), NO PODEMOS BORRARLO:
            #   - PostgreSQL lanzaría error FK violation (no permite dejar references dangling)
            #   - Tampoco queremos BORRAR el historial de ganador = dato oficial del evento.
            # Caso QR USADO → HTTP 409 CONFLICT: usuario usa opcion INHABILITAR en su lugar (ya existe).
            # Caso QR SIN USAR (usado_registro_id NULL) → se puede borrar seguro (no hay FK que apunte).
            qr_usado_registro_id = qr.get("usado_registro_id")
            if qr_usado_registro_id is not None:
                # Chequeo doble por seguridad: cuento filas en promo_registros que lo referencien.
                cur.execute(
                    f"SELECT COUNT(*) FROM promo_registros WHERE qr_id = {ph}",
                    (qr_id,),
                )
                cnt_refs = int((cur.fetchone() or [0])[0] or 0)
                if cnt_refs > 0:
                    raise HTTPException(
                        status_code=409,
                        detail=(
                            "Este QR YA FUE UTILIZADO por una persona ganadora registrada (#registros "
                            f"que lo referencian: {cnt_refs}). NO se puede ELIMINAR para preservar el "
                            "historial de ganadores (integridad referencial base de datos: promo_registros.qr_id "
                            "es NOT NULL con FK a promo_qr_codes). Si lo que quieres es que nadie más lo use, "
                            "usa la opción INHABILITAR en su lugar: el QR seguirá en el historial pero cualquier "
                            "persona que lo escuche recibirá 'QR inhabilitado por el administrador' y no podrá "
                            "registrarse."
                        ),
                    )

            # === QR NO USADO: BORRADO SEGURO. No necesitamos tocar promo_registros (nunca fue referenciado). ===
            if DB_ENGINE == "POSTGRES":
                cur.execute("DELETE FROM promo_qr_codes WHERE id = %s", (qr_id,))
            else:
                cur.execute("DELETE FROM promo_qr_codes WHERE id = ?", (qr_id,))
            if cur.rowcount != 1:
                raise HTTPException(status_code=500, detail="Ninguna fila fue eliminada (QR ya no existía)")
            conn.commit()
        except HTTPException:
            try:
                conn.rollback()
            except Exception:
                pass
            raise
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            # Mensaje amigable si PostgreSQL FK salta de todos modos por algun edge
            msg_str = str(e).lower()
            if "foreignkey" in msg_str or "foreign key" in msg_str or "violates not-null" in msg_str or "qr_id" in msg_str:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "No se puede eliminar este QR: está referenciado por uno o más registros oficiales "
                        "de ganadores. Usa la opción INHABILITAR en su lugar para evitar que se vuelva a usar "
                        "sin borrar el historial."
                    ),
                )
            raise HTTPException(status_code=500, detail=f"Error delete QR: {str(e)}")
    # Auditoria FUERA del with (igual que DELETE REGISTRO) para no mezclar transacciones
    _promo_insert_auditoria(int(admin["id"]), "DELETE_QR", {
        "qr_id": qr_id,
        "qr_uuid": qr.get("uuid_qr") if qr else None,
        "id_humano": qr.get("id_humano") if qr else None,
        "usado": bool(qr.get("usado_registro_id")) if qr else False,
    })
    return {"ok": True, "eliminado": True, "qr_eliminado": qr}


# ======= HELPERS PDF QR =======

def _promo_qr_compute_frontend_base_url(request):
    """Reutiliza la misma lógica de POST /admin/qr/generar para armar la URL FRONTEND del QR.
    Devuelve string SIN slash final: "https://front.up.railway.app"
    """
    scheme = request.base_url.scheme
    host_hdr = request.headers.get("host", "")
    origin_hdr = _clean_env_str(request.headers.get("origin") or "")
    frontend_url_env = _clean_env_str(os.environ.get("FRONTEND_URL") or "", strip_slash_end=True)
    base = None
    if frontend_url_env:
        base = frontend_url_env
    elif origin_hdr:
        try:
            from urllib.parse import urlparse as _urlparse
            _p = _urlparse(origin_hdr)
            if _p.scheme and _p.netloc:
                base = f"{_p.scheme}://{_p.netloc}"
        except Exception:
            base = origin_hdr.rstrip("/")
    if not base:
        base = f"{scheme}://{host_hdr}" if host_hdr else str(request.base_url).rstrip("/")
    return base.rstrip("/")


def _promo_qr_make_pil_for_pdf(url_value, size_cm, dpi=300, size_px_fallback=512):
    """Genera una imagen PIL RGB en memoria con el QR para meterla en el PDF.
    - Si el admin especificó tamaño en cm → TAMAÑO REAL IMPRESO = tamaño_cm.
    - Fórmula: px = cm * dpi / 2.54  (1 inch = 2.54cm)
    - Si falla por algún motivo, fallback al tamaño en píxeles que tenía almacenado.
    Devuelve (pil_img_rgb, ancho_cm, alto_cm)  (ancho = alto, QR cuadrado)
    """
    import qrcode as _qrcode
    size_cm_float = None
    try:
        size_cm_float = float(size_cm) if size_cm is not None else None
    except Exception:
        size_cm_float = None
    if size_cm_float and size_cm_float > 0:
        px = int(round((size_cm_float * float(dpi or 300)) / 2.54))
        px = max(256, min(4096, px))
    else:
        try:
            px = int(size_px_fallback or 512)
        except Exception:
            px = 512
        px = max(256, min(4096, px))
    try:
        dpi_eff = max(72, min(1200, int(dpi or 300)))
    except Exception:
        dpi_eff = 300
    qr = _qrcode.QRCode(version=None, error_correction=_qrcode.constants.ERROR_CORRECT_H,
                        box_size=max(1, px // 30), border=4)
    qr.add_data(url_value)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
    img = img.resize((px, px), Image.LANCZOS if hasattr(Image, "LANCZOS") else Image.Resampling.LANCZOS)
    # 🔴 OBLIGATORIO: Guardar DPI METADATA en la imagen PIL para
    # que cuando el admin DESCARGUE el PNG individual / pegue en Word / imprima,
    # la impresora / editor use el DPI FÍSICO CORRECTO y NO reduzca 5cm a 2cm.
    # Si no se pone esto, PNG no tiene pHYs chunk y cualquier programa asume 72/96 DPI,
    # resultando en tamaños impresos MUY PEQUEÑOS.
    try:
        img.info["dpi"] = (int(dpi_eff), int(dpi_eff))
    except Exception:
        pass
    try:
        # Pillow save() metadata: llamar aquí no escribe a disco (solo setea metadata info dpi).
        img.load()
    except Exception:
        pass
    # Informar cm reales (si venian de tamano_cm usar ese; sino calcular de px/dpi)
    if size_cm_float and size_cm_float > 0:
        cm_eff = float(size_cm_float)
    else:
        cm_eff = round((float(px) * 2.54) / float(dpi_eff), 3)
    return img, cm_eff, cm_eff


class AdminQrPdfReq(BaseModel):
    """Body request para generar PDF de QRs. Cualquier combinación permitida:
    - ids: array de integer IDs (ex: recien generados ids). Si envías => ignoras filtros y traes SOLO esos.
    - OPCIONAL filtros mismos de /list (si no envías ids, trae todos los QRs que coincidan, ordenados id DESC, límite max_qrs).
    - LAYOUT: cols / filas_por_pagina / pagina_horizontal / margenes mm.
    - QRs: forzar_tamano_cm uniforme / qr_id_on_page / borde_punteado / mostrar_info_tecnica.
    - HEADER/FOOTER: incluir_fecha_titulo / incluir_header_azul / incluir_footer_legal.
    """
    ids: list[int] | None = None
    usado: bool | None = None
    habilitado: bool | None = None
    q: str | None = None
    max_qrs: int = 500
    cols: int = 2
    filas_por_pagina: int = 4
    pagina_horizontal: bool = False
    forzar_tamano_cm: float | None = None
    qr_id_on_page: bool = False  # DEFAULT FALSE por pedido user: NO mostrar código humano debajo del QR en PDF
    incluir_fecha_titulo: bool = True

    # ========= NUEVOS PARÁMETROS DE CONFIGURACIÓN AVANZADA =========
    # Visualización celdas:
    borde_punteado: bool = True   # dibujar borde punteado gris alrededor c/celda (para cortar stickers)
    mostrar_info_tecnica: bool = False  # DEFAULT FALSE por pedido user: NO mostrar info dimensiones (px/cm/dpi/INHAB) en PDF
    incluir_id_humano: bool | None = None  # Alias de qr_id_on_page (sinónimo para el front)
    id_humano_font_size_pt: float = 8.5  # tamaño fuente Helvetica-Bold ID humano debajo QR
    info_font_size_pt: float = 7.0       # tamaño fuente info técnica

    # Márgenes EN MILÍMETROS (mm) para personalizar hoja completa (float decimal permitido):
    margen_mm_izq: float = 15.0
    margen_mm_der: float = 15.0
    margen_mm_sup: float = 22.0
    margen_mm_inf: float = 16.0
    gap_mm_entre_celdas: float = 4.0

    # Incluir header / footer completos (si False => layout SIN marcas, solo QRs + ID minimalista para imprenta profesional):
    incluir_header_azul: bool = True
    incluir_footer_legal: bool = True
    # Color header (hex #XXXXXX default azul marca ILV):
    color_header_hex: str = "#0033A0"
    # Título customizado arriba (si se envía reemplaza el default):
    titulo_pdf: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _alias_incluir_id_humano(cls, data: Any) -> Any:
        """Sinónimo: `incluir_id_humano` es alias de `qr_id_on_page` para que el front mande nombre
        más intuitivo. Si se envía cualquiera de los 2, actualiza el otro para mantener consistencia."""
        if not isinstance(data, dict):
            return data
        d = dict(data)
        a = d.get("qr_id_on_page")
        b = d.get("incluir_id_humano")
        if b is not None and a is None:
            d["qr_id_on_page"] = bool(b)
        if a is not None and b is None:
            d["incluir_id_humano"] = bool(a)
        return d


def _promo_qr_fetch_ids_or_filtered(req: AdminQrPdfReq):
    """Trae QRs de la DB según IDs o filtros (mismo where de list endpoint).
    Devuelve lista de dicts ordenados según req.ids (si existe) o id DESC.
    """
    ph = "%s" if DB_ENGINE == "POSTGRES" else "?"
    cols = [
        "id", "uuid_qr", "id_humano", "size_px", "tamano_cm", "dpi", "unidad",
        "formato", "habilitado", "usado_registro_id", "creado_admin_id", "created_at",
    ]
    cols_str = ", ".join(cols)
    with get_db_conn() as conn:
        cur = conn.cursor()
        if req.ids:
            ids_ok = list({int(x) for x in req.ids if x is not None})
            if not ids_ok:
                return []
            phs = ",".join([ph] * len(ids_ok))
            where_extra = f" WHERE id IN ({phs})"
            sql = f"SELECT {cols_str} FROM promo_qr_codes{where_extra}"
            cur.execute(sql, tuple(ids_ok) if DB_ENGINE == "POSTGRES" else ids_ok)
            rows_raw = _promo_fetch_all_to_dicts(cur, cols)
            # Reordenar con el orden inicial del usuario (ids array)
            pos = {int(r["id"]): idx for idx, r in enumerate(rows_raw)}
            rows_raw.sort(key=lambda r: pos.get(int(r["id"]), 999_999_999))
            items = rows_raw
        else:
            where = []
            params = []
            if req.usado is not None:
                where.append("usado_registro_id IS NOT NULL" if req.usado else "usado_registro_id IS NULL")
            if req.habilitado is not None:
                if DB_ENGINE == "POSTGRES":
                    where.append(f"habilitado = {ph}")
                    params.append(bool(req.habilitado))
                else:
                    where.append(f"habilitado = {ph}")
                    params.append(1 if req.habilitado else 0)
            if req.q:
                q = str(req.q).strip()
                if q:
                    where.append(f"(uuid_qr LIKE {ph} OR id_humano LIKE {ph} OR COALESCE(CAST(id AS TEXT), '') LIKE {ph})")
                    like = f"%{q}%"
                    params += [like, like, like]
            where_sql = f" WHERE {' AND '.join(where)}" if where else ""
            cur.execute(f"SELECT COUNT(*) FROM promo_qr_codes{where_sql}", tuple(params) if DB_ENGINE == "POSTGRES" else params)
            try:
                total = int(cur.fetchone()[0] or 0)
            except Exception:
                total = 0
            limit_qr = max(1, min(10000, int(req.max_qrs or 500)))
            qp = list(params) + [limit_qr]
            sql = f"SELECT {cols_str} FROM promo_qr_codes{where_sql} ORDER BY id DESC LIMIT {ph}"
            cur.execute(sql, tuple(qp) if DB_ENGINE == "POSTGRES" else qp)
            items = _promo_fetch_all_to_dicts(cur, cols)
            _ = total
    # Normalizar tipos numericos / booleano
    for it in items:
        if DB_ENGINE == "POSTGRES":
            it["habilitado"] = bool(it.get("habilitado", True))
        else:
            raw = it.get("habilitado")
            it["habilitado"] = True if raw is None else (int(raw) == 1)
        for kk in ("tamano_cm",):
            if it.get(kk) is not None:
                try: it[kk] = float(it[kk])
                except Exception: it[kk] = None
        for kk in ("dpi", "size_px"):
            if it.get(kk) is not None:
                try: it[kk] = int(it[kk])
                except Exception: it[kk] = None
    return items


# M)pdf POST /api/admin/qr/pdf — Genera PDF con QRs (recién generados o historial filtrado)
@app.post("/api/admin/qr/pdf")
def admin_qr_pdf(req: AdminQrPdfReq, admin: dict = _promo_Depends(get_current_admin), request: Request = None):
    # 1) Traer QRs
    items = _promo_qr_fetch_ids_or_filtered(req)
    if not items:
        raise HTTPException(status_code=400, detail="No se encontraron QRs para este criterio. Genera códigos primero o cambia los filtros.")

    # 2) Layout y tamaños de página
    from reportlab.lib.pagesizes import LETTER, landscape as _landscape_fn
    from reportlab.pdfgen import canvas as _pdfcanvas
    from reportlab.lib.utils import ImageReader as _ImageReader
    from reportlab.lib import colors as _colors

    # Carta (Colombia) por defecto: LETTER en points 612×792
    page_size = LETTER
    cols = max(1, min(6, int(req.cols or 3)))
    rows = max(1, min(12, int(req.filas_por_pagina or 7)))
    if req.pagina_horizontal:
        page_size = _landscape_fn(page_size)

    page_w_pt, page_h_pt = page_size
    mm_pt = 2.83464567  # 1mm = 2.8346 pt aprox

    # ===== NUEVOS MÁRGENES CONFIGURABLES POR EL ADMIN (en mm) =====
    margen_izq_mm = max(2.0, min(60.0, float(req.margen_mm_izq or 15.0)))
    margen_der_mm = max(2.0, min(60.0, float(req.margen_mm_der or 15.0)))
    margen_sup_mm = max(2.0, min(80.0, float(req.margen_mm_sup or 22.0)))
    margen_inf_mm = max(2.0, min(60.0, float(req.margen_mm_inf or 16.0)))
    gap_mm = max(0.0, min(20.0, float(req.gap_mm_entre_celdas or 4.0)))

    # Si NO hay header_azul, reducimos el margen superior automático a un valor más pequeño
    # para aprovechar espacio (excepto si admin puso un margen custom diferente):
    header_visible = bool(req.incluir_header_azul)
    footer_visible = bool(req.incluir_footer_legal)
    if not header_visible and float(req.margen_mm_sup or 22.0) == 22.0:
        margen_sup_mm = 10.0  # default 10mm cuando no hay header
    if not footer_visible and float(req.margen_mm_inf or 16.0) == 16.0:
        margen_inf_mm = 8.0    # default 8mm cuando no hay footer legal

    margen_l_pt = margen_izq_mm * mm_pt
    margen_r_pt = margen_der_mm * mm_pt
    margen_t_pt = margen_sup_mm * mm_pt
    margen_b_pt = margen_inf_mm * mm_pt
    gap_pt = gap_mm * mm_pt

    area_util_w = page_w_pt - margen_l_pt - margen_r_pt
    area_util_h = page_h_pt - margen_t_pt - margen_b_pt

    cell_w_pt = max(1.0, (area_util_w - (max(0, cols - 1) * gap_pt)) / float(cols))
    cell_h_pt = max(1.0, (area_util_h - (max(0, rows - 1) * gap_pt)) / float(rows))

    # Si el admin pidió forzar tamaño uniforme: limitamos el tamaño QR a la celda
    forzar_cm = None
    if req.forzar_tamano_cm and float(req.forzar_tamano_cm) > 0:
        try:
            forzar_cm = float(req.forzar_tamano_cm)
            if forzar_cm <= 0:
                forzar_cm = None
        except Exception:
            forzar_cm = None

    # Opciones visuales nuevas:
    dibujar_borde_punteado = bool(req.borde_punteado)
    mostrar_id_humano = bool(req.qr_id_on_page)
    mostrar_info_tam = bool(req.mostrar_info_tecnica) and mostrar_id_humano
    id_font_sz = max(5.0, min(16.0, float(req.id_humano_font_size_pt or 8.5)))
    info_font_sz = max(4.0, min(14.0, float(req.info_font_size_pt or 7.0)))
    color_header = None
    try:
        color_header = _colors.HexColor(str(req.color_header_hex or "#0033A0").strip() or "#0033A0")
    except Exception:
        color_header = _colors.HexColor("#0033A0")
    titulo_custom = (str(req.titulo_pdf).strip() if req.titulo_pdf else None) or None

    # Crear PDF en memoria
    import io as _io
    buf = _io.BytesIO()
    c = _pdfcanvas.Canvas(buf, pagesize=page_size)
    c.setTitle(titulo_custom or "Códigos QR — Fiesta Aguardiente Blanco del Valle")
    c.setAuthor("ILV 1921 · Admin")
    c.setSubject("QRs promoción Fiesta")
    c.setCreator("Aguardiente Blanco del Valle - FastAPI reportlab")

    # Calcular URLs frontend base (MISMA regla que generación QR)
    front_base = _promo_qr_compute_frontend_base_url(request or Request({"type": "http"}))

    # Header/footer callback y pagina en canvas (reportlab usa drawOn callback pero más fácil: hacemos bucle manual)
    from datetime import datetime as _dt, timezone as _tz
    tz_co = None
    try:
        from zoneinfo import ZoneInfo as _ZI
        tz_co = _ZI("America/Bogota")
    except Exception:
        tz_co = _tz.utc
    ahora = _dt.now(tz_co or _tz.utc)

    def _escribir_header_y_footer(cv, pnum, total_paginas_estimado=None):
        # HEADER zona superior (dentro de los márgenes)
        cv.saveState()
        if header_visible:
            cv.setFillColor(color_header or _colors.HexColor("#0033A0"))
            cv.rect(0, page_h_pt - (10 * mm_pt), page_w_pt, (10 * mm_pt), stroke=0, fill=1)
            cv.setFillColor(_colors.white)
            cv.setFont("Helvetica-Bold", 13)
            cv.drawString(margen_l_pt, page_h_pt - (7.2 * mm_pt), "ILV 1921 — Aguardiente Blanco del Valle")
            cv.setFont("Helvetica", 9)
            cv.drawRightString(page_w_pt - margen_r_pt, page_h_pt - (7.2 * mm_pt),
                               (f"Página {pnum}" + (f" / {total_paginas_estimado}" if total_paginas_estimado else "")))
            # Subtítulo antes iniciar grilla
            if req.incluir_fecha_titulo:
                cv.setFillColor(_colors.HexColor("#0f172a"))
                cv.setFont("Helvetica-Bold", 11)
                cv.drawString(margen_l_pt, page_h_pt - (15.5 * mm_pt),
                              titulo_custom or "Códigos QR — Fiesta · ¡Va con todo!")
                cv.setFillColor(_colors.HexColor("#475569"))
                cv.setFont("Helvetica", 8.5)
                cv.drawRightString(page_w_pt - margen_r_pt, page_h_pt - (15.5 * mm_pt),
                                   f"Generado el {ahora.strftime('%d/%m/%Y %I:%M %p')} (Colombia) · Admin #{int(admin.get('id') or 0)}")
        # FOOTER legal
        if footer_visible:
            cv.setFillColor(_colors.HexColor("#f1f5f9"))
            cv.rect(0, 0, page_w_pt, (10 * mm_pt), stroke=0, fill=1)
            cv.setStrokeColor(_colors.HexColor("#cbd5e1"))
            cv.setLineWidth(0.6)
            cv.line(0, 10 * mm_pt, page_w_pt, 10 * mm_pt)
            cv.setFillColor(_colors.HexColor("#475569"))
            cv.setFont("Helvetica", 7.5)
            texto_legal_izq = ("Uso exclusivo evento Fiesta Aguardiente Blanco del Valle · QR 1 solo uso. "
                               "Cualquier alteración, distribución o comercialización es prohibida.")
            cv.drawString(margen_l_pt, 4.0 * mm_pt, texto_legal_izq)
            cv.drawRightString(page_w_pt - margen_r_pt, 4.0 * mm_pt, f"{len(items)} QR(s) · {cols}×{rows}")
        cv.restoreState()

    # Estimación de páginas (se actualiza al dibujar, al final se hace un show pages count pero no importa)
    per_page = cols * rows
    total_pag_estimado = max(1, (len(items) + per_page - 1) // per_page)

    # ===== WARNING COLLECTOR para avisar al admin cuántos QRs se redujeron de tamaño =====
    # Root cause user: "digo 5cm y me sale 2cm" → rows=7 y cols=3 hacen que cell_h ~3cm < 5cm,
    # el código reducía SILENCIOSAMENTE sin avisar. Ahora se cuenta y se incluye en response headers JSON.
    _warnings_collector = {
        "count_reducidos": 0,
        "cm_target_min": None,
        "cm_target_max": None,
        "cm_efectivo_min": None,
        "cm_efectivo_max": None,
        "cell_w_cm": round((cell_w_pt / mm_pt) / 10.0, 2),
        "cell_h_cm": round((cell_h_pt / mm_pt) / 10.0, 2),
        "cols": cols,
        "rows": rows,
    }
    def _wc_registrar(target, efectivo, reducido_bool):
        try:
            if reducido_bool:
                _warnings_collector["count_reducidos"] += 1
            if target is not None:
                t = float(target)
                if _warnings_collector["cm_target_min"] is None or t < _warnings_collector["cm_target_min"]:
                    _warnings_collector["cm_target_min"] = t
                if _warnings_collector["cm_target_max"] is None or t > _warnings_collector["cm_target_max"]:
                    _warnings_collector["cm_target_max"] = t
            if efectivo is not None:
                e = float(efectivo)
                if _warnings_collector["cm_efectivo_min"] is None or e < _warnings_collector["cm_efectivo_min"]:
                    _warnings_collector["cm_efectivo_min"] = e
                if _warnings_collector["cm_efectivo_max"] is None or e > _warnings_collector["cm_efectivo_max"]:
                    _warnings_collector["cm_efectivo_max"] = e
        except Exception:
            pass

    item_idx = 0
    n_items = len(items)
    pil_cache = {}  # id_qr -> (pil, cm_w, cm_h) para no renderizar 2 veces el mismo si hubiera dup
    while item_idx < n_items:
        # Inicio página
        _escribir_header_y_footer(c, ((item_idx // per_page) + 1), total_pag_estimado)
        # Bucle por celdas dentro de la página
        for pos_in_pagina in range(per_page):
            if item_idx >= n_items:
                break
            qr = items[item_idx]
            qr_id = int(qr["id"])
            col = pos_in_pagina % cols
            fila = pos_in_pagina // cols
            # Calcular esquina inferior-izquierda de la CELDA (reportlab origen abajo-izq)
            # El área útil Y empieza DESPUES del header
            area_y0 = page_h_pt - margen_t_pt  # Y SUPERIOR área util
            cell_x0 = margen_l_pt + (col * (cell_w_pt + gap_pt))
            # Cell top (superior): area_y0 - (fila * (cell_h_pt + gap_pt))
            cell_y_top = area_y0 - (fila * (cell_h_pt + gap_pt))
            cell_y0 = cell_y_top - cell_h_pt
            # Si forzamos tamaño cm o no, calculamos el cuadro del QR DENTRO DE LA CELDA
            # (dejamos espacio vertical para ID humano abajo)
            _hay_etiqueta_id = bool(mostrar_id_humano)
            _hay_etiqueta_info = bool(mostrar_info_tam)
            if _hay_etiqueta_id and _hay_etiqueta_info:
                id_etiqueta_h_pt = 14.0
            elif _hay_etiqueta_id:
                id_etiqueta_h_pt = 8.0
            elif _hay_etiqueta_info:
                id_etiqueta_h_pt = 7.0
            else:
                id_etiqueta_h_pt = 0.0
            area_qr_disponible_w = cell_w_pt
            area_qr_disponible_h = cell_h_pt - (id_etiqueta_h_pt + 2 * mm_pt)
            max_side_pt = max(20.0, min(area_qr_disponible_w, area_qr_disponible_h))
            # 1) Calcular cm real que vamos a dibujar, si forzar_cm o tamano_cm en QR
            cm_target = None
            if forzar_cm:
                cm_target = float(forzar_cm)
            elif qr.get("tamano_cm"):
                cm_target = float(qr["tamano_cm"])
            # FALLBACK SMART si no hay tamano_cm (QRs antiguos generados antes del SHA e2d3c64):
            #   cm = (size_px * 2.54) / dpi
            if (cm_target is None or cm_target <= 0) and qr.get("size_px") and qr.get("dpi"):
                try:
                    _sp = int(qr["size_px"])
                    _dp = int(qr["dpi"])
                    if _sp > 0 and _dp > 0:
                        cm_target = round((_sp * 2.54) / float(_dp), 3)
                except Exception:
                    cm_target = None
            # Si cm_target sale de la celda (muy grande) → reducir al máximo disponible,
            # pero además registrar en warnings para avisarle al admin que sus QRs se encogieron.
            qr_draw_pt = None
            dpi_eff = int(qr.get("dpi") or 300)
            qr_draw_from_cm_pt = None
            reducido = False
            if cm_target and cm_target > 0:
                qr_draw_from_cm_pt = (cm_target * 10.0) * mm_pt  # cm * 10 = mm * mm_pt = pt
                qr_draw_pt = qr_draw_from_cm_pt
                _cm_target_original = float(cm_target)
                if qr_draw_pt > max_side_pt:
                    qr_draw_pt = max_side_pt
                    # actualizar cm_target al reducido (para el texto info)
                    cm_target = round((qr_draw_pt / mm_pt) / 10.0, 2)
                    reducido = True
                _wc_registrar(_cm_target_original, cm_target, reducido)
            else:
                qr_draw_pt = max_side_pt
                cm_target = round((qr_draw_pt / mm_pt) / 10.0, 2)
                _wc_registrar(cm_target, cm_target, False)
            # Center QR horizontal + vertical en el espacio superior (antes de la etiqueta)
            center_x_cell = cell_x0 + (cell_w_pt / 2.0)
            # Area QR = desde (cell_y0 + id_etiqueta_h_pt + 1mm) hasta (cell_y0 + cell_h_pt - 1mm)
            qr_area_y_min = cell_y0 + id_etiqueta_h_pt + (1.0 * mm_pt)
            qr_area_y_max = cell_y0 + cell_h_pt - (1.0 * mm_pt)
            center_y_qr = ((qr_area_y_min + qr_area_y_max) / 2.0)
            qr_x0 = center_x_cell - (qr_draw_pt / 2.0)
            qr_y0 = center_y_qr - (qr_draw_pt / 2.0)
            # Generar PIL imagen del QR (cacheado)
            if qr_id not in pil_cache:
                url_qr = f"{front_base}/ganador?qr={qr.get('uuid_qr') or ''}"
                pil_img, cmw, cmh = _promo_qr_make_pil_for_pdf(
                    url_qr,
                    size_cm=cm_target,
                    dpi=dpi_eff,
                    size_px_fallback=int(qr.get("size_px") or 512),
                )
                pil_cache[qr_id] = (pil_img, cmw, cmh)
            else:
                pil_img, cmw, cmh = pil_cache[qr_id]
            # Dibujar imagen en el PDF
            try:
                c.drawImage(_ImageReader(pil_img),
                            qr_x0, qr_y0,
                            width=qr_draw_pt, height=qr_draw_pt,
                            preserveAspectRatio=True, anchor='c', mask='auto')
            except Exception:
                # Fallback simple: dibujar placeholder gris y texto
                c.setFillColor(_colors.HexColor("#e2e8f0"))
                c.rect(qr_x0, qr_y0, qr_draw_pt, qr_draw_pt, stroke=1, fill=1)
                c.setFillColor(_colors.HexColor("#334155"))
                c.setFont("Helvetica-Bold", 8)
                c.drawCentredString(center_x_cell, center_y_qr, "QR")
            # Borde ligero gris alrededor (cortar stickers a mano) — NUEVO configurable
            if dibujar_borde_punteado:
                c.setStrokeColor(_colors.HexColor("#cbd5e1"))
                c.setLineWidth(0.4)
                c.setDash(1, 1.2)
                c.rect(cell_x0 + 0.3 * mm_pt, cell_y0 + 0.3 * mm_pt,
                       cell_w_pt - 0.6 * mm_pt, cell_h_pt - 0.6 * mm_pt,
                       stroke=1, fill=0)
                c.setDash()
            # Etiqueta debajo: ID humano + tamaño (AHORA configurable show ID + info TÉCNICA de forma INDEPENDIENTE)
            if mostrar_id_humano or mostrar_info_tam:
                # LINEA 1 - ID HUMANO (si se encendió):
                linea1_y = cell_y0 + (max(2.0, id_etiqueta_h_pt) - 1.2)
                if mostrar_id_humano:
                    c.setFillColor(_colors.HexColor("#0f172a"))
                    c.setFont("Helvetica-Bold", id_font_sz)
                    idh = str(qr.get("id_humano") or f"ID-{qr['id']}")
                    # si idh muy largo achicamos fuente (dentro del límite):
                    if len(idh) > 14 and id_font_sz > 7:
                        c.setFont("Helvetica-Bold", max(6.0, id_font_sz - 1.5))
                    c.drawCentredString(center_x_cell, linea1_y, idh)
                # LINEA 2 - información del tamaño (pequeño gris, configurable mostrar)
                if mostrar_info_tam:
                    c.setFillColor(_colors.HexColor("#64748b"))
                    c.setFont("Helvetica", info_font_sz)
                    sz_info = []
                    if qr.get("size_px"):
                        sz_info.append(f"{int(qr['size_px'])}px")
                    if cm_target:
                        sz_info.append(f"{cm_target:g}cm")
                    if qr.get("dpi"):
                        sz_info.append(f"{int(qr['dpi'])}dpi")
                    if qr.get("habilitado") is False:
                        sz_info.append("INHAB")
                    info_txt = " · ".join(sz_info) or f"QR #{qr['id']}"
                    # Posición Y: si había ID, va 1 línea DEBAJO; si no, en la posición única
                    if mostrar_id_humano:
                        info_linea_2_y = linea1_y - (info_font_sz + 1.5)
                    else:
                        info_linea_2_y = linea1_y
                    c.drawCentredString(center_x_cell, info_linea_2_y, info_txt)
            item_idx += 1
        # Fin página
        c.showPage()
    c.save()
    pdf_bytes = buf.getvalue()
    buf.seek(0)
    # Auditoria + warnings de reducción de tamaño QRs (para avisarle al admin por headers)
    wc_info = {}
    try:
        import json as _json_mod
        wc_info = dict(_warnings_collector or {})
        _promo_insert_auditoria(int(admin["id"]), "EXPORT_PDF_QR", {
            "qrs_count": len(items),
            "ids_sample": [int(x["id"]) for x in items[:20]],
            "paginas_estimadas": total_pag_estimado,
            "cols": cols,
            "filas": rows,
            "forzar_tamano_cm": forzar_cm,
            "warnings_reducidos": int(wc_info.get("count_reducidos") or 0),
            "cell_w_cm": wc_info.get("cell_w_cm"),
            "cell_h_cm": wc_info.get("cell_h_cm"),
        })
    except Exception:
        pass
    from fastapi.responses import Response
    filename = f"QRs_Fiesta_ABV_{ahora.strftime('%Y%m%d_%H%M%S')}.pdf"
    # Headers obligatorios PDF + warnings al front para toast user si hay reducción de tamaño:
    #   X-QR-Cell-W-cm / X-QR-Cell-H-cm: tamaño REAL util de celda
    #   X-QRs-Reducidos-Count: cuántos de los QRs pedidos fueron MENORES que el size cm declarado
    #   (si > 0 el front avisa "tus QRs de 5cm se redujeron a 3.1cm porque rows=7, reduce a rows=4 cols=2")
    headers = {
        "Content-Disposition": f'attachment; filename="{filename}"',
        "Content-Length": str(len(pdf_bytes)),
        "Cache-Control": "no-store",
        "Pragma": "no-cache",
        "X-QR-Cell-W-cm": str(wc_info.get("cell_w_cm", "")),
        "X-QR-Cell-H-cm": str(wc_info.get("cell_h_cm", "")),
        "X-QRs-Reducidos-Count": str(int(wc_info.get("count_reducidos") or 0)),
        "X-QR-Cm-Target-Min": str(wc_info.get("cm_target_min", "")),
        "X-QR-Cm-Target-Max": str(wc_info.get("cm_target_max", "")),
        "X-QR-Cm-Efectivo-Min": str(wc_info.get("cm_efectivo_min", "")),
        "X-QR-Cm-Efectivo-Max": str(wc_info.get("cm_efectivo_max", "")),
        "X-QR-Layout-Cols": str(wc_info.get("cols", cols)),
        "X-QR-Layout-Rows": str(wc_info.get("rows", rows)),
    }
    return Response(content=pdf_bytes, media_type="application/pdf", headers=headers)


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

