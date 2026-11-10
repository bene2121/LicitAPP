"""Pestaña "Ofertar paso a paso": guía a cualquier proponente de principio a fin."""
from __future__ import annotations

import io
import os
import re
import zipfile

import pandas as pd
import streamlit as st

from m6_propuesta import asistente as A
from m6_propuesta.expediente import generar_paquete, leer_expediente
from seguridad import esc_md

PASOS = ["1. Tus datos", "2. El proceso", "3. ¿Cumples?", "4. Tu precio", "5. Documentos", "6. Propuesta lista"]
FORMULAS = {"M": "Mediana", "MG": "Media geométrica", "MAB": "Media aritmética baja",
            "MAA": "Media aritmética alta", "MV": "Menor valor"}

GUIA_DOCUMENTOS = {
    "carta": ("Presenta formalmente tu oferta y declara que puedes contratar.",
              "Usa primero el formato oficial del pliego. Si no existe, revisa y firma la carta creada por LicitApp."),
    "consorcio": ("Define integrantes, porcentajes, representante y duración del proponente plural.",
                  "Todos los integrantes deben revisarlo y firmarlo."),
    "existencia": ("Demuestra quién representa legalmente a cada empresa.",
                   "Descárgalo de la Cámara de Comercio; normalmente debe tener máximo 30 días."),
    "rut": ("Acredita la identificación y responsabilidades tributarias.",
            "Descarga una copia actualizada desde la DIAN para cada integrante."),
    "rup": ("Acredita experiencia, capacidad jurídica, financiera y organizacional.",
            "Verifica que esté vigente y en firme en la fecha indicada por el pliego."),
    "seguridad_social": ("Declara que los aportes a seguridad social están al día.",
                         "Debe firmarla el revisor fiscal cuando exista; de lo contrario, el representante legal."),
    "experiencia": ("Prueba contratos similares a los exigidos por la entidad.",
                    "Adjunta el formato del pliego y los certificados o actas que demuestren valor, alcance y terminación."),
    "financiero": ("Permite verificar los indicadores financieros exigidos.",
                   "Compara los indicadores del RUP con los mínimos del pliego antes de continuar."),
    "economica": ("Contiene precios, cantidades, impuestos y valor total ofertado.",
                  "Usa exclusivamente el archivo de la entidad; no cambies fórmulas, columnas ni unidades."),
    "garantia": ("Protege a la entidad si el oferente retira o incumple su oferta.",
                 "Solicítala a una aseguradora con beneficiario, vigencia, valor y número de proceso exactos."),
    "otros": ("Reúne anexos particulares del proceso.",
              "Revisa uno por uno los formatos, pactos, compromisos y autorizaciones del pliego."),
}


def _cop(v) -> str:
    return f"$ {float(v or 0):,.0f}".replace(",", ".")


def _ir(paso: int) -> None:
    st.session_state["asis_paso"] = paso
    st.rerun()


def render(perfil: dict, guardar_perfil, cliente, optimizar_todas=None, diferencias_formulas=None) -> None:
    paso = int(st.session_state.get("asis_paso", 0))
    st.subheader("Ofertar paso a paso")
    st.info("No necesitas conocer SECOP para empezar. LicitApp te guía y organiza la propuesta; "
            "tú confirmas los requisitos del pliego, firmas y haces la presentación final en la plataforma indicada.")
    with st.expander("Antes de empezar: qué vas a necesitar"):
        st.markdown("""
- El número o enlace del proceso publicado por la entidad.
- Los datos legales de la empresa o de los integrantes del consorcio/unión temporal.
- El **pliego de condiciones y sus adendas**: son la regla principal del proceso.
- Certificados legales, RUT, RUP, experiencia, información financiera y garantía, cuando los exijan.
- Tiempo para revisar y cargar todo **antes** de la hora de cierre. LicitApp no radica la oferta por ti.
""")
    st.progress((paso + 1) / len(PASOS), text=f"Paso {PASOS[paso]}")
    if paso == 0:
        _paso_datos(perfil, guardar_perfil)
    elif paso == 1:
        _paso_proceso(cliente)
    elif paso == 2:
        _paso_evaluacion(perfil, guardar_perfil, cliente)
    elif paso == 3:
        _paso_precio(cliente, optimizar_todas, diferencias_formulas)
    elif paso == 4:
        _paso_documentos(perfil)
    else:
        _paso_final(perfil)


