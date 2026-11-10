"""
Scheduler automático — ejecuta el ingestor y evalúa oportunidades diariamente.
Corre en segundo plano mientras la aplicación está abierta.
"""
import os, sys, json, logging, smtplib, ssl, re
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from seguridad import esc_html, leer_secreto, sin_control

logger = logging.getLogger("scheduler")

def _data_dir():
    if os.environ.get("LICITAPP_DATA_DIR"):
        return os.environ["LICITAPP_DATA_DIR"]
    if getattr(sys, "frozen", False):
        return os.path.join(os.path.dirname(sys.executable), "data")
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")

DATA_DIR    = _data_dir()
PERFIL_PATH = os.path.join(DATA_DIR, "perfil_proponente.json")
SMTP_SECRETO_PATH = os.path.join(DATA_DIR, ".smtp_secret")
_CORREO = re.compile(r"^[^@\s<>,;]+@[^@\s<>,;]+\.[^@\s<>,;]+$")


# ── Email ─────────────────────────────────────────────────────────────────────

def _cargar_config_email() -> dict:
    """Lee credenciales SMTP desde perfil_proponente.json o variables de entorno."""
    cfg = {}
    try:
        with open(PERFIL_PATH, encoding="utf-8") as f:
            perfil = json.load(f)
        cfg["destinatario"] = perfil.get("email", "")
        cfg["empresa"]      = perfil.get("empresa", "")
        cfg["alerta_nuevos"]  = perfil.get("alerta_nuevos", True)
        cfg["alerta_cierre"]  = perfil.get("alerta_cierre", True)
        cfg["smtp_user"]    = perfil.get("smtp_user", os.getenv("SMTP_USER", ""))
        # Orden: almacén cifrado, variable de entorno y, solo como respaldo de perfiles
        # antiguos aún sin migrar, el valor que hubiera en el JSON.
        cfg["smtp_pass"]    = leer_secreto(SMTP_SECRETO_PATH) or os.getenv("SMTP_PASS", "") or perfil.get("smtp_pass", "")
        cfg["smtp_host"]    = perfil.get("smtp_host", os.getenv("SMTP_HOST", "smtp.gmail.com"))
        cfg["smtp_port"]    = int(perfil.get("smtp_port", os.getenv("SMTP_PORT", "587")))
    except Exception:
        pass
    return cfg


