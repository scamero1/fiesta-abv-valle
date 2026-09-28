"""
Genera COLLAGES de validación visual:
  1) Por cada escenario (3): Collage "Modelo / Resultado + Zoom borde inf + Zoom contorno".
  2) Collage final: 3x3 con los 9 renders (3 fotos x 3 escenarios).
Salida: tools/out/collages/
"""
import sys
import os
from PIL import Image, ImageDraw, ImageFont

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
BACKEND_DIR = os.path.join(PROJECT_ROOT, "backend-python")
sys.path.insert(0, BACKEND_DIR)

OUT_DIR = os.path.join(SCRIPT_DIR, "out", "collages")
os.makedirs(OUT_DIR, exist_ok=True)
RENDER_DIR = os.path.join(SCRIPT_DIR, "out", "test-compose-local")
FONDO_DIR = os.path.join(BACKEND_DIR, "assets")

ESCENARIOS = [
    ("cristorey", "Cristo Rey", "esc-cristorey.jpg",
     os.path.join(RENDER_DIR, "foto3-grupo-3p__cristorey.jpg")),
    ("museosalsa", "Museo de la Salsa", "esc-museosalsa.jpg",
     os.path.join(RENDER_DIR, "foto3-grupo-3p__museosalsa.jpg")),
    ("plazavarela", "Plaza Varela", "esc-plazavarela.jpg",
     os.path.join(RENDER_DIR, "foto3-grupo-3p__plazavarela.jpg")),
]

CANVAS_W, CANVAS_H = 1920, 1080

