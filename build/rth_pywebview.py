"""
Runtime hook para LicitApp — se ejecuta ANTES de cualquier import del programa.

Problemas que resuelve:
  1. FIX-5: pywebview/util.py::interop_dll_path() usa os.path.dirname(__file__)
     para encontrar sus DLLs, pero en modo frozen __file__ apunta dentro del
     PYZ (no a un directorio real en disco). Este hook parchea la funcion para
     que devuelva la ruta correcta desde sys._MEIPASS.

  2. FIX-6: multiprocessing.freeze_support() debe llamarse al inicio del
     proceso principal para que los subprocesos que PyInstaller spawn internamente
     no entren en bucle. Tambien protege a dependencias que usen multiprocessing
     (pyarrow parallel, numpy, etc.).

  3. Asegura que el directorio de DLLs quede en os.environ['Path'] para que
     Windows pueda cargar WebView2Loader.dll y Python.Runtime.dll correctamente.
"""

import os
import sys

# ── FIX-6: freeze_support ─────────────────────────────────────────────────────
# Debe ser lo primero — antes de cualquier otro import
if __name__ == "__main__":
    # Este bloque solo actua cuando este modulo se ejecuta directamente,
    # lo que no ocurre en un runtime hook, pero por seguridad lo incluimos.
    import multiprocessing
    multiprocessing.freeze_support()
else:
    # En runtime hook, simplemente llamamos freeze_support directamente
    import multiprocessing
    multiprocessing.freeze_support()

# ── FIX-5: parchar interop_dll_path de pywebview ─────────────────────────────
# Solo aplicable en ejecutable frozen
if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
    _MEIPASS = sys._MEIPASS

    def _patched_interop_dll_path(dll_name: str) -> str:
        """
        Version parchada de webview.util.interop_dll_path para modo frozen.

        pywebview 4.4.1 llama a esta funcion con:
          - 'Microsoft.Web.WebView2.Core.dll'
          - 'Microsoft.Web.WebView2.WinForms.dll'
          - 'win-x64', 'win-x86', 'win-arm64'  (directorios de WebView2Loader)

        En el spec copiamos las DLLs principales a "." (raiz de _MEIPASS)
        y WebView2Loader.dll a "win-x64/", "win-x86/", "win-arm64/".
        """
        from platform import architecture

        # Normalizar alias
        if dll_name == "WebBrowserInterop.dll":
            dll_name = (
                "WebBrowserInterop.x64.dll"
                if architecture()[0] == "64bit"
                else "WebBrowserInterop.x86.dll"
            )

        # 1. DLL principal al raiz de _MEIPASS (Microsoft.Web.WebView2.*.dll, WebBrowserInterop.*.dll)
        candidate = os.path.join(_MEIPASS, dll_name)
        if os.path.exists(candidate):
            return candidate

        # 2. Directorio de runtime para WebView2Loader (win-x64, win-x86, win-arm64)
        #    interop_dll_path('win-x64') debe devolver el DIRECTORIO que contiene
        #    WebView2Loader.dll, para que edgechromium.py lo agregue a Path.
        runtime_dir = os.path.join(_MEIPASS, dll_name)
        if os.path.isdir(runtime_dir):
            return runtime_dir

        # 3. DLL dentro de un subdirectorio de runtime
        native_path = os.path.join(_MEIPASS, "webview", "lib", "runtimes", dll_name, "native")
        if os.path.isdir(native_path):
            return native_path

        # 4. Ultima oportunidad: junto al ejecutable
        exe_dir = os.path.dirname(os.path.realpath(sys.executable))
        candidate = os.path.join(exe_dir, dll_name)
        if os.path.exists(candidate):
            return candidate

        raise FileNotFoundError(
            f"[LicitApp] No se encontro la DLL de pywebview: {dll_name}\n"
            f"  Buscado en: {_MEIPASS}"
        )

    # Inyectar el parche ANTES de que webview se importe
    # Usamos sys.modules para interceptar la importacion
    import importlib
    import types

    # Crear un modulo ficticio webview.util con la funcion parchada,
    # o parchar en caliente si ya fue importado
    try:
        import webview.util as _wv_util
        _wv_util.interop_dll_path = _patched_interop_dll_path
    except ImportError:
        # webview aun no esta importado — registrar el parche para cuando se importe
        # usando un import hook
        class _WebviewPatcher:
            def find_module(self, name, path=None):
                if name == "webview.util":
                    return self
                return None

            def load_module(self, name):
                if name in sys.modules:
                    mod = sys.modules[name]
                    mod.interop_dll_path = _patched_interop_dll_path
                    return mod
                mod = importlib.import_module(name)
                mod.interop_dll_path = _patched_interop_dll_path
                sys.modules[name] = mod
                return mod

        sys.meta_path.insert(0, _WebviewPatcher())

    # FIX adicional: asegurar que los directorios de runtime esten en PATH
    # para que Windows pueda cargar WebView2Loader.dll al iniciar EdgeChromium
    for _arch in ("win-x64", "win-x86", "win-arm64"):
        _arch_dir = os.path.join(_MEIPASS, _arch)
        if os.path.isdir(_arch_dir) and _arch_dir not in os.environ.get("PATH", ""):
            os.environ["PATH"] = _arch_dir + os.pathsep + os.environ.get("PATH", "")

    # Agregar _MEIPASS al PATH para que Python.Runtime.dll y ClrLoader.dll
    # sean encontradas por el cargador de DLLs de Windows
    if _MEIPASS not in os.environ.get("PATH", ""):
        os.environ["PATH"] = _MEIPASS + os.pathsep + os.environ.get("PATH", "")
