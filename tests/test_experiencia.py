from m8_experiencia.historial import agregar_participacion, listar_participaciones
from m8_experiencia.ranking import rankear

PERFIL = {"empresa": "Vías del Huila"}


def test_guarda_resultado_y_reemplaza_el_mismo_proceso():
    agregar_participacion(PERFIL, {
        "id": "CO1.BDOS.1",
        "objeto": "Vía terciaria",
        "unspsc": "72101500",
        "departamento": "Huila",
        "presupuesto": 1_000_000_000,
        "resultado": "adjudicado",
    })
    agregar_participacion(PERFIL, {
        "id": "CO1.BDOS.1",
        "objeto": "Vía terciaria",
        "unspsc": "72101500",
        "departamento": "Huila",
        "presupuesto": 1_000_000_000,
        "resultado": "no adjudicado",
    })
    historial = listar_participaciones(PERFIL)
    assert len(historial) == 1
    assert historial[0]["resultado"] == "no_adjudicado"
    assert historial[0]["departamento"] == "HUILA"


def test_prioriza_mismo_sector_region_y_cuantia():
    perfil = {"participaciones": [{
        "id": "CO1.BDOS.9",
        "unspsc": "72101500",
        "departamento": "HUILA",
        "presupuesto": 1_000_000_000,
        "resultado": "adjudicado",
    }]}
    procesos = [
        {"id": "A", "unspsc": "25101500", "departamento": "ANTIOQUIA", "presupuesto_oficial": 50_000_000, "entidad": "X", "titulo": "Otro"},
        {"id": "B", "unspsc": "72101508", "departamento": "HUILA", "presupuesto_oficial": 1_200_000_000, "entidad": "Gobernación", "titulo": "Pavimento"},
    ]
    orden = rankear(procesos, perfil)
    assert orden[0]["id"] == "B"
    assert orden[0]["afinidad"] == 100
    assert "mismo sector" in orden[0]["razones"]
    assert orden[1]["afinidad"] == 0
