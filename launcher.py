"""
Launcher principal de LicitApp.
Arranca Streamlit internamente y abre la app en ventana nativa Windows (PyWebView).
No abre el navegador — la app se ve como una aplicación de escritorio.
"""
import os
import sys

# Ejecutable sin consola (console=False): sys.stdout/stderr valen None y romperían print/logging.
for _flujo in ("stdout", "stderr"):
    if getattr(sys, _flujo) is None:
        setattr(sys, _flujo, open(os.devnull, "w", encoding="utf-8"))

import multiprocessing
# FIX-6: freeze_support debe ser lo primero que se llama en el proceso principal
# de un ejecutable PyInstaller. Sin esto, cualquier dependencia que use
# multiprocessing internamente (pyarrow, numpy parallel, etc.) puede causar
# bucles de subprocesos o crashes al arrancar el exe.
multiprocessing.freeze_support()

import os
import sys
import traceback

# ── Log de errores de arranque ────────────────────────────────────────────────
def _log_dir():
    if os.environ.get("LICITAPP_DATA_DIR"):
        return os.environ["LICITAPP_DATA_DIR"]
    if getattr(sys, "frozen", False):
        return os.path.join(os.path.dirname(sys.executable), "data")
    return os.path.join(os.path.dirname(__file__), "data")

def _write_log(msg: str):
    try:
        d = _log_dir()
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "licitapp_startup.log"), "a", encoding="utf-8") as f:
            import datetime
            f.write(f"\n[{datetime.datetime.now().isoformat()}] {msg}\n")
    except Exception:
        pass

_write_log(f"Iniciando launcher — argv={sys.argv}")

try:
    # ── Modo worker: este proceso ES el backend de Streamlit ──────────────────
    if len(sys.argv) > 1 and sys.argv[1] == "__streamlit_worker__":
        _write_log("Modo worker Streamlit")
        from streamlit.web import cli as stcli
        sys.argv = ["streamlit"] + sys.argv[2:]
        stcli.main()
        sys.exit(0)
    # ─────────────────────────────────────────────────────────────────────────
except Exception as _e:
    _write_log(f"ERROR en worker: {traceback.format_exc()}")
    raise

import threading
import time
import socket
import subprocess  # nosec B404 - solo lanza streamlit con argumentos fijos

# Modo de verificación sin ventana: arranca el servidor, imprime la URL y espera.
# Sirve para probar el ejecutable en equipos sin entorno gráfico.
SIN_VENTANA = "--sin-ventana" in sys.argv or bool(os.environ.get("LICITAPP_SIN_VENTANA"))
if not SIN_VENTANA:
    import webview

# ── Instancia única (solo para el proceso GUI, no para el worker) ─────────────
if sys.platform == "win32" and not SIN_VENTANA:
    import ctypes
    _MUTEX = ctypes.windll.kernel32.CreateMutexW(None, False, "LicitApp_SingleInstance")
    if ctypes.windll.kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
        ctypes.windll.user32.MessageBoxW(
            0,
            "LicitApp ya está abierto.\nRevisa la barra de tareas.",
            "LicitApp",
            0x40,
        )
        sys.exit(0)
# ─────────────────────────────────────────────────────────────────────────────

HOST = "127.0.0.1"


def _elegir_puerto(preferido: int = 8501) -> int:
    """8501 si está libre; si no, un puerto libre que asigne el sistema."""
    for candidato in (preferido, 0):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind((HOST, candidato))
                return s.getsockname()[1]
            except OSError:
                continue
    return preferido


PORT = int(os.environ.get("LICITAPP_PUERTO") or _elegir_puerto())
STREAMLIT_URL = f"http://{HOST}:{PORT}"


