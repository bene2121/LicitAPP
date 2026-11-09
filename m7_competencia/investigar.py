"""Contratos públicos de un competidor y, si es consorcio, de sus socios.

Compara los contratos en ejecución que publica SECOP II con la lista que
el competidor declaró en la oferta. No inventa contratos ni entra a portales privados.
"""
from __future__ import annotations

import json
from datetime import date
import urllib.parse
import urllib.request

from m1_ingestor.campos import fold, soql_like, soql_literal

API_CONTRATOS = "https://www.datos.gov.co/resource/jbjy-vk9h.json"
API_PLURALES = "https://www.datos.gov.co/resource/ceth-n4bn.json"
LIMITE_CONTRATOS = 25
LIMITE_SOCIOS = 12
LIMITE_GRUPOS = 150
LIMITE_GRUPOS_SOCIOS = 15


def investigar(consulta: str, declarados: list[str] | None = None, cliente=None) -> dict:
    """Contratos en ejecución del competidor, sus consorcios y sus socios.

    Los consorcios se enlazan por el código de grupo de SECOP II
    (`codigo_grupo` = `codigo_proveedor` del contrato), no por el nombre:
    hay muchos consorcios homónimos y el nombre solo confunde.
    """
    texto = " ".join(str(consulta or "").split())[:200]
    if len(texto) < 3:
        raise ValueError("Escribe un NIT, el nombre de la empresa o el del consorcio.")
    cliente = cliente or _cliente_publico
    nits = _variantes_nit(texto)
    nombre = "" if nits else texto

    if nits:
        propios = _contratos(cliente, nits, "")
        grupos = _grupos(cliente, nits, "", propios)
    else:
        # Por nombre: primero el consorcio (rápido); la búsqueda por nombre en
        # contratos es lenta y solo se usa si no es un consorcio registrado.
        grupos = _grupos(cliente, [], nombre, [])
        propios = [] if any(g["codigo"] for g in grupos) else _contratos(cliente, [], nombre)
    codigos = [g["codigo"] for g in grupos if g["codigo"]]
    es_consorcio = bool(nombre and grupos) or any(c.get("es_grupo") for c in propios)

    contratos = []
    vistos = set()
    for contrato in propios:
        # Con nombre de consorcio, un contrato de un homónimo (otro código) no es del competidor.
        if nombre and codigos and contrato.get("codigo") and contrato["codigo"] not in codigos:
            continue
        contratos.append(contrato)
        vistos.add(contrato["id"])
    for contrato in _contratos_de_grupos(cliente, codigos):
        if contrato["id"] not in vistos:
            nombre_grupo = next((g["nombre"] for g in grupos if g["codigo"] == contrato.get("codigo")), "")
            contrato["titular"] = nombre_grupo or contrato["proveedor"]
            contrato["via"] = "consorcio"
            contratos.append(contrato)
            vistos.add(contrato["id"])

    if es_consorcio:
        socios = _socios_de_grupos(cliente, grupos)
    else:
        con_contrato = {c.get("codigo") for c in contratos}
        relevantes = [g for g in grupos if g["codigo"] in con_contrato] or grupos[:LIMITE_GRUPOS_SOCIOS]
        socios = _socios_de_grupos(cliente, relevantes[:LIMITE_GRUPOS_SOCIOS])
    consultado = set(nits)
    if es_consorcio:
        # Solo cuando se investiga el consorcio: los contratos propios de cada socio
        # cuentan para su capacidad residual.
        docs = {c.get("documento", "") for c in contratos}
        for socio in socios[:LIMITE_SOCIOS]:
            if not socio["nit"] or socio["nit"] in docs or socio["nit"] in consultado:
                continue
            for contrato in _contratos(cliente, [socio["nit"]], ""):
                if contrato["id"] not in vistos:
                    contrato["titular"] = socio["nombre"] or socio["nit"]
                    contrato["via"] = "socio"
                    contratos.append(contrato)
                    vistos.add(contrato["id"])
            docs.add(socio["nit"])
        # Contratos que cada socio tiene por medio de OTROS consorcios.
        nits_socios = [x["nit"] for x in socios if x["nit"]]
        otros_grupos = [g for g in _grupos(cliente, nits_socios, "", []) if g["codigo"] not in codigos]
        nombres_grupo = {g["codigo"]: g["nombre"] for g in otros_grupos}
        for contrato in _contratos_de_grupos(cliente, list(nombres_grupo)):
            if contrato["id"] not in vistos:
                contrato["titular"] = nombres_grupo.get(contrato.get("codigo")) or contrato["proveedor"]
                contrato["via"] = "socio_consorcio"
                contratos.append(contrato)
                vistos.add(contrato["id"])
    else:
        socios = [s for s in socios if s["nit"] not in consultado]

    en_ejecucion = [c for c in contratos if c["en_ejecucion"]]
    otros = [c for c in contratos if not c["en_ejecucion"]]
    contraste = contrastar(en_ejecucion, declarados or [])
    nombre_hallado = _nombre_principal(propios, grupos if es_consorcio else [], texto)
    for grupo in grupos:
        grupo["en_ejecucion"] = sum(1 for c in en_ejecucion if c.get("codigo") == grupo["codigo"])
    return {
        "consulta": texto,
        "nombre": nombre_hallado,
        "nits": nits,
        "es_plural": es_consorcio or bool(socios),
        "consorcios": grupos,
        "socios": socios,
        "en_ejecucion": en_ejecucion,
        "otros": otros[:LIMITE_CONTRATOS],
        "contraste": contraste,
        "nota": (
            "Lista tomada de SECOP II. Un contrato en ejecución que no aparece "
            "en la declaración de la oferta es uno que el competidor dejó por fuera."
        ),
    }


