"""Ingestor central — corre en el VPS cada 6 horas. Descarga SECOP I+II a PostgreSQL."""
import os, logging, unicodedata, httpx
from datetime import datetime
from sqlalchemy.orm import Session
from .db import SessionLocal
from .models import Proceso, Contrato, Contratista

logger = logging.getLogger("ingestor_central")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [INGESTOR] %(message)s")

SOCRATA_BASE  = "https://www.datos.gov.co/resource"
API_SECOP2    = f"{SOCRATA_BASE}/p6dx-8zbt.json"
API_CONTRATOS = f"{SOCRATA_BASE}/jbjy-vk9h.json"
APP_TOKEN     = os.getenv("SOCRATA_APP_TOKEN", "")
PAGE_SIZE     = 1000

def _headers():
    h = {"Accept": "application/json"}
    if APP_TOKEN:
        h["X-App-Token"] = APP_TOKEN
    return h

def _fetch_page(url: str, offset: int, where: str = None) -> list:
    params = {"$limit": PAGE_SIZE, "$offset": offset}
    if where:
        params["$where"] = where
    try:
        r = httpx.get(url, params=params, headers=_headers(), timeout=30)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        logger.error(f"Error fetch {url}: {e}")
        return []

def _parse_fecha(s: str):
    if not s:
        return None
    for fmt in ["%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"]:
        try:
            return datetime.strptime(str(s)[:19], fmt[:19])
        except Exception:
            pass
    return None

def _parse_valor(v) -> float:
    try:
        return float(str(v or 0).replace(",", "").replace("$", ""))
    except Exception:
        return 0.0

def _fold(texto) -> str:
    base = unicodedata.normalize("NFD", str(texto or ""))
    return "".join(c for c in base if unicodedata.category(c) != "Mn").strip()

def _norm_departamento(texto) -> str:
    plano = _fold(texto).upper()
    if "BOGOTA" in plano:
        return "BOGOTA"
    return plano

def _unspsc(texto) -> str:
    bruto = str(texto or "").strip()
    if bruto.upper().startswith("V1."):
        bruto = bruto[3:]
    digitos = "".join(c for c in bruto if c.isdigit())
    return digitos or bruto

def _texto(*valores) -> str:
    for valor in valores:
        limpio = str(valor or "").strip()
        if limpio and limpio.lower() not in {"no definido", "none", "null"}:
            return limpio
    return ""

def sincronizar_procesos_secop2(db: Session) -> int:
    logger.info("Sincronizando procesos SECOP II...")
    total, offset = 0, 0
    fases = (
        "Presentación de oferta",
        "Fase de ofertas",
        "Manifestación de interés (Menor Cuantía)",
        "Fase de Selección (Presentación de ofertas)",
        "Presentación de observaciones",
    )
    where = (
        "estado_de_apertura_del_proceso='Abierto' AND precio_base > 0 AND fase in("
        + ",".join(f"'{f}'" for f in fases)
        + ")"
    )
    while True:
        registros = _fetch_page(API_SECOP2, offset, where)
        if not registros:
            break
        for r in registros:
            try:
                pid = _texto(r.get("id_del_portafolio"), r.get("id_del_proceso"))
                if not pid:
                    continue
                unspsc_raw = _unspsc(
                    r.get("codigo_principal_de_categoria") or r.get("codigo_unspsc")
                )
                p = db.get(Proceso, pid)
                if p is None:
                    p = Proceso(id_proceso=pid)
                    db.add(p)
                p.fuente              = "SECOP2"
                p.entidad             = _texto(r.get("entidad"), r.get("nombre_entidad"))
                p.nit_entidad         = str(r.get("nit_entidad", "") or "")
                p.objeto              = _texto(
                    r.get("nombre_del_procedimiento"),
                    r.get("descripci_n_del_procedimiento"),
                    r.get("descripcion_del_proceso"),
                )
                p.modalidad           = _texto(r.get("modalidad_de_contratacion"))
                p.estado              = _texto(r.get("fase"), r.get("estado_resumen"), r.get("estado_del_procedimiento"))
                p.presupuesto_oficial = _parse_valor(r.get("precio_base") or r.get("valor_del_contrato"))
                p.fecha_publicacion   = _parse_fecha(
                    r.get("fecha_de_publicacion_del") or r.get("fecha_de_ultima_publicaci")
                )
                p.fecha_cierre        = None
                p.departamento        = _norm_departamento(r.get("departamento_entidad") or r.get("departamento"))
                p.municipio           = _texto(r.get("ciudad_de_la_unidad_de"), r.get("ciudad_entidad"), r.get("ciudad"))
                p.unspsc              = unspsc_raw
                p.unspsc_familia      = unspsc_raw[:2] if unspsc_raw else ""
                p.unspsc_clase        = unspsc_raw[:4] if unspsc_raw else ""
                url_p = r.get("urlproceso")
                p.url_proceso = url_p.get("url", "") if isinstance(url_p, dict) else str(url_p or "")
                p.raw = r
                p.score = _score_proceso(
                    p.modalidad, p.estado, p.presupuesto_oficial, p.unspsc, p.fecha_cierre,
                )
                total += 1
            except Exception as e:
                logger.warning(f"Error proceso: {e}")
        db.commit()
        logger.info(f"  Procesos: {total} (offset={offset})")
        offset += PAGE_SIZE
        if len(registros) < PAGE_SIZE:
            break
    return total

