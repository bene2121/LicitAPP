"""
Validador de licencias — se embebe en la app del cliente.
Lógica híbrida: verifica firma RSA local + ping al servidor cada 24h.
Bloqueo total si vence o si el servidor reporta cancelación.
"""
import os, sys, json, hashlib, platform
from datetime import datetime, timedelta
from pathlib import Path


def _data_dir() -> str:
    """A-1: Directorio de datos persistentes — funciona congelado (PyInstaller) y en desarrollo."""
    if getattr(sys, "frozen", False):
        # En .exe congelado: carpeta junto al ejecutable (tiene permisos de escritura)
        return os.path.join(os.path.dirname(sys.executable), "data")
    # En desarrollo: carpeta data/ en la raíz del proyecto
    return os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")

def _app_dir() -> str:
    """Directorio de la app — para localizar archivos de recursos."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(__file__))

def _write_log(msg: str):
    try:
        d = _data_dir()
        os.makedirs(d, exist_ok=True)
        import datetime
        with open(os.path.join(d, "licitapp_startup.log"), "a", encoding="utf-8") as f:
            f.write(f"\n[{datetime.datetime.now().isoformat()}] [validador] {msg}\n")
    except Exception:
        pass


# Clave pública embebida
_PUBLICA_PATH = os.path.join(os.path.dirname(__file__), "claves", "publica.pem")

# Dónde busca la licencia el cliente
LICENCIA_PATH = os.path.join(_app_dir(), "licencias", "mi_licencia.lic")
CACHE_PATH    = os.path.join(_data_dir(), ".lic_cache")

# URL del servidor de validación (cambiar por tu dominio)
SERVIDOR_URL = os.getenv("SECOP_LICENSE_SERVER", "https://tu-servidor.com/api/validar")
GRACIA_OFFLINE_DIAS = 3   # días sin internet antes de bloquear

def _machine_id() -> str:
    """Huella del equipo (MAC + hostname)."""
    import uuid, socket
    mac  = uuid.getnode()
    host = socket.gethostname()
    raw  = f"{mac}-{host}-secop"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]

def _verificar_firma(licencia_json: str) -> dict:
    """Verifica la firma RSA. Retorna payload si es válida, lanza excepción si no."""
    from cryptography.hazmat.primitives.asymmetric import padding
    from cryptography.hazmat.primitives import hashes, serialization
    data = json.loads(licencia_json)
    payload = data["payload"]
    firma   = bytes.fromhex(data["firma"])
    with open(_PUBLICA_PATH, "rb") as f:
        publica = serialization.load_pem_public_key(f.read())
    payload_bytes = json.dumps(payload, sort_keys=True).encode()
    publica.verify(firma, payload_bytes, padding.PKCS1v15(), hashes.SHA256())
    return payload

def _verificar_con_servidor(license_id: str, nit: str) -> dict:
    """Consulta el servidor. Retorna {'activo': bool, 'fecha_vencimiento': str}"""
    import urllib.request, urllib.parse
    params = urllib.parse.urlencode({"license_id": license_id, "nit": nit, "machine": _machine_id()})
    url = f"{SERVIDOR_URL}?{params}"
    req = urllib.request.Request(url, headers={"User-Agent": "SECOPApp/1.0"})
    with urllib.request.urlopen(req, timeout=8) as resp:
        return json.loads(resp.read().decode())

def _leer_cache() -> dict:
    if not os.path.exists(CACHE_PATH):
        return {}
    try:
        with open(CACHE_PATH) as f:
            return json.load(f)
    except Exception:
        return {}

def _guardar_cache(data: dict):
    os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
    with open(CACHE_PATH, "w") as f:
        json.dump(data, f)

class LicenciaInvalida(Exception):
    """Se lanza cuando la licencia no es válida o venció."""
    pass

def validar_licencia(ruta_licencia: str = None) -> dict:
    """
    Valida la licencia completa (firma + fecha + servidor).
    
    Retorna dict con info del cliente si es válida.
    Lanza LicenciaInvalida con mensaje descriptivo si no lo es.
    """
    ruta = ruta_licencia or LICENCIA_PATH

    # 1. ¿Existe el archivo?
    if not os.path.exists(ruta):
        raise LicenciaInvalida(
            "No se encontró el archivo de licencia.\n"
            "Contacta a tu proveedor para obtener tu licencia:\n"
            "📧 polymodulospvc@gmail.com\n"
            "📱 WhatsApp: [tu número]"
        )

    # 2. Verificar firma RSA
    try:
        with open(ruta, encoding="utf-8") as f:
            contenido = f.read()
        payload = _verificar_firma(contenido)
    except Exception as _e:
        _write_log(f"Error verificando firma: {_e!r} | publica_path={_PUBLICA_PATH} | existe={os.path.exists(_PUBLICA_PATH)}")
        raise LicenciaInvalida(
            "El archivo de licencia es inválido o fue modificado.\n"
            "Solicita una nueva licencia a tu proveedor."
        )

    # 3. Verificar fecha de vencimiento local
    hoy = datetime.now().strftime("%Y-%m-%d")
    if payload["fecha_vencimiento"] < hoy:
        raise LicenciaInvalida(
            f"Tu suscripción venció el {payload['fecha_vencimiento']}.\n"
            f"Renueva tu plan para continuar usando la aplicación:\n"
            "📧 polymodulospvc@gmail.com"
        )

    # 4. Verificar con servidor (cada 24h)
    cache = _leer_cache()
    ultimo_check = cache.get("ultimo_check", "2000-01-01T00:00:00")
    try:
        ultimo_dt = datetime.fromisoformat(ultimo_check)
    except Exception:
        ultimo_dt = datetime.min

    necesita_check = (datetime.now() - ultimo_dt) > timedelta(hours=24)

    if necesita_check:
        try:
            resp = _verificar_con_servidor(payload["license_id"], payload["nit"])
            if not resp.get("activo", False):
                # Limpiar cache y bloquear
                _guardar_cache({})
                raise LicenciaInvalida(
                    "Tu suscripción fue cancelada o suspendida.\n"
                    "Contacta a tu proveedor para reactivarla:\n"
                    "📧 polymodulospvc@gmail.com"
                )
            # Actualizar cache con resultado del servidor
            _guardar_cache({
                "ultimo_check": datetime.now().isoformat(),
                "activo": True,
                "license_id": payload["license_id"],
                "nit": payload["nit"],
                "fecha_vencimiento": resp.get("fecha_vencimiento", payload["fecha_vencimiento"]),
            })
        except LicenciaInvalida:
            raise
        except Exception:
            # Sin internet — usar cache
            dias_sin_check = (datetime.now() - ultimo_dt).days if ultimo_dt != datetime.min else 999
            if dias_sin_check > GRACIA_OFFLINE_DIAS and cache.get("activo") and ultimo_dt != datetime.min:
                raise LicenciaInvalida(
                    f"No se puede verificar la licencia (sin internet hace {dias_sin_check} días).\n"
                    f"Se permiten máximo {GRACIA_OFFLINE_DIAS} días sin conexión.\n"
                    "Conecta a internet para validar tu licencia."
                )
            # Si nunca hubo check exitoso y no hay internet: bloquear
            if not cache.get("activo") or ultimo_dt == datetime.min:
                raise LicenciaInvalida(
                    "Se requiere conexión a internet para activar la licencia\n"
                    "por primera vez. Conéctate a internet y vuelve a abrir la app."
                )

    return {
        "license_id":       payload["license_id"],
        "nit":              payload["nit"],
        "nombre":           payload["nombre"],
        "plan":             payload["plan"],
        "fecha_vencimiento": payload["fecha_vencimiento"],
        "dias_restantes":   max(0, (datetime.strptime(payload["fecha_vencimiento"], "%Y-%m-%d") - datetime.now()).days),
    }

if __name__ == "__main__":
    # Test rápido
    try:
        info = validar_licencia()
        print(f"✅ Licencia válida: {info['nombre']} | Plan: {info['plan']} | Vence en {info['dias_restantes']} días")
    except LicenciaInvalida as e:
        print(f"❌ {e}")
