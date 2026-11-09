import os
from fastapi import FastAPI, Header, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

load_dotenv()

# C-4: Autenticación de licencia en todos los endpoints protegidos
_ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "https://licitapp.co").split(",")

async def verificar_licencia(x_license_key: str = Header(default="")):
    """Valida que el cliente tenga una licencia activa antes de servir datos."""
    if not x_license_key:
        raise HTTPException(status_code=401, detail="Se requiere X-License-Key")
    # Validar contra el servidor de licencias (importación condicional para no crear dependencia circular)
    try:
        import sqlite3
        db_path = os.getenv("SECOP_ADMIN_DB", os.path.join(os.path.expanduser("~"), "secop_clientes.db"))
        if not os.path.exists(db_path):
            raise HTTPException(status_code=503, detail="Servidor de licencias no disponible")
        conn = sqlite3.connect(db_path)
        row = conn.execute(
            "SELECT activo, fecha_vencimiento FROM clientes WHERE license_id=?",
            (x_license_key,)
        ).fetchone()
        conn.close()
        if not row:
            raise HTTPException(status_code=403, detail="Licencia no encontrada")
        activo, fecha_vence = row
        from datetime import datetime
        if not activo or fecha_vence < datetime.now().strftime("%Y-%m-%d"):
            raise HTTPException(status_code=403, detail="Licencia inactiva o vencida")
    except HTTPException:
        raise
    except Exception:
        # DB no disponible o error inesperado — denegar acceso por defecto (fail-closed)
        raise HTTPException(status_code=503, detail="No se pudo verificar la licencia")

try:
    from .db import engine, Base
    from .routers import procesos, competidores, entidades
    Base.metadata.create_all(bind=engine)
    _DB_AVAILABLE = True
except Exception as _e:
    print(f"[WARN] BD no disponible: {_e}. Corriendo sin DB.")
    _DB_AVAILABLE = False

app = FastAPI(
    title="SECOP API Central",
    description="API central para SECOP Automatizador — plataforma SaaS de licitaciones Colombia",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

if _DB_AVAILABLE:
    _auth = [Depends(verificar_licencia)]
    app.include_router(procesos.router,     prefix="/v1/procesos",     tags=["Procesos"],     dependencies=_auth)
    app.include_router(competidores.router, prefix="/v1/competidores", tags=["Competidores"], dependencies=_auth)
    app.include_router(entidades.router,    prefix="/v1/entidades",    tags=["Entidades"],    dependencies=_auth)

@app.get("/v1/health", tags=["Sistema"])
def health():
    return {"status": "ok", "version": "1.0.0", "db": _DB_AVAILABLE}

@app.get("/", tags=["Sistema"])
def root():
    return {"mensaje": "SECOP API Central v1.0. Docs en /docs"}
