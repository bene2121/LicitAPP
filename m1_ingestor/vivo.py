"""Consulta en vivo del Explorador: los filtros viajan dentro del pedido a SECOP II."""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone

from m1_ingestor.campos import FASES_ABIERTAS, fila_proceso_s2, soql_literal
from m1_ingestor.entidades import where_entidad
from m1_ingestor.secop_client import SecopClient

MAX_VIVO = 400
CACHE_SEGUNDOS = 180
_VOCALES = set("AEIOU")


def comodin_vocales(texto: str) -> str:
    """Atlántico queda _TL_NT_C_ para que el like ignore las tildes."""
    from m1_ingestor.campos import fold
    plano = fold(texto).upper()
    return "".join("_" if caracter in _VOCALES else caracter for caracter in plano)


def where_vivo(
    departamentos: list[str] | None = None,
    unspsc: list[str] | None = None,
    modalidades: list[str] | None = None,
) -> str:
    fases = ",".join(f"'{soql_literal(fase)}'" for fase in FASES_ABIERTAS)
    partes = [
        "estado_de_apertura_del_proceso='Abierto'",
        "precio_base > 0",
        f"fase in({fases})",
    ]
    deptos = _likes("departamento_entidad", departamentos or [])
    if deptos:
        partes.append(deptos)
    codigos = []
    for codigo in unspsc or []:
        digitos = "".join(c for c in str(codigo) if c.isdigit())
        if len(digitos) >= 2:
            codigos.append(f"codigo_principal_de_categoria like '%{digitos}%'")
    if codigos:
        partes.append("(" + " OR ".join(dict.fromkeys(codigos)) + ")")
    modalidades_like = _likes("modalidad_de_contratacion", modalidades or [])
    if modalidades_like:
        partes.append(modalidades_like)
    return " AND ".join(partes)


def consultar_vivo(
    departamentos: list[str] | None = None,
    unspsc: list[str] | None = None,
    modalidades: list[str] | None = None,
    max_records: int = MAX_VIVO,
    cliente=None,
    cache_dir: str | None = None,
) -> list[dict]:
    """Pide a SECOP II solo lo que cabe en los filtros. Tope 400."""
    return _consultar(
        where_vivo(departamentos, unspsc, modalidades),
        max_records,
        cliente=cliente,
        cache_dir=cache_dir,
    )


def consultar_entidad(nit: str, max_records: int = MAX_VIVO, cliente=None, cache_dir: str | None = None) -> list[dict]:
    return _consultar(where_entidad(nit), max_records, cliente=cliente, cache_dir=cache_dir)


def _consultar(where: str, max_records: int, cliente=None, cache_dir: str | None = None) -> list[dict]:
    tope = min(max_records, MAX_VIVO)
    clave = f"{tope}|{where}"
    guardado = _leer_cache(clave, cache_dir)
    if guardado is not None:
        return guardado
    cliente = cliente or SecopClient()
    registros = cliente.get_procesos_s2(
        filters={
            "$where": where,
            "$order": "fecha_de_ultima_publicaci DESC",
        },
        max_records=tope,
    )
    ahora = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    filas = []
    for registro in registros:
        fila = fila_proceso_s2(registro, ahora)
        if fila:
            filas.append(fila)
    _guardar_cache(clave, filas, cache_dir)
    return filas


def _directorio_cache(cache_dir: str | None) -> str:
    destino = cache_dir or os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "data",
        "cache_secop",
    )
    os.makedirs(destino, exist_ok=True)
    return destino


def _ruta_cache(clave: str, cache_dir: str | None) -> str:
    nombre = hashlib.sha256(clave.encode("utf-8")).hexdigest() + ".json"
    return os.path.join(_directorio_cache(cache_dir), nombre)


def _leer_cache(clave: str, cache_dir: str | None) -> list[dict] | None:
    ruta = _ruta_cache(clave, cache_dir)
    if not os.path.exists(ruta):
        return None
    try:
        with open(ruta, encoding="utf-8") as archivo:
            dato = json.load(archivo)
        edad = datetime.now(timezone.utc).timestamp() - float(dato["guardado"])
        if edad > CACHE_SEGUNDOS:
            return None
        filas = dato.get("filas")
        return filas if isinstance(filas, list) else None
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        return None


def _guardar_cache(clave: str, filas: list[dict], cache_dir: str | None) -> None:
    ruta = _ruta_cache(clave, cache_dir)
    with open(ruta, "w", encoding="utf-8") as archivo:
        json.dump(
            {"guardado": datetime.now(timezone.utc).timestamp(), "filas": filas},
            archivo,
        )


def _likes(columna: str, valores: list[str]) -> str:
    partes = []
    for valor in valores:
        if not str(valor).strip():
            continue
        patron = soql_literal(comodin_vocales(valor)).replace("%", "")
        partes.append(f"upper({columna}) like '%{patron}%'")
    if not partes:
        return ""
    return "(" + " OR ".join(partes) + ")"
