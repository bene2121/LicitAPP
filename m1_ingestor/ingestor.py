"""Script principal de sincronizacion incremental SECOP -> SQLite."""
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import create_engine, select, text
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeElapsedColumn
from rich.console import Console

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from config import DB_PATH, APP_TOKEN, UNSPSC_INTERES, PRESUPUESTO_MIN, PRESUPUESTO_MAX

from m1_ingestor.db_schema import (
    init_db,
    metadata,
    procesos_s2,
    procesos_s1,
    ofertas as ofertas_table,
    sync_log,
)
from m1_ingestor.campos import (
    fila_oferta,
    fila_proceso_s2,
    where_departamentos,
    where_oferta,
    where_procesos_s2,
)
from m1_ingestor.entidades import ENTIDADES, where_entidad
from m1_ingestor.secop_client import SecopClient, SecopRequestError

logger = logging.getLogger(__name__)
console = Console()

# ---------------------------------------------------------------------------
# Utilidades internas
# ---------------------------------------------------------------------------

def _get_engine(db_path: str):
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    return create_engine(f"sqlite:///{db_path}")


def _get_ultimo_sync(engine, tabla: str) -> Optional[str]:
    """Retorna el timestamp ISO del ultimo sync exitoso para 'tabla', o None."""
    with engine.connect() as conn:
        row = conn.execute(
            select(sync_log.c.ultimo_sync).where(sync_log.c.tabla == tabla)
        ).fetchone()
    return row[0] if row else None


def _set_ultimo_sync(engine, tabla: str, ts: str) -> None:
    """Guarda o actualiza el timestamp del ultimo sync."""
    with engine.begin() as conn:
        conn.execute(
            sqlite_insert(sync_log)
            .values(tabla=tabla, ultimo_sync=ts)
            .on_conflict_do_update(
                index_elements=["tabla"],
                set_={"ultimo_sync": ts},
            )
        )


