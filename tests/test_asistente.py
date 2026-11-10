"""Ofertar paso a paso: un proponente nuevo, sin datos previos, llega a la propuesta."""
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from m6_propuesta import asistente as A

RAIZ = Path(__file__).resolve().parent.parent

# Datos reales de SECOP II (consultados el 2026-11-09).
PROCESO_SECOP = {
    "id_del_proceso": "CO1.REQ.9426412", "id_del_portafolio": "CO1.BDOS.9257883",
    "referencia_del_proceso": "SVCMIN0010-25", "entidad": "GOBERNACION DEL HUILA*", "nit_entidad": "800103913",
    "nombre_del_procedimiento": "INTERVENTORÍA AL MEJORAMIENTO MEDIANTE PAVIMENTO FLEXIBLE EN LA VIA CRUCE",
    "modalidad_de_contratacion": "Concurso de méritos abierto", "fase": "Presentación de oferta",
    "precio_base": "1288612325", "fecha_de_recepcion_de": "2026-06-11T00:00:00.000",
    "urlproceso": {"url": "https://community.secop.gov.co/Public/Tendering/OpportunityDetail/Index?noticeUID=CO1.NTC.9287369"},
}
OFERTAS = [{"identificador_de_la_oferta": f"CO1.RPL.{i}", "nombre_proveedor": f"R{i}", "valor_de_la_oferta": v}
           for i, v in enumerate(["1288612325.00", "1288599235.00", "1288350525.00", "1257553682.00", "128612181.00"])]


def cliente(url, params):
    where = params.get("$where", "")
    if "p6dx-8zbt" in url:
        return [PROCESO_SECOP] if ("SVCMIN0010-25" in where or "CO1.REQ.9426412" in where) else []
    if "wi7w-2nvm" in url:
        return OFERTAS + OFERTAS[:2] if "CO1.BDOS.9257883" in where else []
    return []


def test_buscar_por_referencia_y_por_id():
    for texto in ("SVCMIN0010-25", "CO1.REQ.9426412"):
        procesos = A.buscar_procesos(texto, cliente)
        assert len(procesos) == 1
        p = procesos[0]
        assert p["referencia"] == "SVCMIN0010-25" and p["presupuesto_oficial"] == 1288612325
        assert p["fecha_cierre"] == "2026-06-11"


def test_buscar_texto_corto_avisa():
    with pytest.raises(ValueError):
        A.buscar_procesos("ab", cliente)


def test_ofertas_reales_sin_duplicados():
    proceso = A.buscar_procesos("SVCMIN0010-25", cliente)[0]
    assert len(A.ofertas_del_proceso(proceso, cliente)) == 5


def test_expediente_propio_consorcio_y_subidas(tmp_path):
    perfil = {"empresa": "A2M", "nit": "901267026", "representante": "ANA", "proponente_plural": True,
              "tipo_plural": "Consorcio", "proponente_nombre": "CONSORCIO PRUEBA 2026",
              "integrantes": [{"nombre": "A", "nit": "1", "participacion": 90}, {"nombre": "B", "nit": "2", "participacion": 10}]}
    proceso = A.buscar_procesos("SVCMIN0010-25", cliente)[0]
    carpeta = A.crear_expediente(perfil, proceso, {"precio": 1_000_000}, base=tmp_path)
    assert (carpeta / A.SECCIONES[0][1] / "Carta de Presentacion de la Oferta.docx").exists()
    assert (carpeta / A.SECCIONES[1][1] / "Documento de Conformacion.docx").exists()
    A.guardar_subida(carpeta, A.SECCIONES[3][1], "../../RUT empresa.pdf", b"%PDF")
    assert (carpeta / A.SECCIONES[3][1] / "RUT_empresa.pdf").exists() or list((carpeta / A.SECCIONES[3][1]).glob("*.pdf"))
    with pytest.raises(ValueError):
        A.guardar_subida(carpeta, A.SECCIONES[3][1], "virus.exe", b"MZ")
    assert any("RUT" in f for f in A.faltantes(carpeta, True)) is False


