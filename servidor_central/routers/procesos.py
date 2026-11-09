from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_
from typing import Optional
from datetime import datetime, timedelta, timezone


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)
from ..db import get_db
from ..models import Proceso

router = APIRouter()

@router.get("/")
def listar_procesos(
    db: Session = Depends(get_db),
    departamento: Optional[str] = Query(None),
    municipio: Optional[str] = Query(None),
    unspsc_familia: Optional[str] = Query(None),
    unspsc_clase: Optional[str] = Query(None),
    unspsc: Optional[str] = Query(None),
    modalidad: Optional[str] = Query(None),
    estado: Optional[str] = Query(None),
    fuente: Optional[str] = Query(None),
    q: Optional[str] = Query(None),
    entidad: Optional[str] = Query(None),
    nit_entidad: Optional[str] = Query(None),
    po_min: Optional[float] = Query(None),
    po_max: Optional[float] = Query(None),
    score_min: Optional[float] = Query(0.0),
    dias_cierre_max: Optional[int] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
):
    q_obj = db.query(Proceso)
    if departamento:
        q_obj = q_obj.filter(Proceso.departamento == departamento.upper())
    if municipio:
        q_obj = q_obj.filter(Proceso.municipio.ilike(f"%{municipio}%"))
    if unspsc_familia:
        q_obj = q_obj.filter(Proceso.unspsc_familia == unspsc_familia)
    if unspsc_clase:
        q_obj = q_obj.filter(Proceso.unspsc_clase == unspsc_clase)
    if unspsc:
        q_obj = q_obj.filter(Proceso.unspsc == unspsc)
    if modalidad:
        q_obj = q_obj.filter(Proceso.modalidad.ilike(f"%{modalidad}%"))
    if estado:
        estados = [e.strip().upper() for e in estado.split(",")]
        q_obj = q_obj.filter(Proceso.estado.in_(estados))
    if fuente:
        q_obj = q_obj.filter(Proceso.fuente == fuente.upper())
    if q:
        term = f"%{q}%"
        q_obj = q_obj.filter(or_(
            Proceso.objeto.ilike(term),
            Proceso.entidad.ilike(term),
            Proceso.id_proceso.ilike(term),
        ))
    if entidad:
        q_obj = q_obj.filter(Proceso.entidad.ilike(f"%{entidad}%"))
    if nit_entidad:
        q_obj = q_obj.filter(Proceso.nit_entidad == nit_entidad)
    if po_min is not None:
        q_obj = q_obj.filter(Proceso.presupuesto_oficial >= po_min)
    if po_max is not None:
        q_obj = q_obj.filter(Proceso.presupuesto_oficial <= po_max)
    if score_min:
        q_obj = q_obj.filter(Proceso.score >= score_min)
    if dias_cierre_max:
        fecha_limite = _utcnow() + timedelta(days=dias_cierre_max)
        q_obj = q_obj.filter(or_(
            Proceso.fecha_cierre.is_(None),
            and_(
                Proceso.fecha_cierre <= fecha_limite,
                Proceso.fecha_cierre >= _utcnow(),
            ),
        ))
    total = q_obj.count()
    items = (
        q_obj.order_by(Proceso.score.desc(), Proceso.fecha_cierre.asc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return {
        "total": total, "page": page, "page_size": page_size,
        "items": [_to_dict(p) for p in items],
    }

@router.get("/{id_proceso}")
def detalle_proceso(id_proceso: str, db: Session = Depends(get_db)):
    p = db.query(Proceso).filter(Proceso.id_proceso == id_proceso).first()
    if not p:
        raise HTTPException(status_code=404, detail="Proceso no encontrado")
    return _to_dict(p)

def _to_dict(p: Proceso) -> dict:
    def _dias(f):
        if not f:
            return None
        return max(0, (f - _utcnow()).days)
    return {
        "id": p.id_proceso, "fuente": p.fuente,
        "entidad": p.entidad, "nit_entidad": p.nit_entidad,
        "objeto": p.objeto, "modalidad": p.modalidad, "estado": p.estado,
        "presupuesto_oficial": p.presupuesto_oficial,
        "fecha_publicacion": p.fecha_publicacion.isoformat() if p.fecha_publicacion else None,
        "fecha_cierre": p.fecha_cierre.isoformat() if p.fecha_cierre else None,
        "dias_al_cierre": _dias(p.fecha_cierre),
        "departamento": p.departamento, "municipio": p.municipio,
        "unspsc": p.unspsc, "unspsc_familia": p.unspsc_familia,
        "unspsc_clase": p.unspsc_clase, "score": p.score,
        "url_proceso": p.url_proceso,
    }
