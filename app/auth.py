import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Protocol

import httpx
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


class SupabaseAuthProvider:
    """Production identity adapter for Supabase Auth (Phase 10 boundary).
    Validates Supabase JWTs (via HS256 secret or Supabase /auth/v1/user endpoint).
    """

    def __init__(
        self,
        jwt_secret: str | None = None,
        supabase_url: str | None = None,
        anon_key: str | None = None,
    ):
        self.jwt_secret = jwt_secret or settings().supabase_jwt_secret
        self.supabase_url = (supabase_url or settings().supabase_url).rstrip("/")
        self.anon_key = anon_key or settings().supabase_anon_key

    def request_code(self, email: str, name: str):
        try:
            response = httpx.post(
                f"{self.supabase_url}/auth/v1/otp",
                headers={"apikey": self.anon_key},
                json={"email": email, "create_user": True, "data": {"full_name": name}},
                timeout=15,
            )
        except httpx.HTTPError:
            raise HTTPException(
                503, "Sign-in service temporarily unavailable. Please retry."
            ) from None
        if response.status_code == 429:
            raise HTTPException(429, "Please wait before requesting another sign-in email.")
        if response.status_code not in {200, 201}:
            raise HTTPException(
                503, "Unable to send a sign-in code. Contact the operator if this persists."
            )

    def verify_code(self, db, email: str, code: str):
        try:
            response = httpx.post(
                f"{self.supabase_url}/auth/v1/verify",
                headers={"apikey": self.anon_key},
                json={"email": email, "token": code, "type": "email"},
                timeout=15,
            )
        except httpx.HTTPError:
            raise HTTPException(
                503, "Sign-in service temporarily unavailable. Please retry."
            ) from None
        if response.status_code != 200:
            raise HTTPException(401, "The sign-in code is invalid or expired.")
        token = response.json().get("access_token")
        if not token:
            raise HTTPException(401, "Sign-in did not return a valid session.")
        return self.identify(db, token)

    def identify(self, db, token: str) -> User:
        # Supabase verifies signature, issuer, expiry and current identity. Never decode a
        # JWT as proof of identity, and never authenticate from unverified email metadata.
        if not self.supabase_url or not self.anon_key:
            raise HTTPException(503, "Supabase identity is not configured.")
        try:
            response = httpx.get(
                f"{self.supabase_url}/auth/v1/user",
                headers={"Authorization": f"Bearer {token}", "apikey": self.anon_key},
                timeout=10,
            )
        except httpx.HTTPError:
            raise HTTPException(503, "Identity service unavailable. Please retry.") from None
        if response.status_code != 200:
            raise HTTPException(401, "Invalid or expired authentication token.")
        data = response.json()
        if not data.get("id") or not data.get("email") or not data.get("email_confirmed_at"):
            raise HTTPException(401, "A verified email identity is required.")
        email = data["email"].lower().strip()
        subject = "supabase:" + data["id"]
        user = db.scalar(select(User).where(User.auth_subject == subject))
        if not user:
            existing = db.scalar(select(User).where(User.email == email))
            if existing and existing.auth_subject not in (None, subject):
                raise HTTPException(409, "This email is already linked to another identity.")
            user = existing or User(
                email=email,
                name=(data.get("user_metadata") or {}).get("full_name") or email.split("@")[0],
            )
            user.auth_subject = subject
            db.add(user)
            db.flush()
        return user

    def revoke(self, db, user_id: str):
        for session in db.scalars(select(Session).where(Session.user_id == user_id)):
            db.delete(session)


def get_auth_provider() -> AuthProvider:
    if settings().auth_provider == "supabase":
        return SupabaseAuthProvider()
    return LocalAuthProvider()


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
