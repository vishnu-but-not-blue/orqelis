import asyncio
import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import select

from app.ingest import enqueue, ingest
from app.jobs import claim, run_once, sweep
from app.models import Job, NoticeVersion, Notification, Watch
from app.ted import TedClient, normalize_api
from scripts.seed_demo import demo_notices
from tests.conftest import sign_in


def test_versioning_idempotency_and_material_alert(client, factory):
    org = sign_in(client)
    row = next(demo_notices())
    with factory() as db:
        n, created = ingest(db, row, json.dumps(row), source="DEMO")
        assert created
        db.add(Watch(organization_id=org, notice_id=n.id))
        db.commit()
        _, created = ingest(db, row, json.dumps(row), source="DEMO")
        assert not created
        amended = row | {"source_version": "2", "deadline": "2027-01-01T12:00:00+00:00"}
        ingest(db, amended, json.dumps(amended), source="DEMO")
        db.commit()
        assert len(list(db.scalars(select(NoticeVersion)))) == 2
        assert len(list(db.scalars(select(Notification)))) == 1
        ingest(db, amended, json.dumps(amended), source="DEMO")
        db.commit()
        assert len(list(db.scalars(select(Notification)))) == 1


def test_worker_reclaims_crash_and_dedupes(factory):
    with factory() as db:
        job = enqueue(db, "sweep", "unique")
        assert enqueue(db, "sweep", "unique").id == job.id
        job.status = "RUNNING"
        job.locked_at = datetime.now(UTC) - timedelta(hours=1)
        job.locked_by = "dead-worker"
        db.commit()
    assert run_once(factory)
    with factory() as db:
        assert db.scalar(select(Job)).status == "DONE"
        assert claim(db, "new-worker") is None


def test_failure_backoff(factory):
    with factory() as db:
        enqueue(db, "invalid", "bad-job")
        db.commit()
    assert run_once(factory)
    with factory() as db:
        job = db.scalar(select(Job))
        assert job.status == "PENDING"
        assert job.last_error == "ValueError"
        assert job.attempts == 1


def test_ted_retry_after_and_circuit(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings(), "ted_enabled", True)
    monkeypatch.setattr("app.ted.safe_url", lambda url: url)
    waits = []

    async def sleep(seconds):
        waits.append(seconds)

    async def exercise():
        transport = httpx.MockTransport(
            lambda request: httpx.Response(429, headers={"Retry-After": "10"})
        )
        client = TedClient(httpx.AsyncClient(transport=transport), sleep=sleep)
        with pytest.raises(RuntimeError, match="temporarily unavailable"):
            await client.search("test")
        with pytest.raises(RuntimeError, match="circuit breaker"):
            await client.search("test")
        await client.close()

    asyncio.run(exercise())
    assert len([w for w in waits if w >= 10]) == 4


def test_missing_api_fields_are_not_invented():
    n = normalize_api({"publication-number": "12345-2026", "notice-title": {"eng": ["Test"]}})
    assert n["value"] is None
    assert n["deadline"] is None
    assert not n["requirements_complete"]


def test_deadline_alert_deduplication(client, factory):
    org = sign_in(client)
    row = next(demo_notices()) | {"deadline": (datetime.now(UTC) + timedelta(days=3)).isoformat()}
    with factory() as db:
        n, _ = ingest(db, row, json.dumps(row), source="DEMO")
        db.add(Watch(organization_id=org, notice_id=n.id))
        db.commit()
        sweep(db)
        sweep(db)
        assert len(list(db.scalars(select(Notification)))) == 1
