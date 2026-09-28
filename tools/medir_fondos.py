"""
tools/medir_fondos.py
=====================
PASO 0 del PROMPT MAESTRO. Calcula y guarda:
  1) backend-python/assets/escenarios.json  (coords en px y proporciones 0..1)
  2) backend-python/assets/mask_{cristorey,museosalsa,plazavarela}.png
        = 1920x1080 mode "L". 255 = paisaje permitido, 0 = marco (azul/blanco/titulo/legal)
        Incluye recorte por los bordes INCLINADOS del marco blanco.
  3) tools/out/dbg_mask_{cristorey,museosalsa,plazavarela}.png
        = superposicion roja semitransparente de la mascara sobre el fondo,
        para validar visualmente que coincide con el marco blanco.

SIN OpenCV: solo Pillow + NumPy (ambos en backend-python/requirements.txt).

Ejecutar desde raiz del proyecto:
   python tools/medir_fondos.py
"""
import json
import os
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
ASSETS_BACKEND = ROOT / "backend-python" / "assets"
TOOLS_OUT = ROOT / "tools" / "out"
ASSETS_BACKEND.mkdir(parents=True, exist_ok=True)
TOOLS_OUT.mkdir(parents=True, exist_ok=True)

CANVAS_W, CANVAS_H = 1920, 1080

ESCENARIOS = [
    ("cristorey",  "esc-cristorey.jpg",  ("sunset", "cristo-rey")),
    ("museosalsa", "esc-museosalsa.jpg", ("neon",   "calle-del-sabor")),
    ("plazavarela","esc-plazavarela.jpg",("feria",  "plaza-varela")),
]

# ---------------------------------------------------------------------------
# Utilidades de resize
# ---------------------------------------------------------------------------
def cover_resize(img: Image.Image, tw: int, th: int) -> Image.Image:
    """Resize cover (corta lo que sobra para llenar tw x th sin deformar)."""
    iw, ih = img.size
    scale = max(tw / iw, th / ih)
    nw, nh = max(1, int(round(iw * scale))), max(1, int(round(ih * scale)))
    rz = img.resize((nw, nh), Image.LANCZOS)
    cx, cy = (nw - tw) // 2, (nh - th) // 2
    return rz.crop((cx, cy, cx + tw, cy + th))


