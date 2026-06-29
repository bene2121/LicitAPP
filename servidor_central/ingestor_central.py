"""Ingestor central — corre en el VPS cada 6 horas. Descarga SECOP I+II a PostgreSQL."""
import os, logging, httpx
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

def sincronizar_procesos_secop2(db: Session) -> int:
    logger.info("Sincronizando procesos SECOP II...")
    total, offset = 0, 0
    where = "estado_del_proceso IN ('En Proceso de Seleccion','Convocado','Invitacion Abierta')"
    while True:
        registros = _fetch_page(API_SECOP2, offset, where)
        if not registros:
            break
        for r in registros:
            try:
                pid = r.get("id_del_proceso") or r.get("numero_del_proceso", "")
                if not pid:
                    continue
                unspsc_raw = str(r.get("codigo_unspsc", "") or "")
                p = db.get(Proceso, pid)
                if p is None:
                    p = Proceso(id_proceso=pid)
                    db.add(p)
                p.fuente              = "SECOP2"
                p.entidad             = r.get("nombre_entidad", "")
                p.nit_entidad         = str(r.get("nit_entidad", "") or "")
                p.objeto              = r.get("descripcion_del_proceso") or r.get("nombre_del_procedimiento", "")
                p.modalidad           = r.get("modalidad_de_contratacion", "")
                p.estado              = r.get("estado_del_proceso", "")
                p.presupuesto_oficial = _parse_valor(r.get("precio_base") or r.get("valor_del_contrato"))
                p.fecha_cierre        = _parse_fecha(r.get("fecha_de_cierre_del_proceso") or r.get("fecha_limite_de_recepcion_de_propuestas"))
                p.departamento        = str(r.get("departamento", "") or "").upper()
                p.municipio           = str(r.get("ciudad", "") or r.get("municipio", "") or "")
                p.unspsc              = unspsc_raw
                p.unspsc_familia      = unspsc_raw[:2] if unspsc_raw else ""
                p.unspsc_clase        = unspsc_raw[:4] if unspsc_raw else ""
                url_p = r.get("urlproceso")
                p.url_proceso = url_p.get("url", "") if isinstance(url_p, dict) else str(url_p or "")
                p.raw = r
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
                nit_c = str(r.get("nit_del_contratista", "") or "")
                valor = _parse_valor(r.get("valor_del_contrato"))
                ct.nit_contratista    = nit_c
                ct.nit_entidad        = str(r.get("nit_entidad", "") or "")
                ct.nombre_contratista = r.get("nombre_del_contratista", "")
                ct.entidad            = r.get("nombre_entidad", "")
                ct.objeto             = r.get("objeto_del_contrato", "")
                ct.valor_contrato     = valor
                ct.fecha_inicio       = _parse_fecha(r.get("fecha_de_inicio_del_contrato"))
                ct.departamento       = str(r.get("departamento", "") or "").upper()
                ct.municipio          = str(r.get("ciudad", "") or "")
                ct.unspsc             = str(r.get("codigo_unspsc", "") or "")
                ct.modalidad          = r.get("modalidad_de_contratacion", "")
                ct.raw                = r
                if nit_c:
                    _actualizar_contratista(db, nit_c, r, valor)
                total += 1
            except Exception as e:
                logger.warning(f"Error contrato: {e}")
        db.commit()
        logger.info(f"  Contratos: {total} (offset={offset})")
        offset += PAGE_SIZE
        if len(registros) < PAGE_SIZE:
            break
    return total

def _actualizar_contratista(db: Session, nit: str, r: dict, valor: float):
    c = db.get(Contratista, nit)
    if c is None:
        c = Contratista(nit=nit)
        db.add(c)
    c.nombre            = r.get("nombre_del_contratista", c.nombre or "")
    c.departamento      = str(r.get("departamento", "") or "").upper()
    c.total_contratos   = (c.total_contratos or 0) + 1
    c.valor_total_cop   = (c.valor_total_cop or 0.0) + valor
    unspsc2 = str(r.get("codigo_unspsc", "") or "")[:2]
    s = dict(c.sectores_unspsc or {})
    s[unspsc2] = s.get(unspsc2, 0) + 1
    c.sectores_unspsc = s
    depto = str(r.get("departamento", "") or "").upper()
    d = dict(c.departamentos_ or {})
    d[depto] = d.get(depto, 0) + 1
    c.departamentos_ = d
    mod = r.get("modalidad_de_contratacion", "")
    if mod:
        m = dict(c.modalidades or {})
        m[mod] = m.get(mod, 0) + 1
        c.modalidades = m

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
