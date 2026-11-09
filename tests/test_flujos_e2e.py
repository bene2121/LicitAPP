"""Pruebas de punta a punta de los procesos de LicitApp.

Recorren la interfaz real (m5_dashboard/app.py) con `streamlit.testing.AppTest`
y clientes falsos para datos.gov.co (el contenedor de pruebas no tiene red).

Datos reales usados como fixture (verificados en SECOP II):
  * proceso SVCMIN0010-25 = CO1.REQ.9426412 (portafolio CO1.BDOS.9257883),
    Gobernación del Huila, NIT 800103913, precio base 1.288.612.325.
  * 43 ofertas: 34 exactamente al precio base y las demás las listadas en OFERTAS_REALES.
  * CONSORCIO VIAS DEL HUILA 2026 = codigo_grupo 736763764 con sus dos socios.
Lo que no se conoce de SECOP (modalidad, UNSPSC, identidad de los rivales y el contrato
en ejecución del contraste) es de prueba y está marcado como tal.
"""
from __future__ import annotations

import datetime as dt
import shutil
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

RAIZ = Path(__file__).resolve().parent.parent
APP = str(RAIZ / "m5_dashboard" / "app.py")
EXPEDIENTE_REAL = RAIZ / "expedientes" / "consorcio-vias-del-huila-2026"

ID_SECOP = "CO1.REQ.9426412"
PORTAFOLIO = "CO1.BDOS.9257883"
REFERENCIA = "SVCMIN0010-25"
PRECIO_BASE = 1288612325.0
NIT_ENTIDAD = "800103913"
CODIGO_GRUPO = "736763764"
OBJETO = (
    "INTERVENTORÍA TÉCNICA, ADMINISTRATIVA, FINANCIERA, JURÍDICA, CONTABLE Y AMBIENTAL AL "
    "MEJORAMIENTO MEDIANTE PAVIMENTO FLEXIBLE EN LA VIA CRUCE (ORITOGUAZ-SALADOBLANCO) - "
    "OPORAPA-SAN ROQUE, DEPARTAMENTO DEL HUILA"
)
# Ofertas reales distintas del proceso (además de las 34 al precio base).
OFERTAS_REALES = [
    1288612325.0, 1288599235.0, 1288350525.0, 1288611330.16, 1288612352.0,
    1288438162.55, 1288608772.0, 1257553682.0,
]
OFERTA_ATIPICA = 128612181.0
RIVALES = {f"90000000{i}": valor for i, valor in enumerate(OFERTAS_REALES + [OFERTA_ATIPICA], start=1)}


# ── Clientes falsos de datos.gov.co ──────────────────────────────────────────

def cliente_ofertas(url, params):
    """wi7w-2nvm (ofertas) y p6dx-8zbt (procesos): una oferta por NIT de prueba."""
    where = params.get("$where", "")
    if "wi7w-2nvm" in url:
        filas = []
        for nit, valor in RIVALES.items():
            if f"'{nit}'" in where:
                # SECOP repite la oferta por entidad: debe contarse una sola vez.
                for repeticion in range(2):
                    filas.append({
                        "identificador_de_la_oferta": f"OF-{nit}",
                        "id_del_proceso_de_compra": PORTAFOLIO,
                        "valor_de_la_oferta": str(valor),
                        "nombre_proveedor": f"RIVAL DE PRUEBA {nit}",
                        "nit_del_proveedor": nit,
                    })
        return filas
    if "p6dx-8zbt" in url:
        return [{"id_del_portafolio": PORTAFOLIO, "precio_base": str(PRECIO_BASE)}]
    return []