def test_flujo_completo_en_la_app(tmp_path):
    """Recorre la pestaña con AppTest en un proceso aparte (carpetas de datos temporales)."""
    script = textwrap.dedent(f"""
        import sys; sys.path.insert(0, {str(RAIZ)!r}); sys.path.insert(0, {str(RAIZ / 'tests')!r})
        from test_asistente import cliente
        from streamlit.testing.v1 import AppTest
        at = AppTest.from_file({str(RAIZ / 'm5_dashboard' / 'app.py')!r}, default_timeout=180)
        at.session_state["_cliente_secop_pruebas"] = cliente
        at.run()
        assert not at.exception, at.exception
        def btn(k): return next(b for b in at.button if b.key == k)
        def txt(k): return next(t for t in at.text_input if t.key == k)
        txt("asis_empresa").input("A2M PROYECTOS DE INGENIERIA SAS"); txt("asis_nit").input("901267026")
        txt("asis_rep").input("JOSE ANDRES MURILLO")
        btn("asis_guardar_datos").click().run(); assert not at.exception, at.exception
        txt("asis_buscar").input("SVCMIN0010-25"); btn("asis_btn_buscar").click().run()
        btn("asis_elegir_0").click().run(); assert not at.exception, at.exception
        btn("eval_calcular").click().run(); assert not at.exception, at.exception
        # Reiniciar el árbol evita una limitación de AppTest con number_input al
        # cambiar de paso; el perfil y el diagnóstico ya quedaron persistidos.
        proceso = at.session_state.proceso_seleccionado
        at = AppTest.from_file({str(RAIZ / 'm5_dashboard' / 'app.py')!r}, default_timeout=180)
        at.session_state["_cliente_secop_pruebas"] = cliente
        at.session_state["proceso_seleccionado"] = proceso
        at.session_state["asis_paso"] = 3
        at.run(); assert not at.exception, at.exception
        assert any("4 ofertas" in i.value or "5 ofertas" in i.value for i in at.info), [i.value for i in at.info]
        btn("asis_s2").click().run(); assert not at.exception, at.exception
        assert at.session_state.oferta_guardada["precio"] > 0
        btn("asis_s3").click().run(); assert not at.exception, at.exception
        assert any("Propuesta armada" in s.value for s in at.success), [s.value for s in at.success]
        print("FLUJO_OK", at.session_state["asis_paquete"]["canal"]["tipo"])
    """)
    env = dict(os.environ, LICITAPP_DATA_DIR=str(tmp_path / "data"), LICITAPP_EXPEDIENTES=str(tmp_path / "exp"))
    salida = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, env=env, timeout=600)
    assert "FLUJO_OK secop" in salida.stdout, salida.stdout[-2000:] + salida.stderr[-3000:]


def cliente_vivo(url, params):
    if "p6dx-8zbt" in url:
        from datetime import date, timedelta
        fila = dict(PROCESO_SECOP, fecha_de_recepcion_de=(date.today() + timedelta(days=10)).isoformat() + "T00:00:00.000")
        return [fila]
    return []


def test_where_vivo_solo_procesos_abiertos_y_filtros_seguros():
    from datetime import date
    from m1_ingestor.vivo import where_vivo
    w = where_vivo({"q": "pavimentación' OR '1'='1", "po_min": 1000, "po_max": 5000, "dias_cierre_max": 30}, date(2026, 11, 9))
    assert "fecha_de_recepcion_de >= '2026-11-09" in w and "precio_base <= 5000" in w
    assert "'' OR ''1''=''1" in w.replace("PAVIMENTACION", "").upper() or "''1''" in w
    w_municipio = where_vivo({"municipio": "Barranquilla"}, date(2026, 11, 9))
    assert "ciudad_de_la_unidad_de" in w_municipio and "ciudad_entidad" in w_municipio


def test_explorador_en_vivo_y_guardar(tmp_path):
    script = textwrap.dedent(f"""
        import sys; sys.path.insert(0, {str(RAIZ)!r}); sys.path.insert(0, {str(RAIZ / 'tests')!r})
        from test_asistente import cliente_vivo
        from streamlit.testing.v1 import AppTest
        at = AppTest.from_file({str(RAIZ / 'm5_dashboard' / 'app.py')!r}, default_timeout=180)
        at.session_state["_cliente_secop_pruebas"] = cliente_vivo
        at.run()
        assert not at.exception, at.exception
        next(t for t in at.toggle if t.key == "usar_perfil_tog").set_value(False).run()
        assert any(m.label == "Procesos encontrados" and m.value == "1" for m in at.metric), [(m.label, m.value) for m in at.metric]
        next(b for b in at.button if (b.key or "").startswith("btn_guardar_")).click().run()
        assert not at.exception, at.exception
        assert len(at.session_state.perfil["procesos_guardados"]) == 1
        next(r for r in at.radio if r.key == "vista_explorador").set_value("⭐ Guardados (1)").run()
        assert any((b.key or "").startswith("btn_quitar_") for b in at.button)
        print("VIVO_OK")
    """)
    env = dict(os.environ, LICITAPP_DATA_DIR=str(tmp_path / "data"), LICITAPP_EXPEDIENTES=str(tmp_path / "exp"))
    salida = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, env=env, timeout=600)
    assert "VIVO_OK" in salida.stdout, salida.stdout[-2000:] + salida.stderr[-3000:]


