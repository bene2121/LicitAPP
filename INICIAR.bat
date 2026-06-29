@echo off
echo Iniciando SECOP Automatizador...
echo Abriendo en http://localhost:8501
cd /d "%~dp0"
python -m streamlit run m5_dashboard/app.py --server.port 8501 --browser.gatherUsageStats false
pause
