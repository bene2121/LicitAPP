"""Utilidades de seguridad compartidas por todos los módulos de LicitApp.

Sin dependencias externas. Se importan desde la raíz del proyecto.
"""
from __future__ import annotations

import base64
import html
import os
import re
import sys
import zipfile
from pathlib import Path

# ── Límites razonables para archivos del usuario ─────────────────────────────
MAX_DOCX_BYTES = 50 * 1024 * 1024        # un .docx de propuesta no pasa de esto
MAX_PDF_BYTES = 50 * 1024 * 1024
MAX_ZIP_DESCOMPRIMIDO = 300 * 1024 * 1024  # suma de lo que ocuparía descomprimido
MAX_ZIP_MIEMBRO = 120 * 1024 * 1024
MAX_ZIP_MIEMBROS = 5000
MAX_ZIP_RATIO = 200                       # descomprimido / comprimido por miembro
MAX_RESPUESTA_BYTES = 25 * 1024 * 1024    # respuestas HTTP (JSON de Socrata/API)


class ArchivoNoSeguro(ValueError):
    """El archivo excede los límites o tiene una estructura peligrosa."""


# ── Escapado para mostrar datos remotos ──────────────────────────────────────

def esc_html(valor) -> str:
    """Escapa texto remoto antes de insertarlo en HTML (unsafe_allow_html)."""
    return html.escape(str(valor if valor is not None else ""), quote=True)


_MD_ESPECIALES = re.compile(r"([\\`*_{}\[\]()#+!<>|~$])")


def esc_md(valor) -> str:
    """Escapa Markdown (enlaces, imágenes, HTML) en texto remoto."""
    return _MD_ESPECIALES.sub(r"\\\1", str(valor if valor is not None else ""))


def sin_control(texto, largo: int = 200) -> str:
    """Quita saltos de línea y caracteres de control (cabeceras, nombres)."""
    limpio = "".join(c if c.isprintable() else " " for c in str(texto or ""))
    return " ".join(limpio.split())[:largo]


def nombre_archivo_seguro(texto, largo: int = 60, defecto: str = "archivo") -> str:
    """Nombre de archivo sin separadores, sin puntos iniciales ni caracteres raros."""
    limpio = re.sub(r"[^\w.\-]+", "_", str(texto or "")).strip("_.")
    limpio = re.sub(r"\.{2,}", ".", limpio)[:largo].strip("_.")
    return limpio or defecto


def redactar(texto, secretos) -> str:
    """Reemplaza cada secreto que aparezca en `texto` (para logs y errores)."""
    salida = str(texto)
    for s in secretos or []:
        s = str(s or "")
        if len(s) >= 3:
            salida = salida.replace(s, "***")
    return salida


# ── Rutas y archivos ─────────────────────────────────────────────────────────

def ruta_dentro_de(base: Path | str, ruta: Path | str) -> bool:
    """True si `ruta` (ya resuelta, sin symlinks) queda dentro de `base`."""
    try:
        Path(ruta).resolve().relative_to(Path(base).resolve())
        return True
    except (ValueError, OSError):
        return False


def revisar_tamano(ruta: Path | str, max_bytes: int) -> None:
    tam = Path(ruta).stat().st_size
    if tam > max_bytes:
        raise ArchivoNoSeguro(
            f"{Path(ruta).name} pesa {tam // (1024 * 1024)} MB; el máximo permitido es {max_bytes // (1024 * 1024)} MB."
        )


def revisar_zip(zf: zipfile.ZipFile) -> None:
    """Rechaza zip bombs y nombres con rutas peligrosas (zip-slip)."""
    items = zf.infolist()
    if len(items) > MAX_ZIP_MIEMBROS:
        raise ArchivoNoSeguro("El archivo comprimido tiene demasiados elementos.")
    total = 0
    for it in items:
        nombre = it.filename.replace("\\", "/")
        if nombre.startswith("/") or re.match(r"^[A-Za-z]:", nombre) or ".." in nombre.split("/"):
            raise ArchivoNoSeguro("El archivo comprimido trae rutas no permitidas.")
        if it.file_size > MAX_ZIP_MIEMBRO:
            raise ArchivoNoSeguro("Un elemento del archivo comprimido es demasiado grande.")
        if it.compress_size and it.file_size / it.compress_size > MAX_ZIP_RATIO and it.file_size > 1024 * 1024:
            raise ArchivoNoSeguro("El archivo comprimido tiene una razón de compresión sospechosa.")
        total += it.file_size
        if total > MAX_ZIP_DESCOMPRIMIDO:
            raise ArchivoNoSeguro("El archivo comprimido ocuparía demasiado al descomprimirse.")


