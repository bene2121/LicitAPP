"""Historial de participaciones de la empresa."""
from __future__ import annotations

RESULTADOS = ("adjudicado", "no_adjudicado", "desierto")


def listar_participaciones(perfil: dict) -> list[dict]:
    return list(perfil.get("participaciones") or [])


def agregar_participacion(perfil: dict, registro: dict) -> dict:
    proceso = str(registro.get("id") or registro.get("id_del_proceso") or "").strip()
    if not proceso:
        raise ValueError("La participación necesita el identificador del proceso.")
    resultado = str(registro.get("resultado") or "").strip().lower().replace(" ", "_")
    if resultado not in RESULTADOS:
        raise ValueError("El resultado debe ser adjudicado, no adjudicado o desierto.")
    entrada = {
        "id": proceso,
        "objeto": str(registro.get("objeto") or registro.get("titulo") or "").strip(),
        "entidad": str(registro.get("entidad") or "").strip(),
        "unspsc": "".join(c for c in str(registro.get("unspsc") or "") if c.isdigit()),
        "departamento": str(registro.get("departamento") or registro.get("departamento_entidad") or "").strip().upper(),
        "presupuesto": _numero(registro.get("presupuesto") or registro.get("presupuesto_oficial")),
        "resultado": resultado,
    }
    historial = [item for item in listar_participaciones(perfil) if item.get("id") != proceso]
    historial.append(entrada)
    perfil["participaciones"] = historial
    return entrada


def _numero(valor) -> float:
    try:
        return float(valor or 0)
    except (TypeError, ValueError):
        return 0.0
