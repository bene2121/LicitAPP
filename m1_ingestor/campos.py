"""Traduccion de los campos reales de datos.gov.co al esquema local.

Nombres comprobados contra p6dx-8zbt (SECOP II) y wi7w-2nvm (ofertas).
El dataset de procesos no trae fecha de cierre.
"""
from __future__ import annotations

import unicodedata

FASES_ABIERTAS = (
    "Presentación de oferta",
    "Fase de ofertas",
    "Manifestación de interés (Menor Cuantía)",
    "Fase de Selección (Presentación de ofertas)",
    "Presentación de observaciones",
)


def fold(texto) -> str:
    base = unicodedata.normalize("NFD", str(texto or ""))
    sin_tilde = "".join(c for c in base if unicodedata.category(c) != "Mn")
    return sin_tilde.strip()


def norm_departamento(texto) -> str:
    plano = fold(texto).upper()
    if "BOGOTA" in plano:
        return "BOGOTA"
    return plano


def unspsc_codigo(texto) -> str:
    bruto = str(texto or "").strip()
    if bruto.upper().startswith("V1."):
        bruto = bruto[3:]
    digitos = "".join(c for c in bruto if c.isdigit())
    return digitos or bruto


def _texto(*valores) -> str:
    for valor in valores:
        limpio = str(valor or "").strip()
        if limpio and limpio.lower() not in {"no definido", "none", "null"}:
            return limpio
    return ""


def _url(valor) -> str:
    if isinstance(valor, dict):
        return str(valor.get("url") or "")
    return str(valor or "")


def soql_literal(valor: str) -> str:
    """Escapa un valor para ponerlo entre comillas simples en SoQL.

    Duplica la comilla simple (única forma de cerrar el literal) y descarta
    caracteres de control (NUL, saltos de línea) que no tienen uso legítimo.
    """
    limpio = "".join(c for c in str(valor) if c == " " or c.isprintable())
    return limpio.replace("'", "''")


def soql_like(valor: str, largo_max: int = 120) -> str:
    """Texto seguro para `like '%...%'`: sin comodines del usuario, sin tildes, en mayúsculas.

    Funciona con nombres que traen comillas o &, por ejemplo `CONSORCIO CG&A2M`
    u `O'BRIEN` (el & no tiene significado dentro del literal y la comilla se duplica).
    """
    plano = fold(valor).upper()[:largo_max]
    return soql_literal(plano).replace("%", "").replace("_", " ")


def soql_numero(valor, defecto: float = 0.0) -> float:
    """Convierte a número finito; nunca deja pasar texto a una comparación numérica."""
    try:
        numero = float(valor)
    except (TypeError, ValueError):
        return defecto
    return numero if numero == numero and numero not in (float("inf"), float("-inf")) else defecto


def where_procesos_s2(
    presupuesto_min: float,
    presupuesto_max: float,
    unspsc_interes: list[str],
    ultimo_sync: str | None = None,
    departamento_where: str | None = None,
) -> str:
    fases = ",".join(f"'{soql_literal(f)}'" for f in FASES_ABIERTAS)
    partes = [
        "estado_de_apertura_del_proceso='Abierto'",
        "precio_base > 0",
        f"precio_base >= {soql_numero(presupuesto_min)} AND precio_base <= {soql_numero(presupuesto_max, 1e15)}",
        f"fase in({fases})",
    ]
    codigos = []
    for codigo in unspsc_interes or []:
        digitos = "".join(c for c in str(codigo) if c.isdigit())
        if len(digitos) >= 2:
            codigos.append(f"codigo_principal_de_categoria like '%{digitos[:2]}%'")
    if codigos:
        partes.append("(" + " OR ".join(dict.fromkeys(codigos)) + ")")
    if ultimo_sync:
        marca = soql_literal(ultimo_sync)
        partes.append(
            f"(fecha_de_ultima_publicaci >= '{marca}' OR fecha_de_ultima_publicaci IS NULL)"
        )
    if departamento_where:
        partes.append(f"({departamento_where})")
    return " AND ".join(partes)


