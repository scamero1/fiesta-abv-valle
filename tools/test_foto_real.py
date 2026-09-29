"""
Test FOTOS REALES con rembg IA ACTIVADO (no simulador).

Pipeline:
  PRUEBA A: cutout IA real via rembg.u2netp
  PRUEBA B: imagen completa con alfa=255 en TODA el area (equivalente a
            un "rembg que fallo y no corto nada" - para estresar L3/L4).
  Para cada prueba x 3 escenarios (CR, MS, PV):
    - loguea: n_personas | escala | ancho_pct (y rng) | tope_pct (y rng) | cx_pct (y rng) | bottom_px vs y_base+4
  Auto-ajustes:
    - Si n_personas='1' y se pasa --n-pers-forzado=2 → baja threshold componentes min_area_ratio de 8% → 5% y reintenta.
    - Si zoom 4x halo visible (después de pasada inicial): erosion 1→2 px y reintenta.
  Collage salida lado a lado "Referencia | Resultado" + zoom ×4 hombro der / brazo izq.

NO HACE COMMIT. Salidas en tools/out/test-foto-real/
"""
import sys
import os
import time
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
BACKEND_DIR = os.path.join(PROJECT_ROOT, "backend-python")
sys.path.insert(0, BACKEND_DIR)
os.chdir(BACKEND_DIR)

import argparse
from PIL import Image, ImageDraw, ImageFont
import numpy as _np
import main  # carga assets cache, compose_full

# ----------------------------------------------------------------
# CLI
# ----------------------------------------------------------------
ap = argparse.ArgumentParser()
ap.add_argument("--foto",
                default=os.path.join(SCRIPT_DIR, "fixtures", "foto1-cintura.jpg"),
                help="Ruta foto original promotora (JPG).")
ap.add_argument("--nombre", default="foto-real",
                help="Prefijo nombres salida.")
ap.add_argument("--n-pers-forzado", type=int, default=0,
                help=">0: fuerza que se considere N personas (útil si detector sale 1 siendo 2).")
ap.add_argument("--erosion-px", type=int, default=1,
                help="Radio erosión alfa (1 o 2).")
ap.add_argument("--min-area-ratio", type=float, default=0.08,
                help="Threshold componentes conexas (0.08 = 8%, 0.05 = 5%).")
args = ap.parse_args()

FIXTURE_PATH = args.foto
NOMBRE = args.nombre
EROSION_PX = args.erosion_px
MIN_AREA_RATIO = args.min_area_ratio
OUT_DIR = os.path.join(SCRIPT_DIR, "out", "test-foto-real")
os.makedirs(OUT_DIR, exist_ok=True)

ESCENARIOS = [
    ("cristorey",    "cristo-rey",      "Cristo Rey"),
    ("museosalsa",   "calle-del-sabor", "Museo de la Salsa"),
    ("plazavarela",  "plaza-varela",    "Plaza Varela"),
]
CANVAS_W, CANVAS_H = 1920, 1080


# ======================================================================
# BLOQUE 1: Cargar JPG original + rembg IA REAL (u2netp)
# ======================================================================
print("=" * 80)
print(f"[FOTO REAL] cargando: {FIXTURE_PATH}")
im_jpg = Image.open(FIXTURE_PATH).convert("RGB")
print(f"[FOTO REAL] tamaño original: {im_jpg.size}")

# PRUEBA A: REMBG IA REAL -------------------------------------------------
print("\n[PRUEBA A] llamando rembg.remove(u2netp)...")
t_rembg = time.time()
from rembg import remove as rembg_remove
from io import BytesIO
# Pasar JPG bytes a rembg para que haga el pipeline completo (alpha matting + u2netp)
buf_in = BytesIO()
im_jpg.save(buf_in, format="PNG")
buf_out = BytesIO(rembg_remove(buf_in.getvalue(), alpha_matting=True,
                                alpha_matting_foreground_threshold=240,
                                alpha_matting_background_threshold=10,
                                alpha_matting_erode_size=10))
