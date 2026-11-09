"""Consulta en vivo de procesos abiertos en SECOP II (sin depender de la base local)."""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta

from m1_ingestor.campos import fila_proceso_s2, fold, soql_literal

API_PROCESOS = "https://www.datos.gov.co/resource/p6dx-8zbt.json"
LIMITE = 1000


def _texto_like(texto: str) -> list[str]:
    """Variantes en mayúsculas con y sin tildes (SECOP guarda los objetos con tildes)."""
    crudo = soql_literal(str(texto).upper()).replace("%", "").replace("_", " ")
    plano = soql_literal(fold(texto).upper()).replace("%", "").replace("_", " ")
    return sorted({crudo, plano})


def where_vivo(filtros: dict, hoy: date | None = None) -> str:
    hoy = hoy or date.today()
    partes = [
        f"(fecha_de_recepcion_de >= '{hoy.isoformat()}T00:00:00' "
        "OR fase = 'Presentación de oferta' OR fase = 'Manifestación de interés (Menor Cuantía)')",
        "estado_del_procedimiento != 'Cancelado'",
    ]
    dias_max = int(filtros.get("dias_cierre_max") or 0)
    if dias_max:
        tope = (hoy + timedelta(days=dias_max)).isoformat()
        partes.append(f"(fecha_de_recepcion_de IS NULL OR fecha_de_recepcion_de <= '{tope}T23:59:59')")
    po_min, po_max = float(filtros.get("po_min") or 0), float(filtros.get("po_max") or 0)
    if po_min > 0:
        partes.append(f"precio_base >= {int(po_min)}")
    if po_max > 0:
        partes.append(f"precio_base <= {int(po_max)}")
    q = " ".join(str(filtros.get("q") or "").split())[:120]
    if q:
        if re.match(r"^CO1\.[A-Z]+\.\d+$", q, re.I):
            lit = soql_literal(q.upper())
            partes.append(f"(id_del_portafolio = '{lit}' OR id_del_proceso = '{lit}')")
        else:
            opciones = [f"referencia_del_proceso = '{soql_literal(q)}'"]
            for v in _texto_like(q):
                opciones.append(f"upper(nombre_del_procedimiento) like '%{v}%'")
                opciones.append(f"upper(entidad) like '%{v}%'")
            partes.append("(" + " OR ".join(opciones) + ")")
    entidad = " ".join(str(filtros.get("entidad") or "").split())[:120]
    if entidad:
        partes.append("(" + " OR ".join(f"upper(entidad) like '%{v}%'" for v in _texto_like(entidad)) + ")")
    if filtros.get("nit_entidad"):
        partes.append(f"nit_entidad = '{soql_literal(str(filtros['nit_entidad']))}'")
    return " AND ".join(partes)


def buscar_en_vivo(filtros: dict, cliente, config_score: dict | None = None) -> list[dict]:
    """Procesos abiertos ahora mismo en SECOP II, listos para el Explorador."""
    from m3_filtrado.process_filter import score_proceso

    filas = cliente(API_PROCESOS, {
        "$where": where_vivo(filtros),
        "$order": "fecha_de_publicacion_del DESC",
        "$limit": str(LIMITE),
    })
    hoy = date.today()
    ahora = datetime.now().strftime("%Y-%m-%d %H:%M")
    procesos, vistos = [], set()
    for fila in filas or []:
        p = fila_proceso_s2(fila, ahora)
        if not p or p["id_del_proceso"] in vistos:
            continue
        vistos.add(p["id_del_proceso"])
        p["id"] = str(fila.get("id_del_proceso") or p["id_del_proceso"])
        p["objeto"] = p.get("titulo", "")
        p["nit_entidad"] = str(fila.get("nit_entidad") or "")
        p["departamento"] = p.get("departamento_entidad", "")
        try:
            p["dias_al_cierre"] = (date.fromisoformat(p["fecha_cierre"][:10]) - hoy).days if p.get("fecha_cierre") else None
        except ValueError:
            p["dias_al_cierre"] = None
        try:
            p["score"] = round(float(score_proceso(p, config_score)), 1)
        except Exception:
            p["score"] = 0.0
        procesos.append(p)
    return procesos