def load_font(size=22, bold=False):
    try:
        from PIL import ImageFont
        names = ["C:/Windows/Fonts/arialbd.ttf",
                 "C:/Windows/Fonts/arial.ttf",
                 "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]
        path = names[0] if bold and os.path.exists(names[0]) else (names[1] if os.path.exists(names[1]) else names[-1])
        if os.path.exists(path):
            return ImageFont.truetype(path, size=size)
    except Exception:
        pass
    return ImageFont.load_default()


def add_zoom(imagen, xy_center, zoom_w=520, zoom_h=360, scale_zoom=3.0, title="Zoom"):
    """Recorta xy_center w,h con scale y pega con borde dorado."""
    iw, ih = imagen.size
    cx, cy = xy_center
    rw = int(zoom_w / scale_zoom)
    rh = int(zoom_h / scale_zoom)
    x1 = max(0, cx - rw // 2)
    y1 = max(0, cy - rh // 2)
    x2 = min(iw, x1 + rw)
    y2 = min(ih, y1 + rh)
    crop = imagen.crop((x1, y1, x2, y2))
    crop = crop.resize((zoom_w, zoom_h), Image.LANCZOS)
    # Borde dorado + texto
    marco = Image.new("RGBA", (zoom_w + 12, zoom_h + 56), (0, 0, 0, 255))
    draw_m = ImageDraw.Draw(marco)
    draw_m.rectangle([0, 0, marco.size[0]-1, marco.size[1]-1], outline=(212, 160, 23, 255), width=4)
    try:
        f = load_font(20, bold=True)
        draw_m.text((8, 8), title, font=f, fill=(255, 215, 0, 255))
    except Exception:
        pass
    marco.paste(crop, (6, 48))
    return marco


def collage_escenario(key, titulo, fondo_path, result_path):
    """Collage por escenario: fondo orig | resultado | zoom borde inf | zoom contorno."""
    print(f"[collage] {key} : {titulo}")
    fondo = Image.open(fondo_path).convert("RGB")
    if fondo.size != (CANVAS_W, CANVAS_H):
        from PIL import Image as _I
        fondo = fondo.resize((CANVAS_W, CANVAS_H), _I.LANCZOS)
    result = Image.open(result_path).convert("RGB")
    W_FOTO = 900
    H_FOTO = int(W_FOTO * CANVAS_H / CANVAS_W)
    fondo_s = fondo.resize((W_FOTO, H_FOTO), Image.LANCZOS)
    result_s = result.resize((W_FOTO, H_FOTO), Image.LANCZOS)

    COL_W = 20 + W_FOTO + 20 + W_FOTO + 20
    ROW_H = 80 + H_FOTO + 20
    ZOOM_W, ZOOM_H = 780, 420
    ROW2_H = 60 + ZOOM_H + 20
    TOTAL_W = COL_W + 60
    TOTAL_H = ROW_H + ROW2_H + 40

    base = Image.new("RGB", (TOTAL_W, TOTAL_H), (20, 22, 28, 255))
    draw = ImageDraw.Draw(base)
    ft = load_font(34, bold=True)
    fs = load_font(20, bold=False)
    draw.text((24, 22), f"ESCENARIO: {titulo.upper()}", font=ft, fill=(255, 255, 255, 255))

    y_header = 80
    # Columna 1: fondo original
    base.paste(fondo_s, (20, y_header))
    draw.text((20, y_header - 28), "FONDO ORIGINAL (sagrado - sin modificar)", font=fs, fill=(144, 200, 255, 255))
    # Columna 2: resultado
    rx = 20 + W_FOTO + 20
    base.paste(result_s, (rx, y_header))
    draw.text((rx, y_header - 28), "RESULTADO (persona compuesta)", font=fs, fill=(255, 220, 144, 255))

    # Zoom 1: BORDE INFERIOR result — zona justo encima del marco blanco inf
    y2 = 80 + H_FOTO + 20
    y_borde_inf_px_orig = 962  # 25px encima de y_base=987, muestra persona naciendo del paisaje
    zoom1 = add_zoom(result, (CANVAS_W // 2, y_borde_inf_px_orig),
                     zoom_w=ZOOM_W, zoom_h=ZOOM_H, scale_zoom=3.4,
                     title="BORDE INFERIOR: persona nace del marco blanco (y_base+4), sin franja de paisaje")
    zx1 = 30
    base.paste(zoom1, (zx1, y2))

    # Zoom 2: CONTORNO CABEZA/HOMBRO (coords por escenario, según cx/tope del compose_full)
    if key == "cristorey":
        # escala 0.59, tope 0.425, cx 0.525 => cabeza x~1008 y~480; hombro x~980 y~590
        cx_zoom, cy_zoom = 990, 560
    elif key == "museosalsa":
        # escala 0.60, tope 0.410, cx 0.340 => cabeza x~653 y~443; hombro x~625 y~540
        cx_zoom, cy_zoom = 640, 540
    else:  # plazavarela
        # escala 0.80, tope 0.240, cx 0.459 => cabeza x~881 y~260; hombro x~860 y~350
        cx_zoom, cy_zoom = 860, 360
    zoom2 = add_zoom(result, (cx_zoom, cy_zoom),
                     zoom_w=ZOOM_W, zoom_h=ZOOM_H, scale_zoom=3.6,
                     title="CONTORNO CABEZA/HOMBRO: sin halo claro/gris (erosion 1px + descontam + feather paisaje)")
    zx2 = TOTAL_W - 30 - zoom2.size[0]
    base.paste(zoom2, (zx2, y2))

    out = os.path.join(OUT_DIR, f"collage_{key}.jpg")
    base.save(out, format="JPEG", quality=92, progressive=True, dpi=(180, 180))
    print(f"    -> {out}")
    return out


def collage_3x3_todos():
    """Matriz 3 fotos x 3 escenarios = 9 renders."""
    FOTOS = ["foto1-cintura", "foto2-cuerpo-entero", "foto3-grupo-3p"]
    KEYS = ["cristorey", "museosalsa", "plazavarela"]
    W_CELL = 900
    H_CELL = int(W_CELL * CANVAS_H / CANVAS_W)
    PAD = 18
    HEADER_H = 70
    T_W = PAD + (W_CELL + PAD) * 3
    T_H = HEADER_H + PAD + (H_CELL + PAD) * 3
    base = Image.new("RGB", (T_W, T_H), (18, 20, 26, 255))
    draw = ImageDraw.Draw(base)
    ft = load_font(28, bold=True)
    fs = load_font(18, bold=False)
    draw.text((PAD, 20), "RESULTADOS 3x3: 3 fixtures promotora x 3 escenarios", font=ft, fill=(255, 255, 255, 255))
    # Headers columnas
    for j, k in enumerate(KEYS):
        x = PAD + j * (W_CELL + PAD)
        draw.text((x + W_CELL // 2, HEADER_H - 22), k.upper(), font=fs, fill=(255, 215, 0, 255), anchor="mm")
    for i, fn in enumerate(FOTOS):
        y = HEADER_H + PAD + i * (H_CELL + PAD)
        draw.text((PAD - 6, y + H_CELL // 2), fn, font=fs, fill=(200, 230, 255, 255),
                  anchor="mm")
        for j, k in enumerate(KEYS):
            p = os.path.join(RENDER_DIR, f"{fn}__{k}.jpg")
            if not os.path.exists(p):
                continue
            im = Image.open(p).convert("RGB").resize((W_CELL, H_CELL), Image.LANCZOS)
            x = PAD + j * (W_CELL + PAD)
            base.paste(im, (x, y))
            draw.rectangle([x, y, x + W_CELL - 1, y + H_CELL - 1],
                           outline=(52, 71, 122, 255), width=2)
    out = os.path.join(OUT_DIR, "collage_todos_3x3.jpg")
    base.save(out, format="JPEG", quality=90, progressive=True, dpi=(150, 150))
    print(f"[collage] 3x3 -> {out}")
    return out


if __name__ == "__main__":
    outs = []
    for k, t, fp, rp in ESCENARIOS:
        fp_full = os.path.join(FONDO_DIR, fp)
        outs.append(collage_escenario(k, t, fp_full, rp))
    outs.append(collage_3x3_todos())
    print()
    print("=" * 80)
    print("COLLAGES GENERADOS:")
    for p in outs:
        print(f"  - {p}")
    print("=" * 80)