# ── 1. Datos del proponente ─────────────────────────────────────────────────
def _paso_datos(perfil: dict, guardar_perfil) -> None:
    st.markdown("### ¿Quién va a presentar la oferta?")
    st.markdown("Completa estos datos una sola vez. Los usaremos para preparar cartas y organizar documentos. "
                "Los campos marcados con **asterisco** son necesarios para continuar.")
    tipo = st.radio("¿Cómo te presentas?", ["Empresa o persona sola", "Consorcio", "Unión temporal"],
                    index={"Consorcio": 1, "Unión temporal": 2}.get(perfil.get("tipo_plural"), 0)
                    if perfil.get("proponente_plural") else 0, horizontal=True, key="asis_tipo")
    plural = tipo != "Empresa o persona sola"
    c1, c2 = st.columns(2)
    empresa = c1.text_input("Razón social (tu empresa) *", perfil.get("empresa", ""), key="asis_empresa")
    nit = c2.text_input("NIT *", perfil.get("nit", ""), key="asis_nit", help="Escríbelo sin puntos; el dígito de verificación puede ir separado por guion.")
    representante = c1.text_input("Representante legal *", perfil.get("representante", ""), key="asis_rep")
    cedula = c2.text_input("Cédula del representante", perfil.get("cedula_representante", ""), key="asis_cc")
    email = c1.text_input("Correo para notificaciones", perfil.get("email", ""), key="asis_email")
    telefono = c2.text_input("Teléfono", perfil.get("telefono", ""), key="asis_tel")
    direccion = c1.text_input("Dirección", perfil.get("direccion", ""), key="asis_dir")
    ciudad = c2.text_input("Ciudad", perfil.get("ciudad", ""), key="asis_ciudad")
    nombre_plural, integrantes = "", []
    if plural:
        nombre_plural = st.text_input(f"Nombre del {tipo.lower()}", perfil.get("proponente_nombre", ""),
                                      placeholder="CONSORCIO VÍAS DEL HUILA 2026", key="asis_nombre_plural")
        base = perfil.get("integrantes") or [{"nombre": empresa, "nit": nit, "participacion": 50.0},
                                             {"nombre": "", "nit": "", "participacion": 50.0}]
        tabla = st.data_editor(pd.DataFrame(base, columns=["nombre", "nit", "participacion"]),
                               num_rows="dynamic", use_container_width=True, key="asis_integrantes",
                               column_config={"nombre": "Integrante", "nit": "NIT",
                                              "participacion": st.column_config.NumberColumn("Participación %", min_value=0, max_value=100)})
        integrantes = [r for r in tabla.to_dict("records") if str(r.get("nombre") or "").strip()]
    errores = []
    if not empresa.strip() or not nit.strip():
        errores.append("Escribe la razón social y el NIT.")
    if not representante.strip():
        errores.append("Escribe el representante legal.")
    if nit.strip() and not re.fullmatch(r"[0-9. -]{6,15}", nit.strip()):
        errores.append("Revisa el NIT: usa únicamente números y, si aplica, el guion del dígito de verificación.")
    if email.strip() and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email.strip()):
        errores.append("Revisa el correo para notificaciones.")
    if plural:
        suma = sum(float(r.get("participacion") or 0) for r in integrantes)
        if not nombre_plural.strip():
            errores.append(f"Escribe el nombre del {tipo.lower()}.")
        if len(integrantes) < 2:
            errores.append("Un proponente plural necesita al menos dos integrantes.")
        if abs(suma - 100) > 0.01:
            errores.append(f"Las participaciones suman {suma:g} %; deben sumar 100 %.")
    if st.button("Guardar y seguir ➜", type="primary", key="asis_guardar_datos"):
        if errores:
            for e in errores:
                st.error(e)
            return
        perfil.update({
            "empresa": empresa.strip(), "nit": nit.strip(), "representante": representante.strip(),
            "cedula_representante": cedula.strip(), "email": email.strip(), "telefono": telefono.strip(),
            "direccion": direccion.strip(), "ciudad": ciudad.strip(), "proponente_plural": plural,
            "tipo_plural": tipo if plural else "", "integrantes": integrantes if plural else [],
            "proponente_nombre": nombre_plural.strip() if plural else empresa.strip(),
        })
        guardar_perfil(perfil)
        st.session_state.perfil = perfil
        _ir(1)


# ── 2. Proceso ──────────────────────────────────────────────────────────────
def _paso_proceso(cliente) -> None:
    previo = st.session_state.get("proceso_seleccionado")
    if previo:
        st.success(f"Proceso elegido: **{esc_md(previo.get('referencia') or previo.get('id'))}** — "
                   f"{esc_md(previo.get('entidad'))}")
    st.markdown("### Elige el proceso correcto")
    st.markdown("Busca el proceso en SECOP II por su **ID** (CO1.REQ…, CO1.BDOS…), su **referencia** "
                "(la que usa la entidad) o **palabras del objeto**.")
    st.warning("Antes de preparar la oferta, descarga y lee el pliego, los anexos y todas las adendas en SECOP II. "
               "Una adenda puede cambiar la fecha, los requisitos o el presupuesto.")
    texto = st.text_input("Proceso", key="asis_buscar", placeholder="SVCMIN0010-25 o CO1.REQ.9426412")
    if st.button("Buscar en SECOP II", key="asis_btn_buscar"):
        try:
            with st.spinner("Consultando SECOP II…"):
                st.session_state["asis_resultados"] = A.buscar_procesos(texto, cliente)
        except ValueError as exc:
            st.error(str(exc))
    resultados = st.session_state.get("asis_resultados")
    if resultados is not None and not resultados:
        st.warning("SECOP II no devolvió procesos con esa búsqueda. Revisa el ID o la referencia.")
    for i, p in enumerate(resultados or []):
        with st.container(border=True):
            st.markdown(f"**{esc_md(p.get('referencia') or p['id'])}** · {esc_md(p.get('entidad'))}  \n"
                        f"{esc_md((p.get('objeto') or '')[:220])}  \n"
                        f"Presupuesto: **{_cop(p.get('presupuesto_oficial'))}** · Modalidad: {esc_md(p.get('modalidad'))} · "
                        f"Estado: {esc_md(p.get('estado'))} · Cierre: {esc_md(p.get('fecha_cierre') or 'sin dato')}")
            if st.button("Ofertar en este proceso", key=f"asis_elegir_{i}"):
                st.session_state.proceso_seleccionado = p
                st.session_state.pop("asis_ofertas_reales", None)
                st.session_state.pop("evaluacion_actual", None)
                _ir(2)
    c1, c2 = st.columns(2)
    if c1.button("⬅ Volver", key="asis_v1"):
        _ir(0)
    if previo and c2.button("Seguir con el proceso elegido ➜", type="primary", key="asis_s1"):
        _ir(2)


