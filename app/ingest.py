import json

from sqlalchemy import select

from app.models import (
    Analysis,
    Job,
    Notice,
    NoticeChange,
    NoticeVersion,
    Notification,
    SourceRegistry,
    Watch,
)
from app.ted import content_hash

CRITICAL = {"deadline", "requirements", "description", "value", "lots", "status", "currency"}
MATERIAL = {"procedure", "languages", "buyer", "country", "cpv_codes"}


def register_sources(db):
    if not db.scalar(select(SourceRegistry).where(SourceRegistry.name == "TED")):
        db.add(
            SourceRegistry(
                name="TED",
                terms_url="https://ted.europa.eu/en/legal-notice",
                reviewed_at="2026-09-14",
                notes="Procurement notices reusable subject to stated exceptions and third-party rights. Attribute TED / Publications Office of the European Union. Analysis is independent, without EU endorsement.",
            )
        )
        db.commit()


def notify(db, organization_id, key, title, body, href="/notifications"):
    if not db.scalar(
        select(Notification).where(
            Notification.organization_id == organization_id, Notification.dedupe_key == key
        )
    ):
        db.add(
            Notification(
                organization_id=organization_id, dedupe_key=key, title=title, body=body, href=href
            )
        )


def enqueue(db, type_, key, payload=None):
    job = db.scalar(select(Job).where(Job.dedupe_key == key))
    if not job:
        job = Job(type=type_, dedupe_key=key, payload=payload or {})
        db.add(job)
        db.flush()
    return job


def ingest(db, normalized, raw, source="TED"):
    raw = raw.decode("utf-8") if isinstance(raw, bytes) else raw
    hash_ = content_hash(raw)
    identity = f"{source}:{normalized['source_id']}"
    notice = db.scalar(select(Notice).where(Notice.source_id == identity).with_for_update())
    if not notice and normalized.get("change_reference"):
        reference = normalized["change_reference"]
        prior_identity = (
            reference[:36] if len(reference) >= 36 and reference[8:9] == "-" else reference
        )
        notice = db.scalar(
            select(Notice).where(Notice.source_id == f"{source}:{prior_identity}").with_for_update()
        )
        if not notice:
            prior_version = db.scalar(
                select(NoticeVersion).where(NoticeVersion.publication_number == reference)
            )
            if prior_version:
                notice = db.get(Notice, prior_version.notice_id)
    if not notice:
        notice = Notice(
            source=source,
            source_id=identity,
            title=normalized["title"],
            published=normalized.get("published", ""),
        )
        db.add(notice)
        db.flush()
    existing = db.scalar(
        select(NoticeVersion).where(
            NoticeVersion.notice_id == notice.id, NoticeVersion.content_hash == hash_
        )
    )
    if existing:
        return notice, False
    previous = (
        db.get(NoticeVersion, notice.current_version_id) if notice.current_version_id else None
    )
    version = NoticeVersion(
        notice_id=notice.id,
        source_version=normalized["source_version"],
        publication_number=normalized["publication_number"],
        content_hash=hash_,
        raw_payload=raw,
        normalized=normalized,
    )
    db.add(version)
    db.flush()
    if previous and normalized.get("published", "") < previous.normalized.get("published", ""):
        return notice, True
    if previous:
        changes = {
            k: {"before": previous.normalized.get(k), "after": v}
            for k, v in normalized.items()
            if previous.normalized.get(k) != v
            and k not in {"source_fields", "source_version", "publication_number", "source_url"}
        }
        severity = (
            "CRITICAL"
            if CRITICAL.intersection(changes)
            else "MATERIAL"
            if MATERIAL.intersection(changes)
            else "MINOR"
        )
        db.add(
            NoticeChange(
                notice_id=notice.id, version_id=version.id, change_class=severity, fields=changes
            )
        )
        if severity != "MINOR":
            for analysis in db.scalars(
                select(Analysis).where(Analysis.notice_id == notice.id, Analysis.stale.is_(False))
            ):
                analysis.stale = True
                enqueue(
                    db,
                    "analysis",
                    f"analysis:{analysis.organization_id}:{version.id}",
                    {"organization_id": analysis.organization_id, "notice_id": notice.id},
                )
        for watch in db.scalars(
            select(Watch).where(Watch.notice_id == notice.id, Watch.state == "WATCH")
        ):
            if {"MINOR": 1, "MATERIAL": 2, "CRITICAL": 3}[severity] >= {
                "MINOR": 1,
                "MATERIAL": 2,
                "CRITICAL": 3,
            }[watch.preference]:
                notify(
                    db,
                    watch.organization_id,
                    f"change:{version.id}",
                    f"{severity.title()} notice change",
                    ", ".join(changes) + " changed. Review the updated source and assessment.",
                    f"/opportunities/{notice.id}",
                )
    notice.current_version_id = version.id
    notice.title = normalized["title"]
    notice.country = normalized.get("country", "")
    notice.published = normalized.get("published", "")
    notice.deadline = normalized.get("deadline")
    notice.status = normalized.get("status", "ACTIVE")
    notice.search_text = " ".join(
        [
            notice.title,
            normalized.get("description", ""),
            normalized.get("buyer", ""),
            " ".join(normalized.get("cpv_codes", [])),
        ]
    ).lower()
    db.flush()
    return notice, True


def import_json(db, path):
    with open(path, encoding="utf-8") as stream:
        for row in json.load(stream):
            ingest(db, row, json.dumps(row, sort_keys=True), source="DEMO")
    db.commit()
