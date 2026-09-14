import io
import zipfile

import pytest
from fastapi import HTTPException

from app.storage import LocalStorage, validate_upload
from app.ted import archive_members, normalize_xml, safe_url
from tests.conftest import sign_in


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1",
        "https://169.254.169.254/latest/meta-data",
        "file:///etc/passwd",
        "https://ted.europa.eu.evil.test",
        "https://ted.europa.eu@evil.test",
        "https://ted.europa.eu:444/x",
        "https://localhost",
    ],
)
def test_ssrf_rejected(url):
    with pytest.raises(ValueError):
        safe_url(url, resolve=False)


@pytest.mark.parametrize(
    "data,name",
    [
        (b"MZexecutable", "certificate.pdf"),
        (b"<script>alert(1)</script>", "cert.txt"),
        (b"hello", "../cert.txt"),
        (b"%PDF-1.7 /JavaScript", "cert.pdf"),
        (b"\x89PNG\x00", "cert.txt"),
    ],
)
def test_upload_spoofing_and_traversal(data, name):
    with pytest.raises(HTTPException):
        validate_upload(data, name)


def test_oversize():
    with pytest.raises(HTTPException) as exc:
        validate_upload(b"a" * (10 * 1024 * 1024 + 1), "a.txt")
    assert exc.value.status_code == 413


def test_xxe_and_zip_path_traversal():
    with pytest.raises(Exception):
        normalize_xml(b'<!DOCTYPE a [<!ENTITY x SYSTEM "file:///etc/passwd">]><a>&x;</a>')
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("../escape.xml", "<notice/>")
    with pytest.raises(ValueError):
        list(archive_members(stream.getvalue()))


def test_storage_keys_are_random_and_confined(tmp_path):
    storage = LocalStorage(tmp_path)
    one, two = storage.put(b"hello"), storage.put(b"hello")
    assert one != two
    assert storage.get(one) == b"hello"
    with pytest.raises(ValueError):
        storage.get("../secret")
    storage.delete(one)
    assert not storage.path(one).exists()


def test_auth_csrf_and_origin(client):
    assert client.get("/api/v1/company").status_code == 401
    sign_in(client)
    csrf = client.headers.pop("X-CSRF-Token")
    assert client.put("/api/v1/company", json={}).status_code == 403
    client.headers["X-CSRF-Token"] = csrf
    assert (
        client.put("/api/v1/company", json={}, headers={"Origin": "https://evil.test"}).status_code
        == 403
    )
    response = client.get("/dashboard")
    assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]
    assert response.headers["X-Content-Type-Options"] == "nosniff"


def test_one_time_login(client):
    code = client.post("/api/v1/auth/request", json={"email": "x@example.test"}).json()[
        "development_code"
    ]
    assert client.post("/api/v1/auth/verify", json={"token": code}).status_code == 200
    assert client.post("/api/v1/auth/verify", json={"token": code}).status_code == 401


def test_sql_injection_is_literal(signed):
    assert signed.get("/api/v1/opportunities", params={"q": "' OR 1=1 --"}).json()["items"] == []


def test_production_gate(monkeypatch):
    from app.config import Settings

    config = Settings(environment="production")
    with pytest.raises(RuntimeError, match="Production release blocked"):
        config.validate_deployment()