def sincronizar_contratos(db: Session) -> int:
    logger.info("Sincronizando contratos...")
    total, offset = 0, 0
    while True:
        registros = _fetch_page(API_CONTRATOS, offset)
        if not registros:
            break
        for r in registros:
            try:
                cid = r.get("id_contrato") or r.get("referencia_del_contrato", "")
                if not cid:
                    continue
                ct = db.get(Contrato, cid)
                if ct is None:
                    ct = Contrato(id=cid)
                    db.add(ct)
                nit_c = _texto(r.get("documento_proveedor"), r.get("nit_del_contratista"))
                valor = _parse_valor(r.get("valor_del_contrato"))
                ct.nit_contratista    = nit_c
                ct.nit_entidad        = str(r.get("nit_entidad", "") or "")
                ct.nombre_contratista = _texto(r.get("proveedor_adjudicado"), r.get("nombre_del_contratista"))
                ct.entidad            = _texto(r.get("nombre_entidad"))
                ct.objeto             = _texto(r.get("objeto_del_contrato"))
                ct.valor_contrato     = valor
                ct.fecha_inicio       = _parse_fecha(r.get("fecha_de_inicio_del_contrato"))
                ct.departamento       = _norm_departamento(r.get("departamento"))
                ct.municipio          = _texto(r.get("ciudad"))
                ct.unspsc             = _unspsc(r.get("codigo_de_categoria_principal") or r.get("codigo_unspsc"))
                ct.modalidad          = r.get("modalidad_de_contratacion", "")
                ct.raw                = r
                total += 1
            except Exception as e:
                logger.warning(f"Error contrato: {e}")
        db.commit()
        logger.info(f"  Contratos: {total} (offset={offset})")
        offset += PAGE_SIZE
        if len(registros) < PAGE_SIZE:
            break
    if total:
        _recalcular_contratistas(db)
    return total

