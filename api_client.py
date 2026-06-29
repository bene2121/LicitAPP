"""
Cliente HTTP para consumir la API central de SECOP Automatizador.
Los clientes locales usan este módulo en vez de llamar a Socrata directamente.
"""
import os
import httpx
from typing import Optional
from dotenv import load_dotenv

load_dotenv()

API_BASE    = os.getenv("SECOP_API_URL", "https://api.secop-automatizador.com")
API_TIMEOUT = 15.0


def _headers() -> dict:
    """Incluye la clave de licencia en cada request."""
    try:
        from licencias.validador import validar_licencia
        lic = validar_licencia()
        return {
            "X-License-Key": str(lic.get("license_id", "")),
            "X-NIT": str(lic.get("nit", "")),
        }
    except Exception:
        return {}


def get_procesos(
    departamento: Optional[str] = None,
    municipio: Optional[str] = None,
    unspsc_familia: Optional[str] = None,
    unspsc_clase: Optional[str] = None,
    unspsc: Optional[str] = None,
    modalidad: Optional[str] = None,
    estado: Optional[str] = None,
    fuente: Optional[str] = None,
    q: Optional[str] = None,
    entidad: Optional[str] = None,
    nit_entidad: Optional[str] = None,
    po_min: Optional[float] = None,
    po_max: Optional[float] = None,
    score_min: float = 0.0,
    dias_cierre_max: Optional[int] = None,
    page: int = 1,
    page_size: int = 50,
) -> dict:
    """Retorna dict con 'total', 'items', y opcionalmente 'error'."""
    params = {}
    if departamento:      params["departamento"]    = departamento
    if municipio:         params["municipio"]        = municipio
    if unspsc_familia:    params["unspsc_familia"]   = unspsc_familia
    if unspsc_clase:      params["unspsc_clase"]     = unspsc_clase
    if unspsc:            params["unspsc"]           = unspsc
    if modalidad:         params["modalidad"]        = modalidad
    if estado:            params["estado"]           = estado
    if fuente:            params["fuente"]           = fuente
    if q:                 params["q"]                = q
    if entidad:           params["entidad"]          = entidad
    if nit_entidad:       params["nit_entidad"]      = nit_entidad
    if po_min is not None: params["po_min"]          = po_min
    if po_max is not None: params["po_max"]          = po_max
    if score_min:         params["score_min"]        = score_min
    if dias_cierre_max:   params["dias_cierre_max"]  = dias_cierre_max
    params["page"]      = page
    params["page_size"] = page_size

    try:
        r = httpx.get(
            f"{API_BASE}/v1/procesos/",
            params=params,
            headers=_headers(),
            timeout=API_TIMEOUT,
        )
        r.raise_for_status()
        return r.json()
    except httpx.ConnectError:
        return {
            "error": "Sin conexión al servidor central. Usando datos locales si están disponibles.",
            "items": [],
            "total": 0,
        }
    except httpx.HTTPStatusError as e:
        return {"error": f"Error del servidor: {e.response.status_code}", "items": [], "total": 0}
    except Exception as e:
        return {"error": str(e), "items": [], "total": 0}


def get_detalle_proceso(id_proceso: str) -> dict:
    try:
        r = httpx.get(
            f"{API_BASE}/v1/procesos/{id_proceso}",
            headers=_headers(),
            timeout=API_TIMEOUT,
        )
        r.raise_for_status()
        return r.json()
    except Exception as e:
        return {"error": str(e)}


def get_perfil_competidor(nit: str) -> dict:
    try:
        r = httpx.get(
            f"{API_BASE}/v1/competidores/{nit}",
            headers=_headers(),
            timeout=API_TIMEOUT,
        )
        r.raise_for_status()
        return r.json()
    except httpx.HTTPStatusError as e:
        return {"error": f"NIT {nit} no encontrado ({e.response.status_code})"}
    except Exception as e:
        return {"error": str(e)}


def get_prediccion_competidores(id_proceso: str) -> dict:
    try:
        r = httpx.get(
            f"{API_BASE}/v1/competidores/prediccion/{id_proceso}",
            headers=_headers(),
            timeout=API_TIMEOUT,
        )
        r.raise_for_status()
        return r.json()
    except Exception as e:
        return {"error": str(e), "rivales_probables": []}


def get_entidades(q: Optional[str] = None, departamento: Optional[str] = None, page: int = 1) -> dict:
    params = {"page": page}
    if q:            params["q"]            = q
    if departamento: params["departamento"] = departamento
    try:
        r = httpx.get(
            f"{API_BASE}/v1/entidades/",
            params=params,
            headers=_headers(),
            timeout=API_TIMEOUT,
        )
        r.raise_for_status()
        return r.json()
    except Exception as e:
        return {"error": str(e), "items": []}


def get_detalle_entidad(nit_entidad: str) -> dict:
    try:
        r = httpx.get(
            f"{API_BASE}/v1/entidades/{nit_entidad}",
            headers=_headers(),
            timeout=API_TIMEOUT,
        )
        r.raise_for_status()
        return r.json()
    except Exception as e:
        return {"error": str(e)}


def check_salud_api() -> dict:
    """Verifica que la API central esté disponible."""
    try:
        r = httpx.get(f"{API_BASE}/v1/health", timeout=5.0)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        return {"status": "offline", "error": str(e)}
