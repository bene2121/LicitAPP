"""
Motor de fórmulas SECOP — M2
Implementa las 5 metodologías colombianas de evaluación de ofertas económicas.
"""

from __future__ import annotations

import numpy as np
from scipy.stats import gmean


class FormulaEngine:
    """Calcula puntajes de ofertas según las 5 metodologías SECOP colombianas."""

    # ------------------------------------------------------------------
    # Métodos individuales
    # ------------------------------------------------------------------

    def score_M(self, oferta: float, ofertas: list[float], pts_max: float) -> float:
        """Mediana: (1 - |oferta - MEDIAN| / MEDIAN) * pts_max"""
        arr = np.array(ofertas, dtype=float)
        ref = float(np.median(arr))
        if ref == 0:
            return 0.0
        score = (1.0 - abs(oferta - ref) / ref) * pts_max
        return max(0.0, score)

    def score_MG(self, oferta: float, ofertas: list[float], pts_max: float) -> float:
        """Media Geométrica: (1 - |oferta - GEOMEAN| / GEOMEAN) * pts_max
        Fallback a mediana si algún valor es <= 0.
        """
        arr = np.array(ofertas, dtype=float)
        if np.any(arr <= 0):
            ref = float(np.median(arr))
        else:
            try:
                ref = float(gmean(arr))
            except Exception:
                ref = float(np.median(arr))
        if ref == 0:
            return 0.0
        score = (1.0 - abs(oferta - ref) / ref) * pts_max
        return max(0.0, score)

    def score_MAB(self, oferta: float, ofertas: list[float], pts_max: float) -> float:
        """Media Aritmética Baja: ref = (AVERAGE + MIN) / 2"""
        arr = np.array(ofertas, dtype=float)
        ref = (float(np.mean(arr)) + float(np.min(arr))) / 2.0
        if ref == 0:
            return 0.0
        score = (1.0 - abs(oferta - ref) / ref) * pts_max
        return max(0.0, score)

    def score_MAA(self, oferta: float, ofertas: list[float], pts_max: float) -> float:
        """Media Aritmética Alta: ref = (AVERAGE + MAX) / 2
        Si oferta < ref  -> formula normal
        Si oferta >= ref -> penalizacion doble: (1 - 2*|oferta-ref|/ref) * pts_max
        """
        arr = np.array(ofertas, dtype=float)
        ref = (float(np.mean(arr)) + float(np.max(arr))) / 2.0
        if ref == 0:
            return 0.0
        if oferta < ref:
            score = (1.0 - abs(oferta - ref) / ref) * pts_max
        else:
            score = (1.0 - 2.0 * abs(oferta - ref) / ref) * pts_max
        return max(0.0, score)

    def score_MV(self, oferta: float, ofertas: list[float], pts_max: float) -> float:
        """Menor Valor: (MIN(ofertas) / oferta) * pts_max"""
        arr = np.array(ofertas, dtype=float)
        min_val = float(np.min(arr))
        if oferta == 0:
            return 0.0
        score = (min_val / oferta) * pts_max
        return max(0.0, score)

    def pct_mejora(self, oferta: float, presupuesto: float) -> float:
        """% Mejora = (presupuesto_oficial - oferta) / presupuesto_oficial"""
        if presupuesto == 0:
            return 0.0
        return (presupuesto - oferta) / presupuesto

    # ------------------------------------------------------------------
    # Método agregado
    # ------------------------------------------------------------------

    def calcular_todos(
        self,
        oferta: float,
        ofertas_rivales: list[float],
        pts_max: float,
        presupuesto: float,
    ) -> dict:
        """
        Retorna dict con keys: M, MG, MAB, MAA, MV, pct_mejora, promedio
        Cada valor es el puntaje que obtendria `oferta` bajo esa metodologia.
        """
        # Incluir la propia oferta en el pool para la evaluacion
        ofertas_completas = list(ofertas_rivales) + [oferta]

        scores = {
            "M":   self.score_M(oferta, ofertas_completas, pts_max),
            "MG":  self.score_MG(oferta, ofertas_completas, pts_max),
            "MAB": self.score_MAB(oferta, ofertas_completas, pts_max),
            "MAA": self.score_MAA(oferta, ofertas_completas, pts_max),
            "MV":  self.score_MV(oferta, ofertas_completas, pts_max),
        }
        scores["pct_mejora"] = self.pct_mejora(oferta, presupuesto)
        scores["promedio"] = float(
            np.mean([scores["M"], scores["MG"], scores["MAB"], scores["MAA"], scores["MV"]])
        )
        return scores
