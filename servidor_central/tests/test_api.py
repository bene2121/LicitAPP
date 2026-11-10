"""Tests de la API central usando SQLite en memoria."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

TEST_DB = "sqlite:///:memory:"

@pytest.fixture(scope="module")
def client(tmp_path_factory):
    # Base de licencias y base de datos temporales: los endpoints exigen X-License-Key (C-4).
    import os, sqlite3
    tmp = tmp_path_factory.mktemp("central")
    lic_db = tmp / "clientes.db"
    con = sqlite3.connect(lic_db)
    con.execute("CREATE TABLE clientes (license_id TEXT, activo INTEGER, fecha_vencimiento TEXT)")
    con.execute("INSERT INTO clientes VALUES ('TEST-LIC', 1, '2099-12-31')")
    con.commit()
    con.close()
    os.environ["SECOP_ADMIN_DB"] = str(lic_db)
    os.environ.setdefault("DATABASE_URL", f"sqlite:///{tmp / 'central.db'}")
    from servidor_central.db import Base, get_db
    from sqlalchemy.pool import StaticPool  # una sola conexión: la BD en memoria vive entre hilos
    eng = create_engine(TEST_DB, connect_args={"check_same_thread": False}, poolclass=StaticPool)
    # SQLite no soporta JSONB — monkey-patch para test
    import sqlalchemy.dialects.postgresql as pg
    from sqlalchemy import JSON
    if not hasattr(pg, '_patched'):
        pg.JSONB = JSON
        pg._patched = True
    import servidor_central.models  # noqa: F401  registra las tablas antes de crearlas
    Base.metadata.create_all(bind=eng)
    S = sessionmaker(bind=eng)
    def override():
        db = S()
        try:
            yield db
        finally:
            db.close()
    from servidor_central.main import app
    app.dependency_overrides[get_db] = override
    with TestClient(app, headers={"X-License-Key": "TEST-LIC"}) as c:
        yield c

def test_health(client):
    r = client.get("/v1/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"

def test_procesos_empty(client):
    r = client.get("/v1/procesos/")
    assert r.status_code == 200
    assert r.json()["total"] == 0

def test_proceso_404(client):
    r = client.get("/v1/procesos/NO-EXISTE")
    assert r.status_code == 404

def test_entidades_empty(client):
    r = client.get("/v1/entidades/")
    assert r.status_code == 200

def test_competidor_404(client):
    r = client.get("/v1/competidores/000000000")
    assert r.status_code == 404
