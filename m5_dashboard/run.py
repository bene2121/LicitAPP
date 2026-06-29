#!/usr/bin/env python3
"""Lanzar el dashboard SECOP Automatizador."""
import subprocess, sys, os
os.chdir(os.path.dirname(os.path.abspath(__file__)))
print("🏗️  Iniciando SECOP Automatizador en http://localhost:8501")
subprocess.run([sys.executable, "-m", "streamlit", "run", "app.py", "--server.port", "8501"])
