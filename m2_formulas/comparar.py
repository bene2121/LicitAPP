"""Diferencias entre las cinco fórmulas, sobre el mismo grupo de rivales."""
from __future__ import annotations

from m2_formulas.optimizador import FORMULAS_VALIDAS


def diferencias_formulas(resultados: dict) -> list[dict]:
    """Precio de cada fórmula y cuánto se aparta de las otras."""
    precios = {cod: float(resultados[cod]["oferta_optima"]) for cod in FORMULAS_VALIDAS}
    mas_baja = min(precios.values())
    promedio = sum(precios.values()) / len(precios)
    precio_mv = precios["MV"]
    filas = []
    for cod in FORMULAS_VALIDAS:
        precio = precios[cod]
        filas.append({
            "formula": cod,
            "precio": precio,
            "puntaje": float(resultados[cod]["scores"][cod]),
            "pct_mejora": float(resultados[cod]["pct_mejora"]),
            "dif_vs_mas_baja": precio - mas_baja,
            "dif_vs_mv": precio - precio_mv,
            "dif_vs_promedio": precio - promedio,
        })
    return filas
