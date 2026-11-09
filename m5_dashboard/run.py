#!/usr/bin/env python3
"""Lanzar el dashboard SECOP Automatizador (solo accesible desde este equipo)."""
import subprocess, sys, os  # nosec B404 - argumentos fijos
RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(RAIZ)  # la raíz tiene .streamlit/config.toml y los paquetes licencias/, m1..m7
print("🏗️  Iniciando SECOP Automatizador en http://localhost:8501")
subprocess.run([  # nosec B603 - sin datos del usuario
    sys.executable, "-m", "streamlit", "run", os.path.join("m5_dashboard", "app.py"),
    "--server.port", "8501",
    "--server.address", "127.0.0.1",
    "--server.enableXsrfProtection", "true",
    "--browser.gatherUsageStats", "false",
])