# ── 3. Precio ───────────────────────────────────────────────────────────────
def _paso_precio(cliente, optimizar_todas, diferencias_formulas) -> None:
    proceso = st.session_state.get("proceso_seleccionado") or {}
    po = float(proceso.get("presupuesto_oficial") or 0)
    st.markdown("### Define un precio sostenible")
    st.markdown(f"**{esc_md(proceso.get('referencia') or proceso.get('id'))}** · Presupuesto oficial: **{_cop(po)}**")
    st.warning("La fórmula ayuda a comparar escenarios, pero no reemplaza tu presupuesto de obra. Incluye costos directos, "
               "AIU, impuestos, riesgos y utilidad; no presentes un valor que no puedas ejecutar.")
    if po <= 0:
        po = st.number_input("El proceso no trae presupuesto. Escríbelo del pliego (COP)", min_value=0.0, step=1000.0)
    if "asis_ofertas_reales" not in st.session_state:
        try:
            st.session_state["asis_ofertas_reales"] = A.ofertas_del_proceso(proceso, cliente)
        except Exception:
            st.session_state["asis_ofertas_reales"] = []
    reales = st.session_state["asis_ofertas_reales"]
    if reales:
        st.info(f"SECOP II ya publica {len(reales)} ofertas de este proceso. Se usan para calcular las fórmulas.")
    else:
        st.caption("Todavía no hay ofertas públicas de este proceso. Escribe las que conozcas o pon tu precio.")
    rivales_txt = st.text_area("Precios de otros oferentes que conozcas (uno por línea, opcional)", key="asis_rivales")
    rivales = [o["valor"] for o in reales]
    for linea in rivales_txt.splitlines():
        limpio = linea.replace("$", "").replace(".", "").replace(",", "").strip()
        if limpio.isdigit():
            rivales.append(float(limpio))
    rivales = [v for v in rivales if po and po * 0.5 <= v <= po]

    modo = st.radio("¿Cómo quieres fijar el precio?",
                    ["Calcular con las fórmulas del pliego", "Escribir mi precio"], horizontal=True, key="asis_modo")
    precio, formula = 0.0, ""
    if modo.startswith("Calcular"):
        if not optimizar_todas:
            st.error("El motor de fórmulas no está disponible. Reinstala LicitApp.")
        elif not rivales:
            st.warning("Para calcular hacen falta precios de otros oferentes. Escribe al menos uno o elige 'Escribir mi precio'.")
        elif po > 0:
            res = optimizar_todas(presupuesto_oficial=po, pts_max=100.0, ofertas_historicas=rivales)
            filas = diferencias_formulas(res)
            st.dataframe([{"Fórmula": f"{f['formula']} — {FORMULAS[f['formula']]}", "Precio sugerido": _cop(f["precio"]),
                           "Bajo el presupuesto": f"{f['pct_mejora'] * 100:.2f} %"} for f in filas],
                         use_container_width=True, hide_index=True)
            formula = st.selectbox("¿Qué fórmula dice el pliego?", list(FORMULAS),
                                   format_func=lambda c: f"{c} — {FORMULAS[c]}", key="asis_formula")
            st.caption("Si el pliego la elige al azar, se usa el último dígito de la TRM del día del cierre: "
                       "0-1 MV · 2-3 M · 4-5 MG · 6-7 MAB · 8-9 MAA.")
            precio = float(res[formula]["oferta_optima"])
    else:
        precio = st.number_input("Tu precio total (COP, con IVA)", min_value=0.0, max_value=po or None,
                                 value=float(po or 0), step=1000.0, key="asis_precio_manual")
    if precio > 0:
        st.metric("Tu oferta", _cop(precio), f"{(po - precio) / po * 100:.2f} % bajo el presupuesto" if po else None)
        if po and precio < po * 0.8:
            st.warning("Tu oferta está más de 20 % por debajo del presupuesto. Verifica cantidades y costos: "
                       "la entidad podría pedir explicación por precio artificialmente bajo.")
    c1, c2 = st.columns(2)
    if c1.button("⬅ Volver", key="asis_v2"):
        _ir(2)
    if c2.button("Usar este precio y seguir ➜", type="primary", key="asis_s2", disabled=precio <= 0):
        st.session_state.oferta_guardada = {"precio": precio, "formula": formula,
                                            "nombre_formula": FORMULAS.get(formula, "precio propio"),
                                            "presupuesto_oficial": po,
                                            "pct_mejora": (po - precio) / po * 100 if po else 0}
        _ir(4)


