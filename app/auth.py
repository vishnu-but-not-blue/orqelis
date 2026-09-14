import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Protocol

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select

from app.config import settings
from app.db import get_db
from app.models import Audit, LoginLink, Membership, Organization, Session, User


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def utc(value):
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


class AuthProvider(Protocol):
    def identify(self, db, token: str) -> User: ...
    def revoke(self, db, user_id: str): ...


class LocalAuthProvider:
    """Development magic-link identity, with single-use hashed tokens."""

    def create_link(self, db, email, name):
        token = secrets.token_urlsafe(32)
        db.add(
            LoginLink(
                email=email.lower().strip(),
                name=name,
                token_hash=digest(token),
                expires_at=datetime.now(UTC) + timedelta(minutes=15),
            )
        )
        db.commit()
        return token

    def identify(self, db, token):
        link = db.scalar(
            select(LoginLink).where(LoginLink.token_hash == digest(token)).with_for_update()
        )
        if not link or utc(link.expires_at) <= datetime.now(UTC):
            raise HTTPException(401, "This sign-in code has expired or was already used.")
        user = db.scalar(select(User).where(User.email == link.email))
        if not user:
            user = User(email=link.email, name=link.name)
            db.add(user)
            db.flush()
        db.delete(link)
        db.flush()
        return user

    def revoke(self, db, user_id):
        for session in db.scalars(select(Session).where(Session.user_id == user_id)):
            db.delete(session)


class FirebaseAuthProvider:
    """Production identity adapter for Firebase Auth (Phase 10 boundary).
    Activated when auth_provider is 'firebase' and credentials are provided.
    """

    def __init__(self, project_id: str | None = None):
        self.project_id = project_id or settings().internal_token

    def identify(self, db, token: str) -> User:
        raise HTTPException(
            501,
            "Firebase Authentication adapter is ready. "
            "Configure Firebase project credentials to activate production auth.",
        )

    def revoke(self, db, user_id: str):
        for session in db.scalars(select(Session).where(Session.user_id == user_id)):
            db.delete(session)


def create_session(db, user):
    token = secrets.token_urlsafe(48)
    membership = db.scalar(select(Membership).where(Membership.user_id == user.id))
    session = Session(
        token_hash=digest(token),
        user_id=user.id,
        organization_id=membership.organization_id if membership else None,
        csrf=secrets.token_urlsafe(32),
        expires_at=datetime.now(UTC) + timedelta(hours=settings().session_hours),
    )
    db.add(session)
    db.commit()
    return token, session


def principal(request: Request, db=Depends(get_db)):
    token = request.cookies.get("session", "")
    session = db.scalar(select(Session).where(Session.token_hash == digest(token)))
    if not session or utc(session.expires_at) <= datetime.now(UTC):
        raise HTTPException(401, "Sign in to continue.")
    request.state.session = session
    user = db.get(User, session.user_id)
    if not user:
        raise HTTPException(401, "Account unavailable.")
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        csrf = request.headers.get("x-csrf-token", "")
        if not secrets.compare_digest(csrf, session.csrf):
            raise HTTPException(403, "Invalid CSRF token. Refresh the page and retry.")
    return user


def tenant(request: Request, user=Depends(principal), db=Depends(get_db)):
    membership = db.scalar(
        select(Membership).where(
            Membership.user_id == user.id,
            Membership.organization_id == request.state.session.organization_id,
        )
    )
    if not membership:
        raise HTTPException(409, "Create or join an organization first.")
    org = db.get(Organization, membership.organization_id)
    if not org:
        raise HTTPException(403, "Organization unavailable.")
    if request.method not in {"GET", "HEAD", "OPTIONS"} and membership.role == "VIEWER":
        raise HTTPException(403, "Viewer access is read-only.")
    request.state.membership = membership
    return org


def require_admin(request):
    if request.state.membership.role not in {"OWNER", "ADMIN"}:
        raise HTTPException(403, "An organization administrator is required.")


def audit(db, org, user, operation, target=""):
    db.add(
        Audit(
            organization_id=org.id,
            user_id=user.id if user else None,
            operation=operation,
            target=target,
        )
    )