def _score_proceso(modalidad, estado, presupuesto, unspsc, fecha_cierre) -> float:
    """Mismo criterio que m3, sin pandas, calculado una vez al guardar."""
    score = 0.0
    if isinstance(fecha_cierre, datetime):
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

    modalidad_l = _fold(modalidad).lower()
    modalidades = (
        ("minima cuantia", 1.0),
        ("menor cuantia", 0.9),
        ("invitacion abierta", 0.85),
        ("invitacion cerrada", 0.75),
        ("concurso de meritos", 0.65),
        ("licitacion publica", 0.5),
        ("contratacion directa", 0.4),
    )
    s_mod = 0.3
    for key, val in modalidades:
        if key in modalidad_l:
            s_mod = val
            break
    score += s_mod * 20

    try:
        po = float(presupuesto or 0)
    except (TypeError, ValueError):
        po = 0.0
    pmin = float(os.getenv("PRESUPUESTO_MINIMO", "5000000"))
    pmax = float(os.getenv("PRESUPUESTO_MAXIMO", "500000000"))
    if pmin <= po <= pmax:
        s_po = 1.0
    elif po < pmin:
        s_po = max(0.0, 1 - (pmin - po) / pmin) if pmin else 0.0
    else:
        s_po = max(0.0, 1 - (po - pmax) / pmax) if pmax else 0.0
    score += s_po * 20

    codigo = _unspsc(unspsc)
    prefijos = {
        "".join(c for c in p if c.isdigit())[:2]
        for p in os.getenv("UNSPSC_INTERES", "72000000,72100000,72110000,72120000").split(",")
        if p.strip()
    }
    score += 25.0 if any(codigo.startswith(p) for p in prefijos if p) else 0.0

    estado_u = _fold(estado).upper()
    if any(marca in estado_u for marca in ("CONVOCADO", "PRESENTACION DE OFERTA", "FASE DE OFERTAS", "FASE DE SELECCION")):
        s_estado = 1.0
    elif "OBSERVACION" in estado_u:
        s_estado = 0.8
    elif any(marca in estado_u for marca in ("INVITACION", "MANIFESTACION", "EXPRESION", "INTERES")):
        s_estado = 0.7
    elif "BORRADOR" in estado_u:
        s_estado = 0.3
    else:
        s_estado = 0.5
    score += s_estado * 15
    return round(score, 2)

def _recalcular_contratistas(db: Session) -> None:
    """Un pase sobre contratos ya guardados. No suma de nuevo en cada sincronizacion."""
    stats = {}
    consulta = db.query(
        Contrato.nit_contratista,
        Contrato.nombre_contratista,
        Contrato.valor_contrato,
        Contrato.departamento,
        Contrato.unspsc,
        Contrato.modalidad,
    ).filter(Contrato.nit_contratista.isnot(None)).filter(Contrato.nit_contratista != "")
    for nit, nombre, valor, depto, unspsc, mod in consulta.yield_per(2000):
        item = stats.get(nit)
        if item is None:
            item = stats[nit] = {
                "nit": nit,
                "nombre": nombre or "",
                "departamento": depto or "",
                "total_contratos": 0,
                "valor_total_cop": 0.0,
                "sectores_unspsc": {},
                "modalidades": {},
                "departamentos_": {},
            }
        item["total_contratos"] += 1
        item["valor_total_cop"] += float(valor or 0)
        if nombre:
            item["nombre"] = nombre
        if depto:
            item["departamento"] = depto
            item["departamentos_"][depto] = item["departamentos_"].get(depto, 0) + 1
        familia = str(unspsc or "")[:2]
        if familia:
            item["sectores_unspsc"][familia] = item["sectores_unspsc"].get(familia, 0) + 1
        if mod:
            item["modalidades"][mod] = item["modalidades"].get(mod, 0) + 1
    db.query(Contratista).delete(synchronize_session=False)
    if stats:
        db.bulk_insert_mappings(Contratista, list(stats.values()))
    db.commit()

def run_sync_completa():
    db = SessionLocal()
    try:
        n_p = sincronizar_procesos_secop2(db)
        n_c = sincronizar_contratos(db)
        logger.info(f"Sync OK: {n_p} procesos, {n_c} contratos")
        return {"procesos": n_p, "contratos": n_c}
    except Exception as e:
        logger.error(f"Error sync: {e}")
        db.rollback()
        return {"error": str(e)}
    finally:
        db.close()

if __name__ == "__main__":
    run_sync_completa()
