"""Motor de filtrado y priorización de procesos SECOP — obras civiles."""
import os, sys, sqlite3, unicodedata
from datetime import datetime
import pandas as pd

def _fold(texto) -> str:
    base = unicodedata.normalize("NFD", str(texto or ""))
    return "".join(c for c in base if unicodedata.category(c) != "Mn")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import PRESUPUESTO_MIN, PRESUPUESTO_MAX, UNSPSC_INTERES

ESTADOS_EXCLUIR = {
    "ADJUDICADO", "CELEBRADO", "LIQUIDADO", "DESIERTO",
    "TERMINADO ANORMALMENTE", "TERMINADO SIN LIQUIDAR", "DESCARTADO",
}

SCORE_MODALIDAD = {
    "minima cuantia": 1.0, "mínima cuantía": 1.0, "contratacion minima cuantia": 1.0,
    "menor cuantia": 0.9, "menor cuantía": 0.9, "seleccion abreviada de menor cuantia": 0.9,
    "invitacion abierta": 0.85, "invitación abierta": 0.85,
    "invitacion cerrada": 0.75,
    "concurso de meritos": 0.65, "concurso de méritos": 0.65,
    "licitacion publica": 0.5, "licitación pública": 0.5,
    "licitacion obra publica": 0.5,
    "contratacion directa": 0.4,
}

def _parse_fecha(s):
    if not s:
        return None
    s_str = str(s)
    for fmt, trunc in (
        ("%Y-%m-%dT%H:%M:%S.%f", s_str),
        ("%Y-%m-%dT%H:%M:%S",    s_str[:19]),
        ("%Y-%m-%d",              s_str[:10]),
    ):
        try:
            return datetime.strptime(trunc, fmt)
        except ValueError:
            continue
    return None

def score_proceso(proceso: dict, config: dict = None) -> float:
    """Score de oportunidad 0-100."""
    pmin = (config or {}).get("presupuesto_min", PRESUPUESTO_MIN)
    pmax = (config or {}).get("presupuesto_max", PRESUPUESTO_MAX)
    unspsc_interes = (config or {}).get("unspsc_interes", UNSPSC_INTERES)

    score = 0.0

    # 1. Días al cierre (20%)
    fecha_cierre = _parse_fecha(proceso.get("fecha_cierre") or proceso.get("cierre"))
    if fecha_cierre:
        dias = (fecha_cierre - datetime.now()).days
        if 3 <= dias <= 15:
            s_dias = 1.0
        elif 1 <= dias < 3:
            s_dias = 0.6
        elif 15 < dias <= 30:
            s_dias = 0.8
        elif 30 < dias <= 60:
            s_dias = 0.5
        else:
            s_dias = 0.2
    else:
        s_dias = 0.3
    score += s_dias * 20

    # 2. Modalidad (20%)
    modalidad = _fold(proceso.get("modalidad")).lower()
    s_mod = 0.3
    for key, val in SCORE_MODALIDAD.items():
        if _fold(key).lower() in modalidad:
            s_mod = val
            break
    score += s_mod * 20

    # 3. Presupuesto en rango (20%)
    try:
        po = float(proceso.get("presupuesto_oficial") or proceso.get("p_o") or 0)
    except (ValueError, TypeError):
        po = 0
    if pmin <= po <= pmax:
        s_po = 1.0
    elif po < pmin:
        s_po = max(0, 1 - (pmin - po) / pmin)
    else:
        s_po = max(0, 1 - (po - pmax) / pmax)
    score += s_po * 20

    # 4. UNSPSC match (25%)
    unspsc = "".join(c for c in str(proceso.get("unspsc") or proceso.get("segmento") or "") if c.isdigit())
    s_unspsc = 0.0
    for u in unspsc_interes:
        prefix = "".join(c for c in str(u) if c.isdigit())[:2]
        if prefix and unspsc.startswith(prefix):
            s_unspsc = 1.0
            break
    score += s_unspsc * 25

    # 5. Estado favorable (15%)
    estado = _fold(proceso.get("estado") or proceso.get("fase")).upper()
    if any(marca in estado for marca in ("CONVOCADO", "PRESENTACION DE OFERTA", "FASE DE OFERTAS", "FASE DE SELECCION")):
        s_estado = 1.0
    elif "OBSERVACION" in estado:
        s_estado = 0.8
    elif any(marca in estado for marca in ("INVITACION", "MANIFESTACION", "EXPRESION", "INTERES")):
        s_estado = 0.7
    elif "BORRADOR" in estado:
        s_estado = 0.3
    else:
        s_estado = 0.5
    score += s_estado * 15

    return round(score, 2)


def filtrar_y_rankear(procesos: list, config: dict = None) -> pd.DataFrame:
    """Filtra y rankea lista de procesos."""
    ahora = datetime.now()
    resultados = []
    for p in procesos:
        estado = str(p.get("estado") or p.get("fase") or "").upper()
        if any(e in estado for e in ESTADOS_EXCLUIR):
            continue
        try:
            po = float(p.get("presupuesto_oficial") or p.get("p_o") or 0)
        except (ValueError, TypeError):
            po = 0
        if po <= 0:
            continue
        fecha_cierre = _parse_fecha(p.get("fecha_cierre") or p.get("cierre"))
        if fecha_cierre and fecha_cierre < ahora:
            continue
        s = score_proceso(p, config)
        dias = (fecha_cierre - ahora).days if fecha_cierre else None
        resultados.append({**p, "score": s, "dias_al_cierre": dias, "presupuesto_oficial": po})

    if not resultados:
        return pd.DataFrame()
    df = pd.DataFrame(resultados)
    return df.sort_values("score", ascending=False).reset_index(drop=True)


def get_oportunidades_top(db_path: str, config: dict = None, top_n: int = 50) -> pd.DataFrame:
    """Lee DB SQLite y retorna top N procesos más prometedores."""
    if not os.path.exists(db_path):
        return pd.DataFrame()
    conn = sqlite3.connect(db_path)
    try:
        df = pd.read_sql(
            "SELECT * FROM procesos_s2 "
            "WHERE COALESCE(presupuesto_oficial, 0) > 0 "
            "LIMIT 5000",
            conn,
        )
    except Exception:
        conn.close()
        return pd.DataFrame()
    conn.close()
    if df.empty:
        return df
    procesos = df.to_dict("records")
    ranked = filtrar_y_rankear(procesos, config)
    return ranked.head(top_n)
