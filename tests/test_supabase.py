from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.auth import SupabaseAuthProvider
from app.models import Session, User
from app.storage import SupabaseStorage, process_document


def provider():
    return SupabaseAuthProvider(
        supabase_url="https://example.supabase.co", anon_key="test-public-key"
    )


def identity(**overrides):
    return {
        "id": "11111111-2222-4333-8444-555555555555",
        "email": "pilot@example.test",
        "email_confirmed_at": "2026-09-01T00:00:00Z",
        "user_metadata": {"full_name": "Test Pilot"},
    } | overrides


def test_verified_immutable_subject(factory, monkeypatch):
    monkeypatch.setattr(httpx, "get", lambda *a, **kw: httpx.Response(200, json=identity()))
    with factory() as db:
        user = provider().identify(db, "provider-verified-token")
        assert user.email == "pilot@example.test"
        assert user.auth_subject == "supabase:" + identity()["id"]
        assert provider().identify(db, "provider-verified-token").id == user.id


@pytest.mark.parametrize(
    "status,data", [(401, {}), (200, identity(email_confirmed_at=None)), (200, identity(id=None))]
)
def test_invalid_identity_rejected(factory, monkeypatch, status, data):
    monkeypatch.setattr(httpx, "get", lambda *a, **kw: httpx.Response(status, json=data))
    with factory() as db, pytest.raises(HTTPException) as error:
        provider().identify(db, "untrusted-token")
    assert error.value.status_code == 401


def test_identity_outage_fails_closed(factory, monkeypatch):
    def outage(*a, **kw):
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(httpx, "get", outage)
    with factory() as db, pytest.raises(HTTPException) as error:
        provider().identify(db, "token")
    assert error.value.status_code == 503


def test_email_otp_exchange(factory, monkeypatch):
    calls = []

    def post(url, **kwargs):
        calls.append((url, kwargs["json"]))
        return httpx.Response(200, json={"access_token": "verified-token"})

    monkeypatch.setattr(httpx, "post", post)
    monkeypatch.setattr(httpx, "get", lambda *a, **kw: httpx.Response(200, json=identity()))
    with factory() as db:
        provider().request_code("pilot@example.test", "Pilot")
        assert (
            provider().verify_code(db, "pilot@example.test", "123456").email == "pilot@example.test"
        )
    assert calls[1][1] == {"email": "pilot@example.test", "token": "123456", "type": "email"}


def test_supabase_revoke(factory):
    with factory() as db:
        user = User(email="revoke@example.test", name="Revoke")
        db.add(user)
        db.flush()
        db.add(
            Session(
                token_hash="fakehash",
                user_id=user.id,
                csrf="csrf",
                expires_at=datetime.now(UTC) + timedelta(hours=1),
            )
        )
        db.commit()
        provider().revoke(db, user.id)
        db.commit()
        assert db.scalar(select(Session).where(Session.user_id == user.id)) is None


def test_bucket_must_be_private(monkeypatch):
    storage = SupabaseStorage()
    storage.url, storage.key = "https://example.supabase.co", "test-service-key"
    monkeypatch.setattr(httpx, "get", lambda *a, **kw: httpx.Response(200, json={"public": True}))
    assert not storage.health()
    monkeypatch.setattr(httpx, "get", lambda *a, **kw: httpx.Response(200, json={"public": False}))
    assert storage.health()


def test_delete_failure_is_not_success(monkeypatch):
    monkeypatch.setattr(httpx, "delete", lambda *a, **kw: httpx.Response(503))
    with pytest.raises(HTTPException):
        SupabaseStorage().delete("a" * 64)


def test_storage_traversal_rejected():
    with pytest.raises(ValueError):
        SupabaseStorage().get("../other-bucket/secret")


def test_remote_scan_does_not_require_storage_path(monkeypatch):
    import hashlib
    from pathlib import Path
    from types import SimpleNamespace

    from app.config import settings

    data = b"Company evidence"
    doc = SimpleNamespace(
        object_key="a" * 64,
        content_hash=hashlib.sha256(data).hexdigest(),
        mime="text/plain",
        status="QUARANTINED",
    )
    storage = SimpleNamespace(get=lambda key: data)
    monkeypatch.setattr(settings(), "malware_command", "clamscan --no-summary")
    paths = []

    def scan(command, **kwargs):
        paths.append(Path(command[-1]))
        assert paths[-1].read_bytes() == data
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr("app.storage.subprocess.run", scan)
    process_document(storage, doc)
    assert doc.status == "READY" and not paths[0].exists()


def test_hosted_login_never_exposes_development_code(client, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings(), "auth_provider", "supabase")
    monkeypatch.setattr(
        httpx, "post", lambda *a, **kw: httpx.Response(200, json={"access_token": "verified"})
    )
    monkeypatch.setattr(httpx, "get", lambda *a, **kw: httpx.Response(200, json=identity()))
    response = client.post("/api/v1/auth/request", json={"email": "pilot@example.test"})
    assert response.json()["provider"] == "supabase"
    assert "development_code" not in response.json()
    assert (
        client.post(
            "/api/v1/auth/verify", json={"email": "pilot@example.test", "token": "123456"}
        ).status_code
        == 200
    )