CONTRATO_PRUEBA = {  # contrato en ejecución de PRUEBA (no hay datos reales de este consorcio)
    "id_contrato": "CO1.PCCNTR.PRUEBA",
    "proveedor_adjudicado": "CONSORCIO VIAS DEL HUILA 2026",
    "documento_proveedor": CODIGO_GRUPO,
    "codigo_proveedor": CODIGO_GRUPO,
    "es_grupo": "Si",
    "estado_contrato": "En ejecución",
    "objeto_del_contrato": "CONTRATO DE PRUEBA DEL CONSORCIO",
    "valor_del_contrato": "500000000",
    "fecha_de_inicio_del_contrato": "2026-06-01T00:00:00.000",
    "fecha_de_fin_del_contrato": "2099-12-01T00:00:00.000",
    "nombre_entidad": "ENTIDAD DE PRUEBA",
}
SOCIOS_REALES = [
    {"nombre_grupo": "CONSORCIO VIAS DEL HUILA 2026", "codigo_grupo": CODIGO_GRUPO,
     "nombre_participante": "INGENIERIA Y CONSULTORIA GHE S.A.S", "nit_participante": "901647575",
     "participacion": "10", "es_lider_del_grupo": "Verdadero", "tipo_empresa_grupo": "Consorcio"},
    {"nombre_grupo": "CONSORCIO VIAS DEL HUILA 2026", "codigo_grupo": CODIGO_GRUPO,
     "nombre_participante": "A2M PROYECTOS DE INGENIERIA SAS", "nit_participante": "901267026",
     "participacion": "90", "es_lider_del_grupo": "Falso", "tipo_empresa_grupo": "Consorcio"},
]


def cliente_consorcio(url, params):
    where = params.get("$where", "")
    seleccion = params.get("$select", "")
    if "ceth-n4bn" in url:
        if "nombre_participante" in seleccion:  # socios del grupo
            return SOCIOS_REALES if CODIGO_GRUPO in where else []
        if "VIAS DEL HUILA" in where.upper() or CODIGO_GRUPO in where:
            return [{"nombre_grupo": "CONSORCIO VIAS DEL HUILA 2026", "codigo_grupo": CODIGO_GRUPO,
                     "nit_participante": "901647575", "participacion": "10",
                     "es_lider_del_grupo": "Verdadero", "fecha_creaci_n_grupo": "2026-05-01T00:00:00.000"}]
        return []
    if "jbjy-vk9h" in url:
        if CODIGO_GRUPO in where or "VIAS DEL HUILA" in where.upper():
            return [CONTRATO_PRUEBA]
        return []
    return []


# ── Entorno aislado ──────────────────────────────────────────────────────────

def _sembrar_db(ruta: Path, dias_cierre: int = 10) -> None:
    from sqlalchemy import create_engine, insert

    from m1_ingestor.db_schema import metadata, procesos_s2

    motor = create_engine(f"sqlite:///{ruta}")
    metadata.create_all(motor)
    cierre = (dt.datetime.now() + dt.timedelta(days=dias_cierre)).strftime("%Y-%m-%dT%H:%M:%S")
    with motor.begin() as con:
        con.execute(insert(procesos_s2).values(
            id_del_proceso=ID_SECOP,
            referencia=REFERENCIA,
            entidad="GOBERNACIÓN DEL HUILA",
            titulo=OBJETO,
            modalidad="Concurso de Méritos",       # de prueba
            estado="Presentación de oferta",       # de prueba
            presupuesto_oficial=PRECIO_BASE,
            fecha_cierre=cierre,                   # de prueba: siempre a futuro
            unspsc="72101500",                     # de prueba (el filtro por defecto solo puntúa la familia 72)
            departamento_entidad="Huila",
            ciudad_unidad="Neiva",
            url_proceso="https://community.secop.gov.co/",
            nit_entidad=NIT_ENTIDAD,
        ))
    motor.dispose()


@pytest.fixture
def entorno(tmp_path, monkeypatch):
    import api_client
    import config
    import licencias.trial as trial
    import licencias.validador as validador
    import m6_propuesta.expediente as expediente
    import importlib

    historial = importlib.import_module("m7_competencia.historial_ofertas")
    investigar = importlib.import_module("m7_competencia.investigar")  # el paquete re-exporta la función

    datos = tmp_path / "data"
    datos.mkdir()
    monkeypatch.setenv("LICITAPP_DATA_DIR", str(datos))
    monkeypatch.setattr(config, "DB_PATH", str(datos / "secop.db"))
    monkeypatch.setattr(trial, "TRIAL_PATH", str(datos / ".trial"))
    monkeypatch.setattr(validador, "LICENCIA_PATH", str(tmp_path / "no_existe.lic"))
    _sembrar_db(datos / "secop.db")
    # Sin servidor central: el Explorador debe caer a la base local.
    monkeypatch.setattr(api_client, "get_procesos", lambda **kw: {"error": "sin red", "items": []})
    monkeypatch.setattr(historial, "_cliente_publico", cliente_ofertas)
    expedientes = tmp_path / "expedientes"
    expedientes.mkdir()
    monkeypatch.setattr(expediente, "RAIZ_EXPEDIENTES", expedientes)
    monkeypatch.setattr(investigar, "_cliente_publico", cliente_consorcio)
    import streamlit as st
    st.cache_data.clear()
    return {"datos": datos, "expedientes": expedientes, "tmp": tmp_path}


