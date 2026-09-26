@echo off
chcp 65001 >nul
cls
title Aguardiente Blanco Fiesta - Servidor Offline

cd /d "%~dp0"

echo.
echo ==============================================
echo   AGUARDIENTE BLANCO FIESTA  -  SERVIDOR OFFLINE
echo ==============================================
echo.

REM ---- Paso 1: Instalar dependencias si falta node_modules ----
if not exist "node_modules" (
  echo [1/4] Instalando dependencias por primera vez...
  call npm.cmd install --omit=dev
  if errorlevel 1 goto :error
)

REM ---- Paso 2: Build produccion si no existe dist ----
if not exist "dist\index.html" (
  echo [2/4] Compilando aplicacion...
  call npm.cmd run build
  if errorlevel 1 goto :error
) else (
  echo [2/4] Build ya existe - omitido
)

REM ---- Paso 3: Mostrar IPs para acceso desde celulares ----
echo [3/4] Detectando interfaces de red...
echo.
echo   Para que los celulares lean el QR y descarguen fotos SIN INTERNET:
echo   1. En esta tablet activa "Hotspot movil" o conecta ambos a la misma red Wi-Fi privada
echo   2. Los celulares escanean el QR y abren el link del servidor de esta tablet
echo.
powershell -Command "Get-NetIPConfiguration | Where-Object { $_.IPv4DefaultGateway -ne $null } | Select-Object -ExpandProperty IPv4Address | Select-Object -ExpandProperty IPAddress | ForEach-Object { Write-Host '        -> Tablet IP: ' $_ }"

REM ---- Paso 4: Lanzar servidor en 0.0.0.0:3000 ----
echo.
echo [4/4] Iniciando servidor web local en PUERTO 3000...
echo.
call node.exe offline-server.js

goto :eof

:error
echo.
echo [!] Ocurrio un error durante el despliegue. Revisa arriba.
pause
exit /b 1