def test_where_vivo_filtra_departamento_modalidad_y_sector_en_secop():
    from datetime import date
    from m1_ingestor.vivo import where_vivo
    w = where_vivo({"departamentos": ["ATLANTICO"], "modalidades": ["Mínima Cuantía"], "unspsc": ["72"]}, date(2026, 11, 9))
    assert "upper(departamento_entidad) like '%_TL_NT_C_%'" in w
    assert "upper(modalidad_de_contratacion) like" in w and "codigo_principal_de_categoria like 'V1.72%'" in w
    assert "fecha_de_recepcion_de >= '2026-11-09" in w and "fase =" not in w


def test_checklist_por_oferta_exige_evidencia_y_revision(tmp_path):
    from m6_propuesta import asistente as A
    perfil = {"empresa": "ALFA SAS", "proponente_nombre": "ALFA SAS", "nit": "900123456",
              "representante": "ANA", "proponente_plural": False}
    proceso = {"id": "CO1.REQ.1", "referencia": "LP-001", "entidad": "ENTIDAD", "objeto": "OBRA"}
    carpeta = A.crear_expediente(perfil, proceso, {"precio": 1000}, base=tmp_path)
    confirmaciones = {"global_pliego": True}
    A.guardar_checklist(carpeta, confirmaciones)
    assert A.cargar_checklist(carpeta)["global_pliego"] is True
    estado = A.estado_checklist(carpeta, False, confirmaciones)
    assert estado["porcentaje"] < 100 and not estado["listo"]
    carta = next(i for i in estado["secciones"] if i["clave"] == "carta")
    assert not carta["evidencia"]  # el Word generado todavía no está firmado en PDF

    for clave, nombre, _ in A.SECCIONES:
        if clave in {"consorcio", "otros"}:
            continue
        (carpeta / nombre / f"{clave}.pdf").write_bytes(b"%PDF")
        confirmaciones[f"seccion_{clave}"] = True
    for clave in ("pliego", "adendas", "requisitos", "cierre", "canal"):
        confirmaciones[f"global_{clave}"] = True
    estado = A.estado_checklist(carpeta, False, confirmaciones)
    assert estado["listo"] and estado["porcentaje"] == 100


def test_evaluacion_experiencia_financiera_y_juridica():
    from m6_propuesta.evaluacion import evaluar_experiencia, evaluar_financiero, evaluar_total
    contratos = [
        {"contrato": "RUP-1", "valor": 800, "participacion": 100, "terminado": True, "soporte": True, "actividad": True},
        {"contrato": "RUP-2", "valor": 400, "participacion": 50, "terminado": True, "soporte": True, "actividad": False},
    ]
    exp = evaluar_experiencia({"pct_total": 100, "pct_especifica": 70, "max_contratos": 2}, contratos, 1000)
    assert exp["cumple"] and exp["total"] == 1000 and exp["especifico"] == 800
    fin = evaluar_financiero({"liquidez": 1.5, "liquidez_min": 1.2,
                              "endeudamiento": 0.5, "endeudamiento_max": 0.7,
                              "aplica_cobertura": False, "aplica_roe": False, "aplica_roa": False})
    jur = {k: True for k in ("capacidad_juridica", "rup_vigente", "sin_inhabilidades", "seguridad_social", "garantia")}
    total = evaluar_total(exp, fin, jur)
    assert total["cumple"] and total["porcentaje"] == 100


def test_ficha_decision_es_conservadora_y_trazable():
    from m6_propuesta.evaluacion import ficha_decision
    resultado = {"cumple": True, "criterios": []}
    matriz = [{"requisito": "Certificado", "estado": "Cumple", "critico": True,
               "fuente": "Pliego p. 12", "evidencia": "certificado.pdf"}]
    ficha = ficha_decision(resultado, matriz, {"ingreso": 100, "costos": 90, "margen_minimo": 5})
    assert ficha["decision"] == "PARTICIPAR" and ficha["margen"] == 10

    sin_evidencia = ficha_decision(resultado, [{**matriz[0], "evidencia": ""}],
                                    {"ingreso": 100, "costos": 90, "margen_minimo": 5})
    assert sin_evidencia["decision"] == "REVISAR"
    assert any("evidencia" in x.lower() for x in sin_evidencia["pendientes"])

    # Un cálculo negativo no descarta silenciosamente; requiere confirmación humana.
    bajo_margen = ficha_decision(resultado, matriz, {"ingreso": 100, "costos": 99, "margen_minimo": 5})
    assert bajo_margen["decision"] == "REVISAR"
    descartada = ficha_decision(resultado, matriz, {"ingreso": 100, "costos": 90, "margen_minimo": 5},
                                {"confirmado": True, "detalle": "No cumple licencia obligatoria"})
    assert descartada["decision"] == "DESCARTAR"


