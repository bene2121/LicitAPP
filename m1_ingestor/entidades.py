"""Entidades con canal de oferta distinto al de una licitación estatal común.

Los NIT se contrastaron con datos.gov.co (dataset p6dx-8zbt):
- 899999068 EMPRESA COLOMBIANA DE PETROLEOS
- 800096329 FINANCIERA DE DESARROLLO TERRITORIAL S.A.

Ecopetrol contrata por derecho privado: la invitación se responde en Ariba.
Findeter usa SECOP II solo para publicar; la oferta va por correo.
"""
from m1_ingestor.campos import FASES_ABIERTAS, soql_literal

ENTIDADES = {
    "ECOPETROL": {
        "nit": "899999068",
        "nombre": "Ecopetrol S.A.",
        "alias": ("EMPRESA COLOMBIANA DE PETROLEOS", "ECOPETROL S.A"),
        "canal_oferta": (
            "Invitación privada en SAP Ariba "
            "(https://proveedores.ecopetrol.com.co). "
            "SECOP II publica la actividad contractual; la oferta no se radica ahí."
        ),
    },
    "FINDETER": {
        "nit": "800096329",
        "nombre": "Findeter",
        "alias": ("FINDETER", "FINANCIERA DE DESARROLLO TERRITORIAL"),
        "canal_oferta": (
            "SECOP II es solo publicitario. "
            "Envíe la oferta a invitacionesaofertar@findeter.gov.co, "
            "según el cronograma del proceso."
        ),
    },
}


def where_entidad(nit: str) -> str:
    fases = ",".join(f"'{soql_literal(fase)}'" for fase in FASES_ABIERTAS)
    return (
        f"nit_entidad='{soql_literal(nit)}' "
        "AND estado_de_apertura_del_proceso='Abierto' "
        "AND precio_base > 0 "
        f"AND fase in({fases})"
    )


def es_entidad(registro: dict, codigo: str) -> bool:
    ficha = ENTIDADES[codigo]
    nit = str(registro.get("nit_entidad") or "").strip()
    if nit == ficha["nit"]:
        return True
    entidad = str(registro.get("entidad") or registro.get("nombre_entidad") or "").upper()
    return any(alias in entidad for alias in ficha["alias"])
