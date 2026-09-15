import json
import os

# Unit tests must never inherit a real Supabase connection from the owner's .env.
os.environ["DATABASE_URL"] = "sqlite:///./var/test-bootstrap.db"
os.environ["ENVIRONMENT"] = "test"
os.environ["AUTH_PROVIDER"] = "local"
os.environ["STORAGE_PROVIDER"] = "local"
os.environ["TED_ENABLED"] = "false"
os.environ["SUPABASE_URL"] = "https://example.supabase.co"
os.environ["SUPABASE_ANON_KEY"] = "test-public-key"
os.environ["SUPABASE_SERVICE_ROLE_KEY"] = "test-service-key"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.db import Base, get_db, make_engine
from app.ingest import ingest
from app.main import app, rate_windows
from scripts.seed_demo import demo_notices


@pytest.fixture
def factory(tmp_path, monkeypatch):
    engine = make_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(settings(), "storage_path", tmp_path / "objects")
    monkeypatch.setattr(settings(), "ted_enabled", False)
    monkeypatch.setattr(settings(), "environment", "test")
    yield factory
    engine.dispose()


@pytest.fixture
def client(factory):
    def override():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = override
    rate_windows.clear()
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


def sign_in(client, email="owner@example.test", company="Example SME"):
    r = client.post("/api/v1/auth/request", json={"email": email, "name": "Alex"})
    assert r.status_code == 200, r.text
    r = client.post("/api/v1/auth/verify", json={"token": r.json()["development_code"]})
    assert r.status_code == 200, r.text
    client.headers["X-CSRF-Token"] = r.json()["csrf"]
    if company:
        r = client.post("/api/v1/organizations", json={"name": company})
        assert r.status_code == 200, r.text
        return r.json()["id"]


@pytest.fixture
def signed(client):
    sign_in(client)
    return client


@pytest.fixture
def notice_id(factory):
    row = next(demo_notices())
    with factory() as db:
        notice, _ = ingest(db, row, json.dumps(row), source="DEMO")
        db.commit()
        return notice.id