def _app() -> AppTest:
    return AppTest.from_file(APP, default_timeout=120).run()


def _boton(at: AppTest, etiqueta: str):
    for b in at.button:
        if etiqueta in b.label:
            return b
    raise AssertionError(f"No hay botón «{etiqueta}». Botones: {[b.label for b in at.button]}")


def _sin_excepciones(at: AppTest) -> None:
    assert not at.exception, [e.value for e in at.exception]


def _textos(at: AppTest) -> str:
    partes = []
    for coleccion in (at.markdown, at.success, at.info, at.warning, at.error, at.caption):
        partes += [str(x.value) for x in coleccion]
    return "\n".join(partes)


def _preparar_oferta(at: AppTest) -> AppTest:
    _boton(at, "Preparar oferta").click()
    return at.run()


def _calcular_y_guardar(at: AppTest) -> AppTest:
    at.text_area(key="competidores_calc").set_value("\n".join(list(RIVALES)[:8]))  # 8 reales, sin la atípica
    at = at.run()
    _boton(at, "Calcular las 5").click()
    at = at.run()
    _sin_excepciones(at)
    _boton(at, "Usar esta oferta").click()
    return at.run()


# ── 1. Explorador ────────────────────────────────────────────────────────────

def test_todas_las_pestanas_cargan_sin_excepciones(entorno):
    at = _app()
    _sin_excepciones(at)
    nombres = [t.label for t in at.tabs]
    for esperado in ("EXPLORADOR", "CALCULADORA", "DOCUMENTOS", "CONSORCIOS", "COMPETIDORES",
                     "SEGUIMIENTO", "PROPUESTA", "CUENTA"):
        assert any(esperado in n for n in nombres), (esperado, nombres)


def test_explorador_muestra_el_proceso_real_y_preparar_oferta_lo_selecciona(entorno):
    at = _app()
    _sin_excepciones(at)
    assert at.session_state["proceso_seleccionado"] is None
    assert any(m.label == "Procesos encontrados" and m.value == "1" for m in at.metric)
    at = _preparar_oferta(at)
    _sin_excepciones(at)
    sel = at.session_state["proceso_seleccionado"]
    assert sel["id_del_proceso"] == ID_SECOP
    assert sel["referencia"] == REFERENCIA
    assert float(sel["presupuesto_oficial"]) == PRECIO_BASE
    # La calculadora recibe el proceso y el presupuesto.
    assert at.number_input[0].value == int(PRECIO_BASE)
    assert "Proceso pre-cargado" in _textos(at)


def test_explorador_busca_por_id_de_secop_y_referencia(entorno):
    at = _app()
    for texto in (ID_SECOP, REFERENCIA, "huila"):
        at.text_input(key="texto_busq_adv").set_value(texto)
        at = at.run()
        _sin_excepciones(at)
        assert any(m.label == "Procesos encontrados" and m.value == "1" for m in at.metric), texto
    at.text_input(key="texto_busq_adv").set_value("zzz-no-existe")
    at = at.run()
    assert any(m.label == "Procesos encontrados" and m.value == "0" for m in at.metric)


def test_explorador_sin_base_local_avisa_como_cargar(entorno):
    Path(entorno["datos"] / "secop.db").unlink()
    at = _app()
    _sin_excepciones(at)
    assert "No hay procesos reales cargados" in _textos(at)


# ── 2. Calculadora ───────────────────────────────────────────────────────────

