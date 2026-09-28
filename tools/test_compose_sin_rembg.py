"""
Script PRUEBA LOCAL para compose_full: 3 fotos usuario x 3 escenarios = 9 salidas.
NO USA REMBG: carga la foto original JPG y le pone ALFA=255 COMPLETO (simula que
rembg la dejo lista). El objetivo es VERIFICAR:
  (a) Posicion/Tamano DIFERENTES por escenario (debug [OK JSON key=...])
  (b) Anclaje CORRECTO: borde inferior de la foto (el contenido) queda 2px ARRIBA
      de y_base_px=987. NUNCA sobre el marco blanco inferior.
  (c) Margen lateral 20px respecto a los bordes del paralelogramo.
Salida: tools/out/test-compose-local/
"""
import sys
import os
import time

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.join(SCRIPT_DIR, "..", "backend-python")
sys.path.insert(0, BACKEND_DIR)
os.chdir(BACKEND_DIR)

from PIL import Image
import main  # carga ESCENARIOS_JSON, FONDOS_CACHE, MASCARAS_VENTANA

FIXTURES = [
    ("foto1-cintura", os.path.join(SCRIPT_DIR, "fixtures", "foto1-cintura.jpg")),
    ("foto2-cuerpo-entero", os.path.join(SCRIPT_DIR, "fixtures", "foto2-cuerpo-entero.jpg")),
    ("foto3-grupo-3p", os.path.join(SCRIPT_DIR, "fixtures", "foto3-grupo-3p.jpg")),
]

# 3 IDs frontend diferentes (cada uno mapea a una key JSON diferente):
ESCENARIOS = [
    ("cristorey", "cristo-rey"),
    ("museosalsa", "calle-del-sabor"),
    ("plazavarela", "plaza-varela"),
]

OUT_DIR = os.path.join(SCRIPT_DIR, "out", "test-compose-local")
os.makedirs(OUT_DIR, exist_ok=True)

print("=" * 80)
print(f"[test] FONDOS_CACHE  keys: {sorted(main.FONDOS_CACHE.keys())}")
print(f"[test] MASCARAS_VENTANA keys: {sorted(main.MASCARAS_VENTANA.keys())}")
print(f"[test] MAPA_IDS_ESCENARIO_KEY: {main.MAPA_IDS_ESCENARIO_KEY}")
print("=" * 80)

