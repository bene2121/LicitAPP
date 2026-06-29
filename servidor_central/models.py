from sqlalchemy import Column, String, Float, DateTime, Integer, Text, Index, Boolean
from sqlalchemy.dialects.postgresql import JSONB
from datetime import datetime
from .db import Base

class Proceso(Base):
    __tablename__ = "procesos"
    id_proceso          = Column(String, primary_key=True)
    fuente              = Column(String, default="SECOP2")
    entidad             = Column(String, index=True)
    nit_entidad         = Column(String, index=True)
    objeto              = Column(Text)
    modalidad           = Column(String, index=True)
    estado              = Column(String, index=True)
    presupuesto_oficial = Column(Float)
    fecha_publicacion   = Column(DateTime)
    fecha_cierre        = Column(DateTime, index=True)
    departamento        = Column(String, index=True)
    municipio           = Column(String, index=True)
    unspsc              = Column(String, index=True)
    unspsc_familia      = Column(String, index=True)
    unspsc_clase        = Column(String, index=True)
    score               = Column(Float, default=0.0)
    url_proceso         = Column(String)
    raw                 = Column(JSONB)
    updated_at          = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    __table_args__ = (
        Index("ix_proc_depto_estado", "departamento", "estado"),
        Index("ix_proc_unspsc_familia", "unspsc_familia", "estado"),
        Index("ix_proc_cierre", "fecha_cierre"),
    )

class Contratista(Base):
    __tablename__ = "contratistas"
    nit               = Column(String, primary_key=True)
    nombre            = Column(String, index=True)
    departamento      = Column(String)
    total_contratos   = Column(Integer, default=0)
    valor_total_cop   = Column(Float, default=0.0)
    sectores_unspsc   = Column(JSONB)
    modalidades       = Column(JSONB)
    departamentos_    = Column("departamentos", JSONB)
    pct_descuento_avg = Column(Float)
    updated_at        = Column(DateTime, default=datetime.utcnow)

class Contrato(Base):
    __tablename__ = "contratos"
    id                 = Column(String, primary_key=True)
    nit_contratista    = Column(String, index=True)
    nit_entidad        = Column(String, index=True)
    nombre_contratista = Column(String)
    entidad            = Column(String)
    objeto             = Column(Text)
    valor_contrato     = Column(Float)
    fecha_inicio       = Column(DateTime)
    departamento       = Column(String, index=True)
    municipio          = Column(String)
    unspsc             = Column(String, index=True)
    modalidad          = Column(String)
    raw                = Column(JSONB)
    updated_at         = Column(DateTime, default=datetime.utcnow)
    __table_args__ = (
        Index("ix_contrato_nit_fecha", "nit_contratista", "fecha_inicio"),
    )

class ClienteLicencia(Base):
    __tablename__ = "clientes_licencia"
    nit        = Column(String, primary_key=True)
    plan       = Column(String, default="basico")
    activo     = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
