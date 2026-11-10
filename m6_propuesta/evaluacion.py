"""Evaluación previa y explicable de requisitos de una oferta.

Los valores provienen del pliego o del usuario. El motor calcula; no inventa
requisitos ni sustituye la lectura jurídica/técnica del proceso.
"""
from __future__ import annotations

from typing import Any


ESTADOS_REQUISITO = {"Cumple", "Pendiente", "No cumple", "No aplica"}


def _num(valor: Any) -> float:
    try:
        return float(valor or 0)
    except (TypeError, ValueError):
        return 0.0


def evaluar_experiencia(requisito: dict, contratos: list[dict], presupuesto: float) -> dict:
    max_contratos = max(1, int(_num(requisito.get("max_contratos")) or 5))
    pct_total = _num(requisito.get("pct_total"))
    pct_especifica = _num(requisito.get("pct_especifica"))
    minimo_total = presupuesto * pct_total / 100
    minimo_especifico = presupuesto * pct_especifica / 100
    validos = []
    for contrato in contratos:
        valor = _num(contrato.get("valor")) * _num(contrato.get("participacion", 100)) / 100
        terminado = bool(contrato.get("terminado"))
        soporte = bool(contrato.get("soporte"))
        actividad = bool(contrato.get("actividad"))
        if valor > 0 and terminado and soporte:
            validos.append({**contrato, "valor_computable": valor, "actividad": actividad})
    # La combinación más favorable dentro del máximo permitido.
    seleccionados = sorted(validos, key=lambda c: c["valor_computable"], reverse=True)[:max_contratos]
    total = sum(c["valor_computable"] for c in seleccionados)
    especifico = sum(c["valor_computable"] for c in seleccionados if c["actividad"])
    criterios = [
        {"nombre": f"Máximo {max_contratos} contratos", "cumple": len(seleccionados) <= max_contratos,
         "detalle": f"Se evaluaron {len(seleccionados)} contratos válidos."},
        {"nombre": f"Experiencia acumulada mínima ({pct_total:g} % del presupuesto)",
         "cumple": total >= minimo_total,
         "detalle": f"Acreditado: $ {total:,.0f} · Exigido: $ {minimo_total:,.0f}"},
        {"nombre": f"Experiencia específica mínima ({pct_especifica:g} % del presupuesto)",
         "cumple": especifico >= minimo_especifico,
         "detalle": f"Acreditado: $ {especifico:,.0f} · Exigido: $ {minimo_especifico:,.0f}"},
    ]
    if not contratos:
        criterios.append({"nombre": "Contratos aportados", "cumple": False, "detalle": "No se registraron contratos."})
    return {"cumple": all(c["cumple"] for c in criterios), "criterios": criterios,
            "seleccionados": seleccionados, "total": total, "especifico": especifico}


def evaluar_financiero(datos: dict) -> dict:
    reglas = [
        ("Índice de liquidez", "liquidez", "liquidez_min", ">="),
        ("Índice de endeudamiento", "endeudamiento", "endeudamiento_max", "<="),
        ("Razón de cobertura de intereses", "cobertura", "cobertura_min", ">="),
        ("Rentabilidad del patrimonio", "roe", "roe_min", ">="),
        ("Rentabilidad del activo", "roa", "roa_min", ">="),
    ]
    criterios = []
    for nombre, actual_k, limite_k, operador in reglas:
        actual, limite = _num(datos.get(actual_k)), _num(datos.get(limite_k))
        aplica = bool(datos.get(f"aplica_{actual_k}", True))
        cumple = True if not aplica else (actual >= limite if operador == ">=" else actual <= limite)
        criterios.append({"nombre": nombre, "cumple": cumple, "aplica": aplica,
                          "detalle": "No exigido" if not aplica else f"Actual {actual:g} {operador} exigido {limite:g}"})
    return {"cumple": all(c["cumple"] for c in criterios), "criterios": criterios}


