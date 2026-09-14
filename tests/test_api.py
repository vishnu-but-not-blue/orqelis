from sqlalchemy import select

from app.jobs import run_once
from app.models import Analysis, Document, Evidence, Membership, User
from tests.conftest import sign_in


def test_complete_flow(signed, factory, notice_id):
    p = signed.get("/api/v1/company").json()["profile"]
    p.update(
        {
            "country": "DEU",
            "operating_countries": ["DEU"],
            "cpv_interests": ["72000000"],
            "languages": ["ENG"],
            "bid_hours_per_day": 8,
        }
    )
    assert signed.put("/api/v1/company", json=p).status_code == 200
    content = b"ISO 27001 certification valid through 2028. Annual turnover EUR 800000."
    r = signed.post("/api/v1/documents", files={"file": ("certificate.txt", content, "text/plain")})
    assert r.status_code == 200, r.text
    doc_id = r.json()["id"]
    assert signed.post(f"/api/v1/documents/{doc_id}/access").status_code == 409
    assert run_once(factory)
    assert signed.get(f"/api/v1/documents/{doc_id}").json()["status"] == "READY"
    for capability, value in [("ISO 27001", None), ("TURNOVER", 800000)]:
        r = signed.post(
            "/api/v1/evidence",
            json={
                "capability": capability,
                "document_id": doc_id,
                "state": "USER_CONFIRMED",
                "valid_until": "2028-12-31",
                "value": value,
                "currency": "EUR",
                "locator": "Section 1",
                "source_excerpt": content.decode(),
            },
        )
        assert r.status_code == 200, r.text
    r = signed.post(f"/api/v1/opportunities/{notice_id}/analysis")
    assert r.status_code == 200, r.text
    result = r.json()
    assert result["result"]["eligibility"] == "PASS"
    again = signed.post(f"/api/v1/opportunities/{notice_id}/analysis").json()
    assert again["id"] == result["id"]
    assert signed.get(f"/api/v1/exports/analyses/{result['id']}").status_code == 200
    assert signed.put(f"/api/v1/watchlist/{notice_id}", json={"state": "WATCH"}).status_code == 200
    assert signed.get("/api/v1/opportunities?saved=true").json()["items"]
    assert signed.get("/api/v1/account/export").headers["content-type"] == "application/zip"
    assert signed.delete(f"/api/v1/documents/{doc_id}").status_code == 200
    with factory() as db:
        assert not list(db.scalars(select(Evidence)))
        assert not list(db.scalars(select(Analysis)))
    assert signed.delete("/api/v1/account").status_code == 200
    assert signed.get("/api/v1/company").status_code == 401


def test_tenant_isolation(client, factory, notice_id):
    org1 = sign_in(client, "first@example.test")
    doc = client.post(
        "/api/v1/documents",
        files={"file": ("private.txt", b"Company private evidence", "text/plain")},
    ).json()["id"]
    run_once(factory)
    token = client.post(f"/api/v1/documents/{doc}/access").json()["access_token"]
    analysis = client.post(f"/api/v1/opportunities/{notice_id}/analysis").json()["id"]
    sign_in(client, "second@example.test")
    for path in [
        f"/documents/{doc}",
        f"/documents/{doc}/download",
        f"/exports/analyses/{analysis}",
    ]:
        assert client.get("/api/v1" + path, headers={"X-Document-Token": token}).status_code == 404
    assert client.delete(f"/api/v1/documents/{doc}").status_code == 404
    assert client.post(f"/api/v1/organizations/{org1}/switch").status_code == 404
    assert (
        client.post(
            "/api/v1/evidence", json={"capability": "ISO 27001", "document_id": doc}
        ).status_code
        == 404
    )
    assert client.get(f"/api/v1/opportunities/{notice_id}/analysis").json()["result"] is None


def test_viewer_cannot_mutate(client, factory):
    org = sign_in(client)
    code = client.post(
        "/api/v1/memberships/invite", json={"email": "viewer@example.test", "role": "VIEWER"}
    ).json()["invitation_code"]
    sign_in(client, "viewer@example.test", company=None)
    assert client.post("/api/v1/memberships/accept", json={"token": code}).status_code == 200
    assert client.get("/api/v1/company").status_code == 200
    assert client.put("/api/v1/company", json={}).status_code == 403
    assert (
        client.post(
            "/api/v1/documents", files={"file": ("a.txt", b"hello", "text/plain")}
        ).status_code
        == 403
    )
    with factory() as db:
        user = db.scalar(select(User).where(User.email == "viewer@example.test"))
        member = db.scalar(
            select(Membership).where(
                Membership.user_id == user.id, Membership.organization_id == org
            )
        )
        db.delete(member)
        db.commit()
    assert client.get("/api/v1/company").status_code == 409


def test_cannot_claim_system_verified_or_cross_tenant(signed):
    r = signed.post(
        "/api/v1/evidence", json={"capability": "ISO 27001", "state": "SYSTEM_VERIFIED"}
    )
    assert r.status_code == 422
    assert signed.put("/api/v1/company", json={"organization_id": "other"}).status_code == 422


def test_billing_fails_closed(signed):
    assert signed.post("/api/v1/billing/webhook", json={"plan": "PRO"}).status_code == 503
    assert signed.get("/api/v1/company").json()["plan"] == "FREE"


def test_all_pages(signed):
    for path in [
        "/dashboard",
        "/onboarding",
        "/opportunities",
        "/evidence",
        "/company",
        "/watchlist",
        "/notifications",
        "/settings",
        "/legal/privacy",
        "/legal/terms",
        "/legal/sources",
    ]:
        response = signed.get(path)
        assert response.status_code == 200, response.text
        assert "text/html" in response.headers["content-type"]


def test_document_download_requires_short_lived_grant(signed, factory):
    doc = signed.post(
        "/api/v1/documents", files={"file": ("private.txt", b"hello", "text/plain")}
    ).json()["id"]
    run_once(factory)
    assert signed.get(f"/api/v1/documents/{doc}/download").status_code == 403
    grant = signed.post(f"/api/v1/documents/{doc}/access").json()["access_token"]
    response = signed.get(f"/api/v1/documents/{doc}/download", headers={"X-Document-Token": grant})
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/octet-stream"
    with factory() as db:
        assert db.get(Document, doc).status == "READY"