def _upsert_rows(engine, table, rows: list, pk_col: str) -> int:
    """Inserta o actualiza en lotes. SQLite limita las variables por sentencia."""
    if not rows:
        return 0
    unicos = {}
    for row in rows:
        pk = row.get(pk_col)
        if pk:
            unicos[pk] = row
    filas = list(unicos.values())
    if not filas:
        return 0
    columnas = [c.name for c in table.columns]
    stmt = sqlite_insert(table)
    stmt = stmt.on_conflict_do_update(
        index_elements=[pk_col],
        set_={c: stmt.excluded[c] for c in columnas if c != pk_col},
    )
    payload = [{c: row.get(c) for c in columnas} for row in filas]
    lote = max(1, 900 // len(columnas))
    with engine.begin() as conn:
        for i in range(0, len(payload), lote):
            conn.execute(stmt, payload[i:i + lote])
    return len(payload)


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")



# ---------------------------------------------------------------------------
# Funciones publicas
# ---------------------------------------------------------------------------

def sync_procesos_s2(db_path: str = DB_PATH, filtros_config: Optional[dict] = None) -> int:
    """Descarga y sincroniza procesos de SECOP II de forma incremental.

    Args:
        db_path: Ruta a la base de datos SQLite.
        filtros_config: Filtros adicionales (dict con claves SoQL).

    Returns:
        Cantidad de registros insertados/actualizados.
    """
    engine = _get_engine(db_path)
    init_db(db_path)

    client = SecopClient()
    ultimo_sync = _get_ultimo_sync(engine, "procesos_s2")
    ahora = _now_iso()

    depto_where = None
    if filtros_config and "$where" in filtros_config:
        depto_where = filtros_config["$where"]
    params: dict = {
        "$where": where_procesos_s2(
            PRESUPUESTO_MIN,
            PRESUPUESTO_MAX,
            UNSPSC_INTERES,
            ultimo_sync,
            depto_where,
        ),
        "$order": "fecha_de_ultima_publicaci DESC",
    }
    # Hereda otros parametros SoQL del config si los hay
    if filtros_config:
        for k, v in filtros_config.items():
            if k != "$where":
                params[k] = v

    total = 0
    fecha_descarga = ahora

    with Progress(
        SpinnerColumn(),
        TextColumn("[bold cyan]{task.description}"),
        BarColumn(),
        TextColumn("{task.completed} registros"),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Sincronizando SECOP II...", total=None)

        try:
            registros = client.get_procesos_s2(filters=params, max_records=10_000)
        except SecopRequestError as exc:
            console.print(f"[red]SECOP II no respondio:[/red] {exc}")
            return 0
        progress.update(task, total=len(registros))

        rows = []
        for r in registros:
            row = fila_proceso_s2(r, fecha_descarga)
            if row:
                rows.append(row)
            progress.advance(task)

        total = _upsert_rows(engine, procesos_s2, rows, "id_del_proceso")

    _set_ultimo_sync(engine, "procesos_s2", ahora)
    console.print(f"[green]SECOP II:[/green] {total} registros sincronizados.")
    return total


def sync_ofertas(db_path: str = DB_PATH, id_proceso: Optional[str] = None) -> int:
    """Descarga y sincroniza ofertas de uno o todos los procesos.

    Args:
        db_path: Ruta a la base de datos SQLite.
        id_proceso: Si se especifica, solo descarga ofertas de ese proceso.

    Returns:
        Cantidad de registros insertados/actualizados.
    """
    engine = _get_engine(db_path)
    init_db(db_path)

    client = SecopClient()
    ahora = _now_iso()
    total = 0

    with Progress(
        SpinnerColumn(),
        TextColumn("[bold cyan]{task.description}"),
        BarColumn(),
        TextColumn("{task.completed} registros"),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task(
            f"Sincronizando ofertas{'...' if not id_proceso else f' de {id_proceso}...'}",
            total=None,
        )

        try:
            registros = client.get_ofertas(id_proceso=id_proceso)
        except SecopRequestError as exc:
            console.print(f"[red]Ofertas no respondieron:[/red] {exc}")
            return 0
        progress.update(task, total=len(registros))

        rows = []
        for r in registros:
            row = fila_oferta(r)
            if row:
                rows.append(row)
            progress.advance(task)

        total = _upsert_rows(engine, ofertas_table, rows, "identificador_de_la_oferta")

    _set_ultimo_sync(engine, "ofertas", ahora)
    console.print(f"[green]Ofertas:[/green] {total} registros sincronizados.")
    return total


def sync_entidad(codigo: str, db_path: str = DB_PATH, max_records: int = 300) -> int:
    """Descarga procesos abiertos de Ecopetrol o Findeter, sin el filtro de obra civil."""
    ficha = ENTIDADES[codigo]
    engine = _get_engine(db_path)
    init_db(db_path)
    client = SecopClient()
    ahora = _now_iso()
    params = {
        "$where": where_entidad(ficha["nit"]),
        "$order": "fecha_de_ultima_publicaci DESC",
    }
    try:
        registros = client.get_procesos_s2(filters=params, max_records=max_records)
    except SecopRequestError as exc:
        console.print(f"[red]{ficha['nombre']} no respondio:[/red] {exc}")
        return 0
    rows = []
    for registro in registros:
        fila = fila_proceso_s2(registro, ahora, canal_oferta=ficha["canal_oferta"])
        if fila:
            rows.append(fila)
    total = _upsert_rows(engine, procesos_s2, rows, "id_del_proceso")
    _set_ultimo_sync(engine, f"entidad_{codigo.lower()}", ahora)
    console.print(f"[green]{ficha['nombre']}:[/green] {total} procesos.")
    return total


def run_full_sync(db_path: str = DB_PATH, config=None) -> dict:
    """Ejecuta la sincronizacion completa: SECOP II + ofertas.

    Args:
        db_path: Ruta a la base de datos SQLite.
        config: Modulo o dict con configuracion (filtros, etc.).

    Returns:
        Resumen {'s2': N, 'ofertas': N}.
    """
    console.rule("[bold blue]SECOP Automatizador — Sincronizacion completa")

    filtros = {}
    if config and hasattr(config, "DEPARTAMENTOS") and config.DEPARTAMENTOS:
        clausula = where_departamentos(config.DEPARTAMENTOS)
        if clausula:
            filtros["$where"] = clausula

    n_s2 = sync_procesos_s2(db_path=db_path, filtros_config=filtros)
    n_ofertas = sync_ofertas(db_path=db_path)
    n_ecopetrol = sync_entidad("ECOPETROL", db_path=db_path)
    n_findeter = sync_entidad("FINDETER", db_path=db_path)

    resumen = {
        "s2": n_s2,
        "ofertas": n_ofertas,
        "ecopetrol": n_ecopetrol,
        "findeter": n_findeter,
    }
    console.rule("[bold blue]Sincronizacion completada")
    console.print(resumen)
    return resumen


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import config as cfg
    logging.basicConfig(level=logging.INFO)
    run_full_sync(DB_PATH, cfg)
