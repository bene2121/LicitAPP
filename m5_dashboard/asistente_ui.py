"""Pestaña "Ofertar paso a paso": guía a cualquier proponente de principio a fin."""
from __future__ import annotations

import io
import os
import zipfile

import pandas as pd
import streamlit as st

from m6_propuesta import asistente as A
from m6_propuesta.expediente import generar_paquete, leer_expediente
from seguridad import esc_md

PASOS = ["1. Tus datos", "2. El proceso", "3. Tu precio", "4. Documentos", "5. Propuesta lista"]
FORMULAS = {"M": "Mediana", "MG": "Media geométrica", "MAB": "Media aritmética baja",
            "MAA": "Media aritmética alta", "MV": "Menor valor"}


def _cop(v) -> str:
    return f"$ {float(v or 0):,.0f}".replace(",", ".")


def _ir(paso: int) -> None:
    st.session_state["asis_paso"] = paso
    st.rerun()


def render(perfil: dict, guardar_perfil, cliente, optimizar_todas=None, diferencias_formulas=None) -> None:
    paso = int(st.session_state.get("asis_paso", 0))
    st.subheader("Ofertar paso a paso")
    st.progress((paso + 1) / len(PASOS), text=f"Paso {PASOS[paso]}")
    if paso == 0:
        _paso_datos(perfil, guardar_perfil)
    elif paso == 1:
        _paso_proceso(cliente)
    elif paso == 2:
        _paso_precio(cliente, optimizar_todas, diferencias_formulas)
    elif paso == 3:
        _paso_documentos(perfil)
    else:
        _paso_final(perfil)


# ── 1. Datos del proponente ─────────────────────────────────────────────────
def _paso_datos(perfil: dict, guardar_perfil) -> None:
    st.markdown("Escribe los datos de quien presenta la oferta. Se guardan para la próxima vez.")
    tipo = st.radio("¿Cómo te presentas?", ["Empresa o persona sola", "Consorcio", "Unión temporal"],
                    index={"Consorcio": 1, "Unión temporal": 2}.get(perfil.get("tipo_plural"), 0)
                    if perfil.get("proponente_plural") else 0, horizontal=True, key="asis_tipo")
    plural = tipo != "Empresa o persona sola"
    c1, c2 = st.columns(2)
    empresa = c1.text_input("Razón social (tu empresa)", perfil.get("empresa", ""), key="asis_empresa")
    nit = c2.text_input("NIT", perfil.get("nit", ""), key="asis_nit")
    representante = c1.text_input("Representante legal", perfil.get("representante", ""), key="asis_rep")
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
    st.markdown("Busca el proceso en SECOP II por su **ID** (CO1.REQ…, CO1.BDOS…), su **referencia** "
                "(la que usa la entidad) o **palabras del objeto**.")
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
    st.markdown(f"**{esc_md(proceso.get('referencia') or proceso.get('id'))}** · Presupuesto oficial: **{_cop(po)}**")
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
    c1, c2 = st.columns(2)
    if c1.button("⬅ Volver", key="asis_v2"):
        _ir(1)
    if c2.button("Usar este precio y seguir ➜", type="primary", key="asis_s2", disabled=precio <= 0):
        st.session_state.oferta_guardada = {"precio": precio, "formula": formula,
                                            "nombre_formula": FORMULAS.get(formula, "precio propio"),
                                            "presupuesto_oficial": po,
                                            "pct_mejora": (po - precio) / po * 100 if po else 0}
        _ir(3)


# ── 4. Documentos ───────────────────────────────────────────────────────────
def _paso_documentos(perfil: dict) -> None:
    proceso = st.session_state.get("proceso_seleccionado") or {}
    oferta = st.session_state.get("oferta_guardada") or {}
    carpeta = A.crear_expediente(perfil, proceso, oferta)
    st.markdown(f"Tus documentos se guardan en `{carpeta}`. Ya dejé ahí la **carta de presentación** "
                + ("y el **documento del consorcio** " if perfil.get("proponente_plural") else "")
                + "en Word con tus datos: revísalos, fírmalos y súbelos en PDF.")
    for clave, nombre, ayuda in A.SECCIONES:
        if clave == "consorcio" and not perfil.get("proponente_plural"):
            continue
        actuales = sorted(p.name for p in (carpeta / nombre).glob("*") if p.is_file())
        with st.expander(f"{'✅' if actuales else '⬜'} {nombre}", expanded=False):
            st.caption(ayuda)
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
    pendientes = A.faltantes(carpeta, bool(perfil.get("proponente_plural")))
    if pendientes:
        st.warning("Aún faltan:\n\n" + "\n".join(f"- {p}" for p in pendientes))
    c1, c2 = st.columns(2)
    if c1.button("⬅ Volver", key="asis_v3"):
        _ir(2)
    if c2.button("Armar la propuesta ➜", type="primary", key="asis_s3"):
        exp = leer_expediente(carpeta)
        st.session_state["asis_paquete"] = generar_paquete(
            exp, proceso, oferta,
            consorcio={"nombre": perfil.get("proponente_nombre"), "integrantes": perfil.get("integrantes")},
            perfil=perfil)
        st.session_state["asis_pendientes"] = pendientes
        _ir(4)


# ── 5. Resultado ────────────────────────────────────────────────────────────
def _paso_final(perfil: dict) -> None:
    paquete = st.session_state.get("asis_paquete")
    if not paquete:
        _ir(3)
        return
    canal = paquete["canal"]
    st.success(f"Propuesta armada en `{paquete['carpeta']}`")
    c1, c2, c3 = st.columns(3)
    c1.metric("Oferta", _cop(paquete["precio"]))
    c2.metric("Archivos", len(paquete["archivos"]))
    c3.metric("Se presenta en", {"secop": "SECOP II", "ariba": "SAP Ariba", "findeter": "Correo Findeter"}[canal["tipo"]])
    st.info(f"**Cómo presentarla:** {canal['instruccion']}  \nDestino: {canal['destino']}")
    pendientes = st.session_state.get("asis_pendientes") or []
    if pendientes:
        st.warning("Antes de presentar, completa:\n\n" + "\n".join(f"- {p}" for p in pendientes))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for rel in paquete["archivos"]:
            z.write(os.path.join(paquete["carpeta"], rel), rel)
    st.download_button("Descargar la propuesta (.zip)", buf.getvalue(),
                       file_name=f"propuesta_{paquete['proceso_id']}.zip", mime="application/zip", key="asis_zip")
    if os.name == "nt" and st.button("Abrir la carpeta de la propuesta", key="asis_abrir"):
        os.startfile(paquete["carpeta"])  # nosec B606 - carpeta creada por la app
    st.caption("LicitApp arma la propuesta; la radicación la haces tú en el canal indicado.")
    c1, c2 = st.columns(2)
    if c1.button("⬅ Volver a documentos", key="asis_v4"):
        _ir(3)
    if c2.button("Ofertar en otro proceso", key="asis_nuevo"):
        for k in ("asis_resultados", "asis_ofertas_reales", "asis_paquete", "asis_pendientes"):
            st.session_state.pop(k, None)
        st.session_state.proceso_seleccionado = None
        st.session_state.oferta_guardada = None
        _ir(1)
