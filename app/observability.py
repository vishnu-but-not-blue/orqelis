import secrets
from collections import Counter
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import func, select

from app.config import settings
from app.db import SessionLocal
from app.models import Analysis, Document, Job, Notice, SourceRegistry, Usage

metrics = Counter()
router = APIRouter(prefix="/internal")


@router.get("/diagnostics")
def diagnostics(request: Request):
    expected = settings().internal_token
    if not expected or not secrets.compare_digest(
        request.headers.get("x-internal-token", ""), expected
    ):
        raise HTTPException(404, "Not found")
    with SessionLocal() as db:
        source = db.scalar(select(SourceRegistry).where(SourceRegistry.name == "TED"))
        return {
            "timestamp": datetime.now(UTC),
            "http": dict(metrics),
            "jobs": dict(db.execute(select(Job.status, func.count()).group_by(Job.status)).all()),
            "notices": db.scalar(select(func.count()).select_from(Notice)),
            "analyses": db.scalar(select(func.count()).select_from(Analysis)),
            "documents": dict(
                db.execute(select(Document.status, func.count()).group_by(Document.status)).all()
            ),
            "usage": dict(
                db.execute(select(Usage.kind, func.sum(Usage.amount)).group_by(Usage.kind)).all()
            ),
            "ted_checkpoint": source.checkpoint if source else None,
        }
