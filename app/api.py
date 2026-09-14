import io
import json
import secrets
import zipfile
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, File, HTTPException, Request, Response, UploadFile
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy import func, select

from app.auth import (
    LocalAuthProvider,
    audit,
    create_session,
    digest,
    principal,
    require_admin,
    tenant,
    utc,
)
from app.billing import DisabledBilling
from app.config import settings
from app.db import get_db
from app.ingest import enqueue
from app.models import (
    Analysis,
    Audit,
    Correction,
    Document,
    Evidence,
    Invitation,
    Job,
    Membership,
    Notice,
    NoticeChange,
    NoticeVersion,
    Notification,
    Organization,
    Outcome,
    SourceRegistry,
    Subscription,
    Usage,
    User,
    Watch,
)
from app.requirements import canonical
from app.schemas import (
    CorrectionInput,
    EvidenceInput,
    InviteInput,
    LoginInput,
    OrgInput,
    OutcomeInput,
    Profile,
    VerifyInput,
    WatchInput,
)
from app.services import evidence_dict, invalidate, plans, quota, run_analysis, scoped
from app.storage import LocalStorage, validate_upload
from app.ted import content_hash

router = APIRouter(prefix="/api/v1")


@router.post("/auth/request")
def login(body: LoginInput, request: Request, db=Depends(get_db)):
    if settings().auth_provider != "local" or settings().environment == "production":
        raise HTTPException(503, "Configure the selected production identity adapter.")
    token = LocalAuthProvider().create_link(db, body.email, body.name or body.email.split("@")[0])
    # Deliberately explicit local adapter. Never exposed by production configuration.
    return {
        "message": "Local development sign-in code. No email is sent.",
        "development_code": token,
    }


@router.post("/auth/verify")
def verify(body: VerifyInput, response: Response, db=Depends(get_db)):
    if settings().auth_provider != "local" or settings().environment == "production":
        raise HTTPException(503, "Production identity adapter required.")
    user = LocalAuthProvider().identify(db, body.token)
    token, session = create_session(db, user)
    response.set_cookie(
        "session",
        token,
        httponly=True,
        secure=settings().environment == "production",
        samesite="strict",
        max_age=settings().session_hours * 3600,
    )
    return {"csrf": session.csrf, "organization_id": session.organization_id}


@router.post("/auth/logout")
def logout(request: Request, response: Response, user=Depends(principal), db=Depends(get_db)):
    db.delete(request.state.session)
    db.commit()
    response.delete_cookie("session")
    return {"ok": True}


@router.get("/auth/me")
def me(request: Request, user=Depends(principal), db=Depends(get_db)):
    memberships = list(db.scalars(select(Membership).where(Membership.user_id == user.id)))
    return {
        "id": user.id,
        "name": user.name,
        "email": user.email,
        "csrf": request.state.session.csrf,
        "organization_id": request.state.session.organization_id,
        "organizations": [
            {
                "id": m.organization_id,
                "name": db.get(Organization, m.organization_id).name,
                "role": m.role,
            }
            for m in memberships
        ],
    }


@router.post("/organizations")
def create_org(body: OrgInput, request: Request, user=Depends(principal), db=Depends(get_db)):
    if (
        db.scalar(select(func.count()).select_from(Membership).where(Membership.user_id == user.id))
        >= 10
    ):
        raise HTTPException(409, "Organization limit reached.")
    org = Organization(name=body.name, profile=Profile().model_dump())
    db.add(org)
    db.flush()
    db.add(Membership(organization_id=org.id, user_id=user.id, role="OWNER"))
    request.state.session.organization_id = org.id
    audit(db, org, user, "organization.created", org.id)
    db.commit()
    return {"id": org.id, "name": org.name}


@router.post("/organizations/{id_}/switch")
def switch_org(id_: str, request: Request, user=Depends(principal), db=Depends(get_db)):
    if not db.scalar(
        select(Membership).where(Membership.organization_id == id_, Membership.user_id == user.id)
    ):
        raise HTTPException(404, "Organization not found.")
    request.state.session.organization_id = id_
    db.commit()
    return {"ok": True}


@router.get("/company")
def company(request: Request, org=Depends(tenant)):
    return {
        "id": org.id,
        "name": org.name,
        "profile": org.profile,
        "capability_version": org.capability_version,
        "plan": org.plan,
        "role": request.state.membership.role,
    }


