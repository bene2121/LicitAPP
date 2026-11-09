"""
Sistema de trial de 7 días.
Si no hay licencia .lic, se activa un trial local con fecha de inicio.
Después de 7 días bloquea y muestra mensaje para comprar.

Formato compatible con versiones anteriores: el archivo `.trial` conserva
{"inicio", "machine", "hash"} con hash = sha256(f"{inicio}-{machine_id}-secop-trial").
Se agregan, sin invalidar los archivos viejos:
  - copias redundantes del inicio (borrar solo `.trial` ya no reinicia el trial);
  - "ultimo" (último día de uso) para detectar que se retrocedió el reloj;
  - archivo ilegible o alterado = bloqueo (antes se reiniciaba el trial).
Un trial offline no puede ser infalsificable: esto sube el costo de los atajos
comunes (borrar, corromper, editar fecha, retroceder el reloj).
"""
import os, json, hashlib, hmac, uuid, platform
from datetime import datetime, timedelta

DIAS_TRIAL = 7
TOLERANCIA_RELOJ_DIAS = 2  # cambios de zona horaria / ajustes menores del reloj


def _data_dir() -> str:
    """A-1: Directorio de datos persistentes compatible con PyInstaller."""
    import sys
    if os.environ.get("LICITAPP_DATA_DIR"):
        return os.environ["LICITAPP_DATA_DIR"]
    if getattr(sys, "frozen", False):
        return os.path.join(os.path.dirname(sys.executable), "data")
    return os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")

TRIAL_PATH = os.path.join(_data_dir(), ".trial")
_TRIAL_PATH_DEFECTO = TRIAL_PATH


def _marcas() -> list:
    """Copias redundantes del trial: junto al principal y, en instalación normal, en el perfil del usuario."""
    rutas = [os.path.join(os.path.dirname(TRIAL_PATH), ".lic_t")]
    if TRIAL_PATH == _TRIAL_PATH_DEFECTO:
        rutas.append(os.path.join(os.path.expanduser("~"), ".licitapp", ".t"))
    return rutas


def _machine_id():
    """Identificador estable del equipo.

    Si Python no logra leer la MAC, `uuid.getnode()` devuelve un número
    aleatorio distinto en cada arranque (bit multicast encendido) y el trial
    se bloqueaba al día siguiente como "modificado". En ese caso se usa el
    identificador del sistema operativo. Con MAC real se conserva la fórmula
    anterior para no invalidar trials ya activos.
    """
    import socket
    mac = uuid.getnode()
    host = socket.gethostname()
    if (mac >> 40) & 1:
        mac = "sys-" + _id_sistema()
    return hashlib.sha256(f"{mac}-{host}".encode()).hexdigest()[:20]


def _id_sistema() -> str:
    try:
        if platform.system() == "Windows":
            import winreg
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography",
                                0, winreg.KEY_READ | getattr(winreg, "KEY_WOW64_64KEY", 0)) as clave:
                return str(winreg.QueryValueEx(clave, "MachineGuid")[0])
        for ruta in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
            if os.path.exists(ruta):
                with open(ruta) as f:
                    valor = f.read().strip()
                if valor:
                    return valor
    except Exception:
        pass
    return platform.node() or "equipo"


def _hash_inicio(inicio: str, mid: str) -> str:
    return hashlib.sha256(f"{inicio}-{mid}-secop-trial".encode()).hexdigest()


def _hash_ultimo(ultimo: str, mid: str) -> str:
    return hashlib.sha256(f"{ultimo}-{mid}-secop-trial-ultimo".encode()).hexdigest()


def _hoy() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _leer(ruta: str, mid: str):
    """None si no existe; dict validado si es íntegro; _Alterado si no se puede confiar."""
    if not os.path.exists(ruta):
        return None
    try:
        with open(ruta, encoding="utf-8") as f:
            data = json.load(f)
        inicio = data["inicio"]
        if not isinstance(inicio, str) or not hmac.compare_digest(str(data.get("hash", "")), _hash_inicio(inicio, mid)):
            return _ALTERADO
        datetime.strptime(inicio, "%Y-%m-%d")
        ultimo = data.get("ultimo")
        if ultimo is not None:
            if not isinstance(ultimo, str) or not hmac.compare_digest(
                    str(data.get("hash_ultimo", "")), _hash_ultimo(ultimo, mid)):
                return _ALTERADO
            datetime.strptime(ultimo, "%Y-%m-%d")
        return {"inicio": inicio, "ultimo": ultimo}
    except Exception:
        return _ALTERADO