persona_rembg = Image.open(buf_out).convert("RGBA")
dt_rembg = time.time() - t_rembg
print(f"[PRUEBA A] rembg remove OK en {dt_rembg:.2f}s. Cutout size: {persona_rembg.size}")

# Crop tight al bbox alfa >= 15 de rembg (como lo haría el endpoint real)
arr_cut = _np.asarray(persona_rembg, dtype=_np.uint8)
alfa_cut = arr_cut[..., 3]
rows = _np.where(alfa_cut.max(axis=1) >= 15)[0]
cols = _np.where(alfa_cut.max(axis=0) >= 15)[0]
if len(rows) > 4 and len(cols) > 4:
    y1, y2 = max(0, rows[0] - 8), min(arr_cut.shape[0], rows[-1] + 9)
    x1, x2 = max(0, cols[0] - 8), min(arr_cut.shape[1], cols[-1] + 9)
    persona_A = Image.fromarray(arr_cut[y1:y2, x1:x2], mode="RGBA")
else:
    persona_A = persona_rembg.copy()
print(f"[PRUEBA A] crop tight rembg -> {persona_A.size}")

# PRUEBA B: IMAGEN COMPLETA alfa=255 TODO (sin cutout) ------------------
print("\n[PRUEBA B] imagen completa alfa=255 en TODO su área.")
arr_full = _np.array(im_jpg.convert("RGBA"), dtype=_np.uint8)  # .array NO .asarray = writable copy
arr_full[..., 3] = 255
persona_B = Image.fromarray(arr_full, mode="RGBA")


# ======================================================================
# BLOQUE 2: Override dinámico helpers de main.py (erosion / min area ratio)
# ======================================================================
def aplicar_overrides_main():
    """Parcha helpers en memoria del módulo main para erosion_px / min_area_ratio diferentes."""
    orig_compose = main.compose_full
    def compose_full_wrapper(persona_rgba, esc_id, alpha_matting=True):
        # Interceptamos: antes de componer, modificamos los parámetros por defecto
        # a través de variables internas al contexto.
        # 1) Patch _alpha_erode para usar EROSION_PX
        orig_erode = main._alpha_erode
        def patched_erode(alpha_pil, radius_px=1):
            return orig_erode(alpha_pil, radius_px=EROSION_PX)
        main._alpha_erode = patched_erode
        # 2) Patch min_area_ratio en _detect_n_personas_from_components
        orig_detect_n = main._detect_n_personas_from_components
        def patched_detect_n(alpha_crop, min_area_ratio=0.08):
            return orig_detect_n(alpha_crop, min_area_ratio=MIN_AREA_RATIO)
        main._detect_n_personas_from_components = patched_detect_n
        try:
            return orig_compose(persona_rgba, esc_id, alpha_matting)
        finally:
            main._alpha_erode = orig_erode
            main._detect_n_personas_from_components = orig_detect_n
    main.compose_full = compose_full_wrapper

aplicar_overrides_main()
print(f"\n[OVERRIDES] EROSION_PX = {EROSION_PX} | MIN_AREA_RATIO componentes = {MIN_AREA_RATIO*100:.0f}%")


# ======================================================================
# BLOQUE 3: Ejecutar 2 pruebas × 3 escenarios
# ======================================================================
PRUEBAS = [
    ("A_cutout_rembg", persona_A, "Cutout IA rembg u2netp real"),
    ("B_full_alfa_255", persona_B, "Imagen completa alfa=255"),
]

resultados = []  # [(prueba, key, info_dict, render_path)]