def contrastar(en_ejecucion: list[dict], declarados: list[str]) -> dict:
    lineas = [linea.strip() for linea in declarados if linea and linea.strip()]
    if not lineas:
        return {"declarados": 0, "cubiertos": [], "omitidos": [], "sin_respaldo": []}
    cubiertos = []
    omitidos = []
    for contrato in en_ejecucion:
        if _declarado(contrato, lineas):
            cubiertos.append(contrato)
        else:
            omitidos.append(contrato)
    sin_respaldo = [linea for linea in lineas if not _linea_encontrada(linea, en_ejecucion)]
    return {
        "declarados": len(lineas),
        "cubiertos": cubiertos,
        "omitidos": omitidos,
        "sin_respaldo": sin_respaldo,
    }


def _contratos(cliente, nits: list[str], nombre: str) -> list[dict]:
    if nits:
        where = " OR ".join(f"documento_proveedor='{soql_literal(nit)}'" for nit in nits[:4])
    else:
        where = f"upper(proveedor_adjudicado) like '%{_like(nombre)}%'"
    filas = cliente(
        API_CONTRATOS,
        {
            "$select": (
                "id_contrato,proveedor_adjudicado,documento_proveedor,codigo_proveedor,es_grupo,"
                "estado_contrato,objeto_del_contrato,valor_del_contrato,"
                "fecha_de_inicio_del_contrato,fecha_de_fin_del_contrato,nombre_entidad"
            ),
            "$where": where,
            "$order": "fecha_de_inicio_del_contrato DESC",
            "$limit": str(LIMITE_CONTRATOS),
        },
    )
    return [_contrato(fila) for fila in filas]


