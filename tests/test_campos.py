"""Mapeo de un registro con la forma real de datos.gov.co. Sin red."""
from m1_ingestor.campos import (
    fila_oferta,
    fila_proceso_s2,
    norm_departamento,
    unspsc_codigo,
    where_departamentos,
    where_oferta,
    where_procesos_s2,
)

PROCESO = {
    "id_del_portafolio": "CO1.BDOS.10191681",
    "id_del_proceso": "CO1.REQ.1",
    "referencia_del_proceso": "EDP-1",
    "entidad": "ALCALDIA DE ZIPAQUIRA",
    "nombre_del_procedimiento": "Mantenimiento de via",
    "modalidad_de_contratacion": "Contratación directa",
    "fase": "Presentación de oferta",
    "precio_base": "73307499",
    "codigo_principal_de_categoria": "V1.72154503",
    "departamento_entidad": "Distrito Capital de Bogotá",
    "ciudad_de_la_unidad_de": "Bogotá",
    "urlproceso": {"url": "https://community.secop.gov.co/ejemplo"},
    "fecha_de_ultima_publicaci": "2024-06-01T00:00:00.000",
    "numero_de_lotes": "2",
}


def test_proceso_usa_portafolio_y_categoria_real():
    fila = fila_proceso_s2(PROCESO, "2026-11-08T00:00:00Z")
    assert fila["id_del_proceso"] == "CO1.BDOS.10191681"
    assert fila["entidad"] == "ALCALDIA DE ZIPAQUIRA"
    assert fila["titulo"] == "Mantenimiento de via"
    assert fila["estado"] == "Presentación de oferta"
    assert fila["unspsc"] == "72154503"
    assert fila["departamento_entidad"] == "BOGOTA"
    assert fila["ciudad_unidad"] == "Bogotá"
    assert fila["url_proceso"] == "https://community.secop.gov.co/ejemplo"
    assert fila["presupuesto_oficial"] == 73307499
    assert fila["fecha_cierre"] == ""
    assert fila["lotes"] == 2


def test_departamento_y_unspsc():
    assert norm_departamento("Boyacá") == "BOYACA"
    assert unspsc_codigo("V1.80111500") == "80111500"


def test_oferta_usa_columnas_reales():
    fila = fila_oferta({
        "identificador_de_la_oferta": "CO1.RPL.5078318",
        "id_del_proceso_de_compra": "CO1.BDOS.8448566",
        "nit_del_proveedor": "900123456",
        "nombre_proveedor": "CONSORCIO HIDROSEN",
        "valor_de_la_oferta": "2681067567.00",
        "fecha_de_registro": "2025-08-08T21:41:36.523",
    })
    assert fila["id_del_proceso"] == "CO1.BDOS.8448566"
    assert fila["nit_oferente"] == "900123456"
    assert fila["nombre_oferente"] == "CONSORCIO HIDROSEN"
    assert fila["propuesta_economica"] == 2681067567.00


def test_where_no_usa_columnas_inexistentes():
    where = where_procesos_s2(5_000_000, 500_000_000, ["72000000"], "2026-01-01T00:00:00Z")
    assert "estado_del_proceso" not in where
    assert "unspsc_codigo_primer_nivel" not in where
    assert "estado_de_apertura_del_proceso='Abierto'" in where
    assert "codigo_principal_de_categoria like '%72%'" in where
    assert where_oferta("CO1.BDOS.1") == "id_del_proceso_de_compra='CO1.BDOS.1'"
    deptos = where_departamentos(["BOGOTA", "CUNDINAMARCA"])
    assert "BOGOT" in deptos
    assert "CUNDIN" in deptos
    assert "in(" not in deptos
