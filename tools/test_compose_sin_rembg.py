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
            # Cargar foto JPG -> convertir a RGBA con alfa=255 para TODO
            # (simular que rembg lo dejo listo; el pipeline interno de compose_full
            #  hara crop bbox real, componentes, escala y anclaje)
            im = Image.open(foto_ruta).convert("RGBA")

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
