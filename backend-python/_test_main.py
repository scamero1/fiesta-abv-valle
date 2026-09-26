import sys, os, asyncio
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    import main
    print('✅ main.py import OK')
    print('  - app:', type(main.app).__name__)
    print('  - DB engine:', main.DB_ENGINE)
    print('  - MODEL_NAME:', main.MODEL_NAME)
    print('  - CANVAS_W x CANVAS_H:', main.CANVAS_W, 'x', main.CANVAS_H)
    print('  - ESCENARIOS:', list(main.ESCENARIO_CONFIG.keys()))
except Exception as e:
    print('❌ main.py syntax error:', type(e).__name__, str(e))
    import traceback; traceback.print_exc()
    sys.exit(1)