def enviar_email_alerta(procesos_top: list, cfg: dict) -> bool:
    """
    Envía un correo HTML con los procesos top vía Gmail SMTP (TLS).
    Requiere que cfg tenga smtp_user, smtp_pass y destinatario.
    Retorna True si el envío fue exitoso.
    """
    smtp_user = cfg.get("smtp_user", "")
    smtp_pass = cfg.get("smtp_pass", "")
    destinatario = cfg.get("destinatario", "")

    if not _CORREO.match(sin_control(smtp_user)) or not _CORREO.match(sin_control(destinatario)):
        destinatario = ""  # direcciones con saltos de línea u otros caracteres: no se envía
    if not smtp_user or not smtp_pass or not destinatario:
        logger.warning(
            "Email no configurado. Ingresa smtp_user, smtp_pass y email en 'Mi Cuenta > Configuración'."
        )
        return False

    # ── Construir cuerpo HTML ──────────────────────────────────────────────────
    filas = ""
    for p in procesos_top[:10]:
        # Texto que viene de SECOP: se escapa antes de armar el HTML del correo.
        nombre = esc_html((p.get("objeto") or p.get("titulo") or "")[:70])
        entidad = esc_html(str(p.get("entidad", "") or "")[:40])
        po = f"$ {float(p.get('presupuesto_oficial', 0) or 0):,.0f}".replace(",", ".")
        dias = p.get("dias_al_cierre", "–")
        score = int(p.get("score", 0))
        color_score = "#28a745" if score >= 80 else "#fd7e14"
        try:
            cierre = datetime.fromisoformat(str(p.get("fecha_cierre", ""))).strftime("%d/%m/%Y")
        except Exception:
            cierre = esc_html(str(p.get("fecha_cierre", ""))[:10])

        filas += f"""
        <tr>
          <td style="text-align:center;font-weight:700;color:{color_score}">{score}</td>
          <td>{entidad}</td>
          <td>{nombre}</td>
          <td style="text-align:right">{po}</td>
          <td style="text-align:center">{cierre}</td>
          <td style="text-align:center;{'color:red;font-weight:700' if isinstance(dias, int) and dias <= 5 else ''}">{esc_html(dias)}</td>
        </tr>"""

    empresa = cfg.get("empresa", "")
    fecha_str = datetime.now().strftime("%d/%m/%Y %H:%M")

    html_body = f"""
<html><body style="font-family:Arial,sans-serif;background:#f4f7fb;padding:20px">
<div style="max-width:700px;margin:auto;background:#fff;border-radius:8px;padding:24px;
            box-shadow:0 2px 8px rgba(0,0,0,.1)">
  <h2 style="color:#1F4E79;margin-bottom:4px">🏗️ SECOP Automatizador — Alertas de Oportunidades</h2>
  <p style="color:#666;margin-top:4px;font-size:0.9em">{fecha_str} | {esc_html(empresa)}</p>
  <p>Se encontraron <strong>{len(procesos_top)} procesos con score ≥ 80</strong>
     listos para ofertar:</p>
  <table width="100%" cellpadding="6" cellspacing="0"
         style="border-collapse:collapse;font-size:0.88em">
    <thead>
      <tr style="background:#1F4E79;color:#fff">
        <th>Score</th><th>Entidad</th><th>Objeto</th>
        <th>P.O.</th><th>Cierre</th><th>Días</th>
      </tr>
    </thead>
    <tbody>{filas}</tbody>
  </table>
  <br>
  <p style="font-size:0.82em;color:#888">
    Abre el dashboard para calcular tu oferta óptima y presentarla.<br>
    Para dejar de recibir alertas, desmarca la opción en <em>Mi Cuenta → Configuración</em>.
  </p>
</div>
</body></html>"""

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"🏗️ SECOP: {len(procesos_top)} oportunidades nuevas ({fecha_str})"
        msg["From"]    = smtp_user
        msg["To"]      = destinatario
        msg.attach(MIMEText(html_body, "html", "utf-8"))

        with smtplib.SMTP(cfg.get("smtp_host", "smtp.gmail.com"),
                          cfg.get("smtp_port", 587), timeout=30) as server:
            server.ehlo()
            server.starttls(context=ssl.create_default_context())  # verifica el certificado del servidor
            server.login(smtp_user, smtp_pass)
            server.sendmail(smtp_user, destinatario, msg.as_string())

        logger.info(f"Alerta enviada a {destinatario} ({len(procesos_top)} procesos)")
        return True
    except Exception as e:
        logger.error(f"Error enviando email: {e}")
        return False


# ── Jobs ──────────────────────────────────────────────────────────────────────

def job_sincronizar():
    """Descarga procesos frescos de SECOP."""
    logger.info("Iniciando sincronización SECOP...")
    try:
        from m1_ingestor.ingestor import run_full_sync
        from config import DB_PATH
        resultado = run_full_sync(DB_PATH, {})
        logger.info(f"Sincronización completa: {resultado}")
        return resultado
    except Exception as e:
        logger.error(f"Error sincronizando: {e}")
        return {}


