"""
Optimizador de oferta SECOP — M2
Calcula la oferta optima sobre ofertas reales, en una sola grilla vectorizada.
No genera precios de rivales.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

FORMULAS_VALIDAS = ("M", "MG", "MAB", "MAA", "MV")
_FORMULAS = set(FORMULAS_VALIDAS)


def optimizar_oferta(
    presupuesto_oficial: float,
    pts_max: float,
    ofertas_historicas: list[float],
    n_rivales_estimados: int = 4,
    formula_conocida: str = None,
    paso_busqueda: float = 0.001,
) -> dict:
    """
    Calcula la oferta que maximiza el puntaje contra las ofertas reales recibidas.

    `n_rivales_estimados` se conserva por compatibilidad y no se usa: el calculo
    solo incluye los precios reales de `ofertas_historicas`.
    """
    del n_rivales_estimados  # no se simulan oferentes
    if formula_conocida is not None and formula_conocida not in _FORMULAS:
        raise ValueError(
            f"formula_conocida='{formula_conocida}' no valida. "
            f"Opciones: {_FORMULAS}"
        )

    tabla = _evaluar_grilla(presupuesto_oficial, pts_max, ofertas_historicas, paso_busqueda)
    columna = "score_esperado" if formula_conocida is None else formula_conocida
    return _resultado(tabla, columna, presupuesto_oficial)


def optimizar_todas(
    presupuesto_oficial: float,
    pts_max: float,
    ofertas_historicas: list[float],
    paso_busqueda: float = 0.001,
) -> dict:
    """Una sola grilla para las cinco formulas. La clave es el codigo de formula."""
    tabla = _evaluar_grilla(presupuesto_oficial, pts_max, ofertas_historicas, paso_busqueda)
    return {
        cod: _resultado(tabla, cod, presupuesto_oficial)
        for cod in FORMULAS_VALIDAS
    }


def _ofertas_reales(ofertas_historicas: list[float]) -> np.ndarray:
    if not ofertas_historicas:
        raise ValueError(
            "Se requiere al menos una oferta real de rival. "
            "No se inventan precios."
        )
    arr = np.asarray(list(ofertas_historicas), dtype=float)
    arr = arr[np.isfinite(arr) & (arr > 0)]
    if arr.size == 0:
        raise ValueError(
            "Las ofertas de rivales deben ser numeros mayores que cero."
        )
    return arr


def _evaluar_grilla(
    presupuesto_oficial: float,
    pts_max: float,
    ofertas_historicas: list[float],
    paso_busqueda: float,
) -> pd.DataFrame:
    if presupuesto_oficial <= 0:
        raise ValueError("El presupuesto oficial debe ser mayor que cero.")
    if paso_busqueda <= 0:
        raise ValueError("paso_busqueda debe ser mayor que cero.")

    rivales = _ofertas_reales(ofertas_historicas)
    precio_min = presupuesto_oficial * 0.50
    precio_max = presupuesto_oficial * 0.99
    paso = presupuesto_oficial * paso_busqueda
    precios = np.arange(precio_min, precio_max + paso * 0.5, paso)
    precios = precios[(precios >= precio_min) & (precios <= precio_max + paso * 1e-9)]
    if precios.size == 0:
        raise ValueError("La grilla de precios quedo vacia.")

    n = rivales.size
    denom = float(n + 1)
    suma = float(rivales.sum())
    rmin = float(rivales.min())
    rmax = float(rivales.max())
    media = (suma + precios) / denom
    vmin = np.minimum(rmin, precios)
    vmax = np.maximum(rmax, precios)

    ref_m = _mediana_insertada(np.sort(rivales), precios)
    if np.any(rivales <= 0):
        ref_mg = ref_m
    else:
        ref_mg = np.exp((float(np.log(rivales).sum()) + np.log(precios)) / denom)
    ref_mab = (media + vmin) / 2.0
    ref_maa = (media + vmax) / 2.0

    s_m = _score_distancia(precios, ref_m, pts_max)
    s_mg = _score_distancia(precios, ref_mg, pts_max)
    s_mab = _score_distancia(precios, ref_mab, pts_max)
    s_maa = _score_maa(precios, ref_maa, pts_max)
    s_mv = np.where(precios == 0, 0.0, (vmin / precios) * pts_max)
    s_mv = np.maximum(0.0, s_mv)
    esperado = (s_m + s_mg + s_mab + s_maa + s_mv) / 5.0

    return pd.DataFrame({
        "precio": precios,
        "M": s_m,
        "MG": s_mg,
        "MAB": s_mab,
        "MAA": s_maa,
        "MV": s_mv,
        "score_esperado": esperado,
    })


def _mediana_insertada(sorted_r: np.ndarray, prices: np.ndarray) -> np.ndarray:
    """Mediana de `sorted_r` mas cada precio, sin copiar el arreglo por candidato."""
    n = sorted_r.size
    m = n + 1
    idx = np.searchsorted(sorted_r, prices, side="left")
    if m % 2 == 1:
        return _valor_en(m // 2, idx, sorted_r, prices)
    k2 = m // 2
    return 0.5 * (
        _valor_en(k2 - 1, idx, sorted_r, prices)
        + _valor_en(k2, idx, sorted_r, prices)
    )


def _valor_en(pos: int, idx: np.ndarray, sorted_r: np.ndarray, prices: np.ndarray) -> np.ndarray:
    pos_arr = np.full(idx.shape, pos, dtype=int)
    out = np.empty(idx.shape, dtype=float)
    left = pos_arr < idx
    mid = pos_arr == idx
    right = ~left & ~mid
    if np.any(left):
        out[left] = sorted_r[pos_arr[left]]
    if np.any(mid):
        out[mid] = prices[mid]
    if np.any(right):
        out[right] = sorted_r[pos_arr[right] - 1]
    return out


def _score_distancia(precios: np.ndarray, ref: np.ndarray, pts_max: float) -> np.ndarray:
    seguro = ref != 0
    dist = np.zeros_like(precios, dtype=float)
    dist[seguro] = (1.0 - np.abs(precios[seguro] - ref[seguro]) / ref[seguro]) * pts_max
    return np.maximum(0.0, dist)


def _score_maa(precios: np.ndarray, ref: np.ndarray, pts_max: float) -> np.ndarray:
    seguro = ref != 0
    bajo = seguro & (precios < ref)
    alto = seguro & ~bajo
    score = np.zeros_like(precios, dtype=float)
    score[bajo] = (1.0 - np.abs(precios[bajo] - ref[bajo]) / ref[bajo]) * pts_max
    score[alto] = (1.0 - 2.0 * np.abs(precios[alto] - ref[alto]) / ref[alto]) * pts_max
    return np.maximum(0.0, score)


def _resultado(tabla: pd.DataFrame, columna: str, presupuesto_oficial: float) -> dict:
    idx = tabla[columna].idxmax()
    mejor = tabla.loc[idx]
    precio = float(mejor["precio"])
    if presupuesto_oficial == 0:
        pct = 0.0
    else:
        pct = (presupuesto_oficial - precio) / presupuesto_oficial
    return {
        "oferta_optima": precio,
        "pct_mejora": pct,
        "scores": {cod: float(mejor[cod]) for cod in FORMULAS_VALIDAS},
        "score_esperado": float(mejor[columna] if columna != "score_esperado" else mejor["score_esperado"]),
        "rango_evaluado": (float(tabla["precio"].iloc[0]), float(tabla["precio"].iloc[-1])),
        "tabla_simulacion": tabla,
    }
