"""Evaluación previa y explicable de requisitos de una oferta.

Los valores provienen del pliego o del usuario. El motor calcula; no inventa
requisitos ni sustituye la lectura jurídica/técnica del proceso.
"""
from __future__ import annotations

from typing import Any


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
