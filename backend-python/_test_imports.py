import sys
packages = ['rembg','PIL','onnxruntime','psycopg','fastapi','uvicorn','numpy']
for name in packages:
    try:
        mod = __import__(name)
        v = getattr(mod, '__version__', 'n/a')
        print(f'OK {name} {v}')
    except Exception as e:
        print(f'FAIL {name}: {e}', file=sys.stderr)
        sys.exit(1)
print('=== TODAS LAS DEPENDENCIAS OK ===')
