"""Tenant overlays from human-reviewed tender documents. Public facts stay immutable."""

import copy

from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field

from app.auth import audit, principal, tenant
from app.db import get_db
from app.models import Correction, Document, Notice, NoticeVersion
from app.requirements import extract_clauses
from app.schemas import Input
from app.services import invalidate, scoped

router = APIRouter(prefix="/api/v1")


class DossierReview(Input):
    document_id: str
    source_excerpt: str = Field(min_length=10, max_length=20000)
    source_locator: str = Field(min_length=3, max_length=500)
    lot_id: str | None = Field(default=None, max_length=80)
    complete: bool = False
    reason: str = Field(min_length=10, max_length=2000)


@router.post("/opportunities/{id_}/dossier-review")
def review_dossier(
    id_: str, body: DossierReview, org=Depends(tenant), user=Depends(principal), db=Depends(get_db)
):
    notice = db.get(Notice, id_)
    if not notice:
        raise HTTPException(404, "Opportunity not found")
    version = db.get(NoticeVersion, notice.current_version_id)
    doc = scoped(db, Document, body.document_id, org)
    if doc.status != "READY" or body.source_excerpt not in doc.text:
        raise HTTPException(422, "The exact excerpt must occur in a validated document.")
    if body.lot_id and not any(
        lot["id"] == body.lot_id for lot in version.normalized.get("lots", [])
    ):
        raise HTTPException(422, "The selected lot is not present in this notice version.")
    requirements = extract_clauses(
        body.source_excerpt.splitlines(), body.source_locator, body.lot_id
    )
    for r in requirements:
        r["user_correction"] = (
            "User-supplied source document and reviewed lot association; deterministic extraction."
        )
        r["document_id"] = doc.id
    data = {
        "requirements": requirements,
        "complete": body.complete,
        "lot_id": body.lot_id,
        "document_id": doc.id,
        "content_hash": doc.content_hash,
    }
    db.add(
        Correction(
            organization_id=org.id,
            notice_id=id_,
            version_id=version.id,
            requirement_id="__dossier__",
            data=data,
            reason=body.reason,
        )
    )
    invalidate(db, org)
    audit(db, org, user, "dossier.reviewed", id_)
    db.commit()
    return {"ok": True, "requirements": requirements}


def apply_dossier(db, normalized, correction, org):
    doc = db.get(Document, correction.data.get("document_id"))
    if not doc or doc.organization_id != org.id or doc.status != "READY":
        return
    normalized["requirements"].extend(copy.deepcopy(correction.data["requirements"]))
    if correction.data.get("complete"):
        lot_id = correction.data.get("lot_id")
        if lot_id:
            for lot in normalized.get("lots", []):
                if lot["id"] == lot_id:
                    lot["requirements_complete"] = True
        elif not normalized.get("lots"):
            normalized["requirements_complete"] = True
        normalized["user_completeness_attestation"] = correction.reason
