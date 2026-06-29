"""
Servidor de licencias SECOP Automatizador.
FastAPI — despliega en cualquier VPS con:
  pip install fastapi uvicorn
  uvicorn licencias.servidor.main:app --host 0.0.0.0 --port 8000
"""
import os, sqlite3, json
from datetime import datetime
from fastapi import FastAPI, Query, HTTPException
from fastapi.responses import JSONResponse

app = FastAPI(title="SECOP License Server", docs_url=None, redoc_url=None)

# DB de clientes (la misma que maneja admin_licencias.py)
DB_PATH = os.getenv("SECOP_ADMIN_DB", os.path.join(os.path.expanduser("~"), "secop_clientes.db"))
# C-5: API key obligatoria — el servidor no inicia sin ella
API_KEY = os.getenv("ADMIN_API_KEY")
if not API_KEY:
    raise RuntimeError(
        "ADMIN_API_KEY no configurada. "
        "Agrega esta variable en tu VPS: export ADMIN_API_KEY='tu-clave-segura'\n"
        "El servidor no puede iniciar sin esta variable de entorno."
    )

def get_cliente(license_id: str = None, nit: str = None):
    if not os.path.exists(DB_PATH):
        return None
    conn = sqlite3.connect(DB_PATH)
    if license_id:
        row = conn.execute(
            "SELECT nit, nombre, plan, fecha_vencimiento, activo FROM clientes WHERE license_id=?",
            (license_id,)
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT nit, nombre, plan, fecha_vencimiento, activo FROM clientes WHERE nit=? ORDER BY fecha_creacion DESC LIMIT 1",
            (nit,)
        ).fetchone()
    conn.close()
    return row

@app.get("/api/validar")
def validar(
    license_id: str = Query(...),
    nit: str = Query(...),
    machine: str = Query(default=""),
):
    """Endpoint que consulta la app del cliente cada 24h."""
    row = get_cliente(license_id=license_id)
    if not row:
        return JSONResponse({"activo": False, "motivo": "Licencia no encontrada"})
    db_nit, nombre, plan, fecha_vencimiento, activo = row
    if db_nit != nit:
        return JSONResponse({"activo": False, "motivo": "NIT no coincide"})
    if not activo:
        return JSONResponse({"activo": False, "motivo": "Suscripción cancelada"})
    hoy = datetime.now().strftime("%Y-%m-%d")
    if fecha_vencimiento < hoy:
        return JSONResponse({"activo": False, "motivo": "Suscripción vencida", "fecha_vencimiento": fecha_vencimiento})
    dias = (datetime.strptime(fecha_vencimiento, "%Y-%m-%d") - datetime.now()).days
    return JSONResponse({
        "activo": True,
        "nombre": nombre,
        "plan": plan,
        "fecha_vencimiento": fecha_vencimiento,
        "dias_restantes": dias,
    })

@app.get("/api/admin/clientes")
def listar_clientes(api_key: str = Query(...)):
    """Lista todos los clientes (protegido con API key)."""
    if api_key != API_KEY:
        raise HTTPException(status_code=403, detail="No autorizado")
    if not os.path.exists(DB_PATH):
        return []
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT license_id, nit, nombre, plan, fecha_vencimiento, activo, email FROM clientes ORDER BY fecha_creacion DESC"
    ).fetchall()
    conn.close()
    return [{"license_id":r[0],"nit":r[1],"nombre":r[2],"plan":r[3],"vence":r[4],"activo":bool(r[5]),"email":r[6]} for r in rows]

@app.get("/api/admin/cancelar")
def cancelar(nit: str = Query(...), api_key: str = Query(...)):
    """Cancela la suscripción de un cliente remotamente."""
    if api_key != API_KEY:
        raise HTTPException(status_code=403, detail="No autorizado")
    conn = sqlite3.connect(DB_PATH)
    cur = conn.execute("UPDATE clientes SET activo=0 WHERE nit=?", (nit,))
    conn.commit()
    conn.close()
    return {"ok": True, "cancelados": cur.rowcount}

@app.get("/health")
def health():
    return {"status": "ok", "time": datetime.now().isoformat()}
