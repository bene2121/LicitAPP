"""Schema SQLite para SECOP Automatizador — usando SQLAlchemy Core (sin ORM)."""
import os
import sys

from sqlalchemy import (
    Column,
    Float,
    Integer,
    MetaData,
    Table,
    Text,
    create_engine,
)

# Permite importar config desde el directorio raiz del proyecto
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from config import DB_PATH

metadata = MetaData()

procesos_s2 = Table(
    "procesos_s2",
    metadata,
    Column("id_del_proceso", Text, primary_key=True),
    Column("referencia", Text),
    Column("entidad", Text),
    Column("titulo", Text),
    Column("modalidad", Text),
    Column("estado", Text),
    Column("presupuesto_oficial", Float),
    Column("fecha_cierre", Text),
    Column("unspsc", Text),
    Column("departamento_entidad", Text),
    Column("ciudad_unidad", Text),
    Column("url_proceso", Text),
    Column("fecha_modificacion", Text),
    Column("lotes", Integer, default=0),
    Column("fecha_descarga", Text),
    Column("nit_entidad", Text),
    Column("canal_oferta", Text),
)

procesos_s1 = Table(
    "procesos_s1",
    metadata,
    Column("numero_de_proceso", Text, primary_key=True),
    Column("entidad", Text),
    Column("objeto", Text),
    Column("modalidad", Text),
    Column("fase", Text),
    Column("presupuesto_oficial", Float),
    Column("municipio_departamento", Text),
    Column("segmento", Text),
    Column("familia", Text),
    Column("clase", Text),
    Column("fecha_cargue", Text),
    Column("fecha_modificacion", Text),
    Column("url_proceso", Text),
    Column("fecha_descarga", Text),
)

ofertas = Table(
    "ofertas",
    metadata,
    Column("identificador_de_la_oferta", Text, primary_key=True),
    Column("id_del_proceso", Text),
    Column("nit_oferente", Text),
    Column("nombre_oferente", Text),
    Column("propuesta_economica", Float),
    Column("fecha_oferta", Text),
)

hitos_seguimiento = Table(
    "hitos_seguimiento",
    metadata,
    Column("id", Text, primary_key=True),
    Column("id_proceso", Text),
    Column("secop", Integer),
    Column("hito1_fecha", Text),
    Column("hito1_nombre", Text),
    Column("hito2_fecha", Text),
    Column("hito2_nombre", Text),
    Column("hito3_fecha", Text),
    Column("hito3_nombre", Text),
    Column("hito4_fecha", Text),
    Column("hito4_nombre", Text),
)

sync_log = Table(
    "sync_log",
    metadata,
    Column("tabla", Text, primary_key=True),
    Column("ultimo_sync", Text),
)


def init_db(db_path: str = DB_PATH):
    """Crea todas las tablas en la base de datos SQLite si no existen."""
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    engine = create_engine(f"sqlite:///{db_path}")
    metadata.create_all(engine)
    _agregar_columnas(engine)
    print(f"[db_schema] Base de datos inicializada en: {db_path}")
    return engine


def _agregar_columnas(engine):
    """SQLite no altera tablas viejas con create_all."""
    from sqlalchemy import text
    with engine.begin() as conn:
        existentes = {fila[1] for fila in conn.execute(text("PRAGMA table_info(procesos_s2)"))}
        if "nit_entidad" not in existentes:
            conn.execute(text("ALTER TABLE procesos_s2 ADD COLUMN nit_entidad TEXT"))
        if "canal_oferta" not in existentes:
            conn.execute(text("ALTER TABLE procesos_s2 ADD COLUMN canal_oferta TEXT"))


if __name__ == "__main__":
    init_db()
