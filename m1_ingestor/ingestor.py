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
from m1_ingestor.secop_client import SecopClient, SecopRequestError

logger = logging.getLogger(__name__)
console = Console()

# Estados de interes para SECOP II
ESTADOS_INTERES = ("CONVOCADO", "INVITACION_ABIERTA", "EXPRESION_DE_INTERES")


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

    # Construir where clause
    where_parts = []

    # Filtro incremental
    if ultimo_sync:
        where_parts.append(f"fecha_de_ultima_publicaci_n > '{ultimo_sync}'")

    # Filtro de estados
    estados_soql = ",".join(f"'{e}'" for e in ESTADOS_INTERES)
    where_parts.append(f"estado_del_proceso in({estados_soql})")

    # Filtro presupuesto
    where_parts.append(
        f"precio_base >= {PRESUPUESTO_MIN} AND precio_base <= {PRESUPUESTO_MAX}"
    )

    # Filtro UNSPSC obras civiles (codigo nivel 72)
    if UNSPSC_INTERES:
        unspsc_conditions = " OR ".join(
            f"unspsc_codigo_primer_nivel like '{p[:2]}%'" for p in UNSPSC_INTERES
        )
        where_parts.append(f"({unspsc_conditions})")

    # Filtros externos adicionales
    if filtros_config and "$where" in filtros_config:
        where_parts.append(f"({filtros_config['$where']})")

    params: dict = {
        "$where": " AND ".join(where_parts),
        "$order": "fecha_de_ultima_publicaci_n DESC",
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
            row = {
                "id_del_proceso": r.get("proceso_de_compra") or r.get("id_del_proceso", ""),
                "referencia": r.get("referencia_del_proceso", ""),
                "entidad": r.get("nombre_entidad", ""),
                "titulo": r.get("objeto_a_contratar", ""),
                "modalidad": r.get("modalidad_de_contratacion", ""),
                "estado": r.get("estado_del_proceso", ""),
                "presupuesto_oficial": _to_float(r.get("precio_base")),
                "fecha_cierre": r.get("fecha_de_cierre_del_proceso", ""),
                "unspsc": r.get("unspsc_codigo_primer_nivel", ""),
                "departamento_entidad": r.get("departamento_entidad", ""),
                "ciudad_unidad": r.get("ciudad_de_la_unidad_de_contratacion", ""),
                "url_proceso": r.get("urlproceso", {}).get("url", "") if isinstance(r.get("urlproceso"), dict) else r.get("urlproceso", ""),
                "fecha_modificacion": r.get("fecha_de_ultima_publicaci_n", ""),
                "lotes": int(r.get("tiene_lotes", 0) or 0),
                "fecha_descarga": fecha_descarga,
            }
            if row["id_del_proceso"]:
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
            row = {
                "identificador_de_la_oferta": r.get("identificador_de_la_oferta", ""),
                "id_del_proceso": r.get("id_del_proceso", ""),
                "nit_oferente": r.get("nit_del_proveedor_oferente", ""),
                "nombre_oferente": r.get("nombre_del_proveedor_oferente", ""),
                "propuesta_economica": _to_float(r.get("valor_de_la_oferta")),
                "fecha_oferta": r.get("fecha_de_presentaci_n_de_la_oferta", ""),
            }
            if row["identificador_de_la_oferta"]:
                rows.append(row)
            progress.advance(task)

        total = _upsert_rows(engine, ofertas_table, rows, "identificador_de_la_oferta")

    _set_ultimo_sync(engine, "ofertas", ahora)
    console.print(f"[green]Ofertas:[/green] {total} registros sincronizados.")
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
        deps_limpios = [d.replace("'", "").strip() for d in config.DEPARTAMENTOS if d]
        deps = ",".join(f"'{d}'" for d in deps_limpios if d)
        if deps:
            filtros["$where"] = f"departamento_entidad in({deps})"

    n_s2 = sync_procesos_s2(db_path=db_path, filtros_config=filtros)
    n_ofertas = sync_ofertas(db_path=db_path)

    resumen = {"s2": n_s2, "ofertas": n_ofertas}
    console.rule("[bold blue]Sincronizacion completada")
    console.print(resumen)
    return resumen


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _to_float(value) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import config as cfg
    logging.basicConfig(level=logging.INFO)
    run_full_sync(DB_PATH, cfg)
