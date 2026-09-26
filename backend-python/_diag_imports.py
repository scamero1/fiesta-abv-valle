import sys, os
print("=" * 70)
print("  DIAGNOSTICO - Modulos Python VENV / Global")
print("=" * 70)
print("  Python EXE: " + sys.executable)
print("  Version: " + sys.version.split()[0])
print()
PYVENV = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".venv", "Scripts", "python.exe")
print("  Venv esperado: " + PYVENV)
print("  Existe .venv? " + str(os.path.exists(PYVENV)))
print()

def try_import(modname, extra_ok=None):
    try:
        m = __import__(modname)
        extra_val = None
        if extra_ok:
            extra_val = extra_ok(m)
        return True, None, extra_val
    except ImportError as e:
        return False, str(e), None
    except Exception as e:
        return False, type(e).__name__ + ": " + str(e), None

checks = [
    ("rembg + U2Net model", "rembg", lambda m: m.new_session("u2net").__class__.__name__),
    ("Pillow (PIL)",       "PIL", None),
    ("onnxruntime",        "onnxruntime", None),
    ("numpy",              "numpy", None),
    ("fastapi",            "fastapi", None),
    ("uvicorn",            "uvicorn", None),
    ("psycopg (Postgres)", "psycopg", None),
]

any_fail = False
for display, mod, fn in checks:
    ok, err, extra = try_import(mod, fn)
    s = "OK  " if ok else "FALTA"
    if ok and extra:
        print("  [" + s + "]  " + display + "  (" + extra + ")")
    elif ok:
        print("  [" + s + "]  " + display)
    else:
        any_fail = True
        print("  [" + s + "]  " + display + "  -> " + str(err))

print()
if os.path.normcase(sys.executable) == os.path.normcase(PYVENV):
    print("  >> ESTE ES EL PYTHON DEL VENV (CORRECTO)")
else:
    any_fail = True
    print("  >> CUIDADO: NO estas usando el VENV! Usa .venv\\Scripts\\python.exe")
print()
sys.exit(1 if any_fail else 0)
