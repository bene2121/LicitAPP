# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec para SECOP Automatizador / LicitApp.
Uso: pyinstaller build/secop.spec --clean --noconfirm

FIXES aplicados (v2):
  FIX-1  DLLs de pywebview (WebView2 + WinForms interop) se copian al raiz
         de _MEIPASS (destino ".") para que interop_dll_path() las encuentre
         en modo frozen (pywebview/util.py comprueba sys._MEIPASS/dll_name).
  FIX-2  hiddenimports completos para todos los backends de pywebview en
         Windows: winforms, edgechromium, clr, clr_loader, pythonnet.
  FIX-3  copy_metadata() ampliado: python-dotenv, pywebview, cryptography,
         httpx, requests, apscheduler para que importlib.metadata no falle.
  FIX-4  collect_data_files('webview') asegura que TODOS los datos del
         paquete webview (lib/, js/, etc.) queden en el bundle.
  FIX-5  runtime_hook rth_pywebview.py parchea la busqueda de DLLs antes
         de que pywebview intente localizarlas con __file__ (que en frozen
         apunta dentro del PYZ, no al disco).
  FIX-6  freeze_support() en runtime_hook para compatibilidad con cualquier
         dependencia que use multiprocessing internamente.
  FIX-7  noarchive=False se mantiene; se agrega collect_submodules para
         streamlit.runtime y apscheduler para evitar ImportError silenciosos.
  FIX-8  UPX desactivado en los .dll de pythonnet / WebView2 — UPX corrompe
         DLLs .NET firmados.
