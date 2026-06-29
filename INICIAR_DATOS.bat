@echo off
echo Sincronizando datos con SECOP (puede tardar unos minutos)...
cd /d "%~dp0"
python m1_ingestor/ingestor.py
echo.
echo Datos actualizados. Ahora puede abrir la aplicacion con INICIAR.bat
pause