_ALTERADO = object()


def _escribir(ruta: str, inicio: str, ultimo: str, mid: str) -> None:
    datos = {"inicio": inicio, "machine": mid, "hash": _hash_inicio(inicio, mid),
             "ultimo": ultimo, "hash_ultimo": _hash_ultimo(ultimo, mid)}
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    tmp = ruta + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(datos, f)
    os.replace(tmp, ruta)  # atómico: un corte de luz no deja el archivo a medias


def _bloqueo_modificado():
    from licencias.validador import LicenciaInvalida
    return LicenciaInvalida(
        "El trial fue modificado manualmente.\n"
        "Para continuar, adquiere tu licencia:\n"
        "📧 polymodulospvc@gmail.com"
    )


def activar_o_verificar_trial() -> dict:
    """
    Activa trial si es primera vez, verifica si sigue vigente.
    Retorna: {"activo": bool, "dias_restantes": int, "es_trial": True}
    Lanza LicenciaInvalida si el trial venció.
    """
    from licencias.validador import LicenciaInvalida

    os.makedirs(os.path.dirname(TRIAL_PATH), exist_ok=True)
    mid = _machine_id()
    hoy = _hoy()

    principal = _leer(TRIAL_PATH, mid)
    copias = [_leer(r, mid) for r in _marcas()]
    existentes = [x for x in [principal] + copias if x is not None]
    validos = [x for x in existentes if x is not _ALTERADO]

    if not validos:
        if existentes:
            # Hay archivos de trial pero ninguno íntegro: no se reinicia el trial.
            raise _bloqueo_modificado()
        # Primera vez — activar trial
        for ruta in [TRIAL_PATH] + _marcas():
            try:
                _escribir(ruta, hoy, hoy, mid)
            except OSError:
                if ruta == TRIAL_PATH:
                    raise
        return {"activo": True, "dias_restantes": DIAS_TRIAL, "es_trial": True, "nombre": "TRIAL"}

    # Vale el inicio más antiguo y el último uso más reciente de cualquier copia íntegra.
    inicio = min(x["inicio"] for x in validos)
    ultimos = [x["ultimo"] for x in validos if x["ultimo"]]
    ultimo = max(ultimos) if ultimos else inicio

    fecha_inicio = datetime.strptime(inicio, "%Y-%m-%d")
    tolerancia = timedelta(days=TOLERANCIA_RELOJ_DIAS)
    ahora = datetime.now()
    if fecha_inicio > ahora + tolerancia or datetime.strptime(ultimo, "%Y-%m-%d") > ahora + tolerancia:
        # Inicio en el futuro o reloj retrocedido respecto al último uso.
        raise _bloqueo_modificado()

    dias_usados = (ahora - fecha_inicio).days
    dias_restantes = max(0, DIAS_TRIAL - dias_usados)

    # Sincroniza las copias (restaura la borrada, migra trials viejos, avanza "ultimo").
    nuevo_ultimo = max(ultimo, hoy)
    for ruta, actual in [(TRIAL_PATH, principal)] + list(zip(_marcas(), copias)):
        if actual is _ALTERADO or actual is None or actual["inicio"] != inicio or actual["ultimo"] != nuevo_ultimo:
            try:
                _escribir(ruta, inicio, nuevo_ultimo, mid)
            except OSError:
                pass
    if dias_restantes == 0:
        raise LicenciaInvalida(
            "Tu período de prueba de 7 días ha terminado.\n\n"
            "Para continuar usando SECOP Automatizador, adquiere tu licencia:\n"
            "📧 polymodulospvc@gmail.com\n"
            "📱 WhatsApp: [tu número]\n\n"
            "Planes desde $350.000/mes"
        )

    return {"activo": True, "dias_restantes": dias_restantes, "es_trial": True, "nombre": "TRIAL"}
