"""
Bot SECOP II — Presentación automática de ofertas.
Usa Playwright para navegar la plataforma de Colombia Compra Eficiente.

Modos:
  dry_run  → completa formularios pero NO envía (captura PDF como comprobante)
  real     → envío efectivo con comprobante

Uso:
  from m4_bot.secop_bot import SecopBot
  bot = SecopBot(usuario="...", contrasena="...", modo="dry_run")
  resultado = bot.presentar_oferta(id_proceso="...", propuesta_economica=85_000_000, documentos={...})
"""

import os, sys, json, time, logging
from datetime import datetime
from pathlib import Path
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import BOT_MODE, SECOP2_URL

logger = logging.getLogger("secop_bot")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [BOT] %(levelname)s %(message)s")

SECOP2_LOGIN   = "https://community.secop.gov.co/Public/Tendering/ContractNoticeManagement/Index?currentLanguage=es-CO&Page=login&Country=CO&SkinName=CCE"
SECOP2_BUSCAR  = "https://community.secop.gov.co/Public/Tendering/ContractNoticeManagement/Index?currentLanguage=es-CO&Page=Menu&SkinName=CCE"
SECOP2_PROCESO = "https://community.secop.gov.co/Public/Tendering/ContractNoticeManagement/Index?currentLanguage=es-CO&Page=ContractNoticeDetails&SkinName=CCE&contractNoticeId={id_proceso}"

ESTADOS_VALIDOS = {"CONVOCADO", "INVITACION_ABIERTA", "INVITACION ABIERTA", "PROCESO_ABIERTO"}


class SecopBotError(Exception):
    """Error esperado del bot (proceso cerrado, ya ofertado, sin credenciales, etc.)"""
    pass