# ── 4. Documentos ───────────────────────────────────────────────────────────
def _paso_documentos(perfil: dict) -> None:
    proceso = st.session_state.get("proceso_seleccionado") or {}
    oferta = st.session_state.get("oferta_guardada") or {}
    carpeta = A.crear_expediente(perfil, proceso, oferta)
    reutilizados = A.sincronizar_documentos_reutilizables(carpeta, perfil)
    st.markdown("### Completa la lista de documentos")
    st.markdown(f"Tus documentos se guardan en `{carpeta}`. Ya dejé ahí la **carta de presentación** "
                + ("y el **documento del consorcio** " if perfil.get("proponente_plural") else "")
                + "en Word con tus datos: revísalos, fírmalos y súbelos en PDF.")
    if reutilizados["copiados"]:
        st.success(f"Se reutilizaron {len(reutilizados['copiados'])} documentos vigentes de tu biblioteca.")
    if reutilizados["vencidos"]:
        st.warning("Debes renovar o solicitar: " + ", ".join(reutilizados["vencidos"]))
    confirmaciones = A.cargar_checklist(carpeta)
    st.markdown("#### Tablero de alistamiento de esta oferta")
    st.caption("Marca cada control únicamente después de compararlo con el pliego y la última adenda. "
               "El avance se guarda automáticamente en esta oferta.")
    with st.container(border=True):
        st.markdown("**Controles generales del proceso**")
        controles_globales = [
            ("pliego", "Descargué y revisé el pliego, anexos y formatos oficiales"),
            ("adendas", "Revisé todas las adendas publicadas"),
            ("requisitos", "Verifiqué requisitos habilitantes y factores de evaluación"),
            ("cierre", "Confirmé fecha y hora exactas de cierre"),
            ("canal", "Confirmé el canal de presentación y el acceso a la plataforma"),
        ]
        for clave, texto in controles_globales:
            confirmaciones[f"global_{clave}"] = st.checkbox(
                texto, value=bool(confirmaciones.get(f"global_{clave}")), key=f"asis_check_global_{clave}")
    for clave, nombre, ayuda in A.SECCIONES:
        if clave == "consorcio" and not perfil.get("proponente_plural"):
            continue
        actuales = sorted(p.name for p in (carpeta / nombre).glob("*") if p.is_file())
        with st.expander(f"{'✅' if actuales else '⬜'} {nombre}", expanded=False):
            que_es, como = GUIA_DOCUMENTOS.get(clave, (ayuda, "Confirma el requisito en el pliego."))
            st.markdown(f"**Qué es:** {que_es}")
            st.markdown(f"**Qué hacer:** {como}")
            st.caption("Regla del proceso: " + ayuda)
            if actuales:
                st.write(" · ".join(actuales))
            subidos = st.file_uploader("Subir archivos", accept_multiple_files=True, key=f"asis_up_{clave}")
            for archivo in subidos or []:
                marca = f"asis_ok_{clave}_{archivo.name}_{archivo.size}"
                if st.session_state.get(marca):
                    continue
                try:
                    A.guardar_subida(carpeta, nombre, archivo.name, archivo.getvalue())
                    st.session_state[marca] = True
                    st.success(f"Guardado: {archivo.name}")
                except ValueError as exc:
                    st.error(str(exc))
            confirmaciones[f"seccion_{clave}"] = st.checkbox(
                "Ya comparé este requisito con el pliego y verifiqué vigencia, contenido y firmas",
                value=bool(confirmaciones.get(f"seccion_{clave}")), key=f"asis_check_seccion_{clave}")
    A.guardar_checklist(carpeta, confirmaciones)
    pendientes = A.faltantes(carpeta, bool(perfil.get("proponente_plural")))
    tablero = A.estado_checklist(carpeta, bool(perfil.get("proponente_plural")), confirmaciones)
    proceso_id = str(proceso.get("id") or proceso.get("referencia") or "proceso")
    eval_resultado = (perfil.get("evaluaciones_requisitos", {}).get(proceso_id, {}).get("resultado") or {})
    eval_completos, eval_total = int(eval_resultado.get("completos", 0)), int(eval_resultado.get("total", 0))
    total_integral = tablero["total"] + eval_total
    completos_integral = tablero["completos"] + eval_completos
    porcentaje_integral = round(completos_integral / total_integral * 100) if total_integral else 0
    listo_integral = tablero["listo"] and bool(eval_resultado.get("cumple"))
    st.progress(porcentaje_integral / 100,
                text=f"Oferta al {porcentaje_integral} % · {completos_integral} de {total_integral} controles completos")
    filas_tablero = []
    for item in tablero["controles"]:
        filas_tablero.append({"Estado": "✅" if item["completo"] else "⬜", "Requisito": item["nombre"],
                              "Evidencia": "Confirmado" if item["completo"] else "Pendiente"})
    for item in tablero["secciones"]:
        estado = "✅" if item["completo"] else ("🟡" if item["evidencia"] or item["revisado"] else "⬜")
        evidencia = "Archivo + revisión" if item["completo"] else (
            "Falta revisión" if item["evidencia"] else "Falta archivo" if item["revisado"] else "Pendiente")
        filas_tablero.append({"Estado": estado, "Requisito": item["nombre"], "Evidencia": evidencia})
    st.dataframe(filas_tablero, hide_index=True, width="stretch")
    pendientes_checklist = [i["nombre"] for i in tablero["controles"] if not i["completo"]]
    pendientes_checklist += [i["nombre"] for i in tablero["secciones"] if not i["completo"]]
    pendientes_checklist += [f"Evaluación previa — {i['nombre']}" for i in eval_resultado.get("criterios", [])
                              if not i.get("cumple")]
    if pendientes:
        st.warning("Aún faltan:\n\n" + "\n".join(f"- {p}" for p in pendientes))
    if listo_integral:
        st.success("Checklist al 100 %. La oferta puede pasar a la revisión final antes de cargarla.")
    c1, c2 = st.columns(2)
    if c1.button("⬅ Volver", key="asis_v3"):
        _ir(3)
    texto_boton = "Preparar borrador para revisar ➜" if not listo_integral else "Armar propuesta lista ➜"
    if c2.button(texto_boton, type="primary", key="asis_s3"):
        exp = leer_expediente(carpeta)
        st.session_state["asis_paquete"] = generar_paquete(
            exp, proceso, oferta,
            consorcio={"nombre": perfil.get("proponente_nombre"), "integrantes": perfil.get("integrantes")},
            perfil=perfil)
        st.session_state["asis_pendientes"] = pendientes_checklist
        st.session_state["asis_porcentaje"] = porcentaje_integral
        _ir(5)


