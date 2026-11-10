"""
Validador de licencias — se embebe en la app del cliente.
Lógica híbrida: verifica firma RSA local + ping al servidor cada 24h.
Bloqueo total si vence o si el servidor reporta cancelación.
"""
import os, sys, json, hashlib, platform
from datetime import datetime, timedelta
from pathlib import Path

# La raíz del proyecto debe estar en sys.path para importar `seguridad` aunque
# Streamlit se lance desde otra carpeta.
_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _RAIZ not in sys.path:
    sys.path.insert(0, _RAIZ)


def _data_dir() -> str:
    """A-1: Directorio de datos persistentes — funciona congelado (PyInstaller) y en desarrollo."""
    if os.environ.get("LICITAPP_DATA_DIR"):
        return os.environ["LICITAPP_DATA_DIR"]
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


# Clave pública embebida en el código. El archivo claves/publica.pem se conserva solo
# como referencia: si fuera la fuente de verdad, quien reemplace ese archivo podría
# firmar sus propias licencias. Si rotas las claves, actualiza AMBOS (hay una prueba
# que falla si no coinciden).
_PUBLICA_PEM = b"""-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA2F6HzFHb/Xx/AvMCvkpo
gIuNXF7utKuJaEsajztUEwSgTwzAubq+J9fGZ7H8XZDc6UqDyBkOwuHu327rqLDr
zCIAq5Mauv7+aGksEbLCb4GqUw0xqSZWqqAEjAnWugTklRs0iVCqH7dA1UUGJ+cI
b6ImpOWeFTXs6bHUm7XWbjm5Q49yCvHNEhOtDkvcxihURQfa7mq23jT+us2hotTJ
MN7giTU+JcUXJH/tFWUs6jZ3PARIyeoNuzGLdjUkAONLDK0nKqiATg+/+9lfCYWD
tnj+BjugZbYVJyWaNj0YI49r9DEpYszxNqp5n9+JbC3qjcfBMVUVHmtcxyvvgzwI
FwIDAQAB
-----END PUBLIC KEY-----
"""
_PUBLICA_PATH = os.path.join(os.path.dirname(__file__), "claves", "publica.pem")  # solo referencia

# Dónde busca la licencia el cliente
LICENCIA_PATH = os.path.join(_app_dir(), "licencias", "mi_licencia.lic")
CACHE_PATH    = os.path.join(_data_dir(), ".lic_cache")

# URL del servidor de validación (cambiar por tu dominio)
SERVIDOR_URL = os.getenv("SECOP_LICENSE_SERVER", "https://tu-servidor.com/api/validar")
GRACIA_OFFLINE_DIAS = 3   # días sin internet antes de bloquear

def _servidor_configurado() -> bool:
    """El valor de fabrica no es un servidor real."""
    return "tu-servidor.com" not in SERVIDOR_URL.lower()

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
    publica = serialization.load_pem_public_key(_PUBLICA_PEM)
    payload_bytes = json.dumps(payload, sort_keys=True).encode()
    publica.verify(firma, payload_bytes, padding.PKCS1v15(), hashes.SHA256())
    return payload

def _verificar_con_servidor(license_id: str, nit: str) -> dict:
    """Consulta el servidor. Retorna {'activo': bool, 'fecha_vencimiento': str}"""
    import urllib.request, urllib.parse
    from seguridad import exigir_https, leer_limitado
    exigir_https(SERVIDOR_URL)  # nunca consultar la licencia por http plano
    params = urllib.parse.urlencode({"license_id": license_id, "nit": nit, "machine": _machine_id()})
    url = f"{SERVIDOR_URL}?{params}"
    req = urllib.request.Request(url, headers={"User-Agent": "SECOPApp/1.0"})
    with urllib.request.urlopen(req, timeout=8) as resp:  # nosec B310 - https validado arriba
        datos = json.loads(leer_limitado(resp, 64 * 1024).decode())
    if not isinstance(datos, dict):
        raise ValueError("Respuesta del servidor de licencias no válida")
    return datos

def _leer_cache() -> dict:
    if not os.path.exists(CACHE_PATH):
        return {}
    try:
        with open(CACHE_PATH) as f:
            datos = json.load(f)
        return datos if isinstance(datos, dict) else {}
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

    # 3. Verificar estructura y fecha de vencimiento local
    try:
        for campo in ("license_id", "nit", "nombre", "plan", "fecha_vencimiento"):
            if not isinstance(payload[campo], str):
                raise TypeError(campo)
        datetime.strptime(payload["fecha_vencimiento"], "%Y-%m-%d")
    except (KeyError, TypeError, ValueError):
        raise LicenciaInvalida(
            "El archivo de licencia es inválido o fue modificado.\n"
            "Solicita una nueva licencia a tu proveedor."
        )
    hoy = datetime.now().strftime("%Y-%m-%d")
    if payload["fecha_vencimiento"] < hoy:
        raise LicenciaInvalida(
            f"Tu suscripción venció el {payload['fecha_vencimiento']}.\n"
            f"Renueva tu plan para continuar usando la aplicación:\n"
            "📧 polymodulospvc@gmail.com"
        )

    info_local = {
        "license_id":       payload["license_id"],
        "nit":              payload["nit"],
        "nombre":           payload["nombre"],
        "plan":             payload["plan"],
        "fecha_vencimiento": payload["fecha_vencimiento"],
        "dias_restantes":   max(0, (datetime.strptime(payload["fecha_vencimiento"], "%Y-%m-%d") - datetime.now()).days),
    }
    if not _servidor_configurado():
        return info_local

    # 4. Verificar con servidor (cada 24h)
    cache = _leer_cache()
    ultimo_check = cache.get("ultimo_check", "2000-01-01T00:00:00")
    try:
        ultimo_dt = datetime.fromisoformat(ultimo_check)
    except Exception:
        ultimo_dt = datetime.min

    # Un ultimo_check en el futuro (cache manipulada) obliga a consultar de nuevo.
    if ultimo_dt > datetime.now() + timedelta(minutes=5):
        ultimo_dt = datetime.min
    necesita_check = (datetime.now() - ultimo_dt) > timedelta(hours=24)

    if necesita_check:
        try:
            resp = _verificar_con_servidor(payload["license_id"], payload["nit"])
            if resp.get("activo") is not True:
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

    return info_local


def resolver_acceso(ruta_licencia: str = None) -> dict:
    """Licencia firmada si existe. Si no hay archivo, abre el trial de 7 dias."""
    ruta = ruta_licencia or LICENCIA_PATH
    if os.path.exists(ruta):
        info = validar_licencia(ruta)
        info["es_trial"] = False
        return info
    from licencias.trial import activar_o_verificar_trial
    trial = activar_o_verificar_trial()
    dias = int(trial["dias_restantes"])
    return {
        "license_id": "trial",
        "nit": "",
        "nombre": "Prueba",
        "plan": "trial",
        "fecha_vencimiento": (datetime.now() + timedelta(days=dias)).strftime("%Y-%m-%d"),
        "dias_restantes": dias,
        "es_trial": True,
    }

if __name__ == "__main__":
    # Test rápido
    try:
        info = validar_licencia()
        print(f"✅ Licencia válida: {info['nombre']} | Plan: {info['plan']} | Vence en {info['dias_restantes']} días")
    except LicenciaInvalida as e:
        print(f"❌ {e}")