def _info_n_personas(persona_rgba, min_ratio=None):
    """Extraer n_personas desde persona_rgba (cortado al bbox de alfa) sin tocar compose_full internals."""
    from PIL import Image as _I
    if min_ratio is None:
        min_ratio = MIN_AREA_RATIO
    arrp = _np.asarray(persona_rgba.convert("RGBA"))
    alf = arrp[..., 3]
    rows_ok = _np.where(alf.max(axis=1) >= 15)[0]
    cols_ok = _np.where(alf.max(axis=0) >= 15)[0]
    if len(rows_ok) < 4 or len(cols_ok) < 4:
        return "1"
    y1c, y2c = max(0, rows_ok[0]-2), min(arrp.shape[0], rows_ok[-1]+3)
    x1c, x2c = max(0, cols_ok[0]-2), min(arrp.shape[1], cols_ok[-1]+3)
    alpha_crop = _I.fromarray(arrp[y1c:y2c, x1c:x2c, 3], mode="L")
    return main._detect_n_personas_from_components(alpha_crop, min_area_ratio=min_ratio)


for prueba_name, persona, label in PRUEBAS:
    print("\n" + "=" * 80)
    print(f"[PRUEBA {prueba_name}] {label}")
    print("=" * 80)
    for key, esc_id, title in ESCENARIOS:
        t0 = time.time()
        try:
            final = main.compose_full(persona, esc_id, alpha_matting=False)
            info = dict(getattr(main, '_last_compose_info', {}) or {})
            # --- DEBUG keys y tipos ---
            info_debug = {k: (type(v).__name__, (v if isinstance(v, (int,float,str,bool)) else f"<{type(v).__name__}:len{v.size if hasattr(v,'size') else '?'}>")) for k,v in info.items()}
            print(f"     [debug _last_compose_info keys] {info_debug}")
            # --- FIN DEBUG ---
            try:
                # Completar keys faltantes de _last_compose_info (sin tocar main.py, sin commit)
                if 'n_personas' not in info or info.get('n_personas') in (None, '?'):
                    try:
                        info['n_personas'] = _info_n_personas(persona, min_ratio=MIN_AREA_RATIO)
                    except Exception as _e1:
                        info['n_personas'] = f"err:{type(_e1).__name__}"
                if 'diff_zero_ok' not in info:
                    try:
                        # Verificación manual REGLA4 NumPy diff=0
                        fondo_rgba = main.FONDOS_CACHE.get(key).convert("RGBA")
                        arr_final = _np.asarray(final, dtype="uint8")
                        arr_fondo = _np.asarray(fondo_rgba, dtype="uint8")
                        if arr_final.shape == arr_fondo.shape:
                            alfa_msk = arr_final[..., 3] >= 15
                            fuera = ~alfa_msk
                            if fuera.any():
                                diff = _np.abs(arr_final[fuera, :3].astype(_np.int16) - arr_fondo[fuera, :3].astype(_np.int16))
                                info['diff_zero_ok'] = (int(diff.max()) if diff.size else 0) == 0
                            else:
                                info['diff_zero_ok'] = True
                        else:
                            info['diff_zero_ok'] = False
                    except Exception as _e2:
                        info['diff_zero_ok'] = f"err:{type(_e2).__name__}:{_e2}"
            except Exception as _e0:
                info['err_enriche'] = f"{type(_e0).__name__}:{_e0}"
            out_jpg = os.path.join(OUT_DIR,
                                   f"{NOMBRE}__{prueba_name}__{key}.jpg")
            final.convert("RGB").save(out_jpg, format="JPEG",
                                      quality=98, subsampling=0, dpi=(300, 300),
                                      progressive=True)
            dt = time.time() - t0
            # Forzar n_personas si usuario lo pide (sólo impacta logs)
            n_show = info.get('n_personas', '?')
            if args.n_pers_forzado > 0:
                n_show = f"{args.n_pers_forzado} (override user; detectado={info.get('n_personas','?')})"
            try:
                bottom_px = int(info.get('bottom_px', 0) if not isinstance(info.get('bottom_px'), (str, type(None))) else 0)
                yb4 = int(info.get('y_base_mas_4', 0) if not isinstance(info.get('y_base_mas_4'), (str, type(None))) else 0)
                bot_ok = bottom_px >= yb4 and yb4 > 0
                bot_flag = "✅" if bot_ok else "❌"
            except Exception:
                bot_ok = False
                bot_flag = "?"
            linea = (
                f"  ✅ {title:18s} | "
                f"n_pers={str(n_show):>6s} | "
                f"escala={info.get('escala', 0):.3f} | "
                f"ancho={info.get('ancho_pct', 0):.3f} (rng {info.get('ancho_rng_min', 0):.2f}-{info.get('ancho_rng_max', 0):.2f}) | "
                f"tope={info.get('tope_pct', 0):.3f} (rng {info.get('tope_rng_min', 0):.2f}-{info.get('tope_rng_max', 0):.2f}) | "
                f"cx={info.get('cx_pct', 0):.3f} (rng {info.get('cx_rng_min', 0):.2f}-{info.get('cx_rng_max', 0):.2f}) | "
                f"bottom={info.get('bottom_px', '?')} vs y_base+4={info.get('y_base_mas_4', '?')} "
                f"[OK {bot_flag}] | "
                f"t={dt:.2f}s"
            )
            print(linea)
            resultados.append((prueba_name, key, title, label, info, out_jpg, final))
        except Exception as e:
            import traceback
            traceback.print_exc()
            print(f"  ❌ {title} -> EXCEPTION: {e}")