@router.put("/company")
def update_company(body: Profile, org=Depends(tenant), user=Depends(principal), db=Depends(get_db)):
    if body.min_contract > body.max_contract:
        raise HTTPException(422, "Minimum contract size cannot exceed maximum.")
    org.profile = body.model_dump()
    invalidate(db, org)
    audit(db, org, user, "profile.updated")
    db.commit()
    return {"ok": True, "capability_version": org.capability_version}


@router.get("/memberships")
def members(org=Depends(tenant), db=Depends(get_db)):
    return [
        {"id": m.id, "user_id": m.user_id, "email": db.get(User, m.user_id).email, "role": m.role}
        for m in db.scalars(select(Membership).where(Membership.organization_id == org.id))
    ]


@router.post("/memberships/invite")
def invite(
    body: InviteInput,
    request: Request,
    org=Depends(tenant),
    user=Depends(principal),
    db=Depends(get_db),
):
    require_admin(request)
    count = db.scalar(
        select(func.count()).select_from(Membership).where(Membership.organization_id == org.id)
    )
    pending = db.scalar(
        select(func.count())
        .select_from(Invitation)
        .where(Invitation.organization_id == org.id, Invitation.expires_at > datetime.now(UTC))
    )
    if count + pending >= plans()[org.plan]["members"]:
        raise HTTPException(429, "Your team member quota has been reached.")
    token = secrets.token_urlsafe(32)
    db.add(
        Invitation(
            organization_id=org.id,
            email=body.email.lower(),
            role=body.role,
            token_hash=digest(token),
            expires_at=datetime.now(UTC) + timedelta(days=7),
        )
    )
    audit(db, org, user, "membership.invited")
    db.commit()
    return {
        "invitation_code": token,
        "expires_in_days": 7,
        "message": "Share this one-use code with the intended team member.",
    }


@router.post("/memberships/accept")
def accept(body: VerifyInput, request: Request, user=Depends(principal), db=Depends(get_db)):
    invitation = db.scalar(
        select(Invitation).where(Invitation.token_hash == digest(body.token)).with_for_update()
    )
    if (
        not invitation
        or invitation.email != user.email
        or utc(invitation.expires_at) <= datetime.now(UTC)
    ):
        raise HTTPException(404, "Valid invitation not found for this account.")
    membership = db.scalar(
        select(Membership).where(
            Membership.organization_id == invitation.organization_id, Membership.user_id == user.id
        )
    )
    if not membership:
        db.add(
            Membership(
                organization_id=invitation.organization_id, user_id=user.id, role=invitation.role
            )
        )
    request.state.session.organization_id = invitation.organization_id
    db.delete(invitation)
    db.commit()
    return {"ok": True}


@router.delete("/memberships/{id_}")
def remove_member(
    id_: str, request: Request, org=Depends(tenant), user=Depends(principal), db=Depends(get_db)
):
    require_admin(request)
    member = scoped(db, Membership, id_, org)
    if member.role == "OWNER":
        raise HTTPException(409, "The organization owner cannot be removed.")
    db.delete(member)
    audit(db, org, user, "membership.removed", id_)
    db.commit()
    return {"ok": True}


@router.get("/documents")
def documents(org=Depends(tenant), db=Depends(get_db)):
    return [
        {
            "id": d.id,
            "filename": d.filename,
            "mime": d.mime,
            "size": d.size,
            "status": d.status,
            "created_at": d.created_at,
            "content_hash": d.content_hash,
        }
        for d in db.scalars(
            select(Document)
            .where(Document.organization_id == org.id)
            .order_by(Document.created_at.desc())
        )
    ]


@router.post("/documents")
async def upload(
    file: UploadFile = File(...), org=Depends(tenant), user=Depends(principal), db=Depends(get_db)
):
    quota(db, org, "documents")
    data = await file.read(settings().max_upload_bytes + 1)
    mime = validate_upload(data, file.filename or "document")
    checksum = content_hash(data)
    existing = db.scalar(
        select(Document).where(
            Document.organization_id == org.id, Document.content_hash == checksum
        )
    )
    if existing:
        return {"id": existing.id, "status": existing.status, "duplicate": True}
    storage = LocalStorage()
    key = storage.put(data)
    try:
        doc = Document(
            organization_id=org.id,
            filename=(file.filename or "document")[:200],
            object_key=key,
            content_hash=checksum,
            mime=mime,
            size=len(data),
        )
        db.add(doc)
        db.flush()
        enqueue(
            db, "document", f"document:{doc.id}", {"document_id": doc.id, "organization_id": org.id}
        )
        db.add(Usage(organization_id=org.id, kind="storage_bytes", amount=len(data)))
        audit(db, org, user, "document.uploaded", doc.id)
        db.commit()
    except Exception:
        storage.delete(key)
        raise
    return {"id": doc.id, "status": doc.status}