def test_calculadora_calcula_las_cinco_formulas_y_guarda_la_oferta(entorno):
    at = _preparar_oferta(_app())
    at.text_area(key="competidores_calc").set_value("\n".join(list(RIVALES)[:8]))
    at = at.run()
    _boton(at, "Calcular las 5").click()
    at = at.run()
    _sin_excepciones(at)
    texto = _textos(at)
    assert "Comparativa de las 5 Fórmulas" in texto
    assert "Cómo han ofertado antes" in texto
    assert len(at.dataframe) >= 2
    # Cinco pestañas, una por fórmula
    etiquetas = " ".join(t.label for t in at.tabs)
    for cod in ("M —", "MG —", "MAB —", "MAA —", "MV —"):
        assert cod in etiquetas, etiquetas
    # «Usar esta oferta» tiene que sobrevivir al rerun del propio botón
    _boton(at, "Usar esta oferta").click()
    at = at.run()
    _sin_excepciones(at)
    oferta = at.session_state["oferta_guardada"]
    assert oferta is not None
    assert oferta["proceso"] == ID_SECOP
    assert 0 < oferta["precio"] <= PRECIO_BASE
    assert oferta["formula"] in {"M", "MG", "MAB", "MAA", "MV"}
    assert at.session_state["perfil"]["historial_ofertas"][-1]["precio"] == oferta["precio"]
    assert (entorno["datos"] / "perfil_proponente.json").exists()


def test_calculadora_cambiar_formula_conserva_los_resultados(entorno):
    at = _preparar_oferta(_app())
    at.text_area(key="competidores_calc").set_value("\n".join(list(RIVALES)[:8]))
    at = at.run()
    _boton(at, "Calcular las 5").click()
    at = at.run()
    def precio_sugerido():
        return next(n.value for n in at.number_input if "Mi precio final" in n.label)

    precios = {at.radio(key="formula_radio").value: precio_sugerido()}
    at.radio(key="formula_radio").set_value("MV")
    at = at.run()
    _sin_excepciones(at)
    assert "Comparativa de las 5 Fórmulas" in _textos(at)
    precios["MV"] = precio_sugerido()
    assert precios["MV"] != next(v for k, v in precios.items() if k != "MV"), precios  # el campo sigue a la fórmula
    _boton(at, "Usar esta oferta").click()
    at = at.run()
    assert at.session_state["oferta_guardada"]["formula"] == "MV"
    assert at.session_state["oferta_guardada"]["precio"] == precios["MV"]


def test_calculadora_deja_fuera_ofertas_atipicas(entorno):
    at = _preparar_oferta(_app())
    lineas = list(RIVALES)[:7] + [list(RIVALES)[-1]]  # incluye el rival de 128.612.181
    at.text_area(key="competidores_calc").set_value("\n".join(lineas))
    at = at.run()
    _boton(at, "Calcular las 5").click()
    at = at.run()
    _sin_excepciones(at)
    assert "ofertas atípicas" in _textos(at)
    at.checkbox(key="incluir_atipicas").check()
    at = at.run()
    _sin_excepciones(at)
    assert "Se dejaron fuera" not in _textos(at)


def test_calculadora_sin_rivales_pide_datos_reales(entorno):
    at = _preparar_oferta(_app())
    _boton(at, "Calcular las 5").click()
    at = at.run()
    _sin_excepciones(at)
    assert "al menos una oferta" in _textos(at)
    assert at.session_state["oferta_guardada"] is None


# ── 3. Documentos, consorcios, seguimiento, cuenta ───────────────────────────

def test_mis_documentos_guarda_el_perfil(entorno):
    at = _app()
    _boton(at, "Guardar perfil").click()
    at = at.run()
    _sin_excepciones(at)
    assert (entorno["datos"] / "perfil_proponente.json").exists()
    assert "Perfil guardado" in _textos(at)


def test_consorcios_arma_y_valida_porcentajes(entorno):
    at = _app()
    at.session_state["perfil"]["empresa"] = "A2M PROYECTOS DE INGENIERIA SAS"
    at.session_state["perfil"]["socios"] = [
        {"NIT": "901647575", "Razón Social": "INGENIERIA Y CONSULTORIA GHE S.A.S",
         "Contacto": "", "Especialidad": "", "Departamento": "HUILA", "K disponible (COP)": 0}]
    at = at.run()
    _sin_excepciones(at)
    at.multiselect(key="miembros_cons").set_value(
        ["A2M PROYECTOS DE INGENIERIA SAS", "INGENIERIA Y CONSULTORIA GHE S.A.S"])
    at = at.run()
    _sin_excepciones(at)
    assert "Total: 100%" in _textos(at)
    assert any(ID_SECOP in o for o in at.selectbox(key="proc_cons_sel").options)
    _boton(at, "Generar acuerdo de consorcio").click()
    at = at.run()
    _sin_excepciones(at)