def job_alertas():
    """Evalúa procesos nuevos y envía alertas por email si hay oportunidades top."""
    logger.info("Evaluando oportunidades para alertas...")
    cfg = _cargar_config_email()

    if not cfg.get("alerta_nuevos", True):
        logger.info("Alertas desactivadas por el usuario.")
        return

    try:
        from m3_filtrado.process_filter import get_oportunidades_top
        from config import DB_PATH
        df = get_oportunidades_top(DB_PATH, top_n=50)
        if df.empty:
            logger.info("Sin procesos en la base de datos aún.")
            return
        top = df[df["score"] >= 80]
        if top.empty:
            logger.info("Sin procesos con score >= 80.")
            return
        logger.info(f"Encontrados {len(top)} procesos con score >= 80")
        procesos = top.to_dict("records")
        enviar_email_alerta(procesos, cfg)
    except Exception as e:
        logger.error(f"Error en alertas: {e}")


def job_alertas_cierre():
    """Alerta cuando un proceso interesante cierra en <= 3 días."""
    cfg = _cargar_config_email()

    if not cfg.get("alerta_cierre", True):
        return

    try:
        from m3_filtrado.process_filter import get_oportunidades_top
        from config import DB_PATH
        df = get_oportunidades_top(DB_PATH, top_n=100)
        if df.empty:
            return
        # filtrar score >= 70 y días al cierre <= 3
        from datetime import datetime as _dt
        def _dias(row):
            try:
                return (_dt.fromisoformat(str(row.get("fecha_cierre", ""))) - _dt.now()).days
            except Exception:
                return 999
        df["dias_al_cierre"] = df.apply(_dias, axis=1)
        urgentes = df[(df["score"] >= 70) & (df["dias_al_cierre"] <= 3) & (df["dias_al_cierre"] >= 0)]
        if urgentes.empty:
            return
        logger.info(f"{len(urgentes)} procesos cierran en <= 3 días")
        procesos = urgentes.to_dict("records")
        cfg_mod = dict(cfg)
        enviar_email_alerta(procesos, cfg_mod)
    except Exception as e:
        logger.error(f"Error en alertas de cierre: {e}")


def enviar_alerta_manual(score_min: int = 80) -> dict:
    """
    Dispara una alerta de email inmediatamente (llamado desde el dashboard).
    Retorna dict con: enviado, n_procesos, mensaje.
    """
    cfg = _cargar_config_email()
    try:
        from m3_filtrado.process_filter import get_oportunidades_top
        from config import DB_PATH
        df = get_oportunidades_top(DB_PATH, top_n=50)
        if df.empty:
            return {"enviado": False, "n_procesos": 0, "mensaje": "Sin datos en la base de datos."}
        top = df[df["score"] >= score_min]
        if top.empty:
            return {"enviado": False, "n_procesos": 0, "mensaje": f"Sin procesos con score >= {score_min}."}
        ok = enviar_email_alerta(top.to_dict("records"), cfg)
        return {
            "enviado": ok,
            "n_procesos": len(top),
            "mensaje": f"Email enviado a {cfg.get('destinatario','')} con {len(top)} procesos."
                       if ok else "Error al enviar. Verifica smtp_user y smtp_pass en Mi Cuenta.",
        }
    except Exception as e:
        return {"enviado": False, "n_procesos": 0, "mensaje": str(e)}


# ── Iniciar scheduler ─────────────────────────────────────────────────────────

def iniciar_scheduler():
    """Inicia el scheduler en hilo separado."""
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        sched = BackgroundScheduler(timezone="America/Bogota")
        # Sincronizar cada mañana a las 6am
        sched.add_job(job_sincronizar,    "cron", hour=6,       minute=0,  id="sync_secop")
        # Revisar alertas cada 2 horas en horario laboral
        sched.add_job(job_alertas,        "cron", hour="8,10,12,14,16,18", minute=30, id="alertas")
        # Alertas de cierre inminente cada mañana a las 7am
        sched.add_job(job_alertas_cierre, "cron", hour=7,       minute=0,  id="alertas_cierre")
        sched.start()
        logger.info("Scheduler iniciado — sync 6am · alertas cada 2h · cierre 7am")
        return sched
    except ImportError:
        logger.warning("APScheduler no instalado. Instala con: pip install apscheduler")
        return None
    except Exception as e:
        logger.error(f"Error iniciando scheduler: {e}")
        return None
