@ECHO OFF
SETLOCAL ENABLEEXTENSIONS ENABLEDELAYEDEXPANSION
TITLE Check Instalacion - ABV Fiesta Backend IA
CD /D "%~dp0"
SET "ROOT=%CD%"
SET "BACK=%ROOT%\backend-python"
SET "VPY=%BACK%\.venv\Scripts\python.exe"
SET "VUV=%BACK%\.venv\Scripts\uvicorn.exe"
SET "PORT=8000"
SET "PASS=0"
SET "FAIL=0"

ECHO.
ECHO  ========================================================================
ECHO    CHECK INSTALACION - BACKEND IA ABV FIESTA  (doble click seguro)
ECHO  ========================================================================
ECHO.

ECHO  [1/7] Python VENV:
IF EXIST "%VPY%" ( ECHO   [OK  ] "%VPY%" & SET /A PASS+=1 ) ELSE ( ECHO   [FALLO] Falta "%VPY%" & SET /A FAIL+=1 )

ECHO  [2/7] Uvicorn VENV:
IF EXIST "%VUV%" ( ECHO   [OK  ] "%VUV%" & SET /A PASS+=1 ) ELSE ( ECHO   [FALLO] Falta "%VUV%" & SET /A FAIL+=1 )

ECHO.
ECHO  [3/7] Modulos Python VENV (rembg + U2Net + dependencias):
ECHO.
"%VPY%" "%BACK%\_diag_imports.py"
IF %ERRORLEVEL% EQU 0 ( SET /A PASS+=1 & ECHO. & ECHO   [OK  ] Modulos Python VENV todos OK ) ELSE ( SET /A FAIL+=1 & ECHO. & ECHO   [FALLO] Faltan modulos en VENV ^(ve arriba cuales^) )

ECHO.
ECHO  [4/7] Carpeta public-fotos (almacen JPGs finales):
IF EXIST "%BACK%\public-fotos\" ( ECHO   [OK  ] "%BACK%\public-fotos\" & SET /A PASS+=1 ) ELSE ( ECHO   [FALLO] Falta carpeta & SET /A FAIL+=1 )

ECHO  [5/7] Base datos SQLite fotos-local.sqlite3:
IF EXIST "%BACK%\fotos-local.sqlite3" ( ECHO   [OK  ] "%BACK%\fotos-local.sqlite3" & SET /A PASS+=1 ) ELSE ( ECHO   [INFO  ] Aun no existe (se crea al primer POST /api/procesar-foto) & SET /A PASS+=1 )

ECHO  [6/7] Archivo .env frontend con VITE_PROCESS_URL:
IF EXIST "%ROOT%\.env" ( ECHO   [OK  ] "%ROOT%\.env" & SET /A PASS+=1 ) ELSE ( ECHO   [FALLO] Falta, crea archivo .env con linea: VITE_PROCESS_URL=http://127.0.0.1:8000 & SET /A FAIL+=1 )

ECHO.
ECHO  [7/7] IPs WiFi IPv4 locales (tabletas MISMA RED):
ECHO.
FOR /F "tokens=2 delims=:" %%a in ('IPCONFIG ^| FINDSTR /R /C:"IPv4"') DO @(
  FOR /F "tokens=* delims= " %%b in ("%%a") DO @ECHO   - %%b    Frontend: http://%%b:5173   Backend: http://%%b:%PORT%/health
)

ECHO.
ECHO  --- Puerto %PORT% TCP (backend IA) ---
SET "PIDP=NONE"
FOR /F "usebackq tokens=5" %%P IN (`NETSTAT -ano 2^>NUL ^| FINDSTR /R /C:"LISTENING" ^| FINDSTR /L /C:":%PORT% "`) DO SET "PIDP=%%P"
IF "%PIDP%"=="NONE" (
  ECHO   [LIBRE] Puerto %PORT% libre. Levanta con: doble click INICIAR_BACKEND_PYTHON.bat
) ELSE (
  ECHO   [EN USO] Ocupado por PID %PIDP% (Backend VIVO, comprueba /health abajo)
)

ECHO.
ECHO  --- GET http://127.0.0.1:%PORT%/health (timeout 3s):
ECHO.
curl.exe -s -m 3 "http://127.0.0.1:%PORT%/health"
ECHO.

ECHO.
ECHO  ========================================================================
ECHO    PASOS OK = !PASS!      FALLOS = !FAIL!
ECHO  ========================================================================
IF !FAIL! GTR 0 (
  ECHO.
  ECHO  [ATENCION] Hay !FAIL! fallos. Si fallan modulos, re-crea VENV:
  ECHO     cd %BACK%
  ECHO     RD /S /Q .venv
  ECHO     C:\Program Files\Python313\python.exe -m venv .venv
  ECHO     .\.venv\Scripts\python.exe -m pip install --no-cache-dir -r requirements.txt
  ECHO.
  ECHO  Si falla Firewall para tabletas (acceso denegado):
  ECHO     Doble click DERECHO - Ejecutar como ADMIN: ABRIR_FIREWALL_puerto_8000.bat
) ELSE (
  ECHO.
  ECHO  [TODO OK] ^(PASOS OK 7/7^) Instalacion perfecta.
  ECHO   1) Doble click en: INICIAR_BACKEND_PYTHON.bat
  ECHO   2) Nueva terminal: cd %ROOT%  ^&  npm run dev
  ECHO   3) Tabletas MISMA RED WiFi: abrir la IP [7/7] en Chrome al puerto 5173
)
ECHO.
ECHO  Pulsa cualquier tecla para salir...
PAUSE >NUL
ENDLOCAL