def test_seguimiento_agrega_y_quita_un_proceso(entorno):
    at = _app()
    at.text_input(key="ws_nuevo_id").set_value(ID_SECOP)
    at = at.run()
    _boton(at, "Agregar").click()
    at = at.run()
    _sin_excepciones(at)
    assert [w["id"] for w in at.session_state["perfil"]["watchlist"]] == [ID_SECOP]
    _boton(at, "Quitar").click()
    at = at.run()
    _sin_excepciones(at)
    assert at.session_state["perfil"]["watchlist"] == []


def test_mi_cuenta_muestra_la_prueba_de_siete_dias(entorno):
    at = _app()
    _sin_excepciones(at)
    assert any(m.label == "Plan" and m.value == "TRIAL" for m in at.metric)
    assert any(m.label == "Días restantes" and m.value == "7" for m in at.metric)
    assert (entorno["datos"] / ".trial").exists()


def test_mi_cuenta_bloquea_si_la_prueba_vencio(entorno):
    import hashlib
    import json

    from licencias import trial

    inicio = (dt.datetime.now() - dt.timedelta(days=9)).strftime("%Y-%m-%d")
    mid = trial._machine_id()
    h = hashlib.sha256(f"{inicio}-{mid}-secop-trial".encode()).hexdigest()
    Path(trial.TRIAL_PATH).write_text(json.dumps({"inicio": inicio, "machine": mid, "hash": h}))
    at = _app()
    assert "Acceso bloqueado" in " ".join(str(e.value) for e in at.error)


# ── 4. Competidores ──────────────────────────────────────────────────────────

def test_competidores_muestra_consorcio_socios_y_contratos(entorno):
    at = _app()
    at.text_input(key="consulta_comp").set_value("CONSORCIO VIAS DEL HUILA 2026")
    at.text_area(key="declarados_comp").set_value("CO1.PCCNTR.OTRO")
    at = at.run()
    _boton(at, "Investigar competencia").click()
    at = at.run()
    _sin_excepciones(at)
    assert [e.value for e in at.error] == ["Estos contratos están en ejecución y no aparecen en la declaración."]
    tablas = [df.value.to_dict("records") if hasattr(df.value, "to_dict") else df.value for df in at.dataframe]
    aplanado = str(tablas)
    assert "INGENIERIA Y CONSULTORIA GHE" in aplanado and "A2M PROYECTOS" in aplanado
    assert "901647575" in aplanado and "901267026" in aplanado
    assert CODIGO_GRUPO in aplanado or "CONTRATO DE PRUEBA" in aplanado
    assert "CO1.PCCNTR.PRUEBA" in aplanado  # contratos en ejecución
    assert any(m.label == "En ejecución dejados por fuera" and m.value == "1" for m in at.metric)


def test_competidores_nit_inexistente_avisa(entorno):
    at = _app()
    at.text_input(key="consulta_comp").set_value("999999999")
    at = at.run()
    _boton(at, "Investigar competencia").click()
    at = at.run()
    _sin_excepciones(at)
    assert "No hay contratos públicos" in _textos(at)


def test_competidores_consulta_corta_no_revienta(entorno):
    at = _app()
    at.text_input(key="consulta_comp").set_value("ab")
    at = at.run()
    _boton(at, "Investigar competencia").click()
    at = at.run()
    _sin_excepciones(at)
    assert at.error


def test_competidores_sin_servidor_central_degrada_con_aviso(entorno, monkeypatch):
    import api_client

    for nombre in ("get_perfil_competidor", "get_prediccion_competidores", "get_entidades"):
        monkeypatch.setattr(api_client, nombre, lambda *a, **k: {"error": "sin conexión", "items": []})
    at = _app()
    at.text_input(key="nit_buscar_inp").set_value("901267026")
    at.text_input(key="id_pred_rival").set_value(PORTAFOLIO)
    at.text_input(key="ent_q_comp").set_value("HUILA")
    at = at.run()
    for etiqueta in ("Consultar rival", "Predecir rivales", "Buscar"):
        _boton(at, etiqueta).click()
        at = at.run()
        _sin_excepciones(at)


