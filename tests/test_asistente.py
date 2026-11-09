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
