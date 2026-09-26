@ECHO OFF
SETLOCAL ENABLEEXTENSIONS
TITLE Abrir Firewall Puertos 8000 y 5173 - ABV Fiesta

REM ============================================================================
REM  COMO USAR: Doble click normal (UAC se activa solo).
REM  Abre PUERTO 8000 (Backend IA) y PUERTO 5173 (Frontend Vite)
REM ============================================================================

REM --- 1) Si NO somos Admin, re-lanzamos con UAC elevacion automaticamente ---
net session >NUL 2>&1
IF %ERRORLEVEL% NEQ 0 (
    ECHO [INFO] No eres ADMINISTRADOR. Re-lanzando con elevacion UAC...
    powershell -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    EXIT /B
)

REM --- 2) Borramos reglas ANTERIORES para evitar duplicados ---
ECHO [1/4] Limpiando reglas antiguas...
netsh advfirewall firewall delete rule name="ABV-Fiesta-Backend-IA" >NUL 2>&1
netsh advfirewall firewall delete rule name="ABV-Fiesta-Vite-5173" >NUL 2>&1
netsh advfirewall firewall delete rule name="ABV Fiesta Backend 8000" >NUL 2>&1
netsh advfirewall firewall delete rule name="ABV Fiesta Vite 5173" >NUL 2>&1

ECHO [2/4] Puerto 8000 TCP  -> Backend IA (Uvicorn / FastAPI)
netsh advfirewall firewall add rule name="ABV-Fiesta-Backend-IA" dir=in action=allow protocol=TCP localport=8000 profile=private,domain >NUL 2>&1

ECHO [3/4] Puerto 5173 TCP  -> Frontend React (Vite Dev Server)
netsh advfirewall firewall add rule name="ABV-Fiesta-Vite-5173" dir=in action=allow protocol=TCP localport=5173 profile=private,domain >NUL 2>&1

ECHO [4/4] Verificando reglas...
FOR %%P IN (8000, 5173) DO (
    netsh advfirewall firewall show rule name=ABV-Fiesta-Backend-IA | findstr "%%P" >NUL 2>&1
    netsh advfirewall firewall show rule name=ABV-Fiesta-Vite-5173   | findstr "%%P" >NUL 2>&1
)

ECHO.
ECHO  ========================================================================
ECHO    AGUARDIENTE BLANCO DEL VALLE - FIESTA - FIREWALL ACCESSO TABLET
ECHO  ========================================================================
ECHO    Backend IA (Fotos + U2Net)  :  http://TU-IP:8000/health
ECHO    Frontend React PWA           :  http://TU-IP:5173/   <- USAR ESTE EN TABLETA
ECHO  ========================================================================
ECHO    [EXITO] Puertos 8000 y 5173 TCP ahora son ACCESIBLES desde tablets.
ECHO    Configura tu red WiFi como PRIVADA si aun falla (Ajustes > WiFi > Perfil).
ECHO  ========================================================================
ECHO.
PAUSE
ENDLOCAL
