"""
tools/ajuste_manual_escenarios.py
==================================
Parchea el JSON y las máscaras PNG usando valores MEDIDOS MANUALMENTE
basados en la indicación del PROMPT MAESTRO y los 3 JPG reales.
Los 3 diseños comparten la MISMA plantilla de marco (solo cambia el paisaje interior).
"""
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
ASSETS_BACKEND = ROOT / "backend-python" / "assets"
TOOLS_OUT = ROOT / "tools" / "out"
CANVAS_W, CANVAS_H = 1920, 1080

ESCENARIOS = [
    ("cristorey",  "esc-cristorey.jpg",  ["sunset", "cristo-rey"]),
    ("museosalsa", "esc-museosalsa.jpg", ["neon",   "calle-del-sabor"]),
    ("plazavarela","esc-plazavarela.jpg",["feria",  "plaza-varela"]),
]

def cover_resize(img: Image.Image, tw: int, th: int) -> Image.Image:
    iw, ih = img.size
    scale = max(tw / iw, th / ih)
    nw, nh = max(1, int(round(iw * scale))), max(1, int(round(ih * scale)))
    rz = img.resize((nw, nh), Image.LANCZOS)
    cx, cy = (nw - tw) // 2, (nh - th) // 2
    return rz.crop((cx, cy, cx + tw, cy + th))


def main():
    # Valores manuales medidos (paralelogramo = bordes inclinados):
    TL = (96, 89)    # top-left (x,y)
    TR = (1822, 89)  # top-right
    BR = (1868, 987) # bottom-right (inferior: un poco más a la dcha -> inclinación borde dcho)
    BL = (52, 987)   # bottom-left  (inferior: un poco más a la izq -> inclinación borde izq)
    Y_BASE_PX = 987       # borde inferior horizontal ventana
    Y_TOP_PX = 89         # borde superior ventana
    # Keep-outs (bbox = x1,y1,x2,y2):
    SLOGAN = (int(CANVAS_W * 0.07), int(CANVAS_H * 0.13),
              int(CANVAS_W * 0.26), int(CANVAS_H * 0.40))   # 134..499 / 140..432
    PASTILLA = (int(CANVAS_W * 0.80), int(CANVAS_H * 0.02),
                int(CANVAS_W * 0.985), int(CANVAS_H * 0.22))# 1536..1892 / 22..238
    TITULO = (0, 0, CANVAS_W, int(CANVAS_H * 0.08))          # y 0..86
    LEGAL  = (0, int(CANVAS_H * 0.945), CANVAS_W, CANVAS_H)  # y 1021..1080

    def pct(xy):
        return [round(xy[0] / CANVAS_W, 4), round(xy[1] / CANVAS_H, 4)]
    def pct_bbox(bb):
        return [round(bb[0] / CANVAS_W, 4), round(bb[1] / CANVAS_H, 4),
                round(bb[2] / CANVAS_W, 4), round(bb[3] / CANVAS_H, 4)]

    valores_recomendados = {
        "cristorey":  {"escala_altura_ventana": [0.55, 0.62], "centro_horizontal_pct_canvas": [0.50, 0.55], "cabeza_pct_canvas": [0.16, 0.23]},
        "museosalsa": {"escala_altura_ventana": [0.58, 0.65], "centro_horizontal_pct_canvas": [0.30, 0.38], "cabeza_pct_canvas": [0.16, 0.23]},
        "plazavarela":{"escala_altura_ventana": [0.80, 0.88], "centro_horizontal_pct_canvas": [0.42, 0.45], "cabeza_pct_canvas": [0.16, 0.23]},
    }

    salida = {}
    for key, fname, ids in ESCENARIOS:
        # a) Regenerar mascara PNG L (ventana - keepout pastilla)
        mask = Image.new("L", (CANVAS_W, CANVAS_H), 0)
        d = ImageDraw.Draw(mask)
        d.polygon([TL, TR, BR, BL], fill=255)
        d.rectangle(PASTILLA, fill=0)  # Mascara "zona permitida" = ventana - keepout logo
        mask_path = ASSETS_BACKEND / f"mask_{key}.png"
        mask.save(mask_path)
        print(f"[{key}] Guardada mascara: {mask_path.name}")

        # b) PNG depuracion: fondo + mascara en rojo + rectángulos keepouts (verde slogan, dorado pastilla)
        src = ASSETS_BACKEND / fname
        if not src.exists():
            src = ROOT / "public" / "assets" / fname
        with Image.open(src) as im:
            fondo_1920 = cover_resize(im.convert("RGB"), CANVAS_W, CANVAS_H).convert("RGBA")
        red = Image.new("RGBA", (CANVAS_W, CANVAS_H), (228, 0, 43, 0))
        # Rellenar rojo semitransparente DENTRO de mascara
        red.paste((228, 0, 43, 128), (0, 0), mask)
        fondo_1920.alpha_composite(red)
        dd = ImageDraw.Draw(fondo_1920)
        dd.rectangle(SLOGAN, outline=(34, 197, 94, 255), width=3)
        dd.rectangle(PASTILLA, outline=(212, 160, 23, 255), width=3)
        dd.line([TL, TR, BR, BL, TL], fill=(255, 255, 255, 255), width=2)
        dbg_path = TOOLS_OUT / f"dbg_mask_{key}.png"
        fondo_1920.convert("RGB").save(dbg_path, quality=95)
        print(f"       Guardada depuracion: {dbg_path}")

        salida[key] = {
            "ids_frontend": ids,
            "archivo_fondo": fname,
            "canvas": {"w": CANVAS_W, "h": CANVAS_H},
            "ventana_paisaje_px": {
                "esquinas_tl_tr_br_bl": [list(TL), list(TR), list(BR), list(BL)],
                "y_top_paisaje": Y_TOP_PX,
                "y_base_borde_inf": Y_BASE_PX,
                "ancho_ventana_inf_px": BR[0] - BL[0],
                "alto_ventana_px": Y_BASE_PX - Y_TOP_PX,
            },
            "ventana_paisaje_pct": {
                "esquinas_tl_tr_br_bl": [pct(TL), pct(TR), pct(BR), pct(BL)],
                "y_top_pct": round(Y_TOP_PX / CANVAS_H, 4),
                "y_base_pct": round(Y_BASE_PX / CANVAS_H, 4),
            },
            "keep_out_slogan_px":    {"bbox": list(SLOGAN)},
            "keep_out_slogan_pct":   {"bbox": pct_bbox(SLOGAN)},
            "keep_out_logo_px":      {"bbox": list(PASTILLA)},
            "keep_out_logo_pct":     {"bbox": pct_bbox(PASTILLA)},
            "franja_titulo_px":      {"bbox": list(TITULO)},
            "franja_legal_px":       {"bbox": list(LEGAL)},
            "y_base_px": Y_BASE_PX,
            "y_base_pct": round(Y_BASE_PX / CANVAS_H, 4),
            "valores_recomendados": valores_recomendados[key],
        }
    salida["__meta__"] = {
        "canvas_w": CANVAS_W,
        "canvas_h": CANVAS_H,
        "generado_por": "tools/ajuste_manual_escenarios.py (valores medidos manualmente)",
    }

    json_path = ASSETS_BACKEND / "escenarios.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(salida, f, ensure_ascii=False, indent=2)
    print(f"\nJSON actualizado: {json_path}")
    print("Revisar tools/out/dbg_mask_*.png para confirmar la mascara coincide con marco blanco y keepouts.")
    return 0

if __name__ == "__main__":
    sys.exit(main())