def abrir_docx_zip(ruta: Path | str) -> zipfile.ZipFile:
    """Abre un .docx como zip tras validar tamaño y estructura."""
    revisar_tamano(ruta, MAX_DOCX_BYTES)
    zf = zipfile.ZipFile(ruta)
    try:
        revisar_zip(zf)
    except Exception:
        zf.close()
        raise
    return zf


# ── Red ──────────────────────────────────────────────────────────────────────

def exigir_https(url: str, permitir_local: bool = True) -> str:
    """Devuelve la URL si usa https (o http a localhost); si no, ValueError."""
    from urllib.parse import urlparse
    u = urlparse(str(url or ""))
    if u.scheme == "https" and u.hostname:
        return url
    if permitir_local and u.scheme == "http" and u.hostname in {"localhost", "127.0.0.1", "::1"}:
        return url
    raise ValueError("La URL debe usar https://")


def leer_limitado(fp, max_bytes: int | None = None) -> bytes:
    """Lee como máximo `max_bytes` de un objeto con .read(); error si hay más."""
    max_bytes = MAX_RESPUESTA_BYTES if max_bytes is None else max_bytes
    datos = fp.read(max_bytes + 1)
    if len(datos) > max_bytes:
        raise ValueError("La respuesta del servidor es demasiado grande.")
    return datos


# ── Secretos en reposo (solo Windows, DPAPI; sin dependencias) ───────────────

def _dpapi(datos: bytes, proteger: bool) -> bytes | None:
    if sys.platform != "win32":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        class _Blob(ctypes.Structure):
            _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

        entrada = _Blob(len(datos), ctypes.cast(ctypes.create_string_buffer(datos, len(datos)),
                                                ctypes.POINTER(ctypes.c_char)))
        salida = _Blob()
        f = ctypes.windll.crypt32.CryptProtectData if proteger else ctypes.windll.crypt32.CryptUnprotectData
        args = (ctypes.byref(entrada), None, None, None, None, 0, ctypes.byref(salida))
        if not f(*args):
            return None
        try:
            return ctypes.string_at(salida.pbData, salida.cbData)
        finally:
            ctypes.windll.kernel32.LocalFree(salida.pbData)
    except Exception:
        return None


def guardar_secreto(ruta: Path | str, valor: str) -> bool:
    """Guarda `valor` cifrado con la cuenta de Windows. False si no se puede cifrar.

    Nunca escribe el secreto en claro: sin cifrado disponible no guarda nada.
    """
    ruta = Path(ruta)
    if not valor:
        try:
            ruta.unlink()
        except OSError:
            pass
        return True
    blob = _dpapi(valor.encode("utf-8"), True)
    if blob is None:
        return False
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(base64.b64encode(blob).decode("ascii"), encoding="ascii")
    return True


def leer_secreto(ruta: Path | str) -> str:
    ruta = Path(ruta)
    try:
        blob = base64.b64decode(ruta.read_text(encoding="ascii"))
    except (OSError, ValueError):
        return ""
    claro = _dpapi(blob, False)
    return claro.decode("utf-8", "ignore") if claro else ""


def escribir_json_privado(ruta: Path | str, texto: str) -> None:
    """Escribe de forma atómica y con permisos 600 donde el sistema los respeta."""
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    tmp = ruta.with_name(ruta.name + ".tmp")
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(texto)
    os.replace(tmp, ruta)


# ── Perfil del proponente: nunca con contraseñas en el JSON ──────────────────

def guardar_perfil_json(ruta_perfil: Path | str, ruta_secreto: Path | str, perfil: dict) -> bool:
    """Escribe el perfil sin `smtp_pass`; la clave va cifrada aparte (ver guardar_secreto).

    Devuelve False solo si había una clave y el sistema no pudo cifrarla (no se guarda).
    """
    import json
    sin_secretos = {k: v for k, v in perfil.items() if k != "smtp_pass"}
    escribir_json_privado(ruta_perfil, json.dumps(sin_secretos, ensure_ascii=False, indent=2))
    clave = perfil.get("smtp_pass") or ""
    return guardar_secreto(ruta_secreto, clave) if clave else True


def cargar_perfil_json(ruta_perfil: Path | str, ruta_secreto: Path | str):
    """Lee el perfil; migra una clave en claro de versiones anteriores al almacén cifrado."""
    import json
    with open(ruta_perfil, encoding="utf-8") as f:
        perfil = json.load(f)
    if not isinstance(perfil, dict):
        return None
    if perfil.get("smtp_pass"):
        guardar_perfil_json(ruta_perfil, ruta_secreto, perfil)  # reescribe el JSON sin la clave
    perfil["smtp_pass"] = leer_secreto(ruta_secreto) or perfil.get("smtp_pass", "")
    return perfil
