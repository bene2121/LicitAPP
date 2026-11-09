"""Configuracion central del aplicativo SECOP Automatizador."""
import os
from dotenv import load_dotenv

load_dotenv()

# Proponente
NIT = os.getenv("NIT_PROPONENTE", "")
NOMBRE = os.getenv("NOMBRE_PROPONENTE", "")

# APIs SECOP (Socrata - datos.gov.co)
SOCRATA_BASE = "https://www.datos.gov.co/resource"
API_SECOP1   = f"{SOCRATA_BASE}/f789-7hwg.json"
API_SECOP2   = f"{SOCRATA_BASE}/p6dx-8zbt.json"
API_CONTRATOS = f"{SOCRATA_BASE}/jbjy-vk9h.json"
API_OFERTAS  = f"{SOCRATA_BASE}/wi7w-2nvm.json"
API_PLURALES = f"{SOCRATA_BASE}/ceth-n4bn.json"

APP_TOKEN = os.getenv("SOCRATA_APP_TOKEN", "")
PAGE_SIZE = 1000  # registros por pagina

# Filtros por defecto (obras civiles)
UNSPSC_INTERES = os.getenv("UNSPSC_INTERES", "72000000,72100000,72110000,72120000").split(",")
DEPARTAMENTOS  = os.getenv("DEPARTAMENTOS", "").split(",") if os.getenv("DEPARTAMENTOS") else []
PRESUPUESTO_MIN = float(os.getenv("PRESUPUESTO_MINIMO", "5000000"))
PRESUPUESTO_MAX = float(os.getenv("PRESUPUESTO_MAXIMO", "500000000"))

# Base de datos — ruta compatible con PyInstaller frozen exe
import sys as _sys
def _data_dir():
    if os.environ.get("LICITAPP_DATA_DIR"):
        return os.environ["LICITAPP_DATA_DIR"]
    if getattr(_sys, "frozen", False):
        return os.path.join(os.path.dirname(_sys.executable), "data")
    return os.path.join(os.path.dirname(__file__), "data")

DB_PATH = os.path.join(_data_dir(), "secop.db")

# Bot
BOT_MODE = os.getenv("BOT_MODE", "dry_run")  # dry_run | real
SECOP2_URL = "https://www.colombiacompra.gov.co/secop/secop2.html"