# ── 3. Evaluación previa ────────────────────────────────────────────────────
def _paso_evaluacion(perfil: dict, guardar_perfil, cliente) -> None:
    from m6_propuesta.evaluacion import evaluar_experiencia, evaluar_financiero, evaluar_total, ficha_decision
    from m7_competencia.entidad import analizar_entidad, extraer_requisitos_documentos, hallazgos_a_requisitos

    proceso = st.session_state.get("proceso_seleccionado") or {}
    proceso_id = str(proceso.get("id") or proceso.get("referencia") or "proceso")
    po = float(proceso.get("presupuesto_oficial") or 0)
    guardadas = perfil.setdefault("evaluaciones_requisitos", {})
    previa = guardadas.get(proceso_id, {})
    st.markdown("### Evalúa si puedes participar antes de invertir más tiempo")
    st.info("Copia los valores exactamente del pliego y su matriz de experiencia. LicitApp hace los cálculos y "
            "muestra faltantes; los criterios técnicos ambiguos deben ser confirmados por el responsable de la oferta.")

    st.markdown("#### Ficha del proyecto")
    f1, f2, f3, f4 = st.columns(4)
    f1.metric("Entidad", str(proceso.get("entidad") or "Sin dato")[:30])
    f2.metric("Presupuesto", _cop(po))
    f3.metric("Modalidad", str(proceso.get("modalidad") or "Sin dato")[:30])
    f4.metric("Cierre", str(proceso.get("fecha_cierre") or "Sin dato")[:20])
    st.markdown(f"**Objeto:** {esc_md(proceso.get('objeto') or proceso.get('titulo') or 'Sin descripción publicada')}")
    st.caption(f"Referencia: {proceso.get('referencia') or proceso.get('id')} · "
               f"UNSPSC: {proceso.get('unspsc') or 'sin dato'} · Estado: {proceso.get('estado') or 'sin dato'}")
    if proceso.get("url_proceso"):
        st.link_button("Abrir proceso y documentos oficiales en SECOP II", proceso["url_proceso"])

    with st.expander("Leer requisitos del pliego", expanded=False):
        st.markdown("Carga el **pliego PDF**. LicitAPP localizará fragmentos sobre experiencia, habilitantes, "
                    "indicadores, personal y causales de rechazo. No reemplaza las tablas ni las adendas.")
        # AppTest no implementa el estado binario de file_uploader; el cliente falso
        # solo se inyecta en pruebas y no existe en la aplicación instalada.
        pliegos = [] if "_cliente_secop_pruebas" in st.session_state else st.file_uploader(
            "Pliego, anexos y adendas en PDF", type=["pdf"], accept_multiple_files=True,
            key=f"eval_pliego_{proceso_id}")
        if pliegos and st.button("Analizar documentos", key=f"eval_analizar_pliego_{proceso_id}"):
            with st.spinner("Leyendo el expediente…"):
                try:
                    st.session_state[f"pliego_resultado_{proceso_id}"] = extraer_requisitos_documentos(
                        [(archivo.name, archivo.getvalue()) for archivo in pliegos])
                except ValueError as exc:
                    st.error(str(exc))
        lectura = st.session_state.get(f"pliego_resultado_{proceso_id}")
        if lectura:
            estados = {"texto_completo": "Texto legible", "texto_parcial": "Lectura parcial",
                       "ocr_completo": "Leído con OCR local", "ocr_parcial": "OCR local parcial",
                       "ocr_fallido": "Falló OCR: revisión manual", "escaneado_sin_texto": "Sin texto reconocible"}
            st.caption(f"Documento: {lectura.get('documento', 'Pliego')} · Páginas: {lectura['paginas']} · "
                       f"legibles: {lectura['legibles']} · cobertura: {lectura.get('cobertura', 0)} % · "
                       f"estado: {estados.get(lectura.get('estado_lectura'), 'Sin verificar')}")
            st.warning(lectura["aviso"])
            if lectura.get("documentos"):
                st.dataframe([{
                    "Documento": x.get("documento"), "Páginas": x.get("paginas"),
                    "Páginas legibles": x.get("legibles"), "Cobertura": f"{x.get('cobertura', 0)} %",
                    "Páginas con OCR": x.get("paginas_ocr", 0),
                    "Estado": estados.get(x.get("estado_lectura"), "Sin verificar"),
                } for x in lectura["documentos"]], hide_index=True, width="stretch")
            if lectura.get("impactos_adendas"):
                st.error("Posibles impactos encontrados en documentos llamados 'adenda'. Debes compararlos con la versión anterior.")
                for impacto in lectura["impactos_adendas"]:
                    st.caption(f"{impacto['documento']}, p. {impacto['pagina']} · {impacto['categoria']}: "
                               f"…{impacto['texto']}…")
            if not lectura["secciones"]:
                st.info("No se localizaron secciones automáticamente. Revisa el PDF completo y sus anexos.")
            confirmados = dict(previa.get("hallazgos_confirmados") or {})
            for titulo, fragmentos in lectura["secciones"].items():
                st.markdown(f"**{titulo}**")
                for fragmento in fragmentos:
                    st.caption(f"{fragmento.get('documento', lectura.get('documento'))}, página {fragmento['pagina']}: "
                               f"…{fragmento['texto']}…")
                    confirmados[fragmento["id"]] = st.checkbox(
                        "Confirmé que este fragmento contiene una exigencia aplicable",
                        value=bool(confirmados.get(fragmento["id"])), key=f"hallazgo_{proceso_id}_{fragmento['id']}")
            if lectura.get("hallazgos") and st.button("Enviar confirmados a la matriz", key=f"importar_hallazgos_{proceso_id}"):
                nuevos = hallazgos_a_requisitos(lectura, confirmados)
                existentes = list(previa.get("matriz_requisitos") or [])
                fuentes = {(x.get("fuente"), x.get("requisito")) for x in existentes}
                existentes.extend(x for x in nuevos if (x.get("fuente"), x.get("requisito")) not in fuentes)
                previa["matriz_requisitos"] = existentes
                previa["hallazgos_confirmados"] = confirmados
                guardadas[proceso_id] = previa
                perfil["evaluaciones_requisitos"] = guardadas
                guardar_perfil(perfil)
                st.success(f"Se agregaron {len(nuevos)} hallazgos confirmados a la matriz.")
                st.rerun()

    with st.expander("Historial de esta entidad — últimos 3 años", expanded=False):
        st.markdown("Muestra quiénes han presentado ofertas y quiénes han recibido contratos publicados por la entidad. "
                    "Sirve para conocer recurrencia y competencia; no garantiza quién participará en este proceso.")
        if st.button("Consultar historial de la entidad", key=f"eval_entidad_{proceso_id}"):
            try:
                with st.spinner("Consultando ofertas y contratos de SECOP II…"):
                    st.session_state[f"entidad_resultado_{proceso_id}"] = analizar_entidad(proceso, cliente)
            except Exception as exc:
                st.error(f"No fue posible consultar el historial: {exc}")
        historia = st.session_state.get(f"entidad_resultado_{proceso_id}")
        if historia:
            h1, h2, h3, h4 = st.columns(4)
            h1.metric("Procesos con ofertas", historia["procesos_con_ofertas"])
            h2.metric("Ofertas publicadas", historia["ofertas"])
            h3.metric("Oferentes únicos", historia["oferentes_unicos"])
            h4.metric("Contratos publicados", historia["contratos"])
            st.caption(f"Periodo: {historia['desde']} a {historia['hasta']}. {historia['nota']}")
            if historia["oferentes"]:
                st.markdown("**Oferentes más frecuentes**")
                st.dataframe([{
                    "Oferente": x["nombre"], "NIT": x["nit"], "Ofertas": x["ofertas"],
                    "Procesos": x["procesos"], "Contratos publicados": x["adjudicaciones"],
                    "Tasa orientativa": f"{x['tasa_exito']:.1f} %", "Oferta promedio": _cop(x["oferta_promedio"]),
                } for x in historia["oferentes"]], hide_index=True, width="stretch")
            else:
                st.info("SECOP no devolvió ofertas publicadas de esta entidad en el periodo.")
            if historia["adjudicatarios"]:
                st.markdown("**Adjudicatarios más frecuentes**")
                st.dataframe([{
                    "Adjudicatario": x["nombre"], "NIT": x["nit"], "Contratos": x["contratos"],
                    "Valor contratado": _cop(x["valor"]), "Como grupo": x["grupos"],
                } for x in historia["adjudicatarios"]], hide_index=True, width="stretch")

    with st.expander("1. Experiencia exigida", expanded=True):
        c1, c2, c3 = st.columns(3)
        pct_total = c1.number_input("Experiencia acumulada mínima (% del presupuesto)", min_value=0.0,
                                    value=float(previa.get("requisito", {}).get("pct_total", 100.0)), step=5.0,
                                    key="eval_pct_total")
        pct_especifica = c2.number_input("Experiencia específica mínima (%)", min_value=0.0,
                                         value=float(previa.get("requisito", {}).get("pct_especifica", 0.0)), step=5.0,
                                         key="eval_pct_especifica")
        max_contratos = c3.number_input("Máximo de contratos permitidos", min_value=1, max_value=20,
                                        value=int(previa.get("requisito", {}).get("max_contratos", 5)),
                                        key="eval_max_contratos")
        st.caption("Marca 'Actividad exigida' únicamente si el contrato acredita la actividad general/específica "
                   "definida por la matriz. El valor computable se ajustará por el porcentaje de participación.")
        base = previa.get("contratos") or []
        contratos_df = st.data_editor(
            pd.DataFrame(base, columns=["contrato", "objeto", "valor", "participacion", "terminado", "soporte", "actividad"]),
            num_rows="dynamic", width="stretch", key="eval_contratos",
            column_config={
                "contrato": "Contrato / RUP", "objeto": "Objeto o actividad",
                "valor": st.column_config.NumberColumn("Valor ejecutado", min_value=0),
                "participacion": st.column_config.NumberColumn("Participación %", min_value=0, max_value=100, default=100),
                "terminado": st.column_config.CheckboxColumn("Terminó antes del cierre"),
                "soporte": st.column_config.CheckboxColumn("Tiene soporte"),
                "actividad": st.column_config.CheckboxColumn("Actividad exigida"),
            })

    with st.expander("2. Capacidad financiera y organizacional"):
        st.caption("Registra el indicador del RUP y el límite del pliego. Desmarca los que el proceso no exija.")
        fin_previa = previa.get("financiero", {})
        financieros = {}
        campos = [
            ("liquidez", "Liquidez", "Mínimo", 1.0), ("endeudamiento", "Endeudamiento", "Máximo", 0.70),
            ("cobertura", "Cobertura de intereses", "Mínimo", 0.0),
            ("roe", "Rentabilidad del patrimonio", "Mínimo", 0.0),
            ("roa", "Rentabilidad del activo", "Mínimo", 0.0),
        ]
        for clave, nombre, tipo_limite, limite_defecto in campos:
            a, b, c = st.columns([1.4, 1, 1])
            financieros[f"aplica_{clave}"] = a.checkbox(f"Exigen {nombre}", value=bool(fin_previa.get(f"aplica_{clave}", True)), key=f"eval_aplica_{clave}")
            financieros[clave] = b.number_input(f"{nombre} actual", value=float(fin_previa.get(clave, 0.0)), key=f"eval_actual_{clave}")
            sufijo = "max" if clave == "endeudamiento" else "min"
            financieros[f"{clave}_{sufijo}"] = c.number_input(f"{tipo_limite} exigido", value=float(fin_previa.get(f"{clave}_{sufijo}", limite_defecto)), key=f"eval_limite_{clave}")

    with st.expander("3. Jurídico y habilitantes"):
        jur_previa = previa.get("juridicos", {})
        juridicos = {}
        for clave, texto in [
            ("capacidad_juridica", "Representación legal y facultades para contratar verificadas"),
            ("rup_vigente", "RUP vigente y en firme, cuando el proceso lo exige"),
            ("sin_inhabilidades", "Inhabilidades, incompatibilidades y conflictos revisados"),
            ("seguridad_social", "Seguridad social y parafiscales acreditados"),
            ("garantia", "Garantía de seriedad revisada, cuando aplica"),
        ]:
            juridicos[clave] = st.checkbox(texto, value=bool(jur_previa.get(clave)), key=f"eval_jur_{clave}")

    with st.expander("4. Matriz trazable de requisitos", expanded=True):
        st.caption("Registra cada exigencia con su página exacta, evidencia, responsable y fecha. "
                   "'Cumple' sin evidencia seguirá apareciendo como pendiente.")
        matriz_base = previa.get("matriz_requisitos") or []
        matriz_df = st.data_editor(
            pd.DataFrame(matriz_base, columns=["requisito", "grupo", "estado", "critico", "fuente",
                                               "evidencia", "responsable", "fecha_limite"]),
            num_rows="dynamic", width="stretch", key="eval_matriz_requisitos",
            column_config={
                "requisito": "Requisito del pliego", "grupo": "Grupo",
                "estado": st.column_config.SelectboxColumn("Estado", options=["Pendiente", "Cumple", "No cumple", "No aplica"]),
                "critico": st.column_config.CheckboxColumn("Crítico / causal de rechazo"),
                "fuente": "Documento y página", "evidencia": "Archivo o soporte",
                "responsable": "Responsable", "fecha_limite": "Fecha límite",
            })

    with st.expander("5. Viabilidad económica y decisión"):
        eco_previa = previa.get("economia") or {}
        e1, e2, e3 = st.columns(3)
        ingreso_estimado = e1.number_input("Ingreso / oferta estimada", min_value=0.0,
                                           value=float(eco_previa.get("ingreso") or po or 0), step=100000.0,
                                           key="eval_eco_ingreso")
        costos_estimados = e2.number_input("Costo total estimado", min_value=0.0,
                                           value=float(eco_previa.get("costos") or 0), step=100000.0,
                                           key="eval_eco_costos",
                                           help="Incluye ejecución, impuestos, logística, garantías y financiación.")
        margen_minimo = e3.number_input("Margen mínimo aceptable (%)", min_value=0.0, max_value=100.0,
                                        value=float(eco_previa.get("margen_minimo") or 5), step=0.5,
                                        key="eval_eco_margen")
        blocker_previo = previa.get("blocker") or {}
        blocker_confirmado = st.checkbox("Confirmo que existe un impedimento crítico e insubsanable",
                                         value=bool(blocker_previo.get("confirmado")), key="eval_blocker")
        blocker_detalle = st.text_input("Impedimento confirmado (obligatorio para recomendar descartar)",
                                        value=str(blocker_previo.get("detalle") or ""), key="eval_blocker_detalle",
                                        disabled=not blocker_confirmado)

    if st.button("Evaluar requisitos", type="primary", key="eval_calcular"):
        contratos = [r for r in contratos_df.to_dict("records") if str(r.get("contrato") or r.get("objeto") or "").strip()]
        requisito = {"pct_total": pct_total, "pct_especifica": pct_especifica, "max_contratos": max_contratos}
        experiencia = evaluar_experiencia(requisito, contratos, po)
        financiero = evaluar_financiero(financieros)
        total = evaluar_total(experiencia, financiero, juridicos)
        matriz = [r for r in matriz_df.to_dict("records") if str(r.get("requisito") or "").strip()]
        economia = {"ingreso": ingreso_estimado, "costos": costos_estimados, "margen_minimo": margen_minimo}
        blocker = {"confirmado": blocker_confirmado, "detalle": blocker_detalle}
        decision = ficha_decision(total, matriz, economia, blocker)
        evaluacion = {"requisito": requisito, "contratos": contratos, "financiero": financieros,
                      "juridicos": juridicos, "matriz_requisitos": matriz, "economia": economia,
                      "blocker": blocker, "resultado": total, "decision": decision}
        guardadas[proceso_id] = evaluacion
        perfil["evaluaciones_requisitos"] = guardadas
        guardar_perfil(perfil)
        st.session_state["evaluacion_actual"] = evaluacion

    evaluacion = st.session_state.get("evaluacion_actual") or previa
    resultado = evaluacion.get("resultado") if isinstance(evaluacion, dict) else None
    decision = evaluacion.get("decision") if isinstance(evaluacion, dict) else None
    if resultado:
        st.progress(resultado["porcentaje"] / 100, text=f"Cumplimiento preliminar: {resultado['porcentaje']} %")
        filas = [{"Estado": "✅ Cumple" if c["cumple"] else "❌ Pendiente / no cumple",
                  "Grupo": c["grupo"], "Requisito": c["nombre"], "Resultado": c["detalle"]}
                 for c in resultado["criterios"]]
        st.dataframe(filas, hide_index=True, width="stretch")
        if resultado["cumple"]:
            st.success("La información registrada cumple todos los controles preliminares. Continúa con precio y documentos.")
        else:
            st.warning("Hay requisitos pendientes o incumplidos. Puedes guardar el diagnóstico y completar evidencia, "
                       "pero no debes interpretar este proceso como habilitado todavía.")
        if decision:
            colores = {"PARTICIPAR": st.success, "REVISAR": st.warning, "DESCARTAR": st.error}
            colores[decision["decision"]](f"Recomendación automática: **{decision['decision']}**")
            d1, d2, d3 = st.columns(3)
            d1.metric("Cumplimiento", f"{resultado['porcentaje']} %")
            d2.metric("Margen estimado", "Sin calcular" if decision["margen"] is None else f"{decision['margen']:.2f} %")
            d3.metric("Pendientes", len(decision["pendientes"]) + len(decision["bloqueos"]))
            if decision["bloqueos"]:
                st.error("Bloqueos: " + " · ".join(decision["bloqueos"]))
            if decision["pendientes"]:
                st.markdown("**Antes de decidir:**\n\n" + "\n".join(f"- {x}" for x in decision["pendientes"]))
    c1, c2 = st.columns(2)
    if c1.button("⬅ Volver", key="eval_volver"):
        _ir(1)
    if c2.button("Continuar con el diagnóstico ➜", key="eval_continuar", disabled=not bool(resultado)):
        st.session_state["evaluacion_porcentaje"] = resultado["porcentaje"]
        _ir(3)


