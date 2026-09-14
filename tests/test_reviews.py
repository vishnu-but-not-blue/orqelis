from app.jobs import run_once


def test_review_requires_exact_document_source(signed, notice_id, factory):
    excerpt = "ISO 27001 must be provided."
    doc = signed.post(
        "/api/v1/documents", files={"file": ("dossier.txt", excerpt.encode(), "text/plain")}
    ).json()["id"]
    run_once(factory)
    body = {
        "document_id": doc,
        "source_excerpt": "An invented requirement does not occur",
        "source_locator": "Section 3",
        "complete": True,
        "reason": "Reviewed official document section 3",
    }
    assert (
        signed.post(f"/api/v1/opportunities/{notice_id}/dossier-review", json=body).status_code
        == 422
    )
    body["source_excerpt"] = excerpt
    assert (
        signed.post(f"/api/v1/opportunities/{notice_id}/dossier-review", json=body).status_code
        == 200
    )
    result = signed.post(f"/api/v1/opportunities/{notice_id}/analysis").json()["result"]
    assert result["corrections"]
    assert result["eligibility"] == "UNKNOWN"


def test_source_timezone_is_not_invented():
    from app.decision import parse_datetime
    from app.ted import source_datetime

    assert source_datetime("2026-10-13+02:00", "12:00:00") == "2026-10-13T12:00:00+02:00"
    assert source_datetime("2026-10-13+02:00") is None
    assert parse_datetime("2026-10-13+02:00") is None