class SecopBot:
    """Bot para presentación automática de ofertas en SECOP II."""

    def __init__(
        self,
        usuario: str,
        contrasena: str,
        modo: str = None,
        headless: bool = False,
        carpeta_capturas: str = None,
    ):
        self.usuario   = usuario
        self.contrasena = contrasena
        self.modo      = modo or BOT_MODE  # dry_run | real
        self.headless  = headless
        self.capturas  = carpeta_capturas or os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "data", "capturas"
        )
        os.makedirs(self.capturas, exist_ok=True)
        self._browser  = None
        self._page     = None
        self._log      = []

    # ── Ciclo de vida ──────────────────────────────────────────────────────────

    def _iniciar_browser(self):
        from playwright.sync_api import sync_playwright
        self._pw      = sync_playwright().__enter__()
        self._browser = self._pw.chromium.launch(
            headless=self.headless,
            args=["--start-maximized"],
        )
        ctx = self._browser.new_context(
            viewport={"width": 1280, "height": 900},
            locale="es-CO",
        )
        self._page = ctx.new_page()
        self._page.set_default_timeout(30_000)
        self._registrar("Browser iniciado")

    def _cerrar_browser(self):
        try:
            if self._browser:
                self._browser.close()
            if self._pw:
                self._pw.__exit__(None, None, None)
        except Exception:
            pass

    def _registrar(self, msg: str, nivel: str = "INFO"):
        ts = datetime.now().strftime("%H:%M:%S")
        entrada = f"[{ts}] {msg}"
        self._log.append(entrada)
        getattr(logger, nivel.lower())(msg)

    def _captura(self, nombre: str) -> str:
        ts  = datetime.now().strftime("%Y%m%d_%H%M%S")
        ruta = os.path.join(self.capturas, f"{ts}_{nombre}.png")
        try:
            self._page.screenshot(path=ruta, full_page=True)
            self._registrar(f"Captura: {os.path.basename(ruta)}")
        except Exception as e:
            self._registrar(f"Error captura: {e}", "WARNING")
        return ruta

    def _esperar_y_click(self, selector: str, descripcion: str = ""):
        self._registrar(f"Click: {descripcion or selector}")
        self._page.wait_for_selector(selector, state="visible", timeout=20_000)
        self._page.click(selector)

    def _esperar_y_llenar(self, selector: str, valor: str, descripcion: str = ""):
        self._registrar(f"Llenar '{descripcion or selector}': {valor[:30]}")
        self._page.wait_for_selector(selector, state="visible")
        self._page.fill(selector, str(valor))

    # ── Login ──────────────────────────────────────────────────────────────────

    def login(self) -> bool:
        """Inicia sesión en SECOP II. Retorna True si fue exitoso."""
        self._registrar(f"Navegando a login SECOP II")
        self._page.goto(SECOP2_LOGIN, wait_until="networkidle")
        self._captura("01_login_pagina")

        # Llenar usuario
        try:
            self._esperar_y_llenar("input[name='username'], #username, input[type='text']",
                                   self.usuario, "usuario")
            self._esperar_y_llenar("input[name='password'], #password, input[type='password']",
                                   self.contrasena, "contraseña")
            self._captura("02_login_credenciales")
            self._esperar_y_click("button[type='submit'], input[type='submit'], .login-btn, #btnLogin",
                                  "botón login")
            self._page.wait_for_load_state("networkidle")
            self._captura("03_login_resultado")

            # Verificar login exitoso (buscamos elemento del menú principal)
            try:
                self._page.wait_for_selector(".menu-principal, #menu-proveedor, .user-info, [class*='provider'], [class*='proveedor']",
                                             timeout=10_000)
                self._registrar("Login exitoso")
                return True
            except Exception:
                # Verificar si hay mensaje de error
                page_text = self._page.inner_text("body")
                if "contraseña" in page_text.lower() or "password" in page_text.lower() or "incorrecto" in page_text.lower():
                    raise SecopBotError("Credenciales incorrectas. Verifica usuario y contraseña en SECOP II.")
                self._registrar("Login posiblemente exitoso (no se detectó menú principal)", "WARNING")
                return True
        except SecopBotError:
            raise
        except Exception as e:
            raise SecopBotError(f"Error durante login: {e}")

    # ── Navegar al proceso ─────────────────────────────────────────────────────

    def navegar_proceso(self, id_proceso: str) -> dict:
        """
        Navega al detalle de un proceso y extrae información básica.
        Retorna dict con: titulo, entidad, estado, presupuesto, fecha_cierre
        """
        url = SECOP2_PROCESO.format(id_proceso=id_proceso)
        self._registrar(f"Navegando al proceso {id_proceso}")
        self._page.goto(url, wait_until="networkidle")
        time.sleep(2)
        self._captura("04_proceso_detalle")

        info = {"id": id_proceso, "url": url}
        try:
            texto = self._page.inner_text("body")
            # Extraer estado del proceso
            for estado in ESTADOS_VALIDOS:
                if estado.upper() in texto.upper():
                    info["estado"] = estado
                    break
            else:
                info["estado"] = "DESCONOCIDO"

            # Verificar si el proceso está abierto para ofertas
            if any(cerrado in texto.upper() for cerrado in ["CERRADO", "ADJUDICADO", "DESIERTO", "LIQUIDADO"]):
                raise SecopBotError(
                    f"El proceso {id_proceso} no está abierto para ofertas.\n"
                    "Verifica el estado en SECOP II antes de intentar ofertar."
                )
        except SecopBotError:
            raise
        except Exception as e:
            self._registrar(f"Error extrayendo info del proceso: {e}", "WARNING")

        return info

    # ── Suscribirse al proceso ─────────────────────────────────────────────────

    def suscribirse(self) -> bool:
        """Hace clic en 'Suscribirme' y confirma la suscripción."""
        self._registrar("Intentando suscribirse al proceso")
        page_text = self._page.inner_text("body")

        # Si ya está suscrito, continuar
        if "ya estás suscrito" in page_text.lower() or "ya suscrito" in page_text.lower():
            self._registrar("Ya suscrito al proceso")
            return True

        # Buscar botón de suscripción
        selectores_suscribir = [
            "button:has-text('Suscribirme')",
            "a:has-text('Suscribirme')",
            "input[value*='Suscribir']",
            "[class*='subscribe']",
            "button:has-text('Participar')",
            "a:has-text('Participar')",
        ]
        for sel in selectores_suscribir:
            try:
                if self._page.locator(sel).count() > 0:
                    self._esperar_y_click(sel, "Suscribirme")
                    self._page.wait_for_load_state("networkidle")
                    time.sleep(1)
                    # Confirmar suscripción si aparece modal
                    try:
                        self._page.click("button:has-text('Confirmar'), button:has-text('Aceptar'), button:has-text('OK')",
                                         timeout=3_000)
                    except Exception:
                        pass
                    self._captura("05_suscripcion")
                    self._registrar("Suscripción realizada")
                    return True
            except Exception:
                continue

        self._registrar("Botón de suscripción no encontrado — posiblemente ya suscrito", "WARNING")
        return True

    # ── Navegar a Presentar Oferta ─────────────────────────────────────────────

    def ir_a_presentar_oferta(self) -> bool:
        """Navega a la sección de presentación de oferta del proceso."""
        self._registrar("Navegando a presentar oferta")
        selectores = [
            "a:has-text('Presentar Oferta')",
            "button:has-text('Presentar Oferta')",
            "a:has-text('Mis Ofertas')",
            "a:has-text('Oferta')",
            "[class*='submit-offer']",
            "[href*='offer']",
        ]
        for sel in selectores:
            try:
                if self._page.locator(sel).count() > 0:
                    self._page.click(sel)
                    self._page.wait_for_load_state("networkidle")
                    time.sleep(1)
                    self._captura("06_formulario_oferta")
                    return True
            except Exception:
                continue

        # Intentar navegación directa por URL
        url_actual = self._page.url
        if "ContractNoticeId" in url_actual or "contractNoticeId" in url_actual:
            url_oferta = url_actual.replace("ContractNoticeDetails", "TenderingDetails")
            self._page.goto(url_oferta, wait_until="networkidle")
            self._captura("06_formulario_oferta_directo")
            return True

        raise SecopBotError("No se pudo encontrar el botón 'Presentar Oferta'. Puede que el proceso no esté en etapa de recepción.")

    # ── Cargar documentos habilitantes ────────────────────────────────────────

    def cargar_documentos(self, documentos: dict) -> list:
        """
        Carga los documentos habilitantes del Sobre 1.
        documentos = {
            "rut": "ruta/al/rut.pdf",
            "camara_comercio": "ruta/camara.pdf",
            "rup": "ruta/rup.pdf",
            "estados_financieros": "ruta/estados.pdf",
            "experiencia": ["ruta/cert1.pdf", "ruta/cert2.pdf"],
        }
        Retorna lista de documentos cargados exitosamente.
        """
        cargados = []
        self._registrar(f"Cargando {len(documentos)} tipos de documentos")

        # Buscar inputs de archivo genéricos
        file_inputs = self._page.locator("input[type='file']")
        n_inputs = file_inputs.count()
        self._registrar(f"Encontrados {n_inputs} campos de archivo en el formulario")

        for nombre, ruta in documentos.items():
            rutas = [ruta] if isinstance(ruta, str) else ruta
            for r in rutas:
                if not r or not os.path.exists(r):
                    self._registrar(f"Documento no encontrado: {r}", "WARNING")
                    continue
                # Buscar input de archivo específico por label o nombre
                selectores_doc = [
                    f"input[type='file'][name*='{nombre}']",
                    f"input[type='file'][id*='{nombre}']",
                    f"label:has-text('{nombre}') + input[type='file']",
                    "input[type='file']:visible",
                ]
                for sel in selectores_doc:
                    try:
                        if self._page.locator(sel).count() > 0:
                            self._page.locator(sel).first.set_input_files(r)
                            time.sleep(0.5)
                            cargados.append(nombre)
                            self._registrar(f"Documento cargado: {nombre} ({os.path.basename(r)})")
                            break
                    except Exception as e:
                        self._registrar(f"Error cargando {nombre}: {e}", "WARNING")

        self._captura("07_documentos_cargados")
        return cargados

    # ── Ingresar propuesta económica ──────────────────────────────────────────

    def ingresar_propuesta_economica(self, valor: float) -> bool:
        """Ingresa el valor de la propuesta económica en el formulario."""
        valor_str = f"{int(valor):,}".replace(",", ".")  # formato COP: 85.000.000
        self._registrar(f"Ingresando propuesta económica: ${valor_str}")

        selectores_precio = [
            "input[name*='precio'], input[id*='precio']",
            "input[name*='valor'], input[id*='valor']",
            "input[name*='oferta'], input[id*='oferta']",
            "input[name*='economica'], input[id*='economica']",
            "input[name*='price'], input[id*='price']",
            "input[name*='amount'], input[id*='amount']",
            "input[placeholder*='valor'], input[placeholder*='precio']",
            "input[type='number']:visible",
        ]
        for sel in selectores_precio:
            try:
                loc = self._page.locator(sel)
                if loc.count() > 0:
                    loc.first.clear()
                    loc.first.fill(str(int(valor)))
                    time.sleep(0.3)
                    self._registrar(f"Propuesta ingresada en campo: {sel}")
                    self._captura("08_propuesta_ingresada")
                    return True
            except Exception:
                continue

        self._registrar("No se encontró campo de propuesta económica específico", "WARNING")
        self._captura("08_propuesta_no_encontrada")
        return False

    # ── Enviar oferta ──────────────────────────────────────────────────────────

    def _dry_run_captura(self) -> str:
        """En modo dry_run: captura pantalla de confirmación sin enviar."""
        self._registrar("=== MODO DRY-RUN: NO se enviará la oferta ===")
        self._captura("09_DRY_RUN_confirmacion")
        pdf_path = os.path.join(self.capturas, f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_DRY_RUN_oferta.pdf")
        try:
            self._page.pdf(path=pdf_path, format="A4", print_background=True)
            self._registrar(f"PDF dry-run guardado: {pdf_path}")
        except Exception:
            pass
        return pdf_path

    def enviar_oferta(self) -> dict:
        """
        Envía la oferta (o simula el envío en dry_run).
        Retorna dict con: enviado, comprobante_path, mensaje
        """
        if self.modo == "dry_run":
            pdf = self._dry_run_captura()
            return {
                "enviado": False,
                "dry_run": True,
                "comprobante": pdf,
                "mensaje": "DRY-RUN: Oferta preparada pero NO enviada. Revisa el PDF de comprobante.",
            }

        # Modo REAL — buscar botón de envío
        self._registrar("MODO REAL: Enviando oferta...")
        selectores_enviar = [
            "button:has-text('Enviar Oferta')",
            "button:has-text('Presentar Oferta')",
            "input[value*='Enviar']",
            "button:has-text('Confirmar')",
            "button[type='submit']:has-text('Oferta')",
        ]
        enviado = False
        for sel in selectores_enviar:
            try:
                if self._page.locator(sel).count() > 0:
                    self._page.click(sel)
                    self._page.wait_for_load_state("networkidle")
                    time.sleep(2)
                    # Confirmar modal si aparece
                    try:
                        self._page.click("button:has-text('Confirmar'), button:has-text('Sí'), button:has-text('Aceptar')",
                                         timeout=5_000)
                        self._page.wait_for_load_state("networkidle")
                    except Exception:
                        pass
                    enviado = True
                    break
            except Exception:
                continue

        self._captura("10_envio_resultado")

        # Extraer número de oferta
        id_oferta = None
        try:
            texto = self._page.inner_text("body")
            import re
            match = re.search(r'(oferta|identificador)[^\d]*(\d{6,})', texto, re.IGNORECASE)
            if match:
                id_oferta = match.group(2)
        except Exception:
            pass

        # Generar PDF comprobante
        pdf_path = os.path.join(self.capturas, f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_OFERTA_ENVIADA.pdf")
        try:
            self._page.pdf(path=pdf_path, format="A4")
        except Exception:
            pdf_path = None

        return {
            "enviado": enviado,
            "dry_run": False,
            "id_oferta": id_oferta,
            "comprobante": pdf_path,
            "mensaje": "Oferta enviada exitosamente." if enviado else "No se pudo confirmar el envío.",
        }

    # ── Flujo completo ─────────────────────────────────────────────────────────

    def presentar_oferta(
        self,
        id_proceso: str,
        propuesta_economica: float,
        documentos: dict = None,
    ) -> dict:
        """
        Flujo completo de presentación de oferta.

        Args:
            id_proceso: ID del proceso en SECOP II
            propuesta_economica: valor en COP (ej: 85_000_000)
            documentos: dict con rutas a archivos PDF de habilitantes

        Returns:
            dict con resultado completo del proceso
        """
        resultado = {
            "id_proceso": id_proceso,
            "propuesta_economica": propuesta_economica,
            "modo": self.modo,
            "inicio": datetime.now().isoformat(),
            "pasos": [],
            "exito": False,
            "error": None,
        }

        try:
            self._iniciar_browser()

            # Paso 1: Login
            self.login()
            resultado["pasos"].append("login_ok")

            # Paso 2: Navegar al proceso
            info_proceso = self.navegar_proceso(id_proceso)
            resultado["proceso"] = info_proceso
            resultado["pasos"].append("proceso_navegado")

            # Paso 3: Suscribirse
            self.suscribirse()
            resultado["pasos"].append("suscrito")

            # Paso 4: Ir a presentar oferta
            self.ir_a_presentar_oferta()
            resultado["pasos"].append("formulario_abierto")

            # Paso 5: Cargar documentos (si se proporcionan)
            if documentos:
                cargados = self.cargar_documentos(documentos)
                resultado["documentos_cargados"] = cargados
                resultado["pasos"].append(f"documentos_cargados_{len(cargados)}")

            # Paso 6: Ingresar propuesta económica
            propuesta_ok = self.ingresar_propuesta_economica(propuesta_economica)
            resultado["pasos"].append("propuesta_ingresada")
            if not propuesta_ok and self.modo == "real":
                raise SecopBotError(
                    "No se encontró el campo de propuesta económica. "
                    "No se puede enviar la oferta sin el valor económico."
                )

            # Paso 7: Enviar (o dry-run)
            envio = self.enviar_oferta()
            resultado.update(envio)
            resultado["pasos"].append("envio_completado")
            resultado["exito"] = envio.get("enviado", False) or envio.get("dry_run", False)

        except SecopBotError as e:
            resultado["error"] = str(e)
            resultado["exito"] = False
            self._registrar(f"Error controlado: {e}", "ERROR")
            try:
                self._captura("ERROR_estado")
            except Exception:
                pass
        except Exception as e:
            resultado["error"] = f"Error inesperado: {e}"
            resultado["exito"] = False
            self._registrar(f"Error inesperado: {e}", "ERROR")
            try:
                self._captura("ERROR_inesperado")
            except Exception:
                pass
        finally:
            resultado["log"] = self._log
            fin_ts = datetime.now()
            resultado["fin"] = fin_ts.isoformat()
            self._cerrar_browser()
            # Guardar log en archivo usando el mismo timestamp de fin
            log_path = os.path.join(self.capturas, f"{fin_ts.strftime('%Y%m%d_%H%M%S')}_log.json")
            try:
                with open(log_path, "w", encoding="utf-8") as f:
                    json.dump(resultado, f, ensure_ascii=False, indent=2)
            except Exception:
                pass

        return resultado


# ── Interfaz de línea de comandos ──────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Bot SECOP II")
    parser.add_argument("--usuario",    required=True,  help="Usuario SECOP II")
    parser.add_argument("--contrasena", required=True,  help="Contraseña SECOP II")
    parser.add_argument("--proceso",    required=True,  help="ID del proceso en SECOP II")
    parser.add_argument("--valor",      required=True,  type=float, help="Propuesta económica en COP")
    parser.add_argument("--modo",       default="dry_run", choices=["dry_run", "real"])
    parser.add_argument("--visible",    action="store_true", help="Mostrar ventana del navegador")
    args = parser.parse_args()

    bot = SecopBot(
        usuario=args.usuario,
        contrasena=args.contrasena,
        modo=args.modo,
        headless=not args.visible,
    )
    resultado = bot.presentar_oferta(
        id_proceso=args.proceso,
        propuesta_economica=args.valor,
    )
    print(json.dumps(resultado, ensure_ascii=False, indent=2))
