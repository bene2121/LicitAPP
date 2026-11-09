from m1_ingestor.campos import fila_proceso_s2
from m1_ingestor.entidades import ENTIDADES, es_entidad, where_entidad


def test_nit_y_canal():
    assert ENTIDADES["ECOPETROL"]["nit"] == "899999068"
    assert ENTIDADES["FINDETER"]["nit"] == "800096329"
    assert "Ariba" in ENTIDADES["ECOPETROL"]["canal_oferta"]
    assert "invitacionesaofertar@findeter.gov.co" in ENTIDADES["FINDETER"]["canal_oferta"]


def test_where_usa_nit_real():
    where = where_entidad("899999068")
    assert "nit_entidad='899999068'" in where
    assert "unspsc" not in where
    assert "estado_de_apertura_del_proceso='Abierto'" in where


def test_reconoce_nombre_largo_de_secop():
    assert es_entidad({"entidad": "EMPRESA COLOMBIANA DE PETROLEOS"}, "ECOPETROL")
    assert es_entidad({"nit_entidad": "800096329", "entidad": "OTRA"}, "FINDETER")
    assert not es_entidad({"entidad": "INSTITUCION EDUCATIVA ECOPETROL"}, "ECOPETROL")


def test_fila_guarda_canal():
    fila = fila_proceso_s2(
        {
            "id_del_portafolio": "CO1.BDOS.1",
            "entidad": "EMPRESA COLOMBIANA DE PETROLEOS",
            "nit_entidad": "899999068",
            "nombre_del_procedimiento": "Suministro",
            "fase": "Presentación de oferta",
            "precio_base": "10000000",
            "codigo_principal_de_categoria": "V1.15101500",
            "departamento_entidad": "Santander",
        },
        "2026-11-09T00:00:00Z",
        canal_oferta=ENTIDADES["ECOPETROL"]["canal_oferta"],
    )
    assert fila["nit_entidad"] == "899999068"
    assert fila["unspsc"] == "15101500"
    assert "Ariba" in fila["canal_oferta"]
