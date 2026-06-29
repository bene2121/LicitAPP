"""
Sistema de trial de 7 días.
Si no hay licencia .lic, se activa un trial local con fecha de inicio.
Después de 7 días bloquea y muestra mensaje para comprar.
"""
import os, json, hashlib, uuid, platform
from datetime import datetime, timedelta

def _data_dir() -> str:
    """A-1: Directorio de datos persistentes compatible con PyInstaller."""
    import sys
    if getattr(sys, "frozen", False):
        return os.path.join(os.path.dirname(sys.executable), "data")
    return os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")

TRIAL_PATH = os.path.join(_data_dir(), ".trial")

def _machine_id():
    import socket
    mac = uuid.getnode()
    host = socket.gethostname()
    return hashlib.sha256(f"{mac}-{host}".encode()).hexdigest()[:20]

def activar_o_verificar_trial() -> dict:
    """
    Activa trial si es primera vez, verifica si sigue vigente.
    Retorna: {"activo": bool, "dias_restantes": int, "es_trial": True}
    Lanza LicenciaInvalida si el trial venció.
    """
    from licencias.validador import LicenciaInvalida

    os.makedirs(os.path.dirname(TRIAL_PATH), exist_ok=True)
    mid = _machine_id()

    if os.path.exists(TRIAL_PATH):
        try:
            data = json.loads(open(TRIAL_PATH).read())
            # Verificar integridad (no se haya manipulado la fecha)
            expected_hash = hashlib.sha256(f"{data['inicio']}-{mid}-secop-trial".encode()).hexdigest()
            if data.get("hash") != expected_hash:
                raise LicenciaInvalida(
                    "El trial fue modificado manualmente.\n"
                    "Para continuar, adquiere tu licencia:\n"
                    "📧 polymodulospvc@gmail.com"
                )
            inicio = datetime.strptime(data["inicio"], "%Y-%m-%d")
            dias_usados = (datetime.now() - inicio).days
            dias_restantes = max(0, 7 - dias_usados)
            if dias_restantes == 0:
                raise LicenciaInvalida(
                    "Tu período de prueba de 7 días ha terminado.\n\n"
                    "Para continuar usando SECOP Automatizador, adquiere tu licencia:\n"
                    "📧 polymodulospvc@gmail.com\n"
                    "📱 WhatsApp: [tu número]\n\n"
                    "Planes desde $350.000/mes"
                )
            return {"activo": True, "dias_restantes": dias_restantes, "es_trial": True, "nombre": "TRIAL"}
        except LicenciaInvalida:
            raise
        except Exception:
            pass

    # Primera vez — activar trial
    inicio_str = datetime.now().strftime("%Y-%m-%d")
    trial_hash = hashlib.sha256(f"{inicio_str}-{mid}-secop-trial".encode()).hexdigest()
    trial_data = {"inicio": inicio_str, "machine": mid, "hash": trial_hash}
    with open(TRIAL_PATH, "w") as f:
        json.dump(trial_data, f)
    return {"activo": True, "dias_restantes": 7, "es_trial": True, "nombre": "TRIAL"}