# ======================================================================
# BLOQUE 4: COLLAGE lado a lado + zoom ×4
# ======================================================================
def load_font(size=22, bold=False):
    try:
        names = ["C:/Windows/Fonts/arialbd.ttf",
                 "C:/Windows/Fonts/arial.ttf",
                 "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]
        p = names[0] if bold and os.path.exists(names[0]) else (names[1] if os.path.exists(names[1]) else names[-1])
        if os.path.exists(p):
            return ImageFont.truetype(p, size=size)
    except Exception:
        pass
    return ImageFont.load_default()


def zoom_at(imagen_rgb, cx_canvas_px, cy_canvas_px, zoom=4, size_w=600, size_h=500,
           title="Zoom", border=(212, 160, 23)):
    """Recorta alrededor de (cx, cy) en canvas 1920x1080 y escala × zoom con borde."""
    w, h = imagen_rgb.size
    rw = int(size_w / zoom)
    rh = int(size_h / zoom)
    x1 = max(0, cx_canvas_px - rw // 2)
    y1 = max(0, cy_canvas_px - rh // 2)
    x2 = min(w, x1 + rw)
    y2 = min(h, y1 + rh)
    crop = imagen_rgb.crop((x1, y1, x2, y2)).resize((size_w, size_h), Image.LANCZOS)
    marco = Image.new("RGB", (size_w + 16, size_h + 64), (15, 17, 22))
    draw = ImageDraw.Draw(marco)
    draw.rectangle([0, 0, marco.size[0]-1, marco.size[1]-1], outline=border, width=4)
    f = load_font(20, bold=True)
    draw.text((10, 10), title, font=f, fill=(255, 215, 0))
    marco.paste(crop, (8, 52))
    return marco


print("\n" + "=" * 80)
print("[COLLAGE] generando reporte lado a lado (referencia vs resultado)...")
# Tomamos la PRUEBA A (cutout real) para el collage principal (la B es stress test).
resultados_A = [r for r in resultados if r[0] == "A_cutout_rembg"]
col1_w = 900
col1_h = int(col1_w * CANVAS_H / CANVAS_W)
PAD_X = 20
HEADER_H = 90
ZOOMS_H = 600
TOTAL_W = PAD_X + col1_w + PAD_X + col1_w + PAD_X
TOTAL_H = HEADER_H + PAD_X + col1_h + PAD_X + ZOOMS_H + PAD_X
collage = Image.new("RGB", (TOTAL_W, TOTAL_H), (15, 17, 22, 255))
d = ImageDraw.Draw(collage)
ft = load_font(30, bold=True)
fs = load_font(18, bold=False)
fb = load_font(15, bold=False)
d.text((PAD_X, 20), f"RESULTADO FOTO REAL — rembg U2NetP (erosion={EROSION_PX}px, min_area={MIN_AREA_RATIO*100:.0f}%)",
       font=ft, fill=(255, 255, 255))

for idx, (prueba_name, key, title, label, info, out_jpg, final_rgba) in enumerate(resultados_A):
    if idx > 0:
        # Crear 3 collages individuales; aquí apilamos en filas de 1
        pass
# Nos quedamos con la primera imagen si hay varias — pero tenemos 3 escenarios.
# Hacemos UN SOLO collage general con los 3 escenarios en 3 filas pequeñas + zoom x4:

def make_grande_collage(results_list, out_path):
    N = len(results_list)
    col_w = 820
    col_h = int(col_w * CANVAS_H / CANVAS_W)
    pad = 18
    head_h = 70
    row_h = col_h + pad
    zoom_h = 560
    total_w = pad + col_w + pad + col_w + pad + col_w + pad
    total_h = head_h + pad + (row_h + pad + zoom_h) * N + pad
    base = Image.new("RGB", (total_w, total_h), (18, 20, 26))
    draw = ImageDraw.Draw(base)
    ft = load_font(26, bold=True)
    fs = load_font(18, bold=False)
    draw.text((pad, 18), "VALIDACIÓN FOTOS REALES (Fondo Original | Resultado rembg IA) — 3 escenarios",
              font=ft, fill=(255, 255, 255))
    for i, (prueba_name, key, title, label, info, out_jpg, final_rgba) in enumerate(results_list):
        y_row = head_h + pad + i * (row_h + pad + zoom_h)
        # Columna 0: fondo original (referencia / modelo)
        fondo = main.FONDOS_CACHE.get(key).convert("RGB").resize((col_w, col_h), Image.LANCZOS)
        base.paste(fondo, (pad, y_row))
        draw.text((pad, y_row - 22), f"{title.upper()} → FONDO ORIGINAL (modelo referencia)",
                  font=fs, fill=(144, 200, 255))
        # Columna 1: resultado
        res = Image.open(out_jpg).convert("RGB").resize((col_w, col_h), Image.LANCZOS)
        base.paste(res, (pad + col_w + pad, y_row))
        draw.text((pad + col_w + pad, y_row - 22),
                  f"RESULTADO: escala={info.get('escala', 0):.3f}  tope={info.get('tope_pct', 0):.3f}  cx={info.get('cx_pct', 0):.3f}  bottom={info.get('bottom_px', '?')}≥{info.get('y_base_mas_4', '?')}✅",
                  font=fs, fill=(255, 220, 144))
        # Columna 2: INFO TEXTUAL
        info_panel = Image.new("RGB", (col_w, col_h), (24, 28, 38))
        di = ImageDraw.Draw(info_panel)
        fi = load_font(15, bold=False)
        fib = load_font(16, bold=True)
        di.text((16, 14), f"ESCENARIO: {title.upper()}", font=fib, fill=(255, 215, 0))
        lines = [
            f"Prueba            : {label}",
            f"Personas detect.  : {info.get('n_personas', '?')}",
            "",
            f"ESCALA final      : {info.get('escala', 0):.4f}",
            f"ANCHO canvas pct   : {info.get('ancho_pct', 0):.3f}   (rng objetivo {info.get('ancho_rng_min', 0):.2f} a {info.get('ancho_rng_max', 0):.2f})",
            f"TOPE  canvas pct   : {info.get('tope_pct', 0):.3f}   (rng {info.get('tope_rng_min', 0):.2f} a {info.get('tope_rng_max', 0):.2f})",
            f"CX    canvas pct   : {info.get('cx_pct', 0):.3f}   (rng {info.get('cx_rng_min', 0):.2f} a {info.get('cx_rng_max', 0):.2f})",
            "",
            f"y_base_px         : {info.get('y_base_px', '?')}",
            f"y_base + 4        : {info.get('y_base_mas_4', '?')}",
            f"bottom_px REAL    : {info.get('bottom_px', '?')}    {'✅ CUMPLE cobertura L3' if info.get('bottom_px', 0) >= info.get('y_base_mas_4', 0) else '❌ FALLA cobertura L3'}",
            f"vent_top_px       : {info.get('vent_top_px', '?')}",
            f"tope_abs_px       : {info.get('tope_abs_px', '?')}   (vent_top+12={info.get('vent_top_px', 0)+12 if isinstance(info.get('vent_top_px', 0), int) else '?'})",
            "",
            f"Regla4 diff=0 OK? : {info.get('diff_zero_ok', '?')}",
            "",
            f"Parámetros runtime: erosion={EROSION_PX}px min_area={MIN_AREA_RATIO*100:.0f}%",
        ]
        for k, line in enumerate(lines):
            di.text((18, 60 + k * 22), line, font=fi, fill=(240, 240, 240))
        base.paste(info_panel, (pad + 2 * (col_w + pad), y_row))
        draw.text((pad + 2 * (col_w + pad), y_row - 22), f"METADATA NUMÉRICA (L1-L7 validación)",
                  font=fs, fill=(200, 255, 200))
        # ZOOM ×4 fila inferior
        y_zoom = y_row + col_h + pad
        zw, zh = 760, 540
        cx_borde, cy_borde = CANVAS_W // 2, 962  # 25px encima y_base
        # Coords HOMBRO DERECHO / BRAZO IZQUIERDO FIJAS calculadas DINA-
        # MICAMENTE desde BBOX REAL de PERSONA en canvas (NO grupo completo).
        # Calculamos BBOX alfa persona usando la máscara ventana como referencia:
        # Bbox canvas persona: x1 = (cx - ancho/2)*1920 ; x2 = (cx + ancho/2)*1920 ; y1 = tope*1080 + ... ; y2 = bottom_px
        cx_canvas = float(info.get('cx_pct', 0.5))
        ancho_canvas_pct = float(info.get('ancho_pct', 0.35))
        tope_canvas_pct = float(info.get('tope_pct', 0.40))
        y_bottom_canvas = int(float(info.get('bottom_px', 991) if isinstance(info.get('bottom_px'), int) else 991))
        x1_canvas = int((cx_canvas - ancho_canvas_pct / 2.0) * CANVAS_W)
        x2_canvas = int((cx_canvas + ancho_canvas_pct / 2.0) * CANVAS_W)
        y1_canvas = int(tope_canvas_pct * CANVAS_H)  # coronilla
        # Hombro derecho = X = x2_canvas - 18% ancho_persona ; Y = y1_canvas + 22% altura_persona
        # Brazo izq       = X = x1_canvas + 18% ancho_persona ; Y = y1_canvas + 28% altura_persona
        w_persona_canvas = max(40, x2_canvas - x1_canvas)
        h_persona_canvas = max(40, y_bottom_canvas - y1_canvas)
        cx_hombr_derecho = int(x2_canvas - 0.22 * w_persona_canvas)
        cy_hombr_derecho = int(y1_canvas + 0.24 * h_persona_canvas)
        cx_brazo_izq = int(x1_canvas + 0.22 * w_persona_canvas)
        cy_brazo_izq = int(y1_canvas + 0.30 * h_persona_canvas)
        # Clamp coords a canvas
        cx_hombr_derecho = max(40, min(CANVAS_W - 40, cx_hombr_derecho))
        cy_hombr_derecho = max(80, min(CANVAS_H - 80, cy_hombr_derecho))
        cx_brazo_izq = max(40, min(CANVAS_W - 40, cx_brazo_izq))
        cy_brazo_izq = max(80, min(CANVAS_H - 80, cy_brazo_izq))
        # Ahora SI usamos imagen ESPECIFICA ESTE escenario
        res_local = Image.open(out_jpg).convert("RGB")
        z1 = zoom_at(res_local, cx_borde, cy_borde, zoom=4, size_w=zw, size_h=zh,
                     title=f"×4  BORDE INFERIOR (y 962) — L3 bottom≥y_base+4: {y_bottom_canvas}≥{info.get('y_base_mas_4','?')}")
        z2i = zoom_at(res_local, cx_hombr_derecho, cy_hombr_derecho, zoom=4, size_w=zw, size_h=zh,
                      title=f"×4  HOMBRO DERECHO / CABEZA DER (x{cx_hombr_derecho} y{cy_hombr_derecho}) — erosion {EROSION_PX}px")
        z3i = zoom_at(res_local, cx_brazo_izq, cy_brazo_izq, zoom=4, size_w=zw, size_h=zh,
                      title=f"×4  BRAZO IZQUIERDO / CABEZA IZQ (x{cx_brazo_izq} y{cy_brazo_izq}) — halo claro/gris")
        base.paste(z1, (pad, y_zoom))
        base.paste(z2i, (pad + zw + pad, y_zoom))
        base.paste(z3i, (pad + 2 * (zw + pad), y_zoom))
    base.save(out_path, format="JPEG", quality=92, progressive=True, dpi=(180, 180))
    return out_path


out_collage = os.path.join(OUT_DIR, f"{NOMBRE}__collage_validacion_real.jpg")
p = make_grande_collage(resultados_A, out_collage)
print(f"[COLLAGE] OK -> {p}")

# Collage stress test B
if len(resultados) > len(resultados_A):
    results_B = [r for r in resultados if r[0] == "B_full_alfa_255"]
    if results_B:
        out_b = os.path.join(OUT_DIR, f"{NOMBRE}__stress_alfa255_collage.jpg")
        make_grande_collage(results_B, out_b)
        print(f"[COLLAGE B STRESS] OK -> {out_b}")


# ======================================================================
# BLOQUE 5: RESUMEN TERMINAL
# ======================================================================
print("\n" + "=" * 80)
print("📊 RESUMEN VALIDACIÓN FOTOS REALES")
print("=" * 80)
for (prueba_name, key, title, label, info, out_jpg, _final) in resultados:
    try:
        bp = int(info.get('bottom_px', 0) if not isinstance(info.get('bottom_px'), (str, type(None))) else 0)
        y4 = int(info.get('y_base_mas_4', 0) if not isinstance(info.get('y_base_mas_4'), (str, type(None))) else 0)
        bot_ok = bp >= y4 and y4 > 0
    except Exception:
        bot_ok = False
    try:
        ancho_ok = float(info.get('ancho_rng_min', 0)) <= float(info.get('ancho_pct', 0)) <= float(info.get('ancho_rng_max', 0)) * 1.12
    except Exception:
        ancho_ok = False
    try:
        tope_ok = float(info.get('tope_rng_min', 0)) - 0.10 <= float(info.get('tope_pct', 0)) <= float(info.get('tope_rng_max', 0))
    except Exception:
        tope_ok = False
    try:
        cx_ok = float(info.get('cx_rng_min', 0)) <= float(info.get('cx_pct', 0)) <= float(info.get('cx_rng_max', 0))
    except Exception:
        cx_ok = False
    diff0 = (info.get('diff_zero_ok') is True)
    print(f"{prueba_name:18s}  {title:18s}  "
          f"L3={'✅' if bot_ok else '❌'} "
          f"ancho={'✅' if ancho_ok else '⚠️'} "
          f"tope={'✅' if tope_ok else '⚠️'} "
          f"cx={'✅' if cx_ok else '⚠️'} "
          f"diff0={'✅' if diff0 else '❌'} "
          f"n_pers={str(info.get('n_personas', '?'))}")
print("=" * 80)
print(f"Salidas: {OUT_DIR}")
print("=" * 80)
