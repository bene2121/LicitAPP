"""Guía de precio a partir de ofertas anteriores reales de los competidores.

Solo usa pares oferta/presupuesto publicados en SECOP. No completa huecos con cifras inventadas.
"""
from __future__ import annotations

from m7_competencia.investigar import API_PLURALES, _cliente_publico, _like, _numero, _variantes_nit
from m1_ingestor.campos import soql_literal

API_OFERTAS = "https://www.datos.gov.co/resource/wi7w-2nvm.json"
API_PROCESOS = "https://www.datos.gov.co/resource/p6dx-8zbt.json"
LIMITE_OFERTAS = 20


def estimar_ofertas(consultas: list[str], presupuesto: float, cliente=None) -> dict:
    if presupuesto <= 0:
        raise ValueError("El presupuesto oficial debe ser mayor que cero.")
    nombres = [c.strip()[:200] for c in consultas if c and c.strip()]
    if not nombres:
        raise ValueError("Escribe al menos un NIT o nombre de competidor.")
    cliente = cliente or _cliente_publico
    competidores = []
    precios = []
    for consulta in nombres[:8]:
        ficha = _competidor(cliente, consulta, presupuesto)
        competidores.append(ficha)
        if ficha["precio_guia"] > 0:
            precios.append(ficha["precio_guia"])
    return {"competidores": competidores, "precios_guia": precios}


def _competidor(cliente, consulta: str, presupuesto: float) -> dict:
    nits = _variantes_nit(consulta)
    if nits:
        where = " OR ".join(f"nit_del_proveedor='{soql_literal(nit)}'" for nit in nits[:3])
    else:
        where = f"upper(nombre_proveedor) like '%{_like(consulta)}%'"
    ofertas = _ofertas(cliente, where)
    via = "propia"
    if nits and not ofertas:
        # Las ofertas de un consorcio quedan a nombre del consorcio, sin el NIT del socio.
        grupos = _consorcios_de(cliente, nits)
        if grupos:
            lista = ",".join(f"'{soql_literal(g)}'" for g in grupos[:60])
            ofertas = _ofertas(cliente, f"nombre_proveedor in ({lista})")
            via = "consorcios"
    presupuestos = _presupuestos(cliente, ofertas)
    ratios = []
    for oferta in ofertas:
        proceso = str(oferta.get("id_del_proceso_de_compra") or "")
        base = presupuestos.get(proceso)
        valor = _numero(oferta.get("valor_de_la_oferta"))
        if base and base > 0 and valor > 0:
            ratios.append((base - valor) / base)
    nombre = ""
    for oferta in ofertas:
        nombre = str(oferta.get("nombre_proveedor") or "")
        if nombre:
            break
    guia, nota = _guia(ratios, presupuesto)
    return {
        "consulta": consulta,
        "nombre": nombre or consulta,
        "ofertas": len(ofertas),
        "con_presupuesto": len(ratios),
        "descuento_mediano": _mediana(ratios),
        "descuento_promedio": (sum(ratios) / len(ratios)) if ratios else None,
        "descuento_bajo": min(ratios) if ratios else None,
        "descuento_alto": max(ratios) if ratios else None,
        "precio_guia": guia,
        "nota": nota if via == "propia" else nota + " Ofertas tomadas de los consorcios donde participa.",
        "via": via,
    }


def _ofertas(cliente, where: str) -> list[dict]:
    filas = cliente(
        API_OFERTAS,
        {
            "$select": "identificador_de_la_oferta,id_del_proceso_de_compra,valor_de_la_oferta,nombre_proveedor,nit_del_proveedor",
            "$where": where,
            "$order": "fecha_de_registro DESC",
            "$limit": str(LIMITE_OFERTAS * 4),
        },
    )
    # SECOP repite la misma oferta una vez por código de entidad.
    unicas = {}
    for fila in filas:
        clave = fila.get("identificador_de_la_oferta") or (
            fila.get("id_del_proceso_de_compra"), fila.get("nombre_proveedor"), fila.get("valor_de_la_oferta"))
        unicas.setdefault(clave, fila)
    return list(unicas.values())[:LIMITE_OFERTAS]


def _consorcios_de(cliente, nits: list[str]) -> list[str]:
    lista = ",".join(f"'{soql_literal(n)}'" for n in nits[:3])
    filas = cliente(
        API_PLURALES,
        {"$select": "nombre_grupo", "$where": f"nit_participante in ({lista})",
         "$order": "fecha_creaci_n_grupo DESC", "$limit": "300"},
    )
    nombres = []
    for fila in filas:
        nombre = str(fila.get("nombre_grupo") or "").strip()
        if nombre and nombre.lower() != "no definido" and nombre not in nombres:
            nombres.append(nombre)
    return nombres


def _presupuestos(cliente, ofertas: list[dict]) -> dict:
    ids = []
    for oferta in ofertas:
        proceso = str(oferta.get("id_del_proceso_de_compra") or "").strip()
        if proceso and proceso not in ids:
            ids.append(proceso)
    if not ids:
        return {}
    lista = ",".join(f"'{soql_literal(proceso)}'" for proceso in ids[:20])
    filas = cliente(
        API_PROCESOS,
        {
            "$select": "id_del_portafolio,precio_base",
            "$where": f"id_del_portafolio in({lista})",
            "$limit": "40",
        },
    )
    return {
        str(fila.get("id_del_portafolio") or ""): _numero(fila.get("precio_base"))
        for fila in filas
    }


def _guia(ratios: list[float], presupuesto: float) -> tuple[float, str]:
    if not ratios:
        return 0.0, "No hay ofertas anteriores con presupuesto oficial para armar una guía."
    mediana = _mediana(ratios)
    # Sin recortes artificiales: la guía es lo que muestran las ofertas reales,
    # solo acotada al rango posible (no por encima del presupuesto, no a precio cero).
    guia = min(max(presupuesto * (1 - mediana), presupuesto * 0.05), presupuesto)
    extra = ""
    if abs(mediana) < 0.001:
        extra = (" Este competidor suele ofertar el 100 % del presupuesto, típico de concursos de "
                 "méritos donde el precio no puntúa.")
    if len(ratios) == 1:
        return guia, "Hay una sola oferta anterior con presupuesto. Sirve de referencia, no de mediana." + extra
    return guia, f"Guía con {len(ratios)} ofertas anteriores que sí tienen presupuesto oficial." + extra


def _mediana(valores: list[float]) -> float:
    if not valores:
        return 0.0
    orden = sorted(valores)
    mitad = len(orden) // 2
    if len(orden) % 2:
        return orden[mitad]
    return (orden[mitad - 1] + orden[mitad]) / 2
