import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def uid():
    return uuid.uuid4().hex


def now():
    return datetime.now(UTC)


class Identity:
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)


class Tenant:
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )


class User(Identity, Base):
    __tablename__ = "users"
    email: Mapped[str] = mapped_column(String(254), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Organization(Identity, Base):
    __tablename__ = "organizations"
    name: Mapped[str] = mapped_column(String(160))
    capability_version: Mapped[int] = mapped_column(default=1)
    profile: Mapped[dict] = mapped_column(JSON, default=dict)
    plan: Mapped[str] = mapped_column(default="FREE")


class Membership(Identity, Tenant, Base):
    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("organization_id", "user_id"),)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(default="OWNER")


class Session(Identity, Base):
    __tablename__ = "sessions"
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    organization_id: Mapped[str | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    csrf: Mapped[str] = mapped_column(String(100))


class LoginLink(Identity, Base):
    __tablename__ = "login_links"
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    email: Mapped[str] = mapped_column(String(254))
    name: Mapped[str] = mapped_column(String(120))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Invitation(Identity, Tenant, Base):
    __tablename__ = "invitations"
    email: Mapped[str] = mapped_column(String(254))
    role: Mapped[str] = mapped_column(String(20))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Document(Identity, Tenant, Base):
    __tablename__ = "documents"
    filename: Mapped[str] = mapped_column(String(200))
    object_key: Mapped[str] = mapped_column(String(100), unique=True)
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    mime: Mapped[str] = mapped_column(String(100))
    size: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(default="QUARANTINED")
    text: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Evidence(Identity, Tenant, Base):
    __tablename__ = "evidence"
    document_id: Mapped[str | None] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=True
    )
    capability: Mapped[str] = mapped_column(String(160), index=True)
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    state: Mapped[str] = mapped_column(default="UNVERIFIED")
    valid_from: Mapped[str | None] = mapped_column(nullable=True)
    valid_until: Mapped[str | None] = mapped_column(nullable=True)
    locator: Mapped[str] = mapped_column(Text, default="User declaration; no document")


class Notice(Identity, Base):
    __tablename__ = "source_notices"
    source: Mapped[str] = mapped_column(default="TED")
    source_id: Mapped[str] = mapped_column(String(160), unique=True)
    current_version_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    title: Mapped[str] = mapped_column(Text)
    country: Mapped[str] = mapped_column(String(8), default="")
    published: Mapped[str] = mapped_column(String(40), index=True)
    deadline: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    status: Mapped[str] = mapped_column(default="ACTIVE", index=True)
    search_text: Mapped[str] = mapped_column(Text, default="")


class NoticeVersion(Identity, Base):
    __tablename__ = "notice_versions"
    __table_args__ = (UniqueConstraint("notice_id", "source_version", "content_hash"),)
    notice_id: Mapped[str] = mapped_column(
        ForeignKey("source_notices.id", ondelete="CASCADE"), index=True
    )
    source_version: Mapped[str] = mapped_column(String(100))
    publication_number: Mapped[str] = mapped_column(String(100))
    content_hash: Mapped[str] = mapped_column(String(64))
    raw_payload: Mapped[str] = mapped_column(Text)
    normalized: Mapped[dict] = mapped_column(JSON)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    parser_version: Mapped[str] = mapped_column(default="ted-1")


class Analysis(Identity, Tenant, Base):
    __tablename__ = "opportunity_analyses"
    __table_args__ = (UniqueConstraint("organization_id", "cache_key"),)
    notice_id: Mapped[str] = mapped_column(
        ForeignKey("source_notices.id", ondelete="CASCADE"), index=True
    )
    version_id: Mapped[str] = mapped_column(ForeignKey("notice_versions.id"))
    cache_key: Mapped[str] = mapped_column(String(64))
    result: Mapped[dict] = mapped_column(JSON)
    stale: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Watch(Identity, Tenant, Base):
    __tablename__ = "watchlist"
    __table_args__ = (UniqueConstraint("organization_id", "notice_id"),)
    notice_id: Mapped[str] = mapped_column(ForeignKey("source_notices.id", ondelete="CASCADE"))
    state: Mapped[str] = mapped_column(default="WATCH")
    reason: Mapped[str] = mapped_column(default="")
    assigned_to: Mapped[str | None] = mapped_column(nullable=True)
    preference: Mapped[str] = mapped_column(default="MATERIAL")


class Correction(Identity, Tenant, Base):
    __tablename__ = "corrections"
    notice_id: Mapped[str] = mapped_column(ForeignKey("source_notices.id", ondelete="CASCADE"))
    version_id: Mapped[str] = mapped_column(ForeignKey("notice_versions.id"))
    requirement_id: Mapped[str] = mapped_column(String(100))
    data: Mapped[dict] = mapped_column(JSON)
    reason: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class NoticeChange(Identity, Base):
    __tablename__ = "notice_changes"
    notice_id: Mapped[str] = mapped_column(
        ForeignKey("source_notices.id", ondelete="CASCADE"), index=True
    )
    version_id: Mapped[str] = mapped_column(ForeignKey("notice_versions.id"))
    change_class: Mapped[str] = mapped_column(String(20))
    fields: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Notification(Identity, Tenant, Base):
    __tablename__ = "notifications"
    __table_args__ = (UniqueConstraint("organization_id", "dedupe_key"),)
    dedupe_key: Mapped[str] = mapped_column(String(250))
    title: Mapped[str] = mapped_column(String(250))
    body: Mapped[str] = mapped_column(Text)
    href: Mapped[str] = mapped_column(default="/notifications")
    read: Mapped[bool] = mapped_column(default=False)
    delivered: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Job(Identity, Base):
    __tablename__ = "jobs"
    dedupe_key: Mapped[str] = mapped_column(String(250), unique=True)
    type: Mapped[str] = mapped_column(String(50))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(default="PENDING", index=True)
    attempts: Mapped[int] = mapped_column(default=0)
    max_attempts: Mapped[int] = mapped_column(default=5)
    run_after: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    locked_by: Mapped[str | None] = mapped_column(nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class SourceRegistry(Identity, Base):
    __tablename__ = "source_registry"
    name: Mapped[str] = mapped_column(unique=True)
    terms_url: Mapped[str] = mapped_column(Text)
    reviewed_at: Mapped[str] = mapped_column(String(40))
    enabled: Mapped[bool] = mapped_column(default=True)
    checkpoint: Mapped[dict] = mapped_column(JSON, default=dict)
    notes: Mapped[str] = mapped_column(Text)


class Audit(Identity, Tenant, Base):
    __tablename__ = "audit_events"
    user_id: Mapped[str | None] = mapped_column(nullable=True)
    operation: Mapped[str] = mapped_column(String(100))
    target: Mapped[str] = mapped_column(String(100), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Usage(Identity, Tenant, Base):
    __tablename__ = "usage_events"
    kind: Mapped[str] = mapped_column(String(40))
    amount: Mapped[int] = mapped_column(default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)


class Outcome(Identity, Tenant, Base):
    __tablename__ = "outcomes"
    notice_id: Mapped[str] = mapped_column(ForeignKey("source_notices.id", ondelete="CASCADE"))
    data: Mapped[dict] = mapped_column(JSON)


class Subscription(Identity, Tenant, Base):
    __tablename__ = "subscriptions"
    provider_id: Mapped[str] = mapped_column(String(150), unique=True)
    status: Mapped[str] = mapped_column(String(50))
    plan: Mapped[str] = mapped_column(String(30))


Index("ix_notice_search", Notice.search_text)