def fila_proceso_s2(registro: dict, fecha_descarga: str, canal_oferta: str = "") -> dict | None:
    proceso_id = _texto(registro.get("id_del_portafolio"), registro.get("id_del_proceso"))
    if not proceso_id:
        return None
    try:
        lotes = int(registro.get("numero_de_lotes") or 0)
    except (TypeError, ValueError):
        lotes = 0
    precio = registro.get("precio_base")
    try:
        precio = float(precio) if precio not in (None, "") else None
    except (TypeError, ValueError):
        precio = None
    return {
        "id_del_proceso": proceso_id,
        "referencia": _texto(registro.get("referencia_del_proceso")),
        "entidad": _texto(registro.get("entidad"), registro.get("nombre_entidad")),
        "titulo": _texto(
            registro.get("nombre_del_procedimiento"),
            registro.get("descripci_n_del_procedimiento"),
        ),
        "modalidad": _texto(registro.get("modalidad_de_contratacion")),
        "estado": _texto(
            registro.get("fase"),
            registro.get("estado_resumen"),
            registro.get("estado_del_procedimiento"),
        ),
        "presupuesto_oficial": precio,
        # Fecha límite para recibir ofertas (en SECOP II se llama fecha_de_recepcion_de).
        "fecha_cierre": _texto(
            registro.get("fecha_de_recepcion_de"),
            registro.get("fecha_de_recepcion_de_ofertas"),
        )[:10],
        "unspsc": unspsc_codigo(registro.get("codigo_principal_de_categoria")),
        "departamento_entidad": norm_departamento(registro.get("departamento_entidad")),
        "ciudad_unidad": _texto(
            registro.get("ciudad_de_la_unidad_de"),
            registro.get("ciudad_entidad"),
        ),
        "url_proceso": _url(registro.get("urlproceso")),
        "fecha_modificacion": _texto(
            registro.get("fecha_de_ultima_publicaci"),
            registro.get("fecha_de_publicacion_del"),
        ),
        "lotes": lotes,
        "fecha_descarga": fecha_descarga,
        "nit_entidad": _texto(registro.get("nit_entidad")),
        "canal_oferta": canal_oferta,
    }


def fila_oferta(registro: dict) -> dict | None:
    oferta_id = _texto(registro.get("identificador_de_la_oferta"))
    if not oferta_id:
        return None
    valor = registro.get("valor_de_la_oferta")
    try:
        valor = float(valor) if valor not in (None, "") else None
    except (TypeError, ValueError):
        valor = None
    return {
        "identificador_de_la_oferta": oferta_id,
        "id_del_proceso": _texto(
            registro.get("id_del_proceso_de_compra"),
            registro.get("id_del_proceso"),
        ),
        "nit_oferente": _texto(
            registro.get("nit_del_proveedor"),
            registro.get("nit_del_proveedor_oferente"),
        ),
        "nombre_oferente": _texto(
            registro.get("nombre_proveedor"),
            registro.get("nombre_del_proveedor_oferente"),
        ),
        "propuesta_economica": valor,
        "fecha_oferta": _texto(
            registro.get("fecha_de_registro"),
            registro.get("fecha_de_presentaci_n_de_la_oferta"),
        ),
    }


def where_departamentos(nombres: list[str]) -> str:
    """Compara contra el nombre largo que publica SECOP, no contra la sigla local."""
    partes = []
    for nombre in nombres or []:
        token = fold(nombre).upper().replace("'", "").replace("%", "").replace("_", " ")
        if not token.strip():
            continue
        if "BOGOTA" in token:
            partes.append("upper(departamento_entidad) like '%BOGOT%'")
            continue
        pista = token.strip()[:6]
        partes.append(f"upper(departamento_entidad) like '%{soql_literal(pista)}%'")
    if not partes:
        return ""
    return "(" + " OR ".join(partes) + ")"


def where_oferta(id_proceso: str) -> str:
    return f"id_del_proceso_de_compra='{soql_literal(id_proceso)}'"