# ---------------------------------------------------------------------------
# Paso 1: detectar marco blanco (luminosidad >= 245) y calcular las 4 esquinas
# ---------------------------------------------------------------------------
def detectar_ventana_paralelogramo(arr_gray_255: np.ndarray):
    """
    Entrada: ndarray uint8 shape (H,W) gris 0..255 del fondo 1920x1080.
    Salida: 4 esquinas del paralelogramo en px (tl, tr, br, bl) cada una (x,y).
    + y_base (borde inferior horizontal del paisaje: fila justo antes de marco blanco inf)
    + y_top  (borde superior horizontal del paisaje: fila justo despues marco blanco sup)
    """
    H, W = arr_gray_255.shape
    # Binarizacion: blanco >= 245
    binario = (arr_gray_255 >= 245).astype(np.uint8) * 255

    # ----- 1) Filas de bordes horizontales -----
    # Por cada fila, proporcion de blancos.
    row_white_ratio = binario.mean(axis=1) / 255.0
    # Marco superior blanco: primera franja horizontal con row_white_ratio > 0.90
    y_top = None
    for y in range(40, 140):
        if row_white_ratio[y] > 0.90:
            y_top = y
            break
    if y_top is None:
        y_top = 90  # fallback aproximacion del prompt
    # Marco inferior blanco: ultima franja horizontal con row_white_ratio > 0.90
    y_bottom = None
    for y in range(H - 1, H - 140, -1):
        if row_white_ratio[y] > 0.90:
            y_bottom = y
            break
    if y_bottom is None:
        y_bottom = 1008  # fallback

    # Limpieza: excluimos zonas de marco superior (0..y_top) e inferior (y_bottom..H)
    zona_paisaje = np.zeros_like(binario, dtype=bool)
    zona_paisaje[y_top + 1 : y_bottom, :] = True

    # ----- 2) Bordes izquierdo y derecho INCLINADOS -----
    # Para cada fila en [y_top+5, y_bottom-5], encontramos el primer blanco
    # desde la izquierda (borde izq marco) y desde la derecha (borde der marco).
    # El PAISAJE esta ENTRE ambos blancos (x_border_izq < x_paisaje < x_border_der).
    filas = np.arange(y_top + 5, y_bottom - 5)
    xs_izq = np.empty_like(filas)
    xs_der = np.empty_like(filas)
    for i, y in enumerate(filas):
        row = binario[y, :]
        # Primer blanco desde la izquierda
        hits_izq = np.nonzero(row >= 245)[0]
        if len(hits_izq) > 0:
            xs_izq[i] = hits_izq[0]
        else:
            xs_izq[i] = 56  # fallback
        # Ultimo blanco desde la derecha
        hits_der = np.nonzero(row >= 245)[0]
        if len(hits_der) > 0:
            xs_der[i] = hits_der[-1]
        else:
            xs_der[i] = 1864  # fallback

    # Ajustar linea recta: borde izquierdo (xs_izq vs filas)
    A = np.vstack([filas.astype(np.float64), np.ones_like(filas, np.float64)]).T
    m_izq, b_izq = np.linalg.lstsq(A, xs_izq.astype(np.float64), rcond=None)[0]
    m_der, b_der = np.linalg.lstsq(A, xs_der.astype(np.float64), rcond=None)[0]

    # Intersecciones para 4 esquinas:
    #   tl = borde izq con fila y_top + 1
    #   tr = borde der con fila y_top + 1
    #   bl = borde izq con fila y_bottom - 1
    #   br = borde der con fila y_bottom - 1
    tl = (int(round(m_izq * (y_top + 1) + b_izq)), y_top + 1)
    tr = (int(round(m_der * (y_top + 1) + b_der)), y_top + 1)
    bl = (int(round(m_izq * (y_bottom - 1) + b_izq)), y_bottom - 1)
    br = (int(round(m_der * (y_bottom - 1) + b_der)), y_bottom - 1)

    return (tl, tr, br, bl), y_top + 1, y_bottom - 1


# ---------------------------------------------------------------------------
# Paso 2: detectar keep-outs (slogan y pastilla)
# ---------------------------------------------------------------------------
def detectar_keepouts(rgb: np.ndarray):
    H, W, _ = rgb.shape
    # --- Slogan sup-izq: rojo (R alto, G/B bajos) + blanco en x<450 y<500 ---
    zona = rgb[0:H // 2, 0:W // 4, :]
    rojo = (zona[:, :, 0] > 180) & (zona[:, :, 1] < 80) & (zona[:, :, 2] < 80)
    blanco_zona = (zona[:, :, 0] > 220) & (zona[:, :, 1] > 220) & (zona[:, :, 2] > 220)
    mask_slogan = rojo | blanco_zona
    ys, xs = np.nonzero(mask_slogan)
    kslog = None
    if len(xs) > 300:
        kslog = (int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max()))
    else:
        kslog = (int(W * 0.07), int(H * 0.13), int(W * 0.26), int(H * 0.40))

    # --- Pastilla sup-der: azul/negro/blanco en x>1500 y<250 ---
    zona2 = rgb[0:int(H * 0.22), int(W * 0.78):W, :]
    azul = (zona2[:, :, 0] < 100) & (zona2[:, :, 1] < 130) & (zona2[:, :, 2] > 150)
    blanco2 = (zona2[:, :, 0] > 200) & (zona2[:, :, 1] > 200) & (zona2[:, :, 2] > 200)
    negro = (zona2[:, :, 0] < 60) & (zona2[:, :, 1] < 60) & (zona2[:, :, 2] < 60)
    mask_past = azul | blanco2 | negro
    ys2, xs2 = np.nonzero(mask_past)
    kpast = None
    if len(xs2) > 200:
        off_x = int(W * 0.78)
        kpast = (
            int(xs2.min()) + off_x,
            int(ys2.min()),
            int(xs2.max()) + off_x,
            int(ys2.max()),
        )
    else:
        kpast = (int(W * 0.80), int(H * 0.02), int(W * 0.985), int(H * 0.22))
    return kslog, kpast


