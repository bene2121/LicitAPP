"""
Servidor de licencias SECOP Automatizador.
FastAPI — despliega en cualquier VPS con:
  pip install fastapi uvicorn
  uvicorn licencias.servidor.main:app --host 127.0.0.1 --port 8000   (detrás de nginx con HTTPS)
"""
import os, sqlite3, json, hmac, time, logging
from collections import defaultdict, deque
from contextlib import closing
from datetime import datetime
from fastapi import FastAPI, Query, HTTPException, Header, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger("licencias.servidor")

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
if len(API_KEY) < 16:
    raise RuntimeError("ADMIN_API_KEY es demasiado corta: usa al menos 16 caracteres aleatorios.")

# ── Limitador de peticiones en memoria (por IP, ventana deslizante) ─────────────
class _Limitador:
    def __init__(self, maximo: int, ventana: float):
        self.maximo, self.ventana = maximo, ventana
        self._hits = defaultdict(deque)

    def permitir(self, clave: str) -> bool:
        ahora = time.monotonic()
        cola = self._hits[clave]
        while cola and ahora - cola[0] > self.ventana:
            cola.popleft()
        if len(cola) >= self.maximo:
            return False
        cola.append(ahora)
        if len(self._hits) > 10_000:  # evita crecer sin límite
            self._hits.clear()
        return True


_LIM_VALIDAR = _Limitador(60, 60.0)       # consultas de licencia por IP y minuto
_LIM_ADMIN_FALLOS = _Limitador(5, 300.0)  # claves admin erróneas por IP cada 5 minutos


def _ip(request: Request) -> str:
    """IP real: detrás de nginx (127.0.0.1) se usa X-Real-IP; si no, la del socket."""
    ip = request.client.host if request.client else "?"
    if ip in ("127.0.0.1", "::1"):
        return request.headers.get("x-real-ip", ip)[:64]
    return ip


def _exigir_admin(request: Request, x_admin_key: str, api_key: str):
    """Valida la clave de administrador con comparación de tiempo constante.

    Preferido: cabecera `X-Admin-Key`. El parámetro `api_key` en la URL se acepta solo por
    compatibilidad: queda en los logs de nginx/uvicorn, así que migra a la cabecera.
    """
    ip = _ip(request)
    candidata = x_admin_key or api_key or ""
    if not hmac.compare_digest(candidata.encode(), API_KEY.encode()):
        if not _LIM_ADMIN_FALLOS.permitir(ip):
            raise HTTPException(status_code=429, detail="Demasiados intentos")
        raise HTTPException(status_code=403, detail="No autorizado")
    if api_key and not x_admin_key:
        logger.warning("Clave admin recibida en la URL; usa la cabecera X-Admin-Key")


def get_cliente(license_id: str = None, nit: str = None):
    if not os.path.exists(DB_PATH):
        return None
    with closing(sqlite3.connect(DB_PATH)) as conn:
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
    return row

@app.get("/api/validar")
def validar(
    request: Request,
    license_id: str = Query(..., max_length=64),
    nit: str = Query(..., max_length=32),
    machine: str = Query(default="", max_length=64),
):
    """Endpoint que consulta la app del cliente cada 24h."""
    if not _LIM_VALIDAR.permitir(_ip(request)):
        raise HTTPException(status_code=429, detail="Demasiadas consultas")
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
def listar_clientes(
    request: Request,
    x_admin_key: str = Header(default=""),
    api_key: str = Query(default="", max_length=200),
):
    """Lista todos los clientes (protegido con clave de administrador)."""
    _exigir_admin(request, x_admin_key, api_key)
    if not os.path.exists(DB_PATH):
        return []
    with closing(sqlite3.connect(DB_PATH)) as conn:
        rows = conn.execute(
            "SELECT license_id, nit, nombre, plan, fecha_vencimiento, activo, email FROM clientes ORDER BY fecha_creacion DESC"
        ).fetchall()
    return [{"license_id":r[0],"nit":r[1],"nombre":r[2],"plan":r[3],"vence":r[4],"activo":bool(r[5]),"email":r[6]} for r in rows]

@app.get("/api/admin/cancelar")
def cancelar(
    request: Request,
    nit: str = Query(..., max_length=32),
    x_admin_key: str = Header(default=""),
    api_key: str = Query(default="", max_length=200),
):
    """Cancela la suscripción de un cliente remotamente."""
    _exigir_admin(request, x_admin_key, api_key)
    if not os.path.exists(DB_PATH):
        raise HTTPException(status_code=404, detail="Sin base de clientes")
    with closing(sqlite3.connect(DB_PATH)) as conn:
        cur = conn.execute("UPDATE clientes SET activo=0 WHERE nit=?", (nit,))
        conn.commit()
        cancelados = cur.rowcount
    return {"ok": True, "cancelados": cancelados}

@app.get("/health")
def health():
    return {"status": "ok", "time": datetime.now().isoformat()}
