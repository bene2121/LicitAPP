from m7_competencia.investigar import contrastar, investigar

CONTRATO_CONSORCIO = {
    "id_contrato": "CO1.PCCNTR.1",
    "proveedor_adjudicado": "CONSORCIO AMAGA 2023",
    "documento_proveedor": "901727459",
    "es_grupo": "Si",
    "estado_contrato": "En ejecución",
    "objeto_del_contrato": "MEJORAMIENTO DE VIAS TERCIARIAS",
    "valor_del_contrato": "243652500",
    "fecha_de_inicio_del_contrato": "2024-01-01T00:00:00.000",
    "fecha_de_fin_del_contrato": "2026-12-01T00:00:00.000",
    "nombre_entidad": "MUNICIPIO DE AMAGA",
}
CONTRATO_SOCIO = {
    "id_contrato": "CO1.PCCNTR.2",
    "proveedor_adjudicado": "URBESUR SAS",
    "documento_proveedor": "900642880",
    "es_grupo": "No",
    "estado_contrato": "En ejecución",
    "objeto_del_contrato": "SUMINISTRO DE MATERIALES DE OBRA",
    "valor_del_contrato": "80000000",
    "fecha_de_inicio_del_contrato": "2025-02-01T00:00:00.000",
    "fecha_de_fin_del_contrato": "2026-08-01T00:00:00.000",
    "nombre_entidad": "ALCALDIA DE CALDAS",
}
CONTRATO_CERRADO = dict(CONTRATO_SOCIO, id_contrato="CO1.PCCNTR.3", estado_contrato="terminado")
SOCIOS = [
    {
        "nombre_grupo": "CONSORCIO AMAGA 2023",
        "nombre_participante": "URBESUR SAS",
        "nit_participante": "900642880",
        "participacion": "50.0",
        "es_lider_del_grupo": "Falso",
        "tipo_empresa_grupo": "Consorcio",
    },
    {
        "nombre_grupo": "CONSORCIO AMAGA 2023",
        "nombre_participante": "JUAN FELIPE GONZALEZ VELEZ",
        "nit_participante": "71788464",
        "participacion": "50.0",
        "es_lider_del_grupo": "Verdadero",
        "tipo_empresa_grupo": "Consorcio",
    },
]


def cliente(url, params):
    where = params.get("$where", "")
    if "nombre_grupo" in params.get("$select", "") and "nombre_participante" in params.get("$select", ""):
        return SOCIOS
    if "ceth-n4bn" in url and "nombre_grupo" in params.get("$select", ""):
        return [{"nombre_grupo": "CONSORCIO AMAGA 2023"}]
    if "901727459" in where or "CONSORCIO AMAGA" in where:
        return [CONTRATO_CONSORCIO]
    if "900642880" in where:
        return [CONTRATO_SOCIO, CONTRATO_CERRADO]
    if "71788464" in where:
        return []
    return []


def test_consorcio_muestra_socios_y_el_contrato_omitido():
    resultado = investigar(
        "CONSORCIO AMAGA 2023",
        declarados=["MEJORAMIENTO DE VIAS TERCIARIAS"],
        cliente=cliente,
    )
    assert resultado["es_plural"] is True
    nits = {s["nit"] for s in resultado["socios"]}
    assert nits == {"900642880", "71788464"}
    ids_omitidos = {c["id"] for c in resultado["contraste"]["omitidos"]}
    assert ids_omitidos == {"CO1.PCCNTR.2"}
    assert resultado["contraste"]["cubiertos"][0]["id"] == "CO1.PCCNTR.1"
    assert all(c["en_ejecucion"] for c in resultado["en_ejecucion"])


def test_nit_no_arma_busqueda_por_nombre():
    resultado = investigar("901727459", cliente=cliente)
    assert resultado["nits"] == ["901727459"]
    assert resultado["contraste"]["omitidos"] == []
    assert resultado["en_ejecucion"]


def test_contrastar_sin_declaracion_no_marca_omitidos():
    assert contrastar([{"id": "A", "objeto": "OBRA", "entidad": "X"}], [])["omitidos"] == []