"""

import sys
from pathlib import Path
from PyInstaller.utils.hooks import (
    collect_data_files,
    collect_submodules,
    copy_metadata,
)

ROOT = str(Path(SPECPATH).parent.resolve())
BUILD = SPECPATH  # directorio build/ donde vive el .spec y rth_pywebview.py

# ── Metadatos necesarios en runtime (importlib.metadata) ─────────────────────
_metadata = []
for _pkg in [
    "streamlit",
    "altair",
    "pandas",
    "plotly",
    "pyarrow",
    "pydeck",
    "watchdog",
    "python-dotenv",   # FIX-3: el import es 'dotenv', el paquete es 'python-dotenv'
    "cryptography",
    "httpx",
    "requests",
    "apscheduler",
    "pywebview",       # FIX-3: pywebview usa importlib.metadata internamente
    "pythonnet",       # FIX-3
    "click",
    "rich",
]:
    try:
        _metadata += copy_metadata(_pkg)
    except Exception:
        pass

# ── Datos de paquetes con archivos no-Python ──────────────────────────────────
# FIX-1/FIX-4: collect_data_files('webview') devuelve todos los archivos de
#              datos del paquete webview, incluyendo lib/*.dll y lib/runtimes/*.
#              Los reemplazamos con entradas explícitas para que las DLLs
#              principales queden en "." (raiz de _MEIPASS) donde
#              interop_dll_path() las busca en modo frozen.
_webview_data = collect_data_files("webview")

# Separar DLLs principales del resto de datos de webview
import os, glob as _glob, site as _site

def _find_webview_lib():
    """Localiza el directorio webview/lib/ en site-packages."""
    for sp in _site.getsitepackages() + [_site.getusersitepackages()]:
        candidate = os.path.join(sp, "webview", "lib")
        if os.path.isdir(candidate):
            return candidate
    # Fallback: buscar via importlib
    try:
        import importlib.util
        spec = importlib.util.find_spec("webview")
        if spec and spec.origin:
            candidate = os.path.join(os.path.dirname(spec.origin), "lib")
            if os.path.isdir(candidate):
                return candidate
    except Exception:
        pass
    return None

_wvlib = _find_webview_lib()

# DLLs principales de interop (van al raiz de _MEIPASS = ".")
_webview_root_dlls = []
if _wvlib:
    for _dll in [
        "Microsoft.Web.WebView2.Core.dll",
        "Microsoft.Web.WebView2.WinForms.dll",
        "WebBrowserInterop.x64.dll",
        "WebBrowserInterop.x86.dll",
    ]:
        _p = os.path.join(_wvlib, _dll)
        if os.path.isfile(_p):
            _webview_root_dlls.append((_p, "."))

    # WebView2Loader.dll por arquitectura (van a win-x64/, win-x86/, win-arm64/)
    for _arch in ("win-x64", "win-x86", "win-arm64"):
        _p = os.path.join(_wvlib, "runtimes", _arch, "native", "WebView2Loader.dll")
        if os.path.isfile(_p):
            # interop_dll_path('win-x64') frozen -> sys._MEIPASS/win-x64
            # os.environ['Path'] += ';' + that_dir  -> WebView2Loader.dll debe estar ahi
            _webview_root_dlls.append((_p, _arch))

# ── Datos de streamlit ────────────────────────────────────────────────────────
_streamlit_data = collect_data_files("streamlit", include_py_files=False)

a = Analysis(
    [f"{ROOT}/launcher.py"],
    pathex=[ROOT],
    binaries=[],
    datas=[
        # Metadatos para importlib.metadata
        *_metadata,

        # FIX-1: DLLs de pywebview al raiz de _MEIPASS
        *_webview_root_dlls,

        # Resto de datos del paquete webview (js/, localization, etc.)
        *_webview_data,

        # Datos de streamlit (templates, static, etc.)
        *_streamlit_data,

        # Modulos propios del proyecto
        (f"{ROOT}/m2_formulas",  "m2_formulas"),
        (f"{ROOT}/m3_filtrado",  "m3_filtrado"),
        (f"{ROOT}/m4_bot",       "m4_bot"),
        (f"{ROOT}/m5_dashboard", "m5_dashboard"),
        (f"{ROOT}/licencias",    "licencias"),

        # C-1: Solo la clave publica — NUNCA la privada.pem
        (f"{ROOT}/licencias/claves/publica.pem", "licencias/claves"),

        # Archivos sueltos en raiz del bundle
        (f"{ROOT}/config.py",    "."),
        (f"{ROOT}/api_client.py", "."),
    ],
    hiddenimports=[
        # Modulos propios
        "licencias",
        "licencias.validador",
        "licencias.trial",

        # Streamlit internals (no siempre detectados por el analizador estatico)
        "streamlit",
        "streamlit.web.cli",
        "streamlit.web.bootstrap",
        "streamlit.web.server",
        "streamlit.web.server.server",
        "streamlit.runtime.scriptrunner",
        "streamlit.runtime.scriptrunner.magic_funcs",
        "streamlit.runtime.caching",
        "streamlit.runtime.caching.storage",
        "streamlit.runtime.caching.storage.dummy_cache_storage",
        "streamlit.runtime.caching.storage.local_disk_cache_storage",
        "streamlit.components.v1",
        "streamlit.components.v1.components",

        # FIX-2: pywebview backends de Windows — todos necesarios
        "webview",
        "webview.guilib",
        "webview.util",
        "webview.window",
        "webview.event",
        "webview.http",
        "webview.menu",
        "webview.screen",
        "webview.localization",
        "webview.js",
        "webview.platforms",
        "webview.platforms.winforms",       # backend principal Windows
        "webview.platforms.edgechromium",   # backend EdgeChromium / WebView2
        "webview.platforms.mshtml",         # fallback MSHTML
        # FIX-2: pythonnet / clr — requerido por winforms y edgechromium
        "clr",
        "clr_loader",
        "clr_loader.ffi",
        "clr_loader.ffi.dlls",
        "pythonnet",

        # Plotly / visualizacion
        "plotly",
        "plotly.graph_objects",
        "plotly.express",
        "plotly.io",
        "plotly.io._renderers",

        # Pandas / Numpy / PyArrow
        "pandas",
        "pandas._libs.tslibs.np_datetime",
        "pandas._libs.tslibs.nattype",
        "pandas._libs.tslibs.timedeltas",
        "numpy",
        "pyarrow",
        "pyarrow.vendored.version",

        # Red / HTTP
        "httpx",
        "httpx._transports.default",
        "requests",
        "urllib3",
        "certifi",

        # Automatizacion
        "playwright",
        "playwright.sync_api",
        "playwright.async_api",

        # Scheduler
        "apscheduler",
        "apscheduler.schedulers.background",
        "apscheduler.schedulers.blocking",
        "apscheduler.executors.pool",
        "apscheduler.jobstores.memory",
        "apscheduler.triggers.interval",
        "apscheduler.triggers.cron",

        # BD / ORM
        "sqlalchemy",
        "sqlalchemy.dialects.sqlite",
        "sqlalchemy.pool",

        # Criptografia
        "cryptography",
        "cryptography.hazmat.primitives.asymmetric.padding",
        "cryptography.hazmat.primitives.hashes",
        "cryptography.hazmat.primitives.serialization",
        "cryptography.hazmat.backends",
        "cryptography.hazmat.backends.openssl",
        "cryptography.hazmat.backends.openssl.backend",

        # dotenv (paquete python-dotenv, modulo dotenv)
        "dotenv",
        "dotenv.main",

        # Altair
        "altair",
        "altair.vegalite.v6",

        # Utilidades stdlib que PyInstaller a veces excluye
        "email",
        "email.mime",
        "email.mime.text",
        "email.mime.multipart",
        "smtplib",
        "uuid",
        "socket",
        "sqlite3",
        "json",
        "hashlib",
        "platform",
        "threading",
        "subprocess",
        "multiprocessing",
        "multiprocessing.freeze_support",

        # Pydeck
        "pydeck",
    ],

    # FIX-5: runtime hook que parchea la resolucion de DLLs de pywebview
    #         y llama a freeze_support() (FIX-6)
    hookspath=[f"{BUILD}"],        # busca hook-webview.py en build/
    hooksconfig={},
    runtime_hooks=[
        f"{BUILD}/rth_pywebview.py",   # FIX-5 + FIX-6
    ],
    excludes=[
        "tkinter",
        "_tkinter",
        "unittest",
        "test",
        "tests",
        # No necesitamos los backends de pywebview para otros SO
        "webview.platforms.cocoa",
        "webview.platforms.gtk",
        "webview.platforms.qt",
        "webview.platforms.cef",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="SECOP_Automatizador",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    # FIX-8: excluir DLLs .NET firmados del compresor UPX (UPX las corrompe)
    upx_exclude=[
        "Microsoft.Web.WebView2.Core.dll",
        "Microsoft.Web.WebView2.WinForms.dll",
        "WebBrowserInterop.x64.dll",
        "WebBrowserInterop.x86.dll",
        "WebView2Loader.dll",
        "Python.Runtime.dll",
        "ClrLoader.dll",
        "vcruntime140.dll",
        "msvcp140.dll",
    ],
    console=True,   # mantener True para ver stderr en caso de error
    icon=f"{ROOT}/build/icon.ico",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[
        "Microsoft.Web.WebView2.Core.dll",
        "Microsoft.Web.WebView2.WinForms.dll",
        "WebBrowserInterop.x64.dll",
        "WebBrowserInterop.x86.dll",
        "WebView2Loader.dll",
        "Python.Runtime.dll",
        "ClrLoader.dll",
        "vcruntime140.dll",
        "msvcp140.dll",
    ],
    name="SECOP_Automatizador",
)
