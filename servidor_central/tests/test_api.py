"""Tests de la API central usando SQLite en memoria."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

TEST_DB = "sqlite:///:memory:"

@pytest.fixture(scope="module")
def client():
    from servidor_central.db import Base, get_db
    eng = create_engine(TEST_DB, connect_args={"check_same_thread": False})
    # SQLite no soporta JSONB — monkey-patch para test
    import sqlalchemy.dialects.postgresql as pg
    from sqlalchemy import JSON
    if not hasattr(pg, '_patched'):
        pg.JSONB = JSON
        pg._patched = True
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
    with TestClient(app) as c:
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