# ── 5. Resultado ────────────────────────────────────────────────────────────
def _paso_final(perfil: dict) -> None:
    paquete = st.session_state.get("asis_paquete")
    if not paquete:
        _ir(4)
        return
    canal = paquete["canal"]
    pendientes = st.session_state.get("asis_pendientes") or []
    if pendientes:
        st.error("BORRADOR INCOMPLETO — todavía no debes presentar esta propuesta.")
        st.success("Propuesta armada como borrador para revisión.")
    else:
        st.success("LISTA DE CONTROL COMPLETA — propuesta preparada para tu revisión final y presentación.")
    st.caption(f"Carpeta de trabajo: `{paquete['carpeta']}`")
    c1, c2, c3 = st.columns(3)
    c1.metric("Oferta", _cop(paquete["precio"]))
    c2.metric("Archivos", len(paquete["archivos"]))
    c3.metric("Se presenta en", {"secop": "SECOP II", "ariba": "SAP Ariba", "findeter": "Correo Findeter"}[canal["tipo"]])
    st.progress(float(st.session_state.get("asis_porcentaje", 0)) / 100,
                text=f"Checklist de la oferta: {st.session_state.get('asis_porcentaje', 0)} %")
    st.info(f"**Cómo presentarla:** {canal['instruccion']}  \nDestino: {canal['destino']}")
    if pendientes:
        st.warning("Antes de presentar, completa:\n\n" + "\n".join(f"- {p}" for p in pendientes))
    st.markdown("#### Revisión final obligatoria")
    st.markdown("""
- Confirma que usaste los formatos oficiales y la última adenda.
- Abre cada archivo: verifica nombres, firmas, fechas, vigencias y que sea legible.
- Comprueba que el valor del formulario económico coincide con el valor registrado en la plataforma.
- Carga los archivos con anticipación y revisa el acuse o constancia de presentación.
""")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for rel in paquete["archivos"]:
            z.write(os.path.join(paquete["carpeta"], rel), rel)
    st.download_button("Descargar borrador (.zip)" if pendientes else "Descargar propuesta (.zip)", buf.getvalue(),
                       file_name=f"propuesta_{paquete['proceso_id']}.zip", mime="application/zip", key="asis_zip")
    if os.name == "nt" and st.button("Abrir la carpeta de la propuesta", key="asis_abrir"):
        os.startfile(paquete["carpeta"])  # nosec B606 - carpeta creada por la app
    st.caption("LicitApp arma la propuesta; la radicación la haces tú en el canal indicado.")
    c1, c2 = st.columns(2)
    if c1.button("⬅ Volver a documentos", key="asis_v4"):
        _ir(4)
    if c2.button("Ofertar en otro proceso", key="asis_nuevo"):
        for k in ("asis_resultados", "asis_ofertas_reales", "asis_paquete", "asis_pendientes"):
            st.session_state.pop(k, None)
        st.session_state.proceso_seleccionado = None
        st.session_state.oferta_guardada = None
        _ir(1)