def _grupos(cliente, nits: list[str], nombre: str, contratos: list[dict]) -> list[dict]:
    partes = []
    if nits:
        lista = ",".join(f"'{soql_literal(n)}'" for n in nits[:12])
        partes.append(f"nit_participante in ({lista})")
        partes.append(f"nit_grupo in ({lista})")
    if nombre:
        like = _like(nombre)
        partes.append(f"upper(nombre_grupo) like '%{like}%'")
    codigos_contrato = [c["codigo"] for c in contratos if c.get("es_grupo") and c.get("codigo")]
    for codigo in codigos_contrato[:4]:
        partes.append(f"codigo_grupo='{soql_literal(codigo)}'")
    if not partes:
        return []
    filas = cliente(
        API_PLURALES,
        {
            "$select": "nombre_grupo,codigo_grupo,nit_participante,participacion,es_lider_del_grupo,fecha_creaci_n_grupo",
            "$where": " OR ".join(partes[:10]),
            "$order": "fecha_creaci_n_grupo DESC",
            "$limit": "600",
        },
    )
    grupos = {}
    for fila in filas:
        nombre_g = str(fila.get("nombre_grupo") or "").strip()
        codigo = str(fila.get("codigo_grupo") or "").strip()
        if not nombre_g or nombre_g.lower() == "no definido":
            continue
        clave = codigo or nombre_g.upper()
        grupo = grupos.setdefault(clave, {
            "nombre": nombre_g, "codigo": codigo, "participacion": "", "lider": False,
            "creado": str(fila.get("fecha_creaci_n_grupo") or "")[:10],
        })
        # La participación solo se reporta cuando se investiga a una sola empresa.
        if len(nits) <= 2 and _solo_digitos(fila.get("nit_participante")) in nits:
            grupo["participacion"] = str(fila.get("participacion") or "").split(".")[0]
            grupo["lider"] = str(fila.get("es_lider_del_grupo") or "").lower() in {"verdadero", "si", "true"}
    return list(grupos.values())[:LIMITE_GRUPOS]


def _contratos_de_grupos(cliente, codigos: list[str]) -> list[dict]:
    if not codigos:
        return []
    lista = ",".join(f"'{soql_literal(c)}'" for c in codigos[:LIMITE_GRUPOS])
    filas = cliente(
        API_CONTRATOS,
        {
            "$select": (
                "id_contrato,proveedor_adjudicado,documento_proveedor,codigo_proveedor,es_grupo,"
                "estado_contrato,objeto_del_contrato,valor_del_contrato,"
                "fecha_de_inicio_del_contrato,fecha_de_fin_del_contrato,nombre_entidad"
            ),
            "$where": f"codigo_proveedor in ({lista})",
            "$order": "fecha_de_inicio_del_contrato DESC",
            "$limit": "300",
        },
    )
    return [_contrato(fila) for fila in filas]


def _socios_de_grupos(cliente, grupos: list[dict]) -> list[dict]:
    if not grupos:
        return []
    codigos = [g["codigo"] for g in grupos if g.get("codigo")]
    if codigos:
        where = "codigo_grupo in (" + ",".join(f"'{soql_literal(c)}'" for c in codigos) + ")"
    else:
        where = " OR ".join(f"upper(nombre_grupo)='{soql_literal(g['nombre'].upper())}'" for g in grupos)
    filas = cliente(
        API_PLURALES,
        {
            "$select": (
                "nombre_grupo,codigo_grupo,nombre_participante,nit_participante,"
                "participacion,es_lider_del_grupo,tipo_empresa_grupo"
            ),
            "$where": where,
            "$limit": "200",
        },
    )
    socios = []
    vistos = set()
    for fila in filas:
        nit = _solo_digitos(fila.get("nit_participante"))
        nombre = str(fila.get("nombre_participante") or "").strip()
        grupo = str(fila.get("nombre_grupo") or "").strip()
        clave = (grupo, nit or nombre)
        if not nit and not nombre or clave in vistos or nombre.lower() == "no definido":
            continue
        vistos.add(clave)
        socios.append({
            "grupo": grupo,
            "codigo_grupo": str(fila.get("codigo_grupo") or ""),
            "nombre": nombre,
            "nit": nit,
            "participacion": str(fila.get("participacion") or "").split(".")[0],
            "lider": str(fila.get("es_lider_del_grupo") or "").lower() in {"verdadero", "si", "true"},
            "tipo_grupo": str(fila.get("tipo_empresa_grupo") or ""),
        })
    return socios


