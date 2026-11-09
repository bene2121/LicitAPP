# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec de LicitApp (Windows 11 x64; también construye en Linux para verificarlo).

Uso (desde la raíz del proyecto):
    pyinstaller build/secop.spec --clean --noconfirm
Resultado: dist/LicitApp/LicitApp.exe (carpeta, no un solo archivo: arranca más rápido
y Streamlit necesita sus archivos estáticos en disco).

Cómo funciona:
  * launcher.py abre la ventana (pywebview) y relanza el mismo .exe con el argumento
    __streamlit_worker__ para correr Streamlit en 127.0.0.1 en un puerto libre.
  * Streamlit ejecuta m5_dashboard/app.py desde disco (va como dato) y esa app importa
    los módulos m1..m7. PyInstaller no ve esos imports (app.py no se analiza), por eso se
    listan aquí con collect_submodules + hiddenimports de sus dependencias.
  * Solo viaja la clave PÚBLICA de licencias. Nunca la clave de firma ni los generadores de licencias.
  * Datos del usuario (BD, perfil, prueba de 7 días, licencia) quedan junto al .exe
    en <instalación>\\data (ver licencias/trial._data_dir); los expedientes en
    Documentos\\LicitApp\\expedientes (ver m6_propuesta/expediente._raiz_expedientes).
"""

import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import (
    collect_all,
    collect_data_files,
    collect_submodules,
    copy_metadata,
)

ROOT = str(Path(SPECPATH).parent.resolve())
sys.path.insert(0, ROOT)  # collect_submodules importa los paquetes propios al armar la lista
BUILD = SPECPATH
ES_WINDOWS = sys.platform == "win32"

datas = []
binaries = []
hiddenimports = []


def _todo(paquete, requerido=True):
    """collect_all tolerante: datos, binarios, imports ocultos y metadatos de un paquete."""
    try:
        d, b, h = collect_all(paquete)
    except Exception as exc:  # paquete ausente
        if requerido:
            raise
        print(f"[spec] omitido {paquete}: {exc}")
        return
    datas.extend(d)
    binaries.extend(b)
    hiddenimports.extend(h)


# ── Streamlit y su pila (metadatos: importlib.metadata los pide en tiempo de ejecución) ──
_todo("streamlit")
for _pkg in (
    "altair", "pandas", "numpy", "plotly", "pyarrow", "pydeck", "watchdog", "click", "rich",
    "python-dotenv", "cryptography", "httpx", "requests", "apscheduler", "sqlalchemy",
    "openpyxl", "python-docx", "pypdf", "scipy", "packaging", "tornado", "narwhals",
):
    try:
        datas.extend(copy_metadata(_pkg))
    except Exception:
        pass

# Paquetes con datos/plantillas propias
for _pkg in ("docx", "openpyxl", "pypdf", "plotly", "certifi"):
    _todo(_pkg, requerido=_pkg in ("docx", "openpyxl", "pypdf"))
# Streamlit usa pyarrow/pandas a fondo: hooks de PyInstaller cubren sus binarios.
hiddenimports += collect_submodules("streamlit.runtime")
hiddenimports += collect_submodules("streamlit.web")
hiddenimports += collect_submodules("apscheduler")
hiddenimports += ["sqlalchemy.dialects.sqlite", "sqlite3"]

# ── Código propio: se compila dentro del ejecutable ─────────────────────────────────────
for _mod in ("m1_ingestor", "m2_formulas", "m3_filtrado", "m4_bot", "m6_propuesta", "m7_competencia"):
    hiddenimports += collect_submodules(_mod)
hiddenimports += [
    "config", "api_client", "seguridad",
    # Solo lo necesario de licencias (sin generadores ni servidor):
    "licencias", "licencias.validador", "licencias.trial",
    "m5_dashboard",
    "dotenv", "playwright", "playwright.sync_api",
]

# ── Datos propios ──────────────────────────────────────────────────────────────────────
datas += [
    (f"{ROOT}/m5_dashboard/app.py", "m5_dashboard"),
    (f"{ROOT}/m5_dashboard/__init__.py", "m5_dashboard"),
    # C-1: solo la clave pública; nunca privada.pem.
    (f"{ROOT}/licencias/claves/publica.pem", "licencias/claves"),
    (f"{ROOT}/LICENSE.txt", "."),
]
if os.path.isfile(f"{ROOT}/LEAME_CLIENTE.txt"):
    datas.append((f"{ROOT}/LEAME_CLIENTE.txt", "."))
if os.path.isdir(f"{ROOT}/.streamlit"):
    datas.append((f"{ROOT}/.streamlit", ".streamlit"))

# ── Ventana nativa (solo Windows): pywebview + WebView2 + pythonnet ──────────────────────
runtime_hooks = []
# unittest NO se excluye: scipy.stats (fórmula MG) lo importa.
excludes = ["tkinter", "_tkinter", "test", "tests", "pytest",
            "webview.platforms.cocoa", "webview.platforms.gtk", "webview.platforms.qt",
            "webview.platforms.cef", "IPython", "matplotlib"]
if ES_WINDOWS:
    _todo("webview", requerido=True)
    for _pkg in ("pythonnet", "clr_loader"):
        _todo(_pkg, requerido=False)
    try:
        datas.extend(copy_metadata("pywebview"))
        datas.extend(copy_metadata("pythonnet"))
    except Exception:
        pass
    hiddenimports += [
        "webview.platforms.winforms", "webview.platforms.edgechromium", "webview.platforms.mshtml",
        "clr", "clr_loader", "clr_loader.ffi", "pythonnet",
    ]
    # DLLs de interop al raíz del paquete y WebView2Loader por arquitectura (ver rth_pywebview.py)
    import site as _site

    _wvlib = None
    for _sp in _site.getsitepackages() + [_site.getusersitepackages()]:
        if os.path.isdir(os.path.join(_sp, "webview", "lib")):
            _wvlib = os.path.join(_sp, "webview", "lib")
            break
    if _wvlib:
        for _dll in ("Microsoft.Web.WebView2.Core.dll", "Microsoft.Web.WebView2.WinForms.dll",
                     "WebBrowserInterop.x64.dll", "WebBrowserInterop.x86.dll"):
            _p = os.path.join(_wvlib, _dll)
            if os.path.isfile(_p):
                binaries.append((_p, "."))
        for _arch in ("win-x64", "win-x86", "win-arm64"):
            _p = os.path.join(_wvlib, "runtimes", _arch, "native", "WebView2Loader.dll")
            if os.path.isfile(_p):
                binaries.append((_p, _arch))
    runtime_hooks.append(f"{BUILD}/rth_pywebview.py")
else:
    # En Linux (verificación) la ventana no se usa: se prueba con --sin-ventana.
    excludes += ["webview"]

_icono = f"{BUILD}/icon.ico"

# Lista blanca del paquete licencias: nunca claves privadas, licencias ni herramientas admin.
_LICENCIAS_CLIENTE = ("__init__.py", "validador.py", "trial.py")
_licencias_datas = [(f"{ROOT}/licencias/{_f}", "licencias") for _f in _LICENCIAS_CLIENTE]

a = Analysis(
    [f"{ROOT}/launcher.py"],
    pathex=[ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=sorted(set(hiddenimports)),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=runtime_hooks,
    excludes=excludes,
    noarchive=False,
)

pyz = PYZ(a.pure)

# UPX corrompe las DLL .NET firmadas de WebView2/pythonnet; se deja desactivado.
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="LicitApp",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,   # aplicación de ventana; los errores quedan en data/*.log
    icon=_icono if os.path.isfile(_icono) else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="LicitApp",
)
