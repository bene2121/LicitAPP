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


def test_miembro_enlaza_consorcios_por_codigo_y_descarta_homonimos():
    grupos = [
        {"nombre_grupo": "CONSORCIO SIGMA", "codigo_grupo": "707399069", "nit_participante": "901267026",
         "participacion": "40.000000", "es_lider_del_grupo": "Falso"},
    ]
    socios = [
        {"nombre_grupo": "CONSORCIO SIGMA", "codigo_grupo": "707399069", "nombre_participante": "A2M SAS",
         "nit_participante": "901267026", "participacion": "40.0", "es_lider_del_grupo": "Falso"},
        {"nombre_grupo": "CONSORCIO SIGMA", "codigo_grupo": "707399069", "nombre_participante": "SOCIO X SAS",
         "nit_participante": "900000001", "participacion": "60.0", "es_lider_del_grupo": "Verdadero"},
    ]
    del_grupo = dict(CONTRATO_CONSORCIO, id_contrato="CO1.PCCNTR.10", proveedor_adjudicado="CONSORCIO SIGMA",
                     codigo_proveedor="707399069", documento_proveedor="No Definido")

    def cli(url, params):
        where = params.get("$where", "")
        if "ceth-n4bn" in url:
            return socios if "nombre_participante" in params.get("$select", "") else grupos
        if "codigo_proveedor in" in where:
            return [del_grupo] if "707399069" in where else []
        return []

    r = investigar("901267026", cliente=cli)
    assert [g["codigo"] for g in r["consorcios"]] == ["707399069"]
    assert r["consorcios"][0]["participacion"] == "40"
    assert [c["id"] for c in r["en_ejecucion"]] == ["CO1.PCCNTR.10"]
    assert r["en_ejecucion"][0]["via"] == "consorcio"
    assert {s["nit"] for s in r["socios"]} == {"900000001"}


# Datos reales de SECOP II (datos.gov.co, consultados el 2026-11-09).
VIAS_HUILA = {"codigo": "736763764", "nombre": "CONSORCIO VIAS DEL HUILA 2026"}
SOCIOS_HUILA = [
    {"nombre_grupo": "CONSORCIO VIAS DEL HUILA 2026", "codigo_grupo": "736763764",
     "nombre_participante": "INGENIERIA Y CONSULTORIA GHE S.A.S.", "nit_participante": "901647575",
     "participacion": "10.000000", "es_lider_del_grupo": "Verdadero", "tipo_empresa_grupo": "Consorcio"},
    {"nombre_grupo": "CONSORCIO VIAS DEL HUILA 2026", "codigo_grupo": "736763764",
     "nombre_participante": "A2M PROYECTOS DE INGENIERIA SAS", "nit_participante": "901267026",
     "participacion": "90.000000", "es_lider_del_grupo": "Falso", "tipo_empresa_grupo": "Consorcio"},
]
OTRO_GRUPO_A2M = {"nombre_grupo": "CONSORCIO MM 2024", "codigo_grupo": "729661686",
                  "nit_participante": "901267026", "participacion": "90.000000", "es_lider_del_grupo": "Falso"}
CONTRATO_MM = {"id_contrato": "CO1.PCCNTR.7174033", "proveedor_adjudicado": "CONSORCIO MM 2024",
               "codigo_proveedor": "729661686", "documento_proveedor": "No Definido", "es_grupo": "Si",
               "estado_contrato": "En ejecución", "nombre_entidad": "ALCALDÍA LOCAL DE BARRIOS UNIDOS",
               "valor_del_contrato": "531463226", "objeto_del_contrato": "OBRA",
               "fecha_de_fin_del_contrato": "2025-07-19T00:00:00.000"}


def _cliente_huila(url, params):
    where = params.get("$where", "")
    if "ceth-n4bn" in url:
        if "nombre_participante" in params.get("$select", ""):
            return SOCIOS_HUILA if "736763764" in where else []
        if "VIAS DEL HUILA" in where:
            return [{"nombre_grupo": VIAS_HUILA["nombre"], "codigo_grupo": VIAS_HUILA["codigo"]}]
        if "901267026" in where:
            return [dict(OTRO_GRUPO_A2M), {"nombre_grupo": VIAS_HUILA["nombre"], "codigo_grupo": VIAS_HUILA["codigo"],
                                            "nit_participante": "901267026"}]
        return []
    if "codigo_proveedor in" in where:
        return [CONTRATO_MM] if "729661686" in where else []
    return []


def test_consorcio_real_vias_del_huila():
    r = investigar("CONSORCIO VIAS DEL HUILA 2026", declarados=["SECRETARIA DE VIAS"], cliente=_cliente_huila)
    assert r["es_plural"] is True
    assert [(s["nit"], s["participacion"]) for s in r["socios"]] == [("901647575", "10"), ("901267026", "90")]
    assert [c["id"] for c in r["en_ejecucion"]] == ["CO1.PCCNTR.7174033"]
    assert r["en_ejecucion"][0]["via"] == "socio_consorcio"
    assert [c["id"] for c in r["contraste"]["omitidos"]] == ["CO1.PCCNTR.7174033"]


def test_nombre_del_consorcio_no_se_muestra_como_diccionario():
    r = investigar("CONSORCIO VIAS DEL HUILA 2026", cliente=_cliente_huila)
    assert r["nombre"] == "CONSORCIO VIAS DEL HUILA 2026"
