@echo off
rem ============================================================================
rem  LicitApp - construir el ejecutable de Windows e instalarlo (sin administrador)
rem  Uso: doble clic, o desde la carpeta del proyecto:  CONSTRUIR_E_INSTALAR.bat
rem  Opciones:  /pruebas  corre las pruebas antes de construir
rem             /silencioso  no pide pulsar una tecla al final
rem  Se puede repetir las veces que haga falta (es idempotente).
rem ============================================================================
setlocal EnableExtensions
cd /d "%~dp0"
set "RAIZ=%CD%"
set "LOG=%RAIZ%\construir_e_instalar_log.txt"
set "APP=%LOCALAPPDATA%\Programs\LicitApp"
set "PRUEBAS=0"
set "SILENCIOSO=0"
:args
if "%~1"=="" goto args_fin
if /i "%~1"=="/pruebas" set "PRUEBAS=1"
if /i "%~1"=="/silencioso" set "SILENCIOSO=1"
shift
goto args
:args_fin

echo ==== LicitApp: construir e instalar ==== > "%LOG%"
call :log "Carpeta del proyecto: %RAIZ%"
call :log "Registro completo en: %LOG%"

if not exist "%RAIZ%\requirements.txt" goto err_carpeta
if not exist "%RAIZ%\build\secop.spec" goto err_carpeta

rem ---- 1. Python 3.10 a 3.12 --------------------------------------------------
call :log "[1/7] Buscando Python 3.10 a 3.12..."
set "PY="
call :probar "py -3.11"
call :probar "py -3.12"
call :probar "py -3.10"
call :probar "python"
if "%PY%"=="" goto err_python
call :log "      Usando: %PY%"

rem ---- 2. Entorno virtual -----------------------------------------------------
call :log "[2/7] Entorno virtual (.venv)..."
if not exist "%RAIZ%\.venv\Scripts\python.exe" %PY% -m venv "%RAIZ%\.venv" >> "%LOG%" 2>&1
if not exist "%RAIZ%\.venv\Scripts\python.exe" goto err_venv
set "VPY=%RAIZ%\.venv\Scripts\python.exe"

rem ---- 3. Dependencias --------------------------------------------------------
call :log "[3/7] Instalando dependencias (la primera vez tarda varios minutos)..."
"%VPY%" -m pip install --upgrade pip >> "%LOG%" 2>&1
"%VPY%" -m pip install -r "%RAIZ%\requirements.txt" pyinstaller pytest >> "%LOG%" 2>&1
if errorlevel 1 goto err_pip

if "%PRUEBAS%"=="1" call :log "      Corriendo pruebas..."
if "%PRUEBAS%"=="1" "%VPY%" -m pytest -q "%RAIZ%\tests" >> "%LOG%" 2>&1
if "%PRUEBAS%"=="1" if errorlevel 1 goto err_pruebas

rem ---- 4. Construir -----------------------------------------------------------
call :log "[4/7] Construyendo LicitApp.exe con PyInstaller (unos 5 a 10 minutos)..."
taskkill /im LicitApp.exe /f >nul 2>&1
"%VPY%" -m PyInstaller "%RAIZ%\build\secop.spec" --clean --noconfirm --distpath "%RAIZ%\dist" --workpath "%TEMP%\licitapp_pyinstaller" >> "%LOG%" 2>&1
if not exist "%RAIZ%\dist\LicitApp\LicitApp.exe" goto err_build
call :log "      Listo: %RAIZ%\dist\LicitApp\LicitApp.exe"

rem ---- 5. Verificar que el ejecutable arranca ---------------------------------
call :log "[5/7] Verificando que el ejecutable arranca y responde..."
powershell -NoProfile -ExecutionPolicy Bypass -File "%RAIZ%\build\verificar_exe.ps1" -Exe "%RAIZ%\dist\LicitApp\LicitApp.exe" >> "%LOG%" 2>&1
if errorlevel 1 goto err_verificar
call :log "      El ejecutable respondio HTTP 200."