def test_historial_entidad_agrupa_oferentes_y_adjudicatarios():
    from datetime import date
    from m7_competencia.entidad import analizar_entidad

    def cliente_entidad(url, params):
        if "wi7w-2nvm" in url:
            return [
                {"identificador_de_la_oferta": "O1", "id_del_proceso_de_compra": "P1",
                 "nombre_proveedor": "ALFA SAS", "nit_del_proveedor": "9001", "valor_de_la_oferta": "90"},
                {"identificador_de_la_oferta": "O2", "id_del_proceso_de_compra": "P2",
                 "nombre_proveedor": "ALFA SAS", "nit_del_proveedor": "9001", "valor_de_la_oferta": "180"},
                {"identificador_de_la_oferta": "O3", "id_del_proceso_de_compra": "P1",
                 "nombre_proveedor": "BETA SAS", "nit_del_proveedor": "9002", "valor_de_la_oferta": "95"},
            ]
        if "jbjy-vk9h" in url:
            return [{"id_contrato": "C1", "proveedor_adjudicado": "ALFA SAS", "documento_proveedor": "9001",
                     "valor_del_contrato": "88", "es_grupo": "No"}]
        return []

    r = analizar_entidad({"entidad": "ALCALDIA X", "nit_entidad": "800123456"}, cliente_entidad,
                         date(2026, 11, 9))
    assert r["desde"] == "2023-11-09" and r["procesos_con_ofertas"] == 2
    assert r["oferentes"][0]["nombre"] == "ALFA SAS" and r["oferentes"][0]["adjudicaciones"] == 1
    assert r["adjudicatarios"][0]["contratos"] == 1


def test_historial_contextual_tolera_tildes_y_no_devuelve_falso_cero():
    from datetime import date
    from m7_competencia.entidad import analizar_entidad

    def cliente_contexto(url, params):
        if "p6dx-8zbt" in url:
            assert "M_N_M_ C__NT__" in params["$where"]
            return [{"id_del_portafolio": "P1", "precio_base": "100"}]
        if "wi7w-2nvm" in url:
            return [{"identificador_de_la_oferta": "O1", "id_del_proceso_de_compra": "P1",
                     "nombre_proveedor": "ALFA", "nit_del_proveedor": "9001", "valor_de_la_oferta": "90"}]
        if "jbjy-vk9h" in url:
            return [{"id_contrato": "C1", "proceso_de_compra": "P1", "proveedor_adjudicado": "ALFA",
                     "documento_proveedor": "9001", "valor_del_contrato": "90"}]
        return []

    r = analizar_entidad({"entidad": "ENTIDAD", "nit_entidad": "8001", "modalidad": "Mínima cuantía",
                          "unspsc": "UNSPECIFIED"}, cliente_contexto, date(2026, 11, 10), anos=2,
                         filtrar_contexto=True)
    assert r["nivel_comparacion"] == "misma modalidad"
    assert r["procesos_contexto"] == 1 and r["ofertas"] == 1 and r["contratos"] == 1


def test_reutiliza_documentos_vigentes_y_excluye_vencidos(tmp_path):
    from datetime import date
    from m6_propuesta import asistente as A
    vigente = tmp_path / "RUT vigente.pdf"; vigente.write_bytes(b"%PDF")
    vencido = tmp_path / "RUP viejo.pdf"; vencido.write_bytes(b"%PDF")
    perfil = {"empresa": "ALFA", "nit": "9001", "representante": "ANA",
              "biblioteca_documentos": [
                  {"nombre": vigente.name, "categoria": "rut", "vence": "2027-01-01", "ruta": str(vigente)},
                  {"nombre": vencido.name, "categoria": "rup", "vence": "2025-01-01", "ruta": str(vencido)},
              ]}
    carpeta = A.crear_expediente(perfil, {"id": "P1"}, {"precio": 100}, base=tmp_path / "exp")
    r = A.sincronizar_documentos_reutilizables(carpeta, perfil, date(2026, 11, 10))
    assert "RUT_vigente.pdf" in r["copiados"] and vencido.name in r["vencidos"]
    assert list((carpeta / A.SECCIONES[3][1]).glob("*.pdf"))
