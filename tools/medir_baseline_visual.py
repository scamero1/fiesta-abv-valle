"""
Medidor visual DE SUELO PAISAJE (baseline_personas_px) por cada escenario.
Genera 3 PNGs de depuracion con una LINEA HORIZONTAL del color especifico en
la posicion que creemos es EL SUELO donde van los pies de las personas:
  - CRISTO REY: suelo ladrillo rojo mirador → ~870 (detras de balaustrada riel)
  - MUSEO SALSA: suelo vereda/madera Barrio Obrero → ~905
  - PLAZA VARELA: suelo calzada gris trompetas → ~910
Guarda ademas measurement.txt con numeros.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend-python"))
os.chdir(os.path.join(os.path.dirname(__file__), "..", "backend-python"))
from PIL import Image, ImageDraw
import main
import numpy as np

OUT_DIR = os.path.join(os.path.dirname(__file__), "out", "debug-baseline")
os.makedirs(OUT_DIR, exist_ok=True)

# Propuesta de baseline: SUELO VISIBLE del paisaje (NO 987 que es LIMITE MARCO)
BASELINES = {
    "cristorey":   870,   # suelo ladrillo rojo detras de balaustrada (mirador)
    "museosalsa":  905,   # suelo vereda madera/marco suelo del mural
    "plazavarela": 910,   # calzada gris trompetas
}

COLORS = {
    "cristorey":   (255,   0,   0, 230),  # ROJO
    "museosalsa":  (  0, 255,  90, 230),  # VERDE
    "plazavarela": (255, 215,   0, 230),  # DORADO
}

txt = []
for key, baseline in BASELINES.items():
    fondo = main.FONDOS_CACHE[key].copy().convert("RGBA")
    W, H = fondo.size
    draw = ImageDraw.Draw(fondo, "RGBA")
    # Dibujar 3 lineas: baseline-5, baseline (gruesa), baseline+5
    # (1) linea gruesa principal
    draw.rectangle([0, baseline-2, W, baseline+2], fill=COLORS[key])
    # (2) 2 lineas finas (marco 10px arriba y abajo para referencia)
    draw.line([(0, baseline - 50), (W, baseline - 50)], fill=COLORS[key], width=1)
    draw.line([(0, baseline + 50), (W, baseline + 50)], fill=COLORS[key], width=1)
    # (3) texto con Y y diferencia a y_base_px=987
    fontname = None
    try:
        from PIL import ImageFont
        font = ImageFont.truetype("C:/Windows/Fonts/arialbd.ttf", 26)
    except Exception:
        font = ImageFont.load_default()
    draw.text(
        (16, baseline - 46),
        f"BASELINE PERSONAS = Y = {baseline} px  (y_base_px marco=987, diff = {987-baseline} px ARRIBA de blanco)",
        fill=(0,0,0,255),
        font=font,
        stroke_width=2,
        stroke_fill=(255,255,255,255),
    )
    # (4) Marcar tambien el y_base_px 987 con linea Punteada gris
    draw.rectangle([0, 987-1, W, 987+1], fill=(120, 120, 120, 255))
    draw.text(
        (16, 987 + 4),
        f"y_base_px 987 = FIN PAISAJE (LIMITE MARCO BLANCO INCLINADO INFERIOR)  |  EN NUESTRO FIX NUNCA ANCLAMOS ACA.",
        fill=(70,70,70,255),
        font=font,
    )
    out_p = os.path.join(OUT_DIR, f"dbg_baseline_{key}.png")
    fondo.save(out_p)
    txt.append(f"{key}: baseline={baseline}px | 987 - baseline = {987-baseline}px (altura \"suelo\" real arriba de marco)")
    print(f"[OK] guardado: {out_p}")

with open(os.path.join(OUT_DIR, "measurement.txt"), "w", encoding="utf-8") as f:
    f.write("\n".join(txt))
print()
print("\n".join(txt))
