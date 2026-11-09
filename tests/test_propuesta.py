import pytest

from m6_propuesta.armar import armar_propuesta

PROCESO = {
    "id_del_proceso": "CO1.BDOS.10184054",
    "entidad": "EMPRESA COLOMBIANA DE PETROLEOS",
    "nit_entidad": "899999068",
    "titulo": "Suministro de lubricantes",
    "presupuesto_oficial": 50_000_000,
    "estado": "Presentación de oferta",
}

OFERTA = {
    "precio": 46_000_000,
    "formula": "MV",
    "nombre_formula": "Menor Valor",
    "pct_mejora": 8,
    "presupuesto_oficial": 50_000_000,
}

PERFIL = {
    "empresa": "Obras del Río SAS",
    "nit": "900123456",
    "email": "ofertas@obras.example",
    "documentos": {
        "rup_estado": "✅ Vigente",
        "cc_estado": "✅ Vigente",
        "cedula_estado": "✅ Vigente",
        "rut_estado": "✅ Vigente",
        "ef_estado": "✅ Vigente",
    },
}


def test_ecopetrol_queda_lista_y_apunta_a_ariba():
    paquete = armar_propuesta(PROCESO, PERFIL, OFERTA)
    assert paquete["lista_para_presentar"] is True
    assert paquete["canal"]["tipo"] == "ariba"
    assert paquete["canal"]["destino"] == "https://proveedores.ecopetrol.com.co"
    assert "46.000.000" in paquete["carta"]
    assert paquete["correo"] is None
    assert paquete["faltantes"] == []


def test_findeter_arma_el_correo_de_presentacion():
    proceso = {
        "id": "CO1.BDOS.10195093",
        "entidad": "FINANCIERA DE DESARROLLO TERRITORIAL S.A.",
        "nit_entidad": "800096329",
        "objeto": "Mantenimiento de sedes",
        "presupuesto_oficial": 20_000_000,
    }
    paquete = armar_propuesta(proceso, PERFIL, {"precio": 18_000_000, "formula": "M"})
    assert paquete["canal"]["tipo"] == "findeter"
    assert paquete["correo"]["para"] == "invitacionesaofertar@findeter.gov.co"
    assert "CO1.BDOS.10195093" in paquete["correo"]["asunto"]
    assert paquete["correo"]["cuerpo"] == paquete["carta"]


def test_sin_habilitantes_no_esta_lista():
    paquete = armar_propuesta(
        {"id": "CO1.BDOS.1", "entidad": "ALCALDIA", "objeto": "Vía", "presupuesto_oficial": 10_000_000},
        {"empresa": "Obras del Río SAS", "nit": "900123456", "documentos": {}},
        {"precio": 9_000_000},
    )
    assert paquete["canal"]["tipo"] == "secop"
    assert paquete["lista_para_presentar"] is False
    assert "RUP" in paquete["faltantes"]
    assert "Estados financieros" in paquete["faltantes"]


def test_sin_precio_no_arma():
    with pytest.raises(ValueError):
        armar_propuesta(PROCESO, PERFIL, {"precio": 0})
