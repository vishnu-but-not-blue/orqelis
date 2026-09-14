import asyncio
import json
import logging
import secrets
import smtplib
import time
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage

from sqlalchemy import and_, or_, select, update

from app.config import settings
from app.db import SessionLocal
from app.decision import parse_datetime
from app.ingest import enqueue, ingest, notify
from app.models import (
    Document,
    Evidence,
    Invitation,
    Job,
    LoginLink,
    Membership,
    Notice,
    NoticeVersion,
    Notification,
    Organization,
    Session,
    SourceRegistry,
    User,
    Watch,
)
from app.services import invalidate, run_analysis
from app.storage import LocalStorage, process_document
from app.ted import TedClient, normalize_api, normalize_xml

log = logging.getLogger("orqelis.worker")


def claim(db, worker):
    at = datetime.now(UTC)
    expired = at - timedelta(minutes=15)
    eligible = or_(
        and_(Job.status == "PENDING", Job.run_after <= at),
        and_(Job.status == "RUNNING", Job.locked_at < expired),
    )
    job = db.scalar(
        select(Job)
        .where(eligible, Job.attempts < Job.max_attempts)
        .order_by(Job.run_after)
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    if not job:
        return None
    # Conditional update also protects SQLite's lack of FOR UPDATE.
    changed = db.execute(
        update(Job)
        .execution_options(synchronize_session=False)
        .where(Job.id == job.id, eligible)
        .values(status="RUNNING", locked_by=worker, locked_at=at, attempts=Job.attempts + 1)
    )
    db.commit()
    if changed.rowcount != 1:
        return None
    db.refresh(job)
    return job.id


async def sync_ted(db):
    source = db.scalar(select(SourceRegistry).where(SourceRegistry.name == "TED"))
    if not source or not source.enabled or not settings().ted_enabled:
        return
    client = TedClient()
    checkpoint = source.checkpoint or {}
    query = checkpoint.get("query", settings().ted_query)
    page = checkpoint.get("page", 1)
    try:
        # Bounded chunks keep job leases short and preserve resumable pages.
        for _ in range(3):
            response = await client.search(query, page)
            rows = response.get("notices", [])
            for row in rows:
                normalized = normalize_api(row)
                ingest(db, normalized, json.dumps(row, sort_keys=True))
            page += 1
            source.checkpoint = {
                "page": page,
                "query": query,
                "last_success": datetime.now(UTC).isoformat(),
            }
            db.commit()
            if len(rows) < 50:
                source.checkpoint = {
                    "page": 1,
                    "query": f"publication-date >= {(datetime.now(UTC) - timedelta(days=3)).strftime('%Y%m%d')}",
                    "last_success": datetime.now(UTC).isoformat(),
                }
                db.commit()
                break
    finally:
        await client.close()


def sweep(db):
    at = datetime.now(UTC)
    for e in db.scalars(
        select(Evidence).where(
            Evidence.valid_until.is_not(None),
            Evidence.state.in_(["USER_CONFIRMED", "SYSTEM_VERIFIED", "UNVERIFIED"]),
        )
    ):
        expires = datetime.fromisoformat(e.valid_until).replace(tzinfo=UTC)
        if expires.date() < at.date():
            e.state = "EXPIRED"
            org = db.get(Organization, e.organization_id)
            invalidate(db, org, e.capability)
        if expires <= at + timedelta(days=30):
            notify(
                db,
                e.organization_id,
                f"expiry:{e.id}:{e.valid_until}",
                "Evidence needs attention",
                f"{e.capability} expires on {e.valid_until}. Review or upload a renewed document.",
                "/evidence",
            )
    for w in db.scalars(select(Watch).where(Watch.state == "WATCH")):
        notice = db.get(Notice, w.notice_id)
        deadline = parse_datetime(notice.deadline)
        if deadline and at < deadline <= at + timedelta(days=7) and notice.status != "CANCELLED":
            notify(
                db,
                w.organization_id,
                f"deadline:{notice.id}:{notice.deadline}",
                "Watched deadline approaching",
                f"{notice.title}: {notice.deadline}",
                f"/opportunities/{notice.id}",
            )
    for model, field in [
        (Session, Session.expires_at),
        (LoginLink, LoginLink.expires_at),
        (Invitation, Invitation.expires_at),
    ]:
        for row in db.scalars(select(model).where(field < at)):
            db.delete(row)
    for doc in db.scalars(
        select(Document).where(
            Document.status.in_(["QUARANTINED", "REJECTED"]),
            Document.created_at < at - timedelta(days=settings().retention_days),
        )
    ):
        LocalStorage().delete(doc.object_key)
        db.delete(doc)
    db.commit()


def deliver_digests(db):
    if not settings().smtp_host:
        # In-app notifications are the local sink. Never falsely mark email delivered.
        return
    for org in db.scalars(select(Organization)):
        alerts = list(
            db.scalars(
                select(Notification)
                .where(Notification.organization_id == org.id, Notification.delivered.is_(False))
                .limit(100)
            )
        )
        if not alerts:
            continue
        members = list(
            db.scalars(
                select(Membership).where(
                    Membership.organization_id == org.id, Membership.role == "OWNER"
                )
            )
        )
        for member in members:
            user = db.get(User, member.user_id)
            message = EmailMessage()
            message["Subject"] = f"{settings().app_name}: procurement digest"
            message["From"] = settings().email_from
            message["To"] = user.email
            message["Message-ID"] = f"<{org.id}.{alerts[0].id}@orqelis.local>"
            message.set_content(
                "\n\n".join(f"{n.title}\n{n.body}\n{settings().base_url}{n.href}" for n in alerts)
            )
            with smtplib.SMTP(settings().smtp_host, settings().smtp_port, timeout=20) as smtp:
                smtp.starttls()
                if settings().smtp_user:
                    smtp.login(settings().smtp_user, settings().smtp_password)
                smtp.send_message(message)
        for n in alerts:
            n.delivered = True
        db.commit()


def handle(db, job):
    if job.type == "ted_sync":
        asyncio.run(sync_ted(db))
    elif job.type == "notice_xml":
        source = db.scalar(select(SourceRegistry).where(SourceRegistry.name == "TED"))
        if not source or not source.enabled:
            return

        async def download():
            client = TedClient()
            try:
                return await client.xml(job.payload["publication"])
            finally:
                await client.close()

        raw = asyncio.run(download())
        notice = db.get(Notice, job.payload["notice_id"])
        if not notice:
            return
        previous = db.get(NoticeVersion, notice.current_version_id)
        normalized = normalize_xml(raw, job.payload["publication"])
        # Keep source identity stable while retaining XML identifiers separately.
        normalized["xml_notice_identity"] = normalized["source_id"]
        normalized["source_id"] = previous.normalized["source_id"]
        normalized["published"] = previous.normalized["published"]
        for field in ["title", "buyer", "country", "deadline", "value", "currency"]:
            if normalized.get(field) in (None, "", "Not provided", "Untitled procurement notice"):
                normalized[field] = previous.normalized.get(field)
        ingest(db, normalized, raw)
        db.commit()
    elif job.type == "document":
        doc = db.get(Document, job.payload["document_id"])
        if (
            doc
            and doc.organization_id == job.payload["organization_id"]
            and doc.status == "QUARANTINED"
        ):
            try:
                process_document(LocalStorage(), doc)
            except ValueError:
                doc.status = "REJECTED"
            notify(
                db,
                doc.organization_id,
                f"document:{doc.id}:{doc.status}",
                "Evidence document processed",
                f"{doc.filename}: {doc.status}. Confirm evidence against the extracted text.",
                "/evidence",
            )
            db.commit()
    elif job.type == "analysis":
        org = db.get(Organization, job.payload["organization_id"])
        if org and db.get(Notice, job.payload["notice_id"]):
            run_analysis(db, org, job.payload["notice_id"], charge=False)
            db.commit()
    elif job.type == "sweep":
        sweep(db)
    elif job.type == "digest":
        deliver_digests(db)
    else:
        raise ValueError("Unknown job type")


def run_once(factory=SessionLocal):
    worker = secrets.token_hex(8)
    with factory() as db:
        id_ = claim(db, worker)
    if not id_:
        return False
    started = time.monotonic()
    try:
        with factory() as db:
            job = db.get(Job, id_)
            handle(db, job)
            job.status, job.locked_at, job.locked_by = "DONE", None, None
            db.commit()
        log.info(
            json.dumps(
                {
                    "job_id": id_,
                    "operation": "job",
                    "duration": round(time.monotonic() - started, 3),
                    "result": "done",
                }
            )
        )
    except Exception as exc:
        with factory() as db:
            job = db.get(Job, id_)
            job.status = "FAILED" if job.attempts >= job.max_attempts else "PENDING"
            job.run_after = datetime.now(UTC) + timedelta(seconds=min(3600, 30 * 2**job.attempts))
            job.last_error = type(
                exc
            ).__name__  # No document contents, credentials or provider response bodies.
            job.locked_at = None
            db.commit()
        log.error(
            json.dumps(
                {"job_id": id_, "operation": "job", "result": "retry", "error": type(exc).__name__}
            )
        )
    return True


def schedule(db):
    at = datetime.now(UTC)
    enqueue(db, "sweep", f"sweep:{at.strftime('%Y%m%d%H')}")
    enqueue(db, "digest", f"digest:{at.strftime('%Y%m%d')}")
    if settings().ted_enabled:
        enqueue(db, "ted_sync", f"ted:{at.strftime('%Y%m%d%H')}")
    db.commit()


def main():
    logging.basicConfig(level=logging.INFO)
    while True:
        with SessionLocal() as db:
            schedule(db)
        if not run_once():
            time.sleep(5)


if __name__ == "__main__":
    main()
