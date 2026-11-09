"""Contratos públicos de un competidor y, si es consorcio, de sus socios.

Compara los contratos en ejecución que publica SECOP II con la lista que
el competidor declaró en la oferta. No inventa contratos ni entra a portales privados.
"""
from __future__ import annotations

import json
import urllib.parse
import urllib.request

from m1_ingestor.campos import fold, soql_literal

API_CONTRATOS = "https://www.datos.gov.co/resource/jbjy-vk9h.json"
API_PLURALES = "https://www.datos.gov.co/resource/ceth-n4bn.json"
LIMITE_CONTRATOS = 25
LIMITE_SOCIOS = 12


def investigar(consulta: str, declarados: list[str] | None = None, cliente=None) -> dict:
    texto = " ".join(str(consulta or "").split())
    if len(texto) < 3:
        raise ValueError("Escribe un NIT, el nombre de la empresa o el del consorcio.")
    cliente = cliente or _cliente_publico
    nits = _variantes_nit(texto)
    nombre = "" if nits else texto

    contratos = _contratos(cliente, nits, nombre)
    grupos = _grupos(cliente, nits, nombre, contratos)
    socios = _socios_de_grupos(cliente, grupos)
    vistos = {c.get("documento", "") for c in contratos}
    for socio in socios:
        if not socio["nit"] or socio["nit"] in vistos or socio["nit"] in nits:
            continue
        extra = _contratos(cliente, [socio["nit"]], "")
        for contrato in extra:
            contrato["titular"] = socio["nombre"] or socio["nit"]
        contratos.extend(extra)
        vistos.add(socio["nit"])

    en_ejecucion = [c for c in contratos if c["en_ejecucion"]]
    otros = [c for c in contratos if not c["en_ejecucion"]]
    contraste = contrastar(en_ejecucion, declarados or [])
    nombre_hallado = _nombre_principal(contratos, grupos, texto)
    return {
        "consulta": texto,
        "nombre": nombre_hallado,
        "nits": nits,
        "es_plural": bool(socios) or any(c.get("es_grupo") for c in contratos),
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
                "id_contrato,proveedor_adjudicado,documento_proveedor,es_grupo,"
                "estado_contrato,objeto_del_contrato,valor_del_contrato,"
                "fecha_de_inicio_del_contrato,fecha_de_fin_del_contrato,nombre_entidad"
            ),
            "$where": where,
            "$order": "fecha_de_inicio_del_contrato DESC",
            "$limit": str(LIMITE_CONTRATOS),
        },
    )
    return [_contrato(fila) for fila in filas]


def _grupos(cliente, nits: list[str], nombre: str, contratos: list[dict]) -> list[str]:
    partes = []
    for nit in nits[:4]:
        partes.append(f"nit_participante='{soql_literal(nit)}'")
        partes.append(f"nit_grupo='{soql_literal(nit)}'")
    if nombre:
        like = _like(nombre)
        partes.append(f"upper(nombre_grupo) like '%{like}%'")
        partes.append(f"upper(nombre_participante) like '%{like}%'")
    for contrato in contratos:
        if contrato.get("es_grupo") and contrato.get("proveedor"):
            partes.append(f"upper(nombre_grupo)='{soql_literal(contrato['proveedor'].upper())}'")
    if not partes:
        return []
    filas = cliente(
        API_PLURALES,
        {
            "$select": "nombre_grupo",
            "$where": " OR ".join(partes[:8]),
            "$limit": "30",
        },
    )
    nombres = []
    for fila in filas:
        grupo = str(fila.get("nombre_grupo") or "").strip()
        if grupo and grupo.lower() != "no definido" and grupo not in nombres:
            nombres.append(grupo)
    return nombres[:5]


def _socios_de_grupos(cliente, grupos: list[str]) -> list[dict]:
    socios = []
    vistos = set()
    for grupo in grupos:
        filas = cliente(
            API_PLURALES,
            {
                "$select": (
                    "nombre_grupo,nombre_participante,nit_participante,"
                    "participacion,es_lider_del_grupo,tipo_empresa_grupo"
                ),
                "$where": f"upper(nombre_grupo)='{soql_literal(grupo.upper())}'",
                "$limit": str(LIMITE_SOCIOS),
            },
        )
        for fila in filas:
            nit = _solo_digitos(fila.get("nit_participante"))
            nombre = str(fila.get("nombre_participante") or "").strip()
            clave = nit or nombre
            if not clave or clave in vistos or nombre.lower() == "no definido":
                continue
            vistos.add(clave)
            socios.append({
                "grupo": grupo,
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
        "proveedor": str(fila.get("proveedor_adjudicado") or ""),
        "documento": _solo_digitos(fila.get("documento_proveedor")),
        "es_grupo": str(fila.get("es_grupo") or "").lower() in {"si", "true", "verdadero"},
        "estado": estado,
        "en_ejecucion": "EJECUC" in fold(estado).upper(),
        "objeto": str(fila.get("objeto_del_contrato") or ""),
        "valor": _numero(fila.get("valor_del_contrato")),
        "inicio": str(fila.get("fecha_de_inicio_del_contrato") or "")[:10],
        "fin": str(fila.get("fecha_de_fin_del_contrato") or "")[:10],
        "entidad": str(fila.get("nombre_entidad") or ""),
        "titular": str(fila.get("proveedor_adjudicado") or ""),
    }


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
    limpio = soql_literal(fold(texto).upper())
    return limpio.replace("%", "").replace("_", " ")


def _numero(valor) -> float:
    try:
        return float(str(valor or "0").replace(",", ""))
    except (TypeError, ValueError):
        return 0.0


def _cliente_publico(url: str, params: dict) -> list:
    consulta = urllib.parse.urlencode(params)
    req = urllib.request.Request(
        f"{url}?{consulta}",
        headers={"User-Agent": "LicitApp/1.0"},
    )
    try:
        with urllib.request.urlopen(req, timeout=25) as respuesta:
            data = json.loads(respuesta.read().decode())
    except Exception:
        return []
    return data if isinstance(data, list) else []
