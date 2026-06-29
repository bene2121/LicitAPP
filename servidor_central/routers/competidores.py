from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func
from ..db import get_db
from ..models import Contratista, Contrato, Proceso

router = APIRouter()

@router.get("/prediccion/{id_proceso}")
def predecir_competidores(id_proceso: str, db: Session = Depends(get_db)):
    proceso = db.query(Proceso).filter(Proceso.id_proceso == id_proceso).first()
    if not proceso:
        raise HTTPException(404, "Proceso no encontrado")
    rivales_entidad = (
        db.query(
            Contrato.nit_contratista, Contrato.nombre_contratista,
            func.count(Contrato.id).label("veces_entidad"),
            func.avg(Contrato.valor_contrato).label("valor_promedio"),
        )
        .filter(Contrato.nit_entidad == proceso.nit_entidad)
        .group_by(Contrato.nit_contratista, Contrato.nombre_contratista)
        .order_by(func.count(Contrato.id).desc())
        .limit(10).all()
    )
    rivales_sector = (
        db.query(
            Contrato.nit_contratista, Contrato.nombre_contratista,
            func.count(Contrato.id).label("veces_sector"),
        )
        .filter(Contrato.unspsc.like(f"{proceso.unspsc_familia or '72'}%"))
        .filter(Contrato.departamento == proceso.departamento)
        .group_by(Contrato.nit_contratista, Contrato.nombre_contratista)
        .order_by(func.count(Contrato.id).desc())
        .limit(10).all()
    )
    scores: dict = {}
    for r in rivales_entidad:
        scores[r.nit_contratista] = {
            "nit": r.nit_contratista, "nombre": r.nombre_contratista,
            "veces_entidad": r.veces_entidad, "veces_sector": 0,
            "valor_promedio": float(r.valor_promedio or 0),
        }
    for r in rivales_sector:
        if r.nit_contratista in scores:
            scores[r.nit_contratista]["veces_sector"] = r.veces_sector
        else:
            scores[r.nit_contratista] = {
                "nit": r.nit_contratista, "nombre": r.nombre_contratista,
                "veces_entidad": 0, "veces_sector": r.veces_sector,
                "valor_promedio": 0,
            }
    rivales = sorted(
        scores.values(),
        key=lambda x: x["veces_entidad"] * 2 + x["veces_sector"],
        reverse=True,
    )[:8]
    return {
        "id_proceso": id_proceso, "entidad": proceso.entidad,
        "sector_unspsc": proceso.unspsc_familia,
        "rivales_probables": rivales,
    }

@router.get("/{nit}")
def perfil_competidor(nit: str, db: Session = Depends(get_db)):
    c = db.query(Contratista).filter(Contratista.nit == nit).first()
    if not c:
        raise HTTPException(404, f"NIT {nit} no encontrado")
    contratos = (
        db.query(Contrato).filter(Contrato.nit_contratista == nit)
        .order_by(Contrato.fecha_inicio.desc()).limit(10).all()
    )
    return {
        "nit": c.nit, "nombre": c.nombre,
        "total_contratos": c.total_contratos,
        "valor_total_cop": c.valor_total_cop,
        "sectores_unspsc": c.sectores_unspsc or {},
        "modalidades": c.modalidades or {},
        "departamentos": c.departamentos_ or {},
        "pct_descuento_avg": c.pct_descuento_avg,
        "contratos_recientes": [
            {
                "id": ct.id, "entidad": ct.entidad,
                "objeto": (ct.objeto or "")[:100],
                "valor": ct.valor_contrato,
                "fecha": ct.fecha_inicio.isoformat() if ct.fecha_inicio else None,
                "departamento": ct.departamento, "modalidad": ct.modalidad,
            }
            for ct in contratos
        ],
    }
