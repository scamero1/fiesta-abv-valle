"""Test sintetico NUMERICO: persona sintetica sin fondo para medir posiciones por escenario."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend-python"))
os.chdir(os.path.join(os.path.dirname(__file__), "..", "backend-python"))
from PIL import Image
import numpy as np
import main

# Crear persona SINTETICA: 400x700, cuerpo 240x600 (centrada)
H_P, W_P = 700, 400
arr_p = np.zeros((H_P, W_P, 4), dtype=np.uint8)
arr_p[50:650, 80:320] = [255, 255, 255, 255]  # cuerpo (600h x 240w)
persona_sint = Image.fromarray(arr_p, mode="RGBA")
print(f"[sint] Persona sintetica: bbox cuerpo (80,50)-(320,650)")
print()

ESC = [
    ("cristorey",    "cristo-rey",     0.53, 0.50),
    ("museosalsa",   "calle-del-sabor",0.56, 0.30),
    ("plazavarela",  "plaza-varela",   0.78, 0.40),
]

RES = []
for key, esc_id, esc_exp, cx_exp in ESC:
    final = main.compose_full(persona_sint, esc_id, alpha_matting=False)
    fondo = main.FONDOS_CACHE[key].copy().convert("RGBA")
    a_c = np.asarray(final, dtype=np.uint8)[..., :3].astype(np.int16)
    a_f = np.asarray(fondo, dtype=np.uint8)[..., :3].astype(np.int16)
    diff = np.abs(a_c - a_f)
    mask_pers = diff.max(axis=2) >= 15
    ys, xs = np.where(mask_pers)
    if len(ys) == 0:
        print(f"⚠️ {key}: sin diferencia")
        continue
    minx, maxx = int(xs.min()), int(xs.max())
    miny, maxy = int(ys.min()), int(ys.max())
    cx_real = round((minx + maxx) / 2 / main.CANVAS_W, 3)
    alto_real = maxy - miny
    anclaje_ok = maxy <= 986
    fuera = ~mask_pers
    dmax = int(diff[fuera].max()) if fuera.any() else 0
    print(f"{key:12s} | centroX={cx_real:.3f} (exp ~{cx_exp:.2f}) | alto={alto_real:4d} (~{int(898*esc_exp)}) | maxy={maxy:4d} (≤986? {anclaje_ok}) | dmax_fuera={dmax}")
    RES.append((key, cx_real, cx_exp, alto_real, esc_exp, maxy, dmax, anclaje_ok))

print()
print("=" * 100)
print(f"- CentroX DIFERENTES por esc? {len(set(f'{r[1]:.3f}' for r in RES)) > 1}  (3 vals ok)")
print(f"- Alto DIFERENTES por esc?    {len(set(r[3] for r in RES)) > 1}  (3 vals ok)")
print(f"- Anclaje ≤986?              {all(r[7] for r in RES)}  (nunca sobre blanco)")
print(f"- Fondo intacto?             {all(r[6] == 0 for r in RES)}  (diff=0 fuera pers)")
print("=" * 100)