def test_competidores_buscar_entidad_permite_ver_el_perfil(entorno, monkeypatch):
    """«Ver perfil» estaba dentro del botón «Buscar» y nunca se ejecutaba."""
    import api_client

    monkeypatch.setattr(api_client, "get_entidades", lambda **k: {"items": [
        {"entidad": "GOBERNACIÓN DEL HUILA", "departamento": "HUILA", "total_procesos": 1,
         "nit_entidad": NIT_ENTIDAD}]})
    monkeypatch.setattr(api_client, "get_detalle_entidad", lambda nit: {
        "nombre": "GOBERNACIÓN DEL HUILA", "departamento": "HUILA", "total_procesos": 1,
        "contratistas_habituales": [], "entidades_cercanas": []})
    at = _app()
    at.text_input(key="ent_q_comp").set_value("HUILA")
    at = at.run()
    _boton(at, "Buscar").click()
    at = at.run()
    _boton(at, "Ver perfil completo").click()
    at = at.run()
    _sin_excepciones(at)
    assert any(m.label == "Procesos históricos" for m in at.metric)


# ── 5. Propuesta ─────────────────────────────────────────────────────────────

def test_propuesta_simple_pide_proceso_y_precio_y_luego_arma_el_paquete(entorno):
    at = _app()
    assert "Preparar oferta" in _textos(at)  # aviso inicial de la pestaña
    at = _preparar_oferta(at)
    assert "Usar esta oferta" in _textos(at)
    at = _calcular_y_guardar(at)
    _sin_excepciones(at)
    assert any(m.label == "Proceso" and m.value == ID_SECOP for m in at.metric)
    assert any(m.label == "Canal" and m.value == "secop" for m in at.metric)
    _boton(at, "Guardar propuesta en mi cuenta").click()
    at = at.run()
    _sin_excepciones(at)
    assert at.session_state["perfil"]["propuestas"][-1]["proceso"] == ID_SECOP


@pytest.mark.skipif(not EXPEDIENTE_REAL.is_dir(), reason="el expediente real no está en esta máquina")
def test_propuesta_completa_desde_el_expediente_real(entorno):
    destino = entorno["expedientes"] / EXPEDIENTE_REAL.name
    shutil.copytree(EXPEDIENTE_REAL, destino, ignore=shutil.ignore_patterns("propuestas"))
    at = _preparar_oferta(_app())
    at = _calcular_y_guardar(at)
    _sin_excepciones(at)
    assert any(m.label == "Proceso del expediente" and m.value == REFERENCIA for m in at.metric)
    _boton(at, "Generar propuesta en la carpeta del expediente").click()
    at = at.run()
    _sin_excepciones(at)
    assert not at.error, [e.value for e in at.error]
    res = at.session_state["paquete_expediente"]
    carpeta = Path(res["carpeta"])
    assert carpeta.is_dir() and destino in carpeta.parents
    assert res["proceso_id"] == REFERENCIA
    assert res["mismo_proceso"] is True
    assert res["canal"]["tipo"] == "secop"
    assert len(res["archivos"]) > 15
    assert any(p.suffix == ".csv" for p in carpeta.iterdir())  # índice del paquete
    assert not carpeta.is_relative_to(RAIZ / "expedientes")  # nada se escribe en el repositorio


def test_paquete_del_expediente_cubre_un_proceso_nuevo_sin_tocar_el_original(tmp_path):
    from m6_propuesta.expediente import generar_paquete, leer_expediente

    if not EXPEDIENTE_REAL.is_dir():
        pytest.skip("el expediente real no está en esta máquina")
    destino = tmp_path / EXPEDIENTE_REAL.name
    shutil.copytree(EXPEDIENTE_REAL, destino, ignore=shutil.ignore_patterns("propuestas"))
    antes = sorted(str(p.relative_to(EXPEDIENTE_REAL)) for p in EXPEDIENTE_REAL.rglob("*"))
    exp = leer_expediente(destino)
    res = generar_paquete(
        exp,
        {"id": "CO1.REQ.0000001", "referencia": "PROCESO-NUEVO-1", "entidad": "ENTIDAD NUEVA",
         "objeto": "OBJETO NUEVO", "presupuesto_oficial": 1_000_000_000,
         "nit_entidad": "8000000000"},
        {"precio": 990_000_000, "formula": "M", "nombre_formula": "Mediana"},
        consorcio={"nombre": "CONSORCIO VÍAS DEL HUILA 2026", "integrantes": exp["datos"]["integrantes"],
                   "corregir_nombres": True},
        fecha_cierre=dt.date(2026, 12, 1),
    )
    assert res["mismo_proceso"] is False
    assert any(f["estado"] in {"pendiente", "rehacer", "revisar"} for f in res["indice"])
    despues = sorted(str(p.relative_to(EXPEDIENTE_REAL)) for p in EXPEDIENTE_REAL.rglob("*"))
    assert antes == despues