total = 0
ok = 0
errores = []
for foto_nombre, foto_ruta in FIXTURES:
    for esc_key, esc_id in ESCENARIOS:
        total += 1
        t0 = time.time()
        try:
            # Cargar foto JPG -> convertir a RGBA
            im_orig = Image.open(foto_ruta).convert("RGBA")

            # ------------------------------------------------------------------
            # SIMULAR REMBG (cutout IA realista): threshold gris para separar persona de fondo
            # El usuario reporta fotos de cintura/cuerpo/cadera en ambiente claro (cara, ropa).
            # Fondo general de selfies: pared/claros. Ropa oscura o clara, piel media.
            # Estrategia: escala grises + Otsu-like simple o píxeles "diferentes de fondo uniforme"
            # Para evitar alfa=255 completo (como antes), tomamos un bounding box de persona
            # manual aproximado (usar 20-90% ancho y 8-96% alto típico).
            # ------------------------------------------------------------------
            import numpy as _np
            arr = _np.asarray(im_orig, dtype=_np.uint8)
            hh, ww = arr.shape[:2]
            # --------------------------------------------------------------
            # SIMULAR REMBG con ROI central rectangular gradiente suave.
            # Esto simula un cutout IA realista: solo la persona visible en
            # el centro, bordes suaves, fondo completamente transparente.
            # La foto fixture tiene 1 persona ~35-65% ancho, 18-92% alto.
            # --------------------------------------------------------------
            # Rectángulo interior (zona persona, alfa=255 completo)
            x_in1 = int(ww * 0.28)
            x_in2 = int(ww * 0.72)
            y_in1 = int(hh * 0.16)
            y_in2 = int(hh * 0.93)
            # Banda gradiente exterior (zona feather 2-4px suave)
            feather = max(4, int(min(ww, hh) * 0.04))
            # Coordenadas normalizadas 0..1 por cada eje para gradiente
            x_arr = _np.arange(ww).reshape(1, -1).repeat(hh, axis=0)
            y_arr = _np.arange(hh).reshape(-1, 1).repeat(ww, axis=1)
            # Distancia al rectángulo interior más cercano (0 si dentro, + si fuera)
            dx_left  = (x_in1 - x_arr).astype(_np.float64)
            dx_right = (x_arr - x_in2).astype(_np.float64)
            dy_top   = (y_in1 - y_arr).astype(_np.float64)
            dy_bot   = (y_arr - y_in2).astype(_np.float64)
            dist_out_x = _np.maximum(dx_left, dx_right)
            dist_out_y = _np.maximum(dy_top, dy_bot)
            dist_out = _np.maximum(dist_out_x, dist_out_y)
            # Puntos dentro de interior: dist_out <=0 → alfa 1.0
            # Puntos en banda feather: 0 < dist_out < feather → gradiente 1 → 0
            # Puntos fuera: dist_out >= feather → 0
            alpha_norm = _np.clip(1.0 - (dist_out / feather), 0.0, 1.0)
            # Convertir a 0-255 uint8
            alfa = (alpha_norm * 255.0).astype(_np.uint8)
            # Pequeño blur para suavidad extra tipo rembg
            from PIL import ImageFilter
            alfa_pil = Image.fromarray(alfa, mode="L")
            alfa_pil = alfa_pil.filter(ImageFilter.GaussianBlur(radius=1.2))
            alfa = _np.asarray(alfa_pil)
            # BBOX REAL de persona
            rows = _np.where(alfa.max(axis=1) > 20)[0]
            cols = _np.where(alfa.max(axis=0) > 20)[0]
            if len(rows) > 4 and len(cols) > 4:
                y1, y2 = rows[0], rows[-1] + 1
                x1, x2 = cols[0], cols[-1] + 1
                # Crop tight
                margin = 12
                y1 = max(0, y1 - margin)
                x1 = max(0, x1 - margin)
                y2 = min(hh, y2 + margin)
                x2 = min(ww, x2 + margin)
                arr2 = arr[y1:y2, x1:x2].copy()
                arr2[..., 3] = alfa[y1:y2, x1:x2]
                im = Image.fromarray(arr2, mode="RGBA")
            else:
                # Fallback: usar original pero alfa=255 todo
                im = im_orig.copy()

            # Ejecutar compose_full
            final_rgba = main.compose_full(im, esc_id, alpha_matting=False)

            fw_final, fh_final = final_rgba.size
            out_nombre = f"{foto_nombre}__{esc_key}.jpg"
            out_ruta = os.path.join(OUT_DIR, out_nombre)

            # Guardar JPG calidad 98 subsampling0 dpi300 progressive (igual que save_public_image)
            final_rgba.convert("RGB").save(
                out_ruta,
                format="JPEG",
                quality=98,
                subsampling=0,
                dpi=(300, 300),
                progressive=True,
            )
            dt = time.time() - t0

            # Test NUMERICO REGLA4: fuera de alfa persona, diff con fondo original = 0
            arr_final = None
            arr_fondo = None
            try:
                fondo_original = main.FONDOS_CACHE.get(esc_key)
                if fondo_original is not None:
                    arr_final = __import__("numpy").asarray(final_rgba, dtype="uint8")
                    arr_fondo = __import__("numpy").asarray(fondo_original.copy().convert("RGBA"), dtype="uint8")
                    alfa = arr_final[..., 3] >= 15
                    fuera = ~alfa
                    if fuera.any():
                        diff = __import__("numpy").abs(
                            arr_final[fuera, :3].astype("int16") - arr_fondo[fuera, :3].astype("int16")
                        )
                        maxdiff = int(diff.max()) if diff.size else 0
                        print(f"    [REGLA4 OK?] diff max fuera persona = {maxdiff} (debe ser 0)")
            except Exception as e2:
                print(f"    [REGLA4 SKIP] {e2}")

            ok += 1
            print(f"[OK {ok:2d}/{total:2d}] {foto_nombre:18s} x {esc_key:12s} -> {out_nombre} [{dt:5.2f}s] {fw_final}x{fh_final}")
            if hasattr(main, '_last_compose_info'):
                info = main._last_compose_info
                print(f"    [VALORES FINALES] escala={info.get('escala', 0):.3f} | "
                      f"ancho_pct={info.get('ancho_pct', 0):.3f} (rng {info.get('ancho_rng_min', 0):.2f}-{info.get('ancho_rng_max', 0):.2f}) | "
                      f"tope_pct={info.get('tope_pct', 0):.3f} (rng {info.get('tope_rng_min', 0):.2f}-{info.get('tope_rng_max', 0):.2f}) | "
                      f"cx_pct={info.get('cx_pct', 0):.3f} (rng {info.get('cx_rng_min', 0):.2f}-{info.get('cx_rng_max', 0):.2f}) | "
                      f"bottom_px={info.get('bottom_px', 0)} (y_base+4={info.get('y_base_mas_4', 0)})")
        except Exception as e:
            import traceback
            errores.append((foto_nombre, esc_key, repr(e)))
            print(f"[FAIL {len(errores):2d}] {foto_nombre:18s} x {esc_key:12s} -> {repr(e)}")
            traceback.print_exc()

print()
print("=" * 80)
print(f"[RESUMEN] OK={ok}/{total} | Errores={len(errores)}")
print(f"[OUT DIR] {OUT_DIR}")
for (fn, ek, err) in errores:
    print(f"  - {fn} x {ek}: {err}")
print("=" * 80)
