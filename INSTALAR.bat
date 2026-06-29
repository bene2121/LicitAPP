@echo off
echo ============================================
echo   SECOP Automatizador v1.0 - Instalacion
echo ============================================
echo.
echo Instalando dependencias Python...
pip install -r requirements.txt
echo.
echo Verificando instalacion...
python -c "import streamlit, pandas, numpy, scipy, requests, plotly; print('OK - todo instalado')"
echo.
echo ============================================
echo   Para iniciar la aplicacion, ejecute:
echo   INICIAR.bat
echo ============================================
pause