# ---------------------------------------------------------------------------
# Paso 3: mascara de zona permitida (ventana paisaje - keepout pastilla)
# ---------------------------------------------------------------------------
def crear_mascara_ventana(tl, tr, br, bl, pastilla_bbox=None) -> Image.Image:
    from PIL import ImageDraw
    mask = Image.new("L", (CANVAS_W, CANVAS_H), 0)
    draw = ImageDraw.Draw(mask)
    draw.polygon([tl, tr, br, bl], fill=255)
    # Restar keep-out pastilla (NO la persona, sino que al componer restauraremos fondo si invade)
    # Pero PROMPT MAESTRO PASO 0 dice: Mascara "zona permitida" = ventana - keep-out logo.
    if pastilla_bbox:
        draw.rectangle(pastilla_bbox, fill=0)
    return mask


# ---------------------------------------------------------------------------
def main():
    salida_json = {}
    print("=" * 72)
    print("PASO 0 - MEDICION FONDOS ORIGINALES -> JSON + MASCARAS")
    print("=" * 72)
    for key, fname, frontend_ids in ESCENARIOS:
        src = ASSETS_BACKEND / fname
        if not src.exists():
            src = ROOT / "public" / "assets" / fname
        if not src.exists():
            print(f"[SKIP] No existe {fname}")
            continue
        print(f"\n[{key}] Cargando {fname}")
        with Image.open(src) as im_orig:
            im_orig.load()
            print(f"       Tamano original: {im_orig.size} ({im_orig.mode})")
            im_1920 = cover_resize(im_orig.convert("RGB"), CANVAS_W, CANVAS_H)
        rgb = np.asarray(im_1920, dtype=np.uint8)
        gris = np.asarray(im_1920.convert("L"), dtype=np.uint8)

        # a) Paralelogramo ventana
        (tl, tr, br, bl), y_top_paisaje, y_bottom_paisaje = detectar_ventana_paralelogramo(gris)
        print(f"       Esquinas ventana (tl,tr,br,bl)={tl} {tr} {br} {bl}")
        print(f"       y_top (borde sup paisaje)={y_top_paisaje}  y_base (borde inf paisaje)={y_bottom_paisaje}")

        # b) keep-outs
        kslog, kpast = detectar_keepouts(rgb)
        print(f"       keep-out slogan   (x1,y1,x2,y2)={kslog}")
        print(f"       keep-out pastilla (x1,y1,x2,y2)={kpast}")

        # c) Franja titulo y legal
        franja_titulo = (0, 0, CANVAS_W, max(y_top_paisaje - 10, int(CANVAS_H * 0.08)))
        franja_legal = (0, max(y_bottom_paisaje + 20, int(CANVAS_H * 0.945)), CANVAS_W, CANVAS_H)
        print(f"       franja titulo y in [0, {franja_titulo[3]}]  / legal y in [{franja_legal[1]}, {CANVAS_H}]")

        # d) Guardar mascara L
        mask = crear_mascara_ventana(tl, tr, br, bl, pastilla_bbox=kpast)
        mask_path = ASSETS_BACKEND / f"mask_{key}.png"
        mask.save(mask_path)
        print(f"       Guardada mascara: {mask_path}")

        # e) PNG depuracion: superposicion roja semitransparente
        red = Image.new("RGBA", (CANVAS_W, CANVAS_H), (228, 0, 43, 120))
        red.putalpha(mask.point(lambda v: 130 if v > 0 else 0))
        dbg = im_1920.convert("RGBA").copy()
        dbg.alpha_composite(red)
        # Dibujar tambien rectangulos keepouts en verde y amarillo
        from PIL import ImageDraw as IDraw
        d = IDraw.Draw(dbg)
        d.rectangle(kslog, outline=(34, 197, 94, 255), width=3)
        d.rectangle(kpast, outline=(212, 160, 23, 255), width=3)
        d.line([tl, tr, br, bl, tl], fill=(255, 255, 255, 255), width=2)
        dbg_path = TOOLS_OUT / f"dbg_mask_{key}.png"
        dbg.convert("RGB").save(dbg_path, quality=95)
        print(f"       Guardada depuracion: {dbg_path}")

        # f) JSON en proporciones 0..1 y px
        def pct_xy(p):
            return [round(p[0] / CANVAS_W, 4), round(p[1] / CANVAS_H, 4)]
        entrada_json = {
            "ids_frontend": list(frontend_ids),
            "archivo_fondo": fname,
            "canvas": {"w": CANVAS_W, "h": CANVAS_H},
            "ventana_paisaje_px": {
                "esquinas_tl_tr_br_bl": [list(tl), list(tr), list(br), list(bl)],
                "y_top_paisaje": y_top_paisaje,
                "y_base_borde_inf": y_bottom_paisaje,
            },
            "ventana_paisaje_pct": {
                "esquinas_tl_tr_br_bl": [pct_xy(tl), pct_xy(tr), pct_xy(br), pct_xy(bl)],
                "y_top_pct": round(y_top_paisaje / CANVAS_H, 4),
                "y_base_pct": round(y_bottom_paisaje / CANVAS_H, 4),
            },
            "keep_out_slogan_px": {"bbox": list(kslog)},
            "keep_out_slogan_pct": {
                "bbox": [
                    round(kslog[0] / CANVAS_W, 4), round(kslog[1] / CANVAS_H, 4),
                    round(kslog[2] / CANVAS_W, 4), round(kslog[3] / CANVAS_H, 4),
                ]
            },
            "keep_out_logo_px": {"bbox": list(kpast)},
            "keep_out_logo_pct": {
                "bbox": [
                    round(kpast[0] / CANVAS_W, 4), round(kpast[1] / CANVAS_H, 4),
                    round(kpast[2] / CANVAS_W, 4), round(kpast[3] / CANVAS_H, 4),
                ]
            },
            "franja_titulo_px": {"bbox": list(franja_titulo)},
            "franja_legal_px": {"bbox": list(franja_legal)},
            "y_base_px": y_bottom_paisaje,
            "y_base_pct": round(y_bottom_paisaje / CANVAS_H, 4),
        }
        salida_json[key] = entrada_json

    # ------------------------------------------------------------------
    # Valores finales por escenario (PROMPT MAESTRO PASO 2 y PASO 2.6 y 2.3)
    # (Recomendados iniciales, el usuario ajusta comparando visualmente)
    # ------------------------------------------------------------------
    valores_finales = {
        "cristorey":  {"escala_altura_ventana": [0.55, 0.62], "centro_horizontal_pct_canvas": [0.50, 0.55], "cabeza_pct_canvas": [0.16, 0.23]},
        "museosalsa": {"escala_altura_ventana": [0.58, 0.65], "centro_horizontal_pct_canvas": [0.30, 0.38], "cabeza_pct_canvas": [0.16, 0.23]},
        "plazavarela":{"escala_altura_ventana": [0.80, 0.88], "centro_horizontal_pct_canvas": [0.42, 0.45], "cabeza_pct_canvas": [0.16, 0.23]},
    }
    for k, v in valores_finales.items():
        if k in salida_json:
            salida_json[k]["valores_recomendados"] = v
    salida_json["__meta__"] = {
        "canvas_w": CANVAS_W, "canvas_h": CANVAS_H,
        "generado_por": "tools/medir_fondos.py",
    }

    out_json = ASSETS_BACKEND / "escenarios.json"
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(salida_json, f, ensure_ascii=False, indent=2)
    print(f"\nJSON final guardado: {out_json}")
    print(f"\nRevisar visualmente tools/out/dbg_mask_*.png antes de continuar.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