def evaluar_total(experiencia: dict, financiero: dict, juridicos: dict) -> dict:
    criterios = []
    criterios.extend({"grupo": "Experiencia", **c} for c in experiencia["criterios"])
    criterios.extend({"grupo": "Financiero", **c} for c in financiero["criterios"] if c.get("aplica", True))
    etiquetas = {
        "capacidad_juridica": "Capacidad jurídica y representación verificadas",
        "rup_vigente": "RUP vigente y en firme cuando es exigible",
        "sin_inhabilidades": "Sin inhabilidades ni incompatibilidades declaradas",
        "seguridad_social": "Aportes a seguridad social acreditados",
        "garantia": "Garantía de seriedad preparada cuando es exigible",
    }
    for clave, nombre in etiquetas.items():
        criterios.append({"grupo": "Jurídico", "nombre": nombre,
                          "cumple": bool(juridicos.get(clave)),
                          "detalle": "Confirmado" if juridicos.get(clave) else "Pendiente de verificar"})
    completos = sum(bool(c["cumple"]) for c in criterios)
    total = len(criterios)
    return {"criterios": criterios, "completos": completos, "total": total,
            "porcentaje": round(completos / total * 100) if total else 0,
            "cumple": bool(total) and completos == total}


def ficha_decision(resultado: dict | None, requisitos: list[dict] | None = None,
                   economia: dict | None = None, blocker: dict | None = None) -> dict:
    """Recomienda participar, revisar o descartar con razones auditables.

    La falta de información siempre conduce a ``REVISAR``. ``DESCARTAR`` solo
    se usa cuando el usuario confirma un impedimento crítico e insubsanable.
    """
    resultado, economia, blocker = resultado or {}, economia or {}, blocker or {}
    requisitos = requisitos or []
    razones, pendientes, bloqueos = [], [], []

    if blocker.get("confirmado"):
        detalle = str(blocker.get("detalle") or "Impedimento crítico confirmado por el usuario.").strip()
        bloqueos.append(detalle)

    for item in requisitos:
        estado = str(item.get("estado") or "Pendiente").strip().capitalize()
        if estado not in ESTADOS_REQUISITO:
            estado = "Pendiente"
        nombre = str(item.get("requisito") or item.get("nombre") or "Requisito sin nombre").strip()
        if estado == "No cumple":
            (bloqueos if bool(item.get("critico")) else pendientes).append(nombre)
        elif estado == "Pendiente":
            pendientes.append(nombre)
        if estado not in {"No aplica"} and not str(item.get("fuente") or "").strip():
            pendientes.append(f"Ubicar fuente/página: {nombre}")
        if estado == "Cumple" and not str(item.get("evidencia") or "").strip():
            pendientes.append(f"Adjuntar evidencia: {nombre}")

    if not resultado:
        pendientes.append("Completar evaluación de experiencia, capacidad financiera y jurídica")
    elif not resultado.get("cumple"):
        pendientes.extend(str(c.get("nombre") or "Requisito preliminar")
                          for c in resultado.get("criterios", []) if not c.get("cumple"))

    ingreso = _num(economia.get("ingreso"))
    costos = _num(economia.get("costos"))
    margen_minimo = _num(economia.get("margen_minimo"))
    margen = ((ingreso - costos) / ingreso * 100) if ingreso > 0 else None
    if ingreso <= 0 or costos <= 0:
        pendientes.append("Completar ingreso ofertado y costo total estimado")
    elif margen < margen_minimo:
        pendientes.append(f"Margen estimado {margen:.2f} % inferior al mínimo {margen_minimo:.2f} %")
    else:
        razones.append(f"Margen estimado {margen:.2f} % alcanza el mínimo de {margen_minimo:.2f} %")

    # Solo una confirmación expresa permite descartar. Los demás bloqueos son
    # alertas para revisión porque podrían ser subsanables o estar mal leídos.
    if blocker.get("confirmado"):
        decision = "DESCARTAR"
    elif bloqueos or pendientes:
        decision = "REVISAR"
    else:
        decision = "PARTICIPAR"
        razones.append("Requisitos registrados completos y sin bloqueos críticos")
    return {
        "decision": decision,
        "razones": list(dict.fromkeys(razones)),
        "pendientes": list(dict.fromkeys(pendientes)),
        "bloqueos": list(dict.fromkeys(bloqueos)),
        "margen": round(margen, 2) if margen is not None else None,
    }
