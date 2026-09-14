import copy
import json
from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import func, select

from app.auth import audit
from app.config import settings
from app.decision import analyze_lots, cache_key
from app.ingest import enqueue
from app.models import (
    Analysis,
    Correction,
    Document,
    Evidence,
    Notice,
    NoticeVersion,
    Organization,
    Usage,
)


def scoped(db, model, id_, org):
    obj = db.scalar(select(model).where(model.id == id_, model.organization_id == org.id))
    if not obj:
        raise HTTPException(404, "Record not found.")
    return obj


def plans():
    return json.loads(settings().plans_json)


def quota(db, org, kind):
    limit = plans()[org.plan][kind]
    if kind == "analyses":
        used = db.scalar(
            select(func.count())
            .select_from(Usage)
            .where(
                Usage.organization_id == org.id,
                Usage.kind == "analysis",
                Usage.created_at
                >= datetime.now(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0),
            )
        )
    elif kind == "documents":
        used = db.scalar(
            select(func.count()).select_from(Document).where(Document.organization_id == org.id)
        )
    else:
        return
    if used >= limit:
        raise HTTPException(429, f"Your {org.plan} plan's {kind} quota has been reached.")


def evidence_dict(row, doc=None):
    return {
        "id": row.id,
        "capability": row.capability,
        "data": row.data,
        "state": row.state,
        "valid_from": row.valid_from,
        "valid_until": row.valid_until,
        "document_id": row.document_id,
        "document_available": doc is not None and doc.status == "READY",
        "locator": row.locator,
    }


def invalidate(db, org, capability=None):
    org.capability_version += 1
    for analysis in db.scalars(
        select(Analysis).where(Analysis.organization_id == org.id, Analysis.stale.is_(False))
    ):
        requirements = analysis.result.get("requirements", [])
        if capability is None or any(
            r["requirement"]["capability"] == capability for r in requirements
        ):
            analysis.stale = True
            enqueue(
                db,
                "analysis",
                f"profile:{org.id}:{org.capability_version}:{analysis.notice_id}",
                {"organization_id": org.id, "notice_id": analysis.notice_id},
            )


def run_analysis(db, org, notice_id, user=None, charge=True):
    # Serialize quota + cache checks per tenant, including concurrent workers.
    org = db.scalar(select(Organization).where(Organization.id == org.id).with_for_update())
    notice = db.get(Notice, notice_id)
    if not notice:
        raise HTTPException(404, "Opportunity not found.")
    version = db.get(NoticeVersion, notice.current_version_id)
    corrections = list(
        db.scalars(
            select(Correction)
            .where(
                Correction.organization_id == org.id,
                Correction.notice_id == notice.id,
                Correction.version_id == version.id,
            )
            .order_by(Correction.created_at)
        )
    )
    correction_data = [
        {"id": c.id, "requirement_id": c.requirement_id, "data": c.data, "reason": c.reason}
        for c in corrections
    ]
    key = cache_key(version.content_hash, org.capability_version, correction_data)
    cached = db.scalar(
        select(Analysis).where(
            Analysis.organization_id == org.id, Analysis.cache_key == key, Analysis.stale.is_(False)
        )
    )
    if cached:
        return cached
    if charge:
        quota(db, org, "analyses")
    normalized = copy.deepcopy(version.normalized)
    for correction in corrections:
        if correction.requirement_id == "__dossier__":
            from app.reviews import apply_dossier

            apply_dossier(db, normalized, correction, org)
            continue
        for req in normalized.get("requirements", []):
            if req["id"] == correction.requirement_id:
                req.update(correction.data)
                req["user_correction"] = correction.reason
    docs = {d.id: d for d in db.scalars(select(Document).where(Document.organization_id == org.id))}
    evidence = [
        evidence_dict(e, docs.get(e.document_id))
        for e in db.scalars(select(Evidence).where(Evidence.organization_id == org.id))
    ]
    result = analyze_lots(normalized, org.profile, evidence)
    result.update(
        {
            "notice_version": version.source_version,
            "source_url": normalized["source_url"],
            "source_hash": version.content_hash,
            "company_capability_version": org.capability_version,
            "corrections": correction_data,
        }
    )
    analysis = Analysis(
        organization_id=org.id,
        notice_id=notice.id,
        version_id=version.id,
        cache_key=key,
        result=result,
    )
    db.add(analysis)
    if charge:
        db.add(Usage(organization_id=org.id, kind="analysis"))
    audit(db, org, user, "analysis.created", notice.id)
    db.flush()
    return analysis
