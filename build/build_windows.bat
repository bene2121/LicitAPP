@echo off
setlocal

echo ============================================
echo   LicitApp — Build Windows .exe
echo ============================================
echo.

:: Verificar Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python no encontrado. Instala Python 3.11+
    pause
    exit /b 1
)

:: Moverse a la raiz del proyecto
cd /d "%~dp0.."

echo [1/4] Instalando dependencias de build...
pip install pyinstaller pywebview --quiet
if errorlevel 1 (
    echo [ERROR] No se pudieron instalar las dependencias
    pause
    exit /b 1
)

echo [2/4] Limpiando builds anteriores...
if exist "dist\LicitApp" rmdir /s /q "dist\LicitApp"
if exist "build\__pycache__"        rmdir /s /q "build\__pycache__"

echo [3/4] Empaquetando con PyInstaller...
pyinstaller build\secop.spec --clean --noconfirm
if errorlevel 1 (
    echo [ERROR] PyInstaller fallo. Revisa los errores arriba.
    pause
    exit /b 1
)

echo [4/4] Listo.
echo.
echo Ejecutable en: dist\LicitApp\LicitApp.exe
echo.
echo Para crear el instalador .exe:
echo   1. Instala Inno Setup 6 desde https://jrsoftware.org/isinfo.php
echo   2. Abre build\setup.iss con Inno Setup
echo   3. Presiona F9 para compilar
echo   4. El instalador estara en dist\installer\
echo.
pause
