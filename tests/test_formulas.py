"""
Tests del motor de formulas SECOP — M2
Valores validados contra el Excel SECOP UNIFICADO V 5.2.xlsm
"""

import sys
import os

# Asegurar que el root del proyecto esta en sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import numpy as np
import pytest

from m2_formulas.formula_engine import FormulaEngine
from m2_formulas.optimizador import optimizar_oferta


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def engine():
    return FormulaEngine()


OFERTAS_BASE = [100.0, 90.0, 85.0, 80.0]
PTS_MAX = 100.0


# ---------------------------------------------------------------------------
# Tests score_MV
# ---------------------------------------------------------------------------

def test_score_MV_ganador(engine):
    """Si soy el mas barato, debo tener score = pts_max."""
    ofertas = [100.0, 90.0, 85.0, 80.0]
    assert engine.score_MV(80.0, ofertas, PTS_MAX) == pytest.approx(100.0)


def test_score_MV_no_ganador(engine):
    """Si no soy el mas barato, score < pts_max."""
    ofertas = [100.0, 90.0, 85.0, 80.0]
    esperado = (80.0 / 90.0) * PTS_MAX
    assert engine.score_MV(90.0, ofertas, PTS_MAX) == pytest.approx(esperado, rel=1e-3)


def test_score_MV_nunca_negativo(engine):
    """MV no puede ser negativo (aunque en la practica no ocurre con valores positivos)."""
    ofertas = [50.0]
    assert engine.score_MV(200.0, ofertas, PTS_MAX) >= 0.0


# ---------------------------------------------------------------------------
# Tests score_MAA
# ---------------------------------------------------------------------------

def test_MAA_penaliza_precio_alto(engine):
    """Si oferta >= referencia, el score debe ser menor que si oferta < referencia."""
    ofertas = [100.0, 90.0, 85.0, 80.0]
    ref = (np.mean(ofertas) + np.max(ofertas)) / 2
    score_bajo = engine.score_MAA(ref - 1, ofertas, PTS_MAX)
    score_alto = engine.score_MAA(ref + 1, ofertas, PTS_MAX)
    assert score_bajo > score_alto


def test_MAA_en_referencia_es_maximo(engine):
    """Oferta exactamente en la referencia debe dar score = pts_max."""
    ofertas = [100.0, 90.0, 85.0, 80.0]
    ref = (np.mean(ofertas) + np.max(ofertas)) / 2
    # Justo en ref, |oferta - ref| = 0
    assert engine.score_MAA(ref, ofertas, PTS_MAX) == pytest.approx(PTS_MAX)


def test_MAA_score_no_negativo(engine):
    """score_MAA nunca debe retornar valor negativo."""
    ofertas = [100.0, 90.0, 85.0, 80.0]
    # Precio muy alto: deberia dar 0 por el piso
    assert engine.score_MAA(9999.0, ofertas, PTS_MAX) == 0.0


# ---------------------------------------------------------------------------
# Tests score_M (Mediana)
# ---------------------------------------------------------------------------

def test_score_M_en_mediana(engine):
    """Oferta igual a la mediana debe dar pts_max."""
    ofertas = [100.0, 90.0, 85.0, 80.0]
    mediana = float(np.median(ofertas))
    assert engine.score_M(mediana, ofertas, PTS_MAX) == pytest.approx(PTS_MAX)


def test_score_M_no_negativo(engine):
    """score_M nunca debe ser negativo."""
    ofertas = [100.0, 90.0, 85.0, 80.0]
    assert engine.score_M(0.001, ofertas, PTS_MAX) >= 0.0


# ---------------------------------------------------------------------------
# Tests score_MG (Media Geometrica)
# ---------------------------------------------------------------------------

def test_score_MG_fallback_con_ceros(engine):
    """Con valores <= 0 en la lista, debe usar mediana como fallback sin lanzar error."""
    ofertas = [100.0, 0.0, 85.0, 80.0]
    resultado = engine.score_MG(85.0, ofertas, PTS_MAX)
    assert isinstance(resultado, float)
    assert resultado >= 0.0


def test_score_MG_normal(engine):
    """MG con valores positivos no debe lanzar excepcion."""
    ofertas = [100.0, 90.0, 85.0, 80.0]
    resultado = engine.score_MG(88.0, ofertas, PTS_MAX)
    assert isinstance(resultado, float)
    assert resultado >= 0.0


# ---------------------------------------------------------------------------
# Tests score_MAB (Media Aritmetica Baja)
# ---------------------------------------------------------------------------

def test_score_MAB_en_referencia(engine):
    """Oferta en la referencia (avg+min)/2 debe dar pts_max."""
    ofertas = [100.0, 90.0, 85.0, 80.0]
    ref = (np.mean(ofertas) + np.min(ofertas)) / 2
    assert engine.score_MAB(ref, ofertas, PTS_MAX) == pytest.approx(PTS_MAX)


# ---------------------------------------------------------------------------
# Tests pct_mejora
# ---------------------------------------------------------------------------

def test_pct_mejora(engine):
    assert engine.pct_mejora(800_000, 1_000_000) == pytest.approx(0.20)


def test_pct_mejora_sin_descuento(engine):
    assert engine.pct_mejora(1_000_000, 1_000_000) == pytest.approx(0.0)


def test_pct_mejora_presupuesto_cero(engine):
    """No debe dividir por cero."""
    assert engine.pct_mejora(500_000, 0) == 0.0