@router.get("/documents/{id_}")
def document_detail(id_: str, org=Depends(tenant), db=Depends(get_db)):
    doc = scoped(db, Document, id_, org)
    return {
        "id": doc.id,
        "filename": doc.filename,
        "status": doc.status,
        "text": doc.text if doc.status == "READY" else "",
        "content_hash": doc.content_hash,
    }


@router.post("/documents/{id_}/access")
def document_access(
    id_: str, request: Request, org=Depends(tenant), user=Depends(principal), db=Depends(get_db)
):
    doc = scoped(db, Document, id_, org)
    if doc.status != "READY":
        raise HTTPException(409, "Document is not available until validation passes.")
    token = URLSafeTimedSerializer(request.app.state.signing_key, salt="document-access").dumps(
        {"id": doc.id, "org": org.id, "user": user.id}
    )
    return {"access_token": token, "expires_in": 120}


@router.get("/documents/{id_}/download")
def download(
    id_: str, request: Request, org=Depends(tenant), user=Depends(principal), db=Depends(get_db)
):
    doc = scoped(db, Document, id_, org)
    try:
        grant = URLSafeTimedSerializer(request.app.state.signing_key, salt="document-access").loads(
            request.headers.get("x-document-token", ""), max_age=120
        )
    except (BadSignature, SignatureExpired):
        raise HTTPException(403, "Document access grant is invalid or expired.") from None
    if grant != {"id": id_, "org": org.id, "user": user.id} or doc.status != "READY":
        raise HTTPException(403, "Access denied.")
    return Response(
        LocalStorage().get(doc.object_key),
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": 'attachment; filename="evidence-document"',
            "Cache-Control": "no-store",
        },
    )


@router.delete("/documents/{id_}")
def delete_document(id_: str, org=Depends(tenant), user=Depends(principal), db=Depends(get_db)):
    doc = scoped(db, Document, id_, org)
    LocalStorage().delete(doc.object_key)
    db.delete(doc)
    invalidate(db, org)
    # Remove historical private evidence references after source-document deletion.
    for a in db.scalars(select(Analysis).where(Analysis.organization_id == org.id)):
        db.delete(a)
    audit(db, org, user, "document.deleted", id_)
    db.commit()
    return {"ok": True}


@router.get("/evidence")
def evidence_list(org=Depends(tenant), db=Depends(get_db)):
    return [
        evidence_dict(e, db.get(Document, e.document_id) if e.document_id else None)
        for e in db.scalars(select(Evidence).where(Evidence.organization_id == org.id))
    ]


def save_evidence(body, db, org, user, existing=None):
    doc = scoped(db, Document, body.document_id, org) if body.document_id else None
    if body.valid_until and body.valid_from and body.valid_until < body.valid_from:
        raise HTTPException(422, "Expiry precedes validity start.")
    if body.state == "USER_CONFIRMED":
        if (
            not doc
            or doc.status != "READY"
            or not body.locator
            or not body.source_excerpt
            or body.source_excerpt not in doc.text
        ):
            raise HTTPException(
                422,
                "Confirmation requires a validated document, source locator and exact excerpt from the document.",
            )
    e = existing or Evidence(organization_id=org.id)
    e.document_id, e.capability, e.state = body.document_id, canonical(body.capability), body.state
    e.valid_from = body.valid_from.isoformat() if body.valid_from else None
    e.valid_until = body.valid_until.isoformat() if body.valid_until else None
    e.locator = body.locator or "Self-declared; no documentary locator"
    e.data = {
        "value": body.value,
        "currency": body.currency,
        "annual_values": body.annual_values,
        "issuer": body.issuer,
        "jurisdiction": body.jurisdiction,
        "source_excerpt": body.source_excerpt,
        "confidence": 1 if body.state == "USER_CONFIRMED" else 0.3,
        "extraction_version": "manual-1",
        "content_hash": doc.content_hash if doc else None,
    }
    db.add(e)
    invalidate(db, org)
    audit(db, org, user, "evidence.updated")
    db.commit()
    return {"id": e.id, "state": e.state}


@router.post("/evidence")
def evidence_create(
    body: EvidenceInput, org=Depends(tenant), user=Depends(principal), db=Depends(get_db)
):
    return save_evidence(body, db, org, user)