def _puerto_libre(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex((HOST, port)) != 0


def _esperar_streamlit(timeout_seg: int = 60) -> bool:
    """Espera a que Streamlit conteste su chequeo de salud (no solo a que abra el puerto)."""
    import urllib.request

    for _ in range(timeout_seg * 4):
        if not _puerto_libre(PORT):
            try:
                with urllib.request.urlopen(f"{STREAMLIT_URL}/_stcore/health", timeout=2) as r:  # nosec B310 - URL fija http://127.0.0.1:<puerto> propia
                    if r.status == 200:
                        return True
            except Exception:
                pass
        time.sleep(0.25)
    return False


def _iniciar_streamlit() -> subprocess.Popen:
    """Lanza Streamlit como proceso hijo.
    Cuando está congelado (PyInstaller), relanza el mismo .exe con el flag
    __streamlit_worker__ para que corra Streamlit en lugar de la GUI.
    """
    # En modo frozen, __file__ apunta dentro del PYZ; usar sys._MEIPASS en su lugar.
    if getattr(sys, "frozen", False):
        base = sys._MEIPASS  # type: ignore[attr-defined]
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    app_path = os.path.join(base, "m5_dashboard", "app.py")

    streamlit_args = [
        "__streamlit_worker__",
        "run", app_path,
        "--server.port", str(PORT),
        "--server.address", HOST,
        "--server.headless", "true",
        "--server.enableXsrfProtection", "true",
        "--browser.gatherUsageStats", "false",
        "--client.toolbarMode", "viewer",
        "--theme.base", "light",
        "--theme.primaryColor", "#1F4E79",
    ]

    if getattr(sys, "frozen", False):
        cmd = [sys.executable] + streamlit_args
    else:
        cmd = [sys.executable, "-m", "streamlit"] + streamlit_args[1:]

    # Bug 1: --global.developmentMode no es un flag CLI válido — usar env var
    env = os.environ.copy()
    env["STREAMLIT_GLOBAL_DEVELOPMENT_MODE"] = "false"

    # Redirigir stderr del worker a un archivo de log para poder diagnosticar
    # fallos de arranque de Streamlit (antes era DEVNULL y ocultaba errores).
    _worker_log_path = os.path.join(_log_dir(), "streamlit_worker.log")
    try:
        os.makedirs(_log_dir(), exist_ok=True)
        _worker_stderr = open(_worker_log_path, "a", encoding="utf-8")
    except Exception:
        _worker_stderr = subprocess.DEVNULL

    kwargs = {
        "stdout": subprocess.DEVNULL,
        "stderr": _worker_stderr,
        "cwd": base,
        "env": env,
    }
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    return subprocess.Popen(cmd, **kwargs)  # nosec B603 - cmd es sys.executable + argumentos fijos, sin datos del usuario


_HTML_SPLASH = """
<!DOCTYPE html>
<html>
<head>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    background: linear-gradient(135deg, #1E3A5F 0%, #2E75B6 100%);
    display: flex; align-items: center; justify-content: center;
    height: 100vh; font-family: 'Segoe UI', Arial, sans-serif; color: white;
  }
  .container { text-align: center; }
  .icon-wrap { margin-bottom: 16px; }
  .brand { font-size: 2.4rem; font-weight: 900; letter-spacing: -1px; line-height: 1; }
  .brand span { color: #22C55E; }
  .sub { font-size: 0.8rem; opacity: 0.55; letter-spacing: 0.2em; text-transform: uppercase; margin-top: 6px; margin-bottom: 28px; }
  .bar-wrap {
    width: 220px; height: 4px; background: rgba(255,255,255,0.15);
    border-radius: 3px; margin: 0 auto;
  }
  .bar {
    width: 0; height: 100%; background: #22C55E;
    border-radius: 3px; transition: width 0.4s ease;
  }
  .msg { font-size: 0.72rem; opacity: 0.45; margin-top: 10px; }
</style>
</head>
<body>
<div class="container">
  <div class="icon-wrap">
    <svg width="72" height="72" viewBox="0 0 72 72" xmlns="http://www.w3.org/2000/svg">
      <rect x="4" y="4" width="44" height="56" rx="6" fill="white" opacity=".2"/>
      <rect x="12" y="16" width="22" height="4" rx="2" fill="white" opacity=".6"/>
      <rect x="12" y="25" width="18" height="4" rx="2" fill="white" opacity=".4"/>
      <rect x="12" y="34" width="14" height="4" rx="2" fill="white" opacity=".25"/>
      <circle cx="46" cy="56" r="14" fill="white" opacity=".15"/>
      <circle cx="46" cy="56" r="11" fill="#22C55E"/>
      <polyline points="40,56 44,61 53,49" stroke="white" stroke-width="2.5" fill="none" stroke-linecap="round" stroke-linejoin="round"/>
    </svg>
  </div>
  <div class="brand">Licit<span>App</span></div>
  <p class="sub">Licitaciones · Colombia</p>
  <div class="bar-wrap"><div class="bar" id="bar"></div></div>
  <p class="msg" id="msg">Iniciando...</p>
</div>
<script>
  let w = 0;
  const bar = document.getElementById('bar');
  const msg = document.getElementById('msg');
  const msgs = ['Cargando módulos...','Conectando con SECOP...','Preparando dashboard...','Listo en un momento...'];
  let mi = 0;
  setInterval(() => {
    w = Math.min(w + 1.2, 88);
    bar.style.width = w + '%';
    if (w > 20 * (mi + 1) && mi < msgs.length - 1) {
      mi++;
      msg.textContent = msgs[mi];
    }
  }, 80);
</script>
</body>
</html>
"""


def main_sin_ventana():
    """Arranca Streamlit sin ventana nativa (verificación y soporte)."""
    proc = _iniciar_streamlit()
    if not _esperar_streamlit(timeout_seg=90):
        print("LICITAPP_ERROR: Streamlit no respondió", flush=True)
        proc.terminate()
        sys.exit(1)
    print(f"LICITAPP_LISTA {STREAMLIT_URL}", flush=True)
    try:
        while proc.poll() is None:
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        try:
            proc.terminate()
        except Exception:
            pass


def main():
    splash = webview.create_window(
        "LicitApp",
        html=_HTML_SPLASH,
        width=480,
        height=300,
        resizable=False,
        frameless=True,
        on_top=True,
        background_color="#1F4E79",
    )

    proc = [None]

    def _arrancar():
        proc[0] = _iniciar_streamlit()
        ok = _esperar_streamlit(timeout_seg=60)
        time.sleep(0.6)

        if ok:
            # Crear la ventana principal ANTES de destruir el splash.
            # Si se destruye el splash primero, el loop de WinForms/WebView2
            # no tiene ventanas activas y termina — la nueva ventana llega
            # tarde a un loop ya muerto.
            try:
                webview.create_window(
                    "LicitApp — Licitaciones Colombia",
                    STREAMLIT_URL,
                    width=1280,
                    height=900,
                    min_size=(900, 620),
                    resizable=True,
                    background_color="#ffffff",
                )
            except Exception:
                pass
            # Ahora si destruir el splash (la ventana principal ya esta en cola)
            time.sleep(0.3)
            try:
                splash.destroy()
            except Exception:
                pass
        else:
            # Streamlit no levanto — crear ventana de error PRIMERO, luego destruir splash
            webview.create_window(
                "Error — LicitApp",
                html="<html><body style='font-family:Arial;padding:40px;color:#c00'>"
                     "<h2>No se pudo iniciar LicitApp</h2>"
                     "<p>Streamlit no respondio en 60 segundos.</p>"
                     "<p>Revisa el archivo data/streamlit_worker.log para mas detalles.</p>"
                     "<p>Intenta cerrar y volver a abrir la aplicacion.</p>"
                     "</body></html>",
                width=520,
                height=280,
            )
            time.sleep(0.3)
            try:
                splash.destroy()
            except Exception:
                pass

    threading.Thread(target=_arrancar, daemon=True).start()

    # debug=True activa el logger de pywebview y propaga excepciones visibles
    # en el archivo de log de arranque. Cambiar a False solo en release final
    # una vez confirmado que la ventana carga correctamente.
    _debug_webview = getattr(sys, "frozen", False) is False  # True en dev, False en exe
    webview.start(debug=_debug_webview)

    if proc[0]:
        try:
            proc[0].terminate()
        except Exception:
            pass


if __name__ == "__main__":
    try:
        _write_log("Iniciando main()")
        main_sin_ventana() if SIN_VENTANA else main()
        _write_log("main() terminó normalmente")
    except Exception:
        _write_log(f"ERROR FATAL en main():\n{traceback.format_exc()}")
        raise