rem ---- 6. Instalar en %LOCALAPPDATA%\Programs\LicitApp (conserva data y licencia) --
call :log "[6/7] Instalando en %APP% ..."
taskkill /im LicitApp.exe /f >nul 2>&1
robocopy "%RAIZ%\dist\LicitApp" "%APP%" /MIR /XD "%APP%\data" /XF mi_licencia.lic /NFL /NDL /NJH /NJS /NP >> "%LOG%" 2>&1
if errorlevel 8 goto err_copia
if not exist "%APP%\LicitApp.exe" goto err_copia

rem ---- 7. Expedientes y accesos directos --------------------------------------
call :log "[7/7] Expedientes y accesos directos..."
for /f "usebackq delims=" %%D in (`powershell -NoProfile -Command "[Environment]::GetFolderPath('MyDocuments')"`) do set "DOCS=%%D"
if "%DOCS%"=="" set "DOCS=%USERPROFILE%\Documents"
if exist "%RAIZ%\expedientes" robocopy "%RAIZ%\expedientes" "%DOCS%\LicitApp\expedientes" /E /XC /XN /XO /XD propuestas /NFL /NDL /NJH /NJS /NP >> "%LOG%" 2>&1
if errorlevel 8 goto err_expedientes
call :log "      Expedientes en: %DOCS%\LicitApp\expedientes (no se sobrescribe nada)"

powershell -NoProfile -ExecutionPolicy Bypass -Command "$w=New-Object -ComObject WScript.Shell; foreach($d in @([Environment]::GetFolderPath('Desktop'),[Environment]::GetFolderPath('Programs'))){ $s=$w.CreateShortcut((Join-Path $d 'LicitApp.lnk')); $s.TargetPath='%APP%\LicitApp.exe'; $s.WorkingDirectory='%APP%'; $s.Description='LicitApp - Licitaciones Colombia'; $s.Save() }" >> "%LOG%" 2>&1
if errorlevel 1 call :log "      AVISO: no se pudieron crear los accesos directos. Abra %APP%\LicitApp.exe"

call :log ""
call :log "=== LISTO ==="
call :log "Programa instalado en: %APP%\LicitApp.exe"
call :log "Accesos directos: Escritorio y Menu Inicio (LicitApp)"
call :log "Datos del usuario: %APP%\data   Expedientes: %DOCS%\LicitApp\expedientes"
call :log "Registro: %LOG%"
goto fin

:err_carpeta
call :log "ERROR: ejecute este archivo desde la carpeta del proyecto (donde estan requirements.txt y build\secop.spec)."
goto fin_error
:err_python
call :log "ERROR: no hay Python 3.10 a 3.12. Instale Python 3.11 desde https://www.python.org/downloads/ (marque Add python.exe to PATH) y repita."
goto fin_error
:err_venv
call :log "ERROR: no se pudo crear el entorno virtual. Vea el registro."
goto fin_error
:err_pip
call :log "ERROR: fallo la instalacion de dependencias (vea el registro; revise la conexion a internet)."
goto fin_error
:err_pruebas
call :log "ERROR: las pruebas fallaron. No se construye. Vea el registro."
goto fin_error
:err_build
call :log "ERROR: PyInstaller no genero LicitApp.exe. Vea el registro (al final)."
goto fin_error
:err_verificar
call :log "ERROR: el ejecutable se construyo pero no arranca. No se instala. Vea el registro y data\streamlit_worker.log."
goto fin_error
:err_copia
call :log "ERROR: no se pudo copiar a %APP% (cierre LicitApp si esta abierto)."
goto fin_error
:err_expedientes
call :log "ERROR: no se pudieron copiar los expedientes a %DOCS%\LicitApp\expedientes."
goto fin_error

:fin_error
set "CODIGO=1"
goto pausa
:fin
set "CODIGO=0"
:pausa
if "%SILENCIOSO%"=="0" pause
endlocal & exit /b %CODIGO%

rem ---- subrutinas -------------------------------------------------------------
:log
echo.%~1
echo [%date% %time%] %~1 >> "%LOG%"
exit /b 0

:probar
if not "%PY%"=="" exit /b 0
%~1 -c "import sys; sys.exit(0 if (3,10) <= sys.version_info[:2] <= (3,12) else 1)" >nul 2>&1
if errorlevel 1 exit /b 0
set "PY=%~1"
exit /b 0