@router.put("/evidence/{id_}")
def evidence_update(
    id_: str, body: EvidenceInput, org=Depends(tenant), user=Depends(principal), db=Depends(get_db)
):
    return save_evidence(body, db, org, user, scoped(db, Evidence, id_, org))


@router.delete("/evidence/{id_}")
def evidence_delete(id_: str, org=Depends(tenant), user=Depends(principal), db=Depends(get_db)):
    db.delete(scoped(db, Evidence, id_, org))
    invalidate(db, org)
    audit(db, org, user, "evidence.deleted", id_)
    db.commit()
    return {"ok": True}


@router.get("/opportunities")
def opportunities(
    q: str = "",
    country: str = "",
    cpv: str = "",
    cursor: str = "",
    saved: bool = False,
    limit: int = 24,
    org=Depends(tenant),
    db=Depends(get_db),
):
    if len(q) > 200 or len(cursor) > 64:
        raise HTTPException(422, "Search input too long.")
    stmt = select(Notice)
    if q:
        if db.bind.dialect.name == "postgresql":
            stmt = stmt.where(
                func.to_tsvector("simple", Notice.search_text).op("@@")(
                    func.plainto_tsquery("simple", q)
                )
            )
        else:
            stmt = stmt.where(Notice.search_text.contains(q.lower(), autoescape=True))
    if country:
        stmt = stmt.where(Notice.country == country.upper())
    if cpv:
        stmt = stmt.where(Notice.search_text.contains(cpv, autoescape=True))
    if cursor:
        stmt = stmt.where(Notice.id > cursor)
    if saved:
        stmt = stmt.join(Watch, Watch.notice_id == Notice.id).where(
            Watch.organization_id == org.id, Watch.state.in_(["WATCH", "SAVED"])
        )
    rows = list(db.scalars(stmt.order_by(Notice.id).limit(min(max(limit, 1), 100) + 1)))
    page_size = min(max(limit, 1), 100)
    next_cursor = rows[page_size - 1].id if len(rows) > page_size else None
    output = []
    for n in rows[:page_size]:
        v = db.get(NoticeVersion, n.current_version_id)
        a = db.scalar(
            select(Analysis)
            .where(Analysis.notice_id == n.id, Analysis.organization_id == org.id)
            .order_by(Analysis.created_at.desc())
        )
        w = db.scalar(select(Watch).where(Watch.notice_id == n.id, Watch.organization_id == org.id))
        output.append(
            {
                "id": n.id,
                "source": n.source,
                "title": n.title,
                "country": n.country,
                "published": n.published,
                "deadline": n.deadline,
                "status": n.status,
                "buyer": v.normalized.get("buyer"),
                "value": v.normalized.get("value"),
                "currency": v.normalized.get("currency"),
                "cpv_codes": v.normalized.get("cpv_codes", []),
                "decision": a.result["decision"] if a and not a.stale else "UNASSESSED",
                "watch": w.state if w else None,
                "fetched_at": v.fetched_at,
            }
        )
    return {"items": output, "next_cursor": next_cursor}


@router.get("/opportunities/{id_}")
def opportunity(id_: str, org=Depends(tenant), db=Depends(get_db)):
    n = db.get(Notice, id_)
    if not n:
        raise HTTPException(404, "Opportunity not found.")
    v = db.get(NoticeVersion, n.current_version_id)
    versions = list(
        db.scalars(
            select(NoticeVersion)
            .where(NoticeVersion.notice_id == n.id)
            .order_by(NoticeVersion.fetched_at.desc())
        )
    )
    changes = list(
        db.scalars(
            select(NoticeChange)
            .where(NoticeChange.notice_id == n.id)
            .order_by(NoticeChange.created_at.desc())
        )
    )
    return {
        "id": n.id,
        "source": n.source,
        "facts": v.normalized,
        "version_id": v.id,
        "fetched_at": v.fetched_at,
        "versions": [
            {
                "id": x.id,
                "version": x.source_version,
                "content_hash": x.content_hash,
                "fetched_at": x.fetched_at,
            }
            for x in versions
        ],
        "changes": [
            {"class": x.change_class, "fields": x.fields, "created_at": x.created_at}
            for x in changes
        ],
    }


@router.get("/opportunities/{id_}/requirements")
def requirements(id_: str, org=Depends(tenant), db=Depends(get_db)):
    return opportunity(id_, org, db)["facts"].get("requirements", [])