def _contrato(fila: dict) -> dict:
    estado = str(fila.get("estado_contrato") or "")
    return {
        "id": str(fila.get("id_contrato") or ""),
        "codigo": str(fila.get("codigo_proveedor") or ""),
        "via": "propio",
        "proveedor": str(fila.get("proveedor_adjudicado") or ""),
        "documento": _solo_digitos(fila.get("documento_proveedor")),
        "es_grupo": str(fila.get("es_grupo") or "").lower() in {"si", "true", "verdadero"},
        "estado": estado,
        "en_ejecucion": _en_ejecucion(estado, fila.get("fecha_de_fin_del_contrato")),
        "objeto": str(fila.get("objeto_del_contrato") or ""),
        "valor": _numero(fila.get("valor_del_contrato")),
        "inicio": str(fila.get("fecha_de_inicio_del_contrato") or "")[:10],
        "fin": str(fila.get("fecha_de_fin_del_contrato") or "")[:10],
        "entidad": str(fila.get("nombre_entidad") or ""),
        "titular": str(fila.get("proveedor_adjudicado") or ""),
    }


_ESTADOS_VIGENTES = {"MODIFICADO", "ACTIVO", "PRORROGADO", "SUSPENDIDO"}


def _en_ejecucion(estado: str, fin) -> bool:
    """En ejecución, o modificado/activo con fecha de fin que no ha pasado."""
    estado_u = fold(estado).upper()
    if "EJECUC" in estado_u:
        return True
    if estado_u in _ESTADOS_VIGENTES:
        return str(fin or "")[:10] >= date.today().isoformat()
    return False


def _declarado(contrato: dict, lineas: list[str]) -> bool:
    identificador = contrato["id"].upper()
    objeto = fold(contrato["objeto"]).upper()
    entidad = fold(contrato["entidad"]).upper()
    for linea in lineas:
        token = fold(linea).upper()
        if len(token) < 6:
            continue
        if token in identificador or identificador and identificador in token:
            return True
        if token in objeto or token in entidad:
            return True
    return False


def _linea_encontrada(linea: str, contratos: list[dict]) -> bool:
    return any(_declarado(contrato, [linea]) for contrato in contratos)


def _nombre_principal(contratos, grupos, consulta) -> str:
    if grupos:
        return grupos[0]
    for contrato in contratos:
        if contrato.get("proveedor"):
            return contrato["proveedor"]
    return consulta


def _variantes_nit(texto: str) -> list[str]:
    if any(c.isalpha() for c in texto):
        return []
    digitos = _solo_digitos(texto)
    if len(digitos) < 6:
        return []
    variantes = [digitos]
    if "-" in texto:
        base = _solo_digitos(texto.split("-", 1)[0])
        if len(base) >= 6 and base not in variantes:
            variantes.append(base)
    return variantes


def _solo_digitos(valor) -> str:
    return "".join(c for c in str(valor or "") if c.isdigit())


def _like(texto: str) -> str:
    return soql_like(texto)


def _numero(valor) -> float:
    try:
        return float(str(valor or "0").replace(",", ""))
    except (TypeError, ValueError):
        return 0.0


def _cliente_publico(url: str, params: dict) -> list:
    from seguridad import exigir_https, leer_limitado
    consulta = urllib.parse.urlencode(params)
    try:
        exigir_https(url, permitir_local=False)  # solo datos.gov.co por https (verifica certificado)
        req = urllib.request.Request(
            f"{url}?{consulta}",
            headers={"User-Agent": "LicitApp/1.0"},
        )
        with urllib.request.urlopen(req, timeout=45) as respuesta:  # nosec B310 - https validado arriba
            data = json.loads(leer_limitado(respuesta).decode())
    except Exception:
        return []
    return data if isinstance(data, list) else []
