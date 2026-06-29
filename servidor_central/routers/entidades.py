from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import Optional
from ..db import get_db
from ..models import Proceso, Contrato

router = APIRouter()

@router.get("/")
def buscar_entidades(
    db: Session = Depends(get_db),
    q: Optional[str] = Query(None),
    departamento: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(30, ge=1, le=100),
):
    query = db.query(
        Proceso.nit_entidad, Proceso.entidad, Proceso.departamento,
        func.count(Proceso.id_proceso).label("total_procesos"),
        func.sum(Proceso.presupuesto_oficial).label("presupuesto_total"),
    ).group_by(Proceso.nit_entidad, Proceso.entidad, Proceso.departamento)
    if q:
        query = query.filter(Proceso.entidad.ilike(f"%{q}%"))
    if departamento:
        query = query.filter(Proceso.departamento == departamento.upper())
    total = query.count()
    items = (
        query.order_by(func.count(Proceso.id_proceso).desc())
        .offset((page - 1) * page_size).limit(page_size).all()
    )
    return {
        "total": total,
        "items": [
            {
                "nit_entidad": r.nit_entidad, "entidad": r.entidad,
                "departamento": r.departamento,
                "total_procesos": r.total_procesos,
                "presupuesto_total": float(r.presupuesto_total or 0),
            }
            for r in items
        ],
    }

@router.get("/{nit_entidad}")
def detalle_entidad(nit_entidad: str, db: Session = Depends(get_db)):
    procesos = (
        db.query(Proceso).filter(Proceso.nit_entidad == nit_entidad)
        .order_by(Proceso.fecha_publicacion.desc()).limit(50).all()
    )
    if not procesos:
        raise HTTPException(404, "Entidad no encontrada")
    nombre = procesos[0].entidad
    depto  = procesos[0].departamento
    habituales = (
        db.query(
            Contrato.nit_contratista, Contrato.nombre_contratista,
            func.count(Contrato.id).label("contratos_ganados"),
            func.sum(Contrato.valor_contrato).label("valor_total"),
        )
        .filter(Contrato.nit_entidad == nit_entidad)
        .group_by(Contrato.nit_contratista, Contrato.nombre_contratista)
        .order_by(func.count(Contrato.id).desc()).limit(10).all()
    )
    cercanas = (
        db.query(
            Proceso.nit_entidad, Proceso.entidad,
            func.count(Proceso.id_proceso).label("n"),
        )
        .filter(Proceso.departamento == depto)
        .filter(Proceso.nit_entidad != nit_entidad)
        .group_by(Proceso.nit_entidad, Proceso.entidad)
        .order_by(func.count(Proceso.id_proceso).desc()).limit(5).all()
    )
    return {
        "nit_entidad": nit_entidad, "nombre": nombre, "departamento": depto,
        "total_procesos": len(procesos),
        "contratistas_habituales": [
            {
                "nit": h.nit_contratista, "nombre": h.nombre_contratista,
                "contratos_ganados": h.contratos_ganados,
                "valor_total": float(h.valor_total or 0),
            }
            for h in habituales
        ],
        "entidades_cercanas": [
            {"nit": c.nit_entidad, "nombre": c.entidad, "procesos": c.n}
            for c in cercanas
        ],
    }