@router.post("/opportunities/{id_}/refresh-source")
def refresh_source(id_: str, org=Depends(tenant), db=Depends(get_db)):
    notice = db.get(Notice, id_)
    if not notice or notice.source != "TED":
        raise HTTPException(404, "Published TED notice not found")
    version = db.get(NoticeVersion, notice.current_version_id)
    job = enqueue(
        db,
        "notice_xml",
        f"xml:{version.publication_number}",
        {"notice_id": notice.id, "publication": version.publication_number},
    )
    db.commit()
    return {"job_id": job.id, "status": job.status}


@router.post("/opportunities/{id_}/analysis")
def analysis_create(id_: str, org=Depends(tenant), user=Depends(principal), db=Depends(get_db)):
    analysis = run_analysis(db, org, id_, user)
    db.commit()
    return {"id": analysis.id, "result": analysis.result, "stale": analysis.stale}


@router.get("/opportunities/{id_}/analysis")
def analysis_get(id_: str, org=Depends(tenant), db=Depends(get_db)):
    a = db.scalar(
        select(Analysis)
        .where(Analysis.organization_id == org.id, Analysis.notice_id == id_)
        .order_by(Analysis.created_at.desc())
    )
    return {"id": a.id, "result": a.result, "stale": a.stale} if a else {"result": None}


@router.post("/opportunities/{id_}/corrections")
def correction(
    id_: str,
    body: CorrectionInput,
    org=Depends(tenant),
    user=Depends(principal),
    db=Depends(get_db),
):
    n = db.get(Notice, id_)
    v = db.get(NoticeVersion, n.current_version_id) if n else None
    if not v or not any(
        r["id"] == body.requirement_id for r in v.normalized.get("requirements", [])
    ):
        raise HTTPException(404, "Requirement not found.")
    db.add(
        Correction(
            organization_id=org.id,
            notice_id=id_,
            version_id=v.id,
            requirement_id=body.requirement_id,
            data={"hard_gate": body.hard_gate},
            reason=body.reason,
        )
    )
    invalidate(db, org)
    audit(db, org, user, "requirement.corrected", id_)
    db.commit()
    return {"ok": True}


@router.put("/watchlist/{id_}")
def watch(id_: str, body: WatchInput, org=Depends(tenant), db=Depends(get_db)):
    if not db.get(Notice, id_):
        raise HTTPException(404, "Opportunity not found.")
    if body.assigned_to and not db.scalar(
        select(Membership).where(
            Membership.organization_id == org.id, Membership.user_id == body.assigned_to
        )
    ):
        raise HTTPException(422, "Assignee must belong to your organization.")
    w = db.scalar(select(Watch).where(Watch.notice_id == id_, Watch.organization_id == org.id))
    if not w:
        w = Watch(organization_id=org.id, notice_id=id_)
        db.add(w)
    for k, v in body.model_dump().items():
        setattr(w, k, v)
    db.commit()
    return {"ok": True}


@router.get("/watchlist")
def watchlist(org=Depends(tenant), db=Depends(get_db)):
    return [
        {
            "notice_id": w.notice_id,
            "state": w.state,
            "reason": w.reason,
            "assigned_to": w.assigned_to,
        }
        for w in db.scalars(select(Watch).where(Watch.organization_id == org.id))
    ]


@router.post("/opportunities/{id_}/outcome")
def outcome(id_: str, body: OutcomeInput, org=Depends(tenant), db=Depends(get_db)):
    if not db.get(Notice, id_):
        raise HTTPException(404, "Opportunity not found.")
    db.add(Outcome(organization_id=org.id, notice_id=id_, data=body.model_dump()))
    db.commit()
    return {"ok": True}


@router.get("/notifications")
def notifications(org=Depends(tenant), db=Depends(get_db)):
    return [
        {
            "id": n.id,
            "title": n.title,
            "body": n.body,
            "href": n.href,
            "read": n.read,
            "delivered": n.delivered,
            "created_at": n.created_at,
        }
        for n in db.scalars(
            select(Notification)
            .where(Notification.organization_id == org.id)
            .order_by(Notification.created_at.desc())
            .limit(100)
        )
    ]


@router.post("/notifications/{id_}/read")
def read_notification(id_: str, org=Depends(tenant), db=Depends(get_db)):
    scoped(db, Notification, id_, org).read = True
    db.commit()
    return {"ok": True}


