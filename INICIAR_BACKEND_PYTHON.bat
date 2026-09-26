@ECHO OFF
SETLOCAL ENABLEEXTENSIONS ENABLEDELAYEDEXPANSION
TITLE ABV Fiesta - Backend IA U2Net (MODO EVENTO LOCAL)

REM ===========================================================================
REM  ARCHIVO DE INICIO RAPIDO PARA EL EVENTO
REM  Doble click para levantar el servidor de IA FastAPI + Uvicorn.
REM  NO CIERRES ESTA VENTANA MIENTRAS ESTE EN USO EL EVENTO.
REM ===========================================================================

REM --- Ubicacion del script (raiz del proyecto) ---
CD /D "%~dp0"
SET "PROYECTO_RAIZ=%CD%"
SET "BACKEND_DIR=%PROYECTO_RAIZ%\backend-python"
SET "VENV_DIR=%BACKEND_DIR%\.venv"
SET "VENV_PY=%VENV_DIR%\Scripts\python.exe"
SET "VENV_UVICORN=%VENV_DIR%\Scripts\uvicorn.exe"

ECHO.
ECHO  ========================================================================
ECHO    AGUARDIENTE BLANCO DEL VALLE - BACKEND IA U2NET (MODO LOCAL)
ECHO  ========================================================================
ECHO   Proyecto    : %PROYECTO_RAIZ%
ECHO   Python VENV : %VENV_PY%
ECHO   URL local   : http://localhost:8000
ECHO   Health      : http://localhost:8000/health
ECHO   Stats fotos : http://localhost:8000/api/fotos-stats
ECHO  ========================================================================
ECHO.

REM --- 1) Verificar que exista el entorno virtual ---
IF NOT EXIST "%VENV_PY%" (
    ECHO [ERROR] NO SE ENCONTRO EL ENTORNO VIRTUAL .venv
    ECHO.
    ECHO Se requiere crear el venv la PRIMERA VEZ que se usa:
    ECHO   cd backend-python
    ECHO   python -m venv .venv
    ECHO   .\.venv\Scripts\python.exe -m pip install --no-cache-dir -r requirements.txt
    ECHO.
    PAUSE
    EXIT /B 1
)

REM --- 2) Variables de entorno compatibles Railway ---
SET "PUBLIC_URL=http://localhost:8000"
SET "RAILWAY_PUBLIC_DOMAIN=localhost:8000"
SET "STORAGE_DIR=%BACKEND_DIR%\public-fotos"
SET "PUBLIC_ASSETS_DIR=%PROYECTO_RAIZ%\public\assets"
IF NOT EXIST "%STORAGE_DIR%" MKDIR "%STORAGE_DIR%"

REM --- 3) Puerto configurable (Railway usa PORT automaticamente) ---
IF "%PORT%"=="" SET "PORT=8000"

REM --- 3.5) Si el puerto YA ESTA OCUPADO por un backend viejo, MATARLO automaticamente ---
SET "PID_OWNER="
FOR /F "tokens=5" %%P IN ('NETSTAT -ano ^| FINDSTR /R /C:":[0-9][0-9]* .*LISTENING" ^| FINDSTR /R /C:":%PORT% "') DO (
    SET "PID_OWNER=%%P"
)
IF DEFINED PID_OWNER (
    ECHO  [AVISO] Puerto %PORT% ocupado por PID %PID_OWNER%. Terminandolo automaticamente...
    TASKKILL /F /PID %PID_OWNER% >NUL 2>&1
    TIMEOUT /T 2 /NOBREAK >NUL
)

REM --- 4) Mostrar IP WiFi para otras tabletas en la misma red ---
FOR /F "tokens=2 delims=:" %%a in ('IPCONFIG ^| FINDSTR /R /C:"IPv4"') DO (
    FOR /F "tokens=* delims= " %%b in ("%%a") do (
        ECHO  [RED] Tu IP en la red local: http://%%b:%PORT%
    )
)

ECHO.
ECHO [INFO] Iniciando servidor IA. No cierres esta ventana hasta terminar el evento.
ECHO [INFO] Para salir: CTRL + C
ECHO.

REM --- 5) Arrancar Uvicorn (1 worker porque U2Net NO soporta multiproceso bien) ---
"%VENV_UVICORN%" main:app --host 0.0.0.0 --port %PORT% --workers 1 --loop asyncio --log-level info --app-dir "%BACKEND_DIR%"

ECHO.
ECHO [INFO] Servidor se detuvo. Presiona una tecla para cerrar.
PAUSE >NUL
ENDLOCAL