# ---------------------------------------------------------------------------
# Tests calcular_todos
# ---------------------------------------------------------------------------

def test_calcular_todos_retorna_claves(engine):
    resultado = engine.calcular_todos(85.0, [100.0, 90.0, 80.0], PTS_MAX, 110.0)
    claves_esperadas = {"M", "MG", "MAB", "MAA", "MV", "pct_mejora", "promedio"}
    assert claves_esperadas == set(resultado.keys())


def test_calcular_todos_promedio_coherente(engine):
    resultado = engine.calcular_todos(85.0, [100.0, 90.0, 80.0], PTS_MAX, 110.0)
    scores = [resultado["M"], resultado["MG"], resultado["MAB"], resultado["MAA"], resultado["MV"]]
    assert resultado["promedio"] == pytest.approx(np.mean(scores), rel=1e-6)


# ---------------------------------------------------------------------------
# Tests optimizador
# ---------------------------------------------------------------------------

def test_optimizador_sin_ofertas_reales():
    with pytest.raises(ValueError):
        optimizar_oferta(1_000_000, 100, [])


def test_optimizador_retorna_precio_valido():
    resultado = optimizar_oferta(1_000_000, 100, [850_000, 820_000, 880_000])
    assert 500_000 <= resultado["oferta_optima"] <= 999_000


def test_optimizador_retorna_estructura_completa():
    resultado = optimizar_oferta(1_000_000, 100, [850_000, 820_000, 880_000])
    claves = {"oferta_optima", "pct_mejora", "scores", "score_esperado", "rango_evaluado", "tabla_simulacion"}
    assert claves == set(resultado.keys())


def test_optimizador_scores_no_negativos():
    resultado = optimizar_oferta(1_000_000, 100, [850_000, 820_000, 880_000])
    for k, v in resultado["scores"].items():
        assert v >= 0.0, f"Score {k} es negativo: {v}"


def test_optimizador_no_inventa_rivales():
    ofertas = [850_000, 820_000, 880_000, 790_000]
    a = optimizar_oferta(1_000_000, 100, ofertas, n_rivales_estimados=2)
    b = optimizar_oferta(1_000_000, 100, ofertas, n_rivales_estimados=15)
    assert a["oferta_optima"] == b["oferta_optima"]
    for cod in a["scores"]:
        assert a["scores"][cod] == pytest.approx(b["scores"][cod])


def test_optimizador_coincide_con_motor():
    ofertas = [900_000.0, 850_000.0, 800_000.0]
    resultado = optimizar_oferta(1_000_000, 100, ofertas)
    engine = FormulaEngine()
    tabla = resultado["tabla_simulacion"]
    indices = np.linspace(0, len(tabla) - 1, 5).astype(int)
    for i in indices:
        precio = float(tabla.iloc[i]["precio"])
        pool = ofertas + [precio]
        assert tabla.iloc[i]["M"] == pytest.approx(engine.score_M(precio, pool, 100), rel=1e-6, abs=1e-6)
        assert tabla.iloc[i]["MG"] == pytest.approx(engine.score_MG(precio, pool, 100), rel=1e-6, abs=1e-6)
        assert tabla.iloc[i]["MAB"] == pytest.approx(engine.score_MAB(precio, pool, 100), rel=1e-6, abs=1e-6)
        assert tabla.iloc[i]["MAA"] == pytest.approx(engine.score_MAA(precio, pool, 100), rel=1e-6, abs=1e-6)
        assert tabla.iloc[i]["MV"] == pytest.approx(engine.score_MV(precio, pool, 100), rel=1e-6, abs=1e-6)


def test_optimizador_formula_conocida():
    """Con formula_conocida, el score_esperado debe coincidir con ese score."""
    resultado = optimizar_oferta(1_000_000, 100, [850_000, 820_000, 880_000], formula_conocida="MV")
    assert resultado["score_esperado"] == pytest.approx(resultado["scores"]["MV"], rel=1e-6)


def test_optimizador_formula_invalida():
    with pytest.raises(ValueError):
        optimizar_oferta(1_000_000, 100, [], formula_conocida="INVALIDA")


def test_optimizador_con_historico():
    historico = [850_000, 820_000, 880_000, 790_000, 860_000]
    resultado = optimizar_oferta(1_000_000, 100, historico)
    assert 500_000 <= resultado["oferta_optima"] <= 999_000


def test_optimizador_tabla_simulacion_tiene_columnas():
    import pandas as pd
    resultado = optimizar_oferta(500_000, 50, [420_000, 400_000, 450_000])
    tabla = resultado["tabla_simulacion"]
    assert isinstance(tabla, pd.DataFrame)
    for col in ["precio", "M", "MG", "MAB", "MAA", "MV", "score_esperado"]:
        assert col in tabla.columns, f"Columna '{col}' no encontrada en tabla_simulacion"


def test_grilla_permite_ofertar_el_100_por_ciento():
    # Concurso de méritos real (SVCMIN0010-25): 34 de 43 ofertas al 100 % del presupuesto.
    from m2_formulas.optimizador import optimizar_todas
    presupuesto = 1_288_612_325
    rivales = [presupuesto] * 34 + [1_288_599_235, 1_288_350_525, 1_257_553_682]
    resultado = optimizar_todas(presupuesto, 100, rivales)
    assert resultado["M"]["oferta_optima"] == presupuesto
    assert len({round(resultado[c]["oferta_optima"]) for c in resultado}) >= 3