@router.get("/exports/analyses/{id_}")
def report(id_: str, org=Depends(tenant), user=Depends(principal), db=Depends(get_db)):
    a = scoped(db, Analysis, id_, org)
    audit(db, org, user, "analysis.exported", id_)
    db.commit()
    return Response(
        json.dumps(
            {
                "organization": org.name,
                "analysis_id": a.id,
                "historical": a.stale,
                "report": a.result,
            },
            indent=2,
        ),
        media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="decision-report.json"'},
    )


@router.get("/billing")
def billing(org=Depends(tenant), db=Depends(get_db)):
    month = datetime.now(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    usage = dict(
        db.execute(
            select(Usage.kind, func.sum(Usage.amount))
            .where(Usage.organization_id == org.id, Usage.created_at >= month)
            .group_by(Usage.kind)
        ).all()
    )
    return {
        "plan": org.plan,
        "plans": plans(),
        "provider": settings().billing_provider,
        "usage": usage,
        "paid_enabled": False,
    }


@router.post("/billing/checkout")
def checkout(request: Request, org=Depends(tenant)):
    require_admin(request)
    return DisabledBilling().create_checkout(
        org.id, "SME", request.headers.get("idempotency-key", "")
    )


@router.post("/billing/webhook")
async def webhook(request: Request):
    return DisabledBilling().verify_webhook(
        await request.body(), request.headers.get("signature", "")
    )


@router.get("/account/export")
def export_account(org=Depends(tenant), user=Depends(principal), db=Depends(get_db)):
    data = {
        "account": {"email": user.email, "name": user.name},
        "organization": {"name": org.name, "profile": org.profile},
    }
    for model in [
        Evidence,
        Analysis,
        Watch,
        Correction,
        Notification,
        Outcome,
        Usage,
        Audit,
        Subscription,
    ]:
        data[model.__tablename__] = [
            {c.name: getattr(row, c.name) for c in model.__table__.columns}
            for row in db.scalars(select(model).where(model.organization_id == org.id))
        ]
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("account.json", json.dumps(data, default=str, indent=2))
        for doc in db.scalars(
            select(Document).where(Document.organization_id == org.id, Document.status == "READY")
        ):
            archive.writestr(f"documents/{doc.id}.bin", LocalStorage().get(doc.object_key))
    audit(db, org, user, "account.exported")
    db.commit()
    return Response(
        stream.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="orqelis-account.zip"'},
    )


@router.delete("/account")
def delete_account(
    request: Request, response: Response, user=Depends(principal), db=Depends(get_db)
):
    memberships = list(db.scalars(select(Membership).where(Membership.user_id == user.id)))
    for m in memberships:
        if m.role == "OWNER":
            if (
                db.scalar(
                    select(func.count())
                    .select_from(Membership)
                    .where(Membership.organization_id == m.organization_id)
                )
                > 1
            ):
                raise HTTPException(
                    409, "Remove team memberships before deleting an owned organization."
                )
    for m in memberships:
        if m.role == "OWNER":
            for doc in db.scalars(
                select(Document).where(Document.organization_id == m.organization_id)
            ):
                LocalStorage().delete(doc.object_key)
            for job in db.scalars(select(Job)):
                if job.payload.get("organization_id") == m.organization_id:
                    db.delete(job)
            db.delete(db.get(Organization, m.organization_id))
    db.delete(user)
    db.commit()
    response.delete_cookie("session")
    return {
        "ok": True,
        "message": "Active account data deleted. Encrypted backups age out under the configured retention policy.",
    }


@router.post("/sources/ted/sync")
def sync(request: Request, org=Depends(tenant), db=Depends(get_db)):
    require_admin(request)
    source = db.scalar(select(SourceRegistry).where(SourceRegistry.name == "TED"))
    if not settings().ted_enabled or not source or not source.enabled:
        raise HTTPException(503, "TED ingestion is disabled.")
    job = enqueue(db, "ted_sync", f"ted:{datetime.now(UTC).strftime('%Y%m%d%H')}")
    db.commit()
    return {"job_id": job.id, "status": job.status}


@router.get("/sources")
def sources():
    return {
        "source": "TED / Publications Office of the European Union",
        "legal_notice": "https://ted.europa.eu/en/legal-notice",
        "attribution": "Independent analysis. No endorsement by EU institutions.",
    }


@router.get("/health/organization")
def org_health(request: Request, org=Depends(tenant), db=Depends(get_db)):
    require_admin(request)
    return {
        "usage": billing(org, db),
        "pending_notifications": db.scalar(
            select(func.count())
            .select_from(Notification)
            .where(Notification.organization_id == org.id, Notification.delivered.is_(False))
        ),
        "storage": LocalStorage().health(),
    }
