"""
Optimizador de oferta SECOP — M2
Calcula la oferta optima que maximiza el puntaje esperado bajo las 5 metodologias.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from m2_formulas.formula_engine import FormulaEngine

_engine = FormulaEngine()

FORMULAS_VALIDAS = {"M", "MG", "MAB", "MAA", "MV"}


def optimizar_oferta(
    presupuesto_oficial: float,
    pts_max: float,
    ofertas_historicas: list[float],
    n_rivales_estimados: int = 4,
    formula_conocida: str = None,   # None = optimizar para todas
    paso_busqueda: float = 0.001,   # % del presupuesto
) -> dict:
    """
    Calcula la oferta optima que maximiza el puntaje esperado.

    Retorna:
    {
      "oferta_optima": float,
      "pct_mejora": float,
      "scores": {"M": x, "MG": x, "MAB": x, "MAA": x, "MV": x},
      "score_esperado": float,
      "rango_evaluado": (min, max),
      "tabla_simulacion": pd.DataFrame  # precio -> scores para graficar
    }
    """
    if formula_conocida is not None and formula_conocida not in FORMULAS_VALIDAS:
        raise ValueError(
            f"formula_conocida='{formula_conocida}' no valida. "
            f"Opciones: {FORMULAS_VALIDAS}"
        )

    # 1. Generar rivales simulados
    if ofertas_historicas and len(ofertas_historicas) >= 1:
        historico = np.array(ofertas_historicas, dtype=float)
        media = float(np.mean(historico))
        std = float(np.std(historico)) if len(historico) > 1 else media * 0.08
        rng = np.random.default_rng(seed=42)
        rivales = list(rng.normal(loc=media, scale=std, size=n_rivales_estimados))
        # Clip para que no salgan valores negativos
        rivales = [max(r, presupuesto_oficial * 0.40) for r in rivales]
    else:
        media = 0.85 * presupuesto_oficial
        std = 0.08 * presupuesto_oficial
        rng = np.random.default_rng(seed=42)
        rivales = list(rng.normal(loc=media, scale=std, size=n_rivales_estimados))
        rivales = [max(r, presupuesto_oficial * 0.40) for r in rivales]

    # 2. Rango de precios a evaluar: 50% a 99% del presupuesto
    precio_min = presupuesto_oficial * 0.50
    precio_max = presupuesto_oficial * 0.99
    paso = presupuesto_oficial * paso_busqueda
    precios = np.arange(precio_min, precio_max + paso, paso)

    # 3. Evaluar cada precio
    registros = []
    for precio in precios:
        pool = rivales + [precio]
        row = {
            "precio": precio,
            "M":   _engine.score_M(precio, pool, pts_max),
            "MG":  _engine.score_MG(precio, pool, pts_max),
            "MAB": _engine.score_MAB(precio, pool, pts_max),
            "MAA": _engine.score_MAA(precio, pool, pts_max),
            "MV":  _engine.score_MV(precio, pool, pts_max),
        }
        # 4. Score esperado segun formula conocida o promedio
        if formula_conocida is None:
            row["score_esperado"] = float(
                np.mean([row["M"], row["MG"], row["MAB"], row["MAA"], row["MV"]])
            )
        else:
            row["score_esperado"] = row[formula_conocida]
        registros.append(row)

    tabla = pd.DataFrame(registros)

    # 5. Precio optimo
    idx_max = tabla["score_esperado"].idxmax()
    mejor = tabla.loc[idx_max]

    return {
        "oferta_optima": float(mejor["precio"]),
        "pct_mejora": _engine.pct_mejora(float(mejor["precio"]), presupuesto_oficial),
        "scores": {
            "M":   float(mejor["M"]),
            "MG":  float(mejor["MG"]),
            "MAB": float(mejor["MAB"]),
            "MAA": float(mejor["MAA"]),
            "MV":  float(mejor["MV"]),
        },
        "score_esperado": float(mejor["score_esperado"]),
        "rango_evaluado": (float(precio_min), float(precio_max)),
        "tabla_simulacion": tabla,
    }