# ── 6. Bot, alertas y datos ──────────────────────────────────────────────────

def test_bot_dry_run_desde_la_interfaz(entorno, monkeypatch):
    import m4_bot.secop_bot as secop_bot

    llamadas = {}

    class BotFalso:
        def __init__(self, usuario, contrasena, modo, headless):
            llamadas["modo"] = modo

        def presentar_oferta(self, id_proceso, propuesta_economica, documentos=None):
            llamadas["id"] = id_proceso
            llamadas["precio"] = propuesta_economica
            return {"exito": True, "dry_run": True, "comprobante": "x.pdf", "log": ["ok"], "pasos": ["login_ok"]}

    monkeypatch.setattr(secop_bot, "SecopBot", BotFalso)
    at = _preparar_oferta(_app())
    at = _calcular_y_guardar(at)
    at.text_input(key="bot_usuario").set_value("usuario")
    at.text_input(key="bot_pass").set_value("clave")
    at = at.run()
    assert not _boton(at, "Ejecutar Bot").disabled
    _boton(at, "Ejecutar Bot").click()
    at = at.run()
    _sin_excepciones(at)
    assert llamadas["modo"] == "dry_run" and llamadas["id"] == ID_SECOP
    assert llamadas["precio"] == at.session_state["oferta_guardada"]["precio"]
    assert "DRY-RUN completado" in _textos(at)


def test_bot_real_no_se_habilita_sin_confirmacion(entorno):
    at = _app()
    at.text_input(key="bot_usuario").set_value("usuario")
    at.text_input(key="bot_pass").set_value("clave")
    at.text_input(key="bot_id_manual").set_value(ID_SECOP)
    at.radio(key="bot_modo").set_value("real")
    at = at.run()
    assert _boton(at, "PRESENTAR OFERTA").disabled
    at.checkbox(key="bot_confirmar_real").check()
    at = at.run()
    assert not _boton(at, "PRESENTAR OFERTA").disabled


def test_bot_sin_navegador_devuelve_error_controlado(tmp_path, monkeypatch):
    from m4_bot.secop_bot import SecopBot

    def sin_navegador(self):
        raise RuntimeError("Executable doesn't exist")

    monkeypatch.setattr(SecopBot, "_iniciar_browser", sin_navegador)
    res = SecopBot("u", "p", modo="dry_run", carpeta_capturas=str(tmp_path)).presentar_oferta(ID_SECOP, 1_000_000)
    assert res["exito"] is False and "Error inesperado" in res["error"]


def test_alertas_sin_correo_configurado_no_revientan(entorno):
    at = _app()
    _boton(at, "Enviar alerta ahora").click()
    at = at.run()
    _sin_excepciones(at)


def test_ingesta_guarda_procesos_en_la_base_local(tmp_path, monkeypatch):
    """INICIAR_DATOS: sync_procesos_s2 con un cliente falso llena procesos_s2 y el Explorador los lee."""
    import m1_ingestor.ingestor as ingestor
    from m3_filtrado.process_filter import get_oportunidades_top

    class ClienteFalso:
        def get_procesos_s2(self, filters=None, max_records=0):
            return []

    monkeypatch.setattr(ingestor, "SecopClient", ClienteFalso)
    db = str(tmp_path / "secop.db")
    assert ingestor.sync_procesos_s2(db) == 0
    _sembrar_db(Path(db))
    top = get_oportunidades_top(db)
    assert list(top["id_del_proceso"]) == [ID_SECOP]
    assert top.iloc[0]["score"] >= 60
